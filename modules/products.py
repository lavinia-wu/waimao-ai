from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz

from config.settings import settings
from database.db import get_connection
from services.excel_service import build_table_export_file


REQUIRED_FIELDS = [
    'product_name_en',
    'currency',
]

# 库存相关字段
STOCK_TEXT_FIELDS = [
    'sku',
    'unit',
    'warehouse',
    'stock_updated_at',
]
STOCK_NUMBER_FIELDS = ['stock_qty', 'safety_stock']
STOCK_UPDATED_BY_FIELD = 'stock_updated_by'
STOCK_WRITE_FIELDS = [
    'sku',
    'stock_qty',
    'unit',
    'safety_stock',
    'warehouse',
    'stock_updated_at',
    STOCK_UPDATED_BY_FIELD,
]

# 库存状态为派生值，实时计算，不落库存储
STOCK_STATUS_UNMAINTAINED = '未维护'
STOCK_STATUS_OUT = '缺货'
STOCK_STATUS_LOW = '偏低'
STOCK_STATUS_SUFFICIENT = '充足'
STOCK_STATUS_NORMAL = '正常'


def _as_optional_float(value: Any, label: str) -> Optional[float]:
    """库存数值：空值保持 None（表示未维护），非法值直接报错而不是静默填 0。

    与 orders._as_date_text 保持一致：把 'None' / 'NaN' / 'NaT' 这类脏值按空处理。
    """
    if value is None:
        return None
    text = str(value).strip()
    if text == '' or text.casefold() in {'none', 'nat', 'nan'}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        raise ValueError(f'{label}必须是数字，当前值：{value}') from None


def _coerce_float_or_none(value: Any) -> Optional[float]:
    """读取历史数据时使用：非法值按未维护处理，不抛异常。"""
    if value is None:
        return None
    text = str(value).strip()
    if text == '' or text.casefold() in {'none', 'nat', 'nan'}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def compute_stock_status(stock_qty: Any, safety_stock: Any) -> str:
    """派生库存状态。

    优先级：未维护 > 缺货 > 未设安全库存（正常）> 偏低 / 充足。
    stock_qty <= 0 一律为缺货，即使安全库存同为 0。
    """
    qty = _coerce_float_or_none(stock_qty)
    if qty is None:
        return STOCK_STATUS_UNMAINTAINED
    if qty <= 0:
        return STOCK_STATUS_OUT
    safety = _coerce_float_or_none(safety_stock)
    if safety is None:
        return STOCK_STATUS_NORMAL
    if qty < safety:
        return STOCK_STATUS_LOW
    return STOCK_STATUS_SUFFICIENT


