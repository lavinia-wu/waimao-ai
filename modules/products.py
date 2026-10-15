from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz

from config.settings import settings
from database.db import get_connection


REQUIRED_FIELDS = [
    'product_name_en',
    'currency',
]


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
    ]:
        value = payload.get(key, '')
        if value is None:
            normalized[key] = ''
        elif isinstance(value, str):
            normalized[key] = value.strip()
        else:
            normalized[key] = value
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


def create_product(payload: Dict[str, Any]) -> int:
    validate_product_payload(payload)
    item = _normalize_payload(payload)
    with get_connection() as conn:
        cursor = conn.execute(
            """
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
                compliance_description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def update_product(product_id: int, payload: Dict[str, Any]) -> None:
    validate_product_payload(payload)
    item = _normalize_payload(payload)
    with get_connection() as conn:
        conn.execute(
            """
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
                product_id,
            ),
        )
        conn.commit()


def delete_product(product_id: int) -> None:
    with get_connection() as conn:
        conn.execute('DELETE FROM products WHERE id = ?', (product_id,))
        conn.commit()


if __name__ == '__main__':
    print('products module loaded')