def find_sku_conflicts(
    sku: Any,
    exclude_product_id: int | None = None,
) -> List[Dict[str, Any]]:
    """查找 SKU 冲突。

    产品表当前没有 user_id/归属字段（产品为共享基础数据），
    因此这里是**全局范围**查重；为空 SKU 不参与查重。
    """
    text = str(sku or '').strip()
    if not text or text.casefold() == 'none':
        return []
    query = (
        'SELECT id, product_name_en, product_name_cn, specification, created_at'
        ' FROM products WHERE sku = ?'
    )
    params: List[Any] = [text]
    if exclude_product_id is not None:
        query += ' AND id <> ?'
        params.append(exclude_product_id)
    query += ' ORDER BY id'
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _stock_write(
    item: Dict[str, Any],
    owner_id: int | None,
    *,
    force_stamp: bool = False,
) -> tuple[List[str], List[str], List[Any]]:
    """构造库存字段写入片段，返回 (列名, SQL 表达式, 参数)。

    只有确实写入了库存值（或强制盖章）时，才写入 stock_updated_at / stock_updated_by。
    """
    values = {field: item.get(field) for field in STOCK_WRITE_FIELDS}
    stock_provided = any(
        values[field] is not None for field in ('stock_qty', 'safety_stock')
    ) or bool(values.get('unit')) or bool(values.get('warehouse'))
    stamping = force_stamp or stock_provided
    if not values.get('stock_updated_at'):
        values['stock_updated_at'] = None
    if stamping and owner_id is not None:
        values[STOCK_UPDATED_BY_FIELD] = int(owner_id)

    assignments: List[tuple[str, str, Any]] = []
    for field in STOCK_WRITE_FIELDS:
        if field == 'stock_updated_at' and stamping:
            assignments.append((field, 'CURRENT_TIMESTAMP', None))
        else:
            assignments.append((field, '?', values[field]))
    columns = [field for field, _, _ in assignments]
    expressions = [expr for _, expr, _ in assignments]
    params = [value for _, expr, value in assignments if expr == '?']
    return columns, expressions, params


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key in [
        'product_name_en',
        'product_name_cn',
        'hs_code',
        'cas_no',
        'unit_price',
        'currency',
        'packaging_method',
        'gross_weight_per_carton',
        'net_weight_per_carton',
        'carton_volume_cbm',
        'specification',
        'msds_file_path',
        'product_description_en',
        'transport_info',
        'compliance_description',
        'sku',
        'unit',
        'warehouse',
        'stock_updated_at',
    ]:
        value = payload.get(key, '')
        if value is None:
            normalized[key] = ''
        elif isinstance(value, str):
            normalized[key] = value.strip()
        else:
            normalized[key] = value
    normalized['stock_qty'] = _as_optional_float(payload.get('stock_qty'), '库存数量')
    normalized['safety_stock'] = _as_optional_float(payload.get('safety_stock'), '安全库存')
    updated_by = payload.get(STOCK_UPDATED_BY_FIELD)
    if updated_by is None or str(updated_by).strip() == '':
        normalized[STOCK_UPDATED_BY_FIELD] = None
    else:
        try:
            normalized[STOCK_UPDATED_BY_FIELD] = int(updated_by)
        except (TypeError, ValueError):
            raise ValueError('库存更新人必须是用户 ID') from None
    return normalized


def validate_product_payload(payload: Dict[str, Any]) -> None:
    item = _normalize_payload(payload)
    missing = [field for field in REQUIRED_FIELDS if not item.get(field)]
    if missing:
        raise ValueError(f'以下字段为必填：{", ".join(missing)}')


def save_uploaded_pdf(uploaded_file) -> str:
    if uploaded_file is None:
        raise ValueError('请先上传 PDF 文件')
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    filename = uploaded_file.name
    safe_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', filename)
    file_path = settings.uploads_dir / safe_name
    if file_path.exists():
        suffix = file_path.suffix
        base = str(file_path).rsplit(suffix, 1)[0]
        counter = 1
        while True:
            candidate = Path(f'{base}_{counter}{suffix}')
            if not candidate.exists():
                file_path = candidate
                break
            counter += 1
    with open(file_path, 'wb') as target:
        target.write(uploaded_file.getvalue())
    return str(file_path)


def extract_text_from_pdf(pdf_path: str) -> str:
    try:
        with fitz.open(pdf_path) as doc:
            pages = []
            for page in doc:
                text = page.get_text()
                if text:
                    pages.append(text)
            return '\n'.join(pages)
    except Exception:
        return ''


def _extract_number(pattern: str, source: str) -> float:
    match_obj = re.search(pattern, source, flags=re.IGNORECASE)
    if not match_obj:
        return 0.0
    value = match_obj.group(1)
    try:
        return float(value)
    except ValueError:
        return 0.0


def extract_product_metadata_from_pdf(pdf_path: str) -> Dict[str, Any]:
    text = extract_text_from_pdf(pdf_path)
    if not text:
        return {}

    result: Dict[str, Any] = {}

    def match(pattern: str, flags: int = 0) -> str:
        match_obj = re.search(pattern, text, flags)
        return match_obj.group(1).strip() if match_obj and match_obj.group(1) else ''

    result['product_name_en'] = match(r'(?i)(?:product\s*name|产品英文名|品名).*?[:：]\s*([A-Za-z0-9\- /&().,]+)')
    result['product_name_cn'] = match(r'(?i)(?:中文品名|品名).*?[:：]\s*([^\n]+)')
    result['hs_code'] = match(r'(?i)(?:hs\s*code|hs编码|海关编码).*?[:：]\s*([0-9A-Za-z]+)')
    result['cas_no'] = match(r'(?i)(?:cas\s*no|cas号|cas).*?[:：]\s*([0-9-]+)')
    result['currency'] = 'USD' if 'usd' in text.lower() else 'CNY'
    result['packaging_method'] = match(r'(?i)(?:packaging|包装方式|包装).*?[:：]\s*([^\n]+)')
    result['gross_weight_per_carton'] = _extract_number(r'(?i)(?:gross weight|毛重).*?([0-9]+(?:\.[0-9]+)?)\s*(?:kg|kgs)', text)
    result['net_weight_per_carton'] = _extract_number(r'(?i)(?:net weight|净重).*?([0-9]+(?:\.[0-9]+)?)\s*(?:kg|kgs)', text)
    result['carton_volume_cbm'] = _extract_number(r'(?i)(?:volume|体积|cbm).*?([0-9]+(?:\.[0-9]+)?)\s*(?:m3|cbm)', text)
    result['specification'] = match(r'(?i)(?:specification|规格|型号).*?[:：]\s*([^\n]+)')
    result['product_description_en'] = text[:300].replace('\n', ' ')
    result['transport_info'] = match(r'(?i)(?:transport|shipping|运输).*?[:：]\s*([^\n]+)')
    result['compliance_description'] = 'Export compliant; user review required.' if any(keyword in text.lower() for keyword in ['hazard', 'dangerous', 'flammable']) else 'General export compliance review required.'

    return {k: v for k, v in result.items() if v not in ('', None, 0)}


def parse_chat_order_details(chat_text: str) -> Dict[str, Any]:
            
    text = chat_text or ''
    payload: Dict[str, Any] = {}

    patterns = {
        'product_name_en': r'(?i)(?:product\s*(?:name)?|品名|货名)\s*[:：]\s*([A-Za-z0-9\- /&().,]+)',
        'quantity': r'(?i)(?:quantity|数量|qty)\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)',
        'unit_price': r'(?i)(?:price|单价|unit price)\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)',
        'destination_port': r'(?i)(?:destination\s*port|目的港|港口)\s*[:：]\s*([A-Za-z0-9\- /]+)',
        'shipment_date': r'(?i)(?:delivery\s*date|交期|shipment\s*date)\s*[:：]\s*([0-9]{4}-?[0-9]{1,2}-?[0-9]{1,2})',
        'special_requirements': r'(?i)(?:special\s*requirements|特殊要求)\s*[:：]\s*([^\n]+)',
        'packaging_method': r'(?i)(?:packaging|包装要求)\s*[:：]\s*([^\n]+)',
    }

    for key, pattern in patterns.items():
        match_obj = re.search(pattern, text)
        if match_obj:
            value = match_obj.group(1).strip()
            payload[key] = value

    return payload


# ---------------------------------------------------------------------------
# 聊天 / 邮件产品识别
#   把客户原文切分为多条「客户需求」，再按优先级匹配产品库候选。
#   本组函数只做解析与只读查询，**不写入任何数据**；
#   「客户需求数量」与「实际库存」是两个互不相干的概念。
# ---------------------------------------------------------------------------

UNIT_ALIASES = {
    't': 'MT', 'mt': 'MT', 'mts': 'MT', 'ton': 'MT', 'tons': 'MT', '吨': 'MT',
    'kg': 'kg', 'kgs': 'kg', '千克': 'kg', '公斤': 'kg',
    'g': 'g', 'gram': 'g', 'grams': 'g', '克': 'g',
    'lb': 'lb', 'lbs': 'lb', '磅': 'lb',
    'carton': 'carton', 'cartons': 'carton', 'ctn': 'carton', '箱': 'carton', '纸箱': 'carton',
    'bag': 'bag', 'bags': 'bag', '袋': 'bag',
    'drum': 'drum', 'drums': 'drum', '桶': 'drum',
    'pallet': 'pallet', 'pallets': 'pallet', '托': 'pallet', '托盘': 'pallet',
    'pcs': 'pcs', 'pc': 'pcs', 'piece': 'pcs', 'pieces': 'pcs', '个': 'pcs', '件': 'pcs',
    'roll': 'roll', 'rolls': 'roll', '卷': 'roll',
    'l': 'L', 'liter': 'L', 'litre': 'L', '升': 'L',
}

MATCH_LEVEL_SKU = 'sku'
MATCH_LEVEL_NAME_SPEC = 'name_spec'
MATCH_LEVEL_NAME = 'name'
MATCH_LEVEL_FUZZY = 'fuzzy'

_UNIT_ALTERNATION = '|'.join(
    sorted((re.escape(unit) for unit in UNIT_ALIASES), key=len, reverse=True)
)
_QUANTITY_PATTERN = re.compile(
    rf'([0-9]+(?:[.,][0-9]+)?)\s*({_UNIT_ALTERNATION})(?![A-Za-z])',
    flags=re.IGNORECASE,
)

# 只按换行和句号切段；不用分号切，否则「产品：X；数量：Y」会被拆成两段丢失关联
_SEGMENT_SPLIT_PATTERN = re.compile(r'[\n。]+')
_LABELED_PRODUCT_PATTERN = re.compile(
    r'(?i)(?:product\s*name|product|品名|货名|产品名称|产品|货物)\s*[:：]\s*([^\n;；，,。]{1,80})'
)
_LABELED_CN_PATTERN = re.compile(r'(?:中文品名|中文名称|品名中文)\s*[:：]\s*([^\n;；，,。]{1,80})')
_LABELED_SKU_PATTERN = re.compile(
    r'(?i)(?:sku|货号|产品编号|物料编号|物料号|编号|item\s*no|part\s*no)\s*[:：]\s*([A-Za-z0-9\-_/]{1,40})'
)
_LABELED_SPEC_PATTERN = re.compile(
    r'(?i)(?:specification|spec|规格|型号|牌号|grade)\s*[:：]\s*([^\n;；，,。]{1,80})'
)
_CN_COMMODITY_PATTERN = re.compile(
    r'([\u4e00-\u9fa5]{2,12}(?:树脂|聚乙烯|聚丙烯|颗粒|粉料|板材|薄膜|型材|橡胶|石蜡|硫酸|纯碱|片碱))'
)
_NAME_TOKENS_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9\-/#.]*')
_PREFIX_SPLIT_PATTERN = re.compile(
    r'[\n;；，,。、：:（）()【】\[\]]'
    r'|(?:需要|须要|想要|采购|购买|订购|报价|请问|麻烦|另外|还有|以及|同时|客户说|请确认|现货|库存|我们|我司)'
    r'|(?i:\b(?:need|want|require|please|pls|plz|kindly|quote|quotation|inquiry|enquiry|'
    r'price|order|buy|purchase|also|other|another|we|i|for|with)\b)'
)
_GRADE_PATTERN = re.compile(r'\b([A-Za-z]{2,6})\s*([0-9][A-Za-z0-9\-]*)\b')


def normalize_unit(value: Any) -> str:
    """单位归一化：吨/MT/ton→MT，公斤/千克→kg … 未登记的单位返回去空格原文。"""
    text = str(value or '').strip()
    if not text:
        return ''
    return UNIT_ALIASES.get(text.casefold(), text)


def _escape_like(value: str) -> str:
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _run_select(sql: str, params: tuple[Any, ...]) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def _extract_unlabeled_name(snippet: str, qty_match) -> str:
    """从数量词之前取产品/牌号；取不到再退回牌号模式与中文品类模式。"""
    prefix = snippet[:qty_match.start()] if qty_match else snippet
    parts = [part.strip() for part in _PREFIX_SPLIT_PATTERN.split(prefix) if part.strip()]
    tail = parts[-1] if parts else ''
    tokens: List[str] = []
    for token in reversed(tail.split()):
        if _NAME_TOKENS_PATTERN.fullmatch(token):
            tokens.insert(0, token)
        else:
            break
    if tokens:
        candidate = ' '.join(tokens)
        if re.search(r'[A-Za-z]', candidate):
            return candidate
    grade = _GRADE_PATTERN.search(snippet)
    if grade:
        return f'{grade.group(1)} {grade.group(2)}'
    commodity = _CN_COMMODITY_PATTERN.search(snippet)
    if commodity:
        return commodity.group(1)
    return ''


def _build_request_item(block: str, qty_match) -> Dict[str, Any] | None:
    """把一段原文整理成一条客户需求；抓不到任何产品标识时返回 None（不编造）。"""
    snippet = block.strip()
    if not snippet:
        return None

    labeled = _LABELED_PRODUCT_PATTERN.search(snippet)
    product_name_en = labeled.group(1).strip(' ：:') if labeled else ''
    if not product_name_en:
        product_name_en = _extract_unlabeled_name(snippet, qty_match)

    labeled_cn = _LABELED_CN_PATTERN.search(snippet)
    labeled_sku = _LABELED_SKU_PATTERN.search(snippet)
    labeled_spec = _LABELED_SPEC_PATTERN.search(snippet)

    product_name_cn = labeled_cn.group(1).strip(' ：:') if labeled_cn else ''
    sku_hint = labeled_sku.group(1).strip() if labeled_sku else ''
    specification = labeled_spec.group(1).strip(' ：:') if labeled_spec else ''

    requested_qty: Optional[float] = None
    requested_unit = ''
    if qty_match:
        try:
            requested_qty = float(qty_match.group(1).replace(',', ''))
        except ValueError:
            requested_qty = None
        requested_unit = normalize_unit(qty_match.group(2))

    if not (product_name_en or product_name_cn or sku_hint):
        return None
    return {
        'raw_snippet': snippet,
        'product_name_en': product_name_en,
        'product_name_cn': product_name_cn,
        'sku_hint': sku_hint,
        'specification': specification,
        'requested_qty': requested_qty,
        'requested_unit': requested_unit,
    }


def parse_chat_product_requests(chat_text: str) -> List[Dict[str, Any]]:
    """把聊天/邮件原文切成多条客户需求。

    纯函数，无 AI、无网络、**不写数据库**。
    无法确定或原文未提及的字段一律留空。
    """
    text = str(chat_text or '')
    if not text.strip():
        return []

    items: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, Optional[float], str]] = set()
    for raw_segment in _SEGMENT_SPLIT_PATTERN.split(text):
        segment = raw_segment.strip()
        if not segment:
            continue
        quantities = list(_QUANTITY_PATTERN.finditer(segment))
        if len(quantities) <= 1:
            blocks = [(segment, quantities[0] if quantities else None)]
        else:
            blocks = []
            cursor = 0
            for match_obj in quantities:
                blocks.append((segment[cursor:match_obj.end()], match_obj))
                cursor = match_obj.end()
            tail = segment[cursor:].strip()
            if tail:
                blocks.append((tail, None))
        for block, qty_match in blocks:
            item = _build_request_item(block, qty_match)
            if item is None:
                continue
            key = (
                item['product_name_en'],
                item['sku_hint'],
                item['specification'],
                item['requested_qty'],
                item['requested_unit'],
            )
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def _to_candidates(
    rows: List[Dict[str, Any]],
    level: str,
    basis: str,
) -> List[Dict[str, Any]]:
    candidates = []
    for row in rows:
        candidate = dict(row)
        candidate['match_level'] = level
        candidate['match_basis'] = basis
        candidates.append(candidate)
    return candidates


def match_products_for_request(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按优先级匹配已有产品：SKU > 品名+规格 > 品名。

    只返回**命中的最高一级**，避免把模糊结果和精确结果混在一起。
    只读查询，不写数据库。
    """
    source = item or {}
    name = str(source.get('product_name_en') or '').strip()
    name_cn = str(source.get('product_name_cn') or '').strip()
    sku = str(source.get('sku_hint') or '').strip()
    spec = str(source.get('specification') or '').strip()
    if not (name or name_cn or sku or spec):
        return []

    # 1) SKU 完全一致
    if sku:
        rows = _run_select(
            "SELECT * FROM products WHERE LOWER(TRIM(COALESCE(sku, ''))) = ? ORDER BY id",
            (sku.casefold(),),
        )
        if rows:
            return _to_candidates(rows, MATCH_LEVEL_SKU, f'SKU 完全一致：{sku}')

    like_token = f"%{_escape_like(name.casefold())}%" if name else None
    cn_token = f"%{_escape_like(name_cn.casefold())}%" if name_cn else None

    # 2) 品名 + 规格
    if (name or name_cn) and spec:
        spec_token = f"%{_escape_like(spec.casefold())}%"
        rows = _run_select(
            """
            SELECT * FROM products
            WHERE (
                    LOWER(COALESCE(product_name_en, '')) LIKE ? ESCAPE '\\'
                 OR LOWER(COALESCE(product_name_cn, '')) LIKE ? ESCAPE '\\'
                 OR LOWER(COALESCE(sku, '')) LIKE ? ESCAPE '\\'
            ) AND (
                    LOWER(COALESCE(specification, '')) LIKE ? ESCAPE '\\'
                 OR LOWER(COALESCE(product_name_en, '')) LIKE ? ESCAPE '\\'
                 OR LOWER(COALESCE(product_name_cn, '')) LIKE ? ESCAPE '\\'
            )
            ORDER BY id
            """,
            (
                like_token or cn_token or '',
                cn_token or like_token or '',
                like_token or cn_token or '',
                spec_token,
                spec_token,
                spec_token,
            ),
        )
        if rows:
            return _to_candidates(rows, MATCH_LEVEL_NAME_SPEC, f'品名 + 规格匹配：{name or name_cn} / {spec}')

    # 3) 仅品名：完全一致为明确，包含关系为模糊
    if name or name_cn:
        rows = _run_select(
            """
            SELECT * FROM products
            WHERE LOWER(COALESCE(product_name_en, '')) LIKE ? ESCAPE '\\'
               OR LOWER(COALESCE(product_name_cn, '')) LIKE ? ESCAPE '\\'
               OR LOWER(COALESCE(sku, '')) LIKE ? ESCAPE '\\'
            ORDER BY id
            """,
            (
                like_token or cn_token or '',
                cn_token or like_token or '',
                like_token or cn_token or '',
            ),
        )
        candidates = []
        for row in rows:
            english = str(row.get('product_name_en') or '').strip().casefold()
            chinese = str(row.get('product_name_cn') or '').strip().casefold()
            row_sku = str(row.get('sku') or '').strip().casefold()
            exact = bool(
                (name and english == name.casefold())
                or (name_cn and chinese == name_cn.casefold())
                or (name and row_sku == name.casefold())
            )
            candidates.extend(
                _to_candidates(
                    [row],
                    MATCH_LEVEL_NAME if exact else MATCH_LEVEL_FUZZY,
                    f'品名完全一致：{name or name_cn}' if exact else f'品名部分包含：{name or name_cn}',
                )
            )
        return candidates
    return []


def single_match_id(candidates: List[Dict[str, Any]]) -> int | None:
    """仅当有且只有一个候选时返回产品 ID；多个候选必须人工选择。"""
    if len(candidates) != 1:
        return None
    try:
        return int(candidates[0]['id'])
    except (TypeError, ValueError):
        return None


def evaluate_demand_vs_stock(
    product: Dict[str, Any] | None,
    requested_qty: Any,
    requested_unit: Any,
) -> Dict[str, Any]:
    """比较客户需求与实际库存。

    只在「产品明确 + 需求数量明确 + 单位一致（或双方都未填写）」时才给出结论，
    其余情况返回 comparable=False 并说明原因，**不强行比较、不做单位换算**。
    """
    source = product or {}
    demand = _coerce_float_or_none(requested_qty)
    if demand is None or demand <= 0:
        return {'comparable': False, 'enough': None, 'reason': '客户需求数量未明确'}
    stock = _coerce_float_or_none(source.get('stock_qty'))
    if stock is None:
        return {'comparable': False, 'enough': None, 'reason': '该产品库存未维护'}
    stock_unit = normalize_unit(source.get('unit'))
    demand_unit = normalize_unit(requested_unit)
    if stock_unit != demand_unit:
        return {
            'comparable': False,
            'enough': None,
            'reason': f'单位不一致（库存 {stock_unit or "未填写"} / 需求 {demand_unit or "未填写"}）',
        }
    return {'comparable': True, 'enough': stock >= demand, 'reason': ''}


def build_product_payload_from_request(
    item: Dict[str, Any],
    currency: str = 'USD',
) -> Dict[str, Any]:
    """把客户需求整理成**产品资料**（不含库存）。

    刻意不含任何库存字段，也绝不把 requested_qty 写进 stock_qty：
    新增产品资料 ≠ 库存入库。
    """
    source = item or {}
    return {
        'product_name_en': str(source.get('product_name_en') or '').strip(),
        'product_name_cn': str(source.get('product_name_cn') or '').strip(),
        'specification': str(source.get('specification') or '').strip(),
        'sku': str(source.get('sku_hint') or '').strip(),
        'currency': currency or 'USD',
    }


def create_product(payload: Dict[str, Any], owner_id: int | None = None) -> int:
    validate_product_payload(payload)
    item = _normalize_payload(payload)
    stock_columns, stock_expressions, stock_params = _stock_write(item, owner_id)
    with get_connection() as conn:
        cursor = conn.execute(
            f"""
            INSERT INTO products (
                product_name_en,
                product_name_cn,
                hs_code,
                cas_no,
                unit_price,
                currency,
                packaging_method,
                gross_weight_per_carton,
                net_weight_per_carton,
                carton_volume_cbm,
                specification,
                msds_file_path,
                product_description_en,
                transport_info,
                compliance_description,
                {', '.join(stock_columns)}
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {', '.join(stock_expressions)})
            """,
            (
                item['product_name_en'],
                item['product_name_cn'],
                item['hs_code'],
                item['cas_no'],
                float(item['unit_price']) if item['unit_price'] else 0.0,
                item['currency'],
                item['packaging_method'],
                float(item['gross_weight_per_carton']) if item['gross_weight_per_carton'] else 0.0,
                float(item['net_weight_per_carton']) if item['net_weight_per_carton'] else 0.0,
                float(item['carton_volume_cbm']) if item['carton_volume_cbm'] else 0.0,
                item['specification'],
                item['msds_file_path'],
                item['product_description_en'],
                item['transport_info'],
                item['compliance_description'],
                *stock_params,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_products(search_text: str = '') -> List[Dict[str, Any]]:
    query = 'SELECT * FROM products WHERE 1 = 1'
    params: List[Any] = []
    if search_text and search_text.strip():
        query += ' AND (product_name_en LIKE ? OR product_name_cn LIKE ? OR hs_code LIKE ? OR cas_no LIKE ?)'
        keyword = f"%{search_text.strip()}%"
        params.extend([keyword, keyword, keyword, keyword])
    query += ' ORDER BY updated_at DESC, id DESC'
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_product_by_id(product_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
        return dict(row) if row else None


def update_product(
    product_id: int,
    payload: Dict[str, Any],
    owner_id: int | None = None,
) -> None:
    validate_product_payload(payload)
    item = _normalize_payload(payload)
    stock_columns, stock_expressions, stock_params = _stock_write(item, owner_id)
    stock_set = ', '.join(
        f'{column} = {expression}'
        for column, expression in zip(stock_columns, stock_expressions)
    )
    with get_connection() as conn:
        conn.execute(
            f"""
            UPDATE products SET
                product_name_en = ?,
                product_name_cn = ?,
                hs_code = ?,
                cas_no = ?,
                unit_price = ?,
                currency = ?,
                packaging_method = ?,
                gross_weight_per_carton = ?,
                net_weight_per_carton = ?,
                carton_volume_cbm = ?,
                specification = ?,
                msds_file_path = ?,
                product_description_en = ?,
                transport_info = ?,
                compliance_description = ?,
                {stock_set},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                item['product_name_en'],
                item['product_name_cn'],
                item['hs_code'],
                item['cas_no'],
                float(item['unit_price']) if item['unit_price'] else 0.0,
                item['currency'],
                item['packaging_method'],
                float(item['gross_weight_per_carton']) if item['gross_weight_per_carton'] else 0.0,
                float(item['net_weight_per_carton']) if item['net_weight_per_carton'] else 0.0,
                float(item['carton_volume_cbm']) if item['carton_volume_cbm'] else 0.0,
                item['specification'],
                item['msds_file_path'],
                item['product_description_en'],
                item['transport_info'],
                item['compliance_description'],
                *stock_params,
                product_id,
            ),
        )
        conn.commit()


def update_product_stock(
    product_id: int,
    payload: Dict[str, Any],
    owner_id: int | None = None,
) -> None:
    """只更新库存相关字段。

    与 update_product 的区别：**不触发产品必填字段校验**（product_name_en / currency），
    因此可以在没有完整产品资料的情况下单独维护库存。
    """
    writable = [
        field
        for field in ('sku', 'stock_qty', 'unit', 'safety_stock', 'warehouse')
        if field in payload
    ]
    if not writable:
        raise ValueError('未提供需要更新的库存字段。')
    item = _normalize_payload(payload)
    assignments = [f'{field} = ?' for field in writable]
    params: List[Any] = [item[field] for field in writable]
    assignments.append('stock_updated_at = CURRENT_TIMESTAMP')
    assignments.append('stock_updated_by = ?')
    params.append(owner_id)
    assignments.append('updated_at = CURRENT_TIMESTAMP')
    params.append(product_id)

    with get_connection() as conn:
        existing = conn.execute(
            'SELECT id FROM products WHERE id = ?', (product_id,)
        ).fetchone()
        if existing is None:
            raise ValueError('产品不存在，无法更新库存。')
        conn.execute(
            f'UPDATE products SET {", ".join(assignments)} WHERE id = ?',
            params,
        )
        conn.commit()


def delete_product(product_id: int) -> None:
    with get_connection() as conn:
        conn.execute('DELETE FROM products WHERE id = ?', (product_id,))
        conn.commit()


PRODUCT_EXPORT_HEADERS = [
    '产品编码(SKU)', '中文品名', '英文品名', '规格/牌号', 'HS编码', 'CAS号',
    '包装方式', '单价', '币种', '库存数量', '库存单位', '库存快照时间',
    'MSDS资料', '更新时间',
]
# 编码类字段按文本保存：避免前导零丢失或变科学计数法
PRODUCT_EXPORT_TEXT_COLUMNS = {1, 5, 6}
PRODUCT_EXPORT_NUMBER_COLUMNS = {8, 10}


def product_export_rows(search_text: str = '') -> List[List[Any]]:
    """导出用取数：附件只记录有无，不导出文件路径。"""
    products = list_products(search_text)
    rows: List[List[Any]] = []
    for product in products:
        stock_qty = product.get('stock_qty')
        unit_price = product.get('unit_price')
        rows.append([
            product.get('sku') or '',
            product.get('product_name_cn') or '',
            product.get('product_name_en') or '',
            product.get('specification') or '',
            product.get('hs_code') or '',
            product.get('cas_no') or '',
            product.get('packaging_method') or '',
            '' if unit_price is None else unit_price,
            product.get('currency') or '',
            # 未维护（NULL）与真实 0 必须区分：未维护导出为文本，0 导出为数字
            STOCK_STATUS_UNMAINTAINED if stock_qty is None else stock_qty,
            product.get('unit') or '',
            product.get('stock_updated_at') or '',
            '有' if product.get('msds_file_path') else '无',
            product.get('updated_at') or '',
        ])
    return rows


def export_products_excel(search_text: str = '') -> tuple[str, bytes]:
    """导出产品资料为（文件名, 字节流）。产品为共享数据，不按归属过滤。"""
    return build_table_export_file(
        '产品',
        '产品',
        PRODUCT_EXPORT_HEADERS,
        product_export_rows(search_text),
        text_columns=PRODUCT_EXPORT_TEXT_COLUMNS,
        number_columns=PRODUCT_EXPORT_NUMBER_COLUMNS,
    )


if __name__ == '__main__':
    print('products module loaded')
