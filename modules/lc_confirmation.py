from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any

from modules.lc_deadlines import parse_date


FIELD_GROUPS = [
    ('基本信息组', [
        ('lc_no', '信用证编号', 'text', True, ('L/C No.', 'LC No.', '信用证号')),
        ('issuing_bank', '开证行', 'text', False, ('Issuing Bank', '开证行')),
        ('applicant', '申请人', 'text', True, ('Applicant', '申请人')),
        ('beneficiary', '受益人', 'text', True, ('Beneficiary', '受益人')),
    ]),
    ('金额与贸易条款组', [
        ('lc_amount', '信用证金额', 'number', True, ('Amount', 'LC Amount', '金额')),
        ('currency', '币种', 'text', True, ('Currency', '币种', '币别')),
        ('tolerance_percentage', '金额溢短装百分比', 'number', False, ('Tolerance', '溢短装')),
        ('unit_price', '单价', 'number', False, ('Unit Price', '单价')),
        ('incoterm', '贸易条款', 'text', False, ('Incoterm', 'Incoterms', '贸易条款')),
    ]),
    ('日期组', [
        ('issue_date', '开证日期', 'date', False, ('Issue Date', '开证日期')),
        ('latest_shipment_date', '最迟装运日', 'date', False, ('Latest Shipment Date', '最迟装运日')),
        ('presentation_deadline', '固定交单截止日', 'date', False, ('Presentation Deadline', '交单截止日')),
        ('expiry_date', '信用证有效期', 'date', False, ('Expiry Date', 'Expiration Date', '有效期')),
    ]),
    ('港口与运输组', [
        ('loading_port', '起运港', 'text', False, ('Port of Loading', 'Loading Port', '起运港')),
        ('discharge_port', '目的港', 'text', False, ('Port of Discharge', 'Discharge Port', '目的港')),
        ('transshipment_allowed', '是否允许转运', 'boolean', False, ('Transshipment', '转运')),
        ('partial_shipment_allowed', '是否允许分批装运', 'boolean', False, ('Partial Shipment', '分批装运')),
        ('presentation_period', '交单期限原文', 'text', False, ('Presentation Period', '交单期限')),
        ('presentation_period_days', '装运后交单天数', 'number', False, ('Presentation Period', '交单期限')),
        ('dispatch_days_after_shipment', '装运后寄单天数', 'number', False, ('Dispatch Days', '寄单天数')),
        ('dispatch_instruction', '寄单说明', 'text', False, ('Dispatch Instruction', '寄单说明')),
    ]),
    ('货物描述组', [
        ('goods_description', '货物描述', 'multiline', True, ('Description of Goods', 'Goods Description', '货物描述')),
        ('product_name_en', '英文品名', 'text', False, ('Product Name', '品名')),
        ('quantity', '数量', 'number', False, ('Quantity', 'Qty', '数量')),
        ('unit', '数量单位', 'text', False, ('Unit', '单位')),
    ]),
]

REQUIRED_FIELDS = ('lc_no', 'applicant', 'beneficiary', 'lc_amount', 'currency', 'goods_description')
DOCUMENT_ROW_FIELDS = {
    'document_type': ('document_type', '单据类型'),
    'original_count': ('original_count', '正本份数'),
    'copy_count': ('copy_count', '副本份数'),
    'special_requirements': ('special_requirements', '特殊要求', 'requirements'),
}


def _numeric(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool) or str(value).strip() == '':
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip().replace(',', '')
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _plain_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def normalize_field_value(field: str, kind: str, value: Any) -> Any:
    if kind == 'date':
        if _is_blank(value):
            return ''
        parsed = value if isinstance(value, date) else parse_date(value)
        if isinstance(parsed, datetime):
            parsed = parsed.date()
        return parsed.isoformat() if parsed else ''
    if kind == 'number':
        if _is_blank(value):
            return None
        number = _numeric(value)
        if number is None:
            return value
        return _plain_value(number)
    if kind == 'boolean':
        if _is_blank(value):
            return ''
        if isinstance(value, bool):
            return 'Yes' if value else 'No'
        normalized = str(value or '').strip().casefold()
        if normalized in {'yes', 'true', '1', '允许', '是'}:
            return 'Yes'
        if normalized in {'no', 'false', '0', '不允许', '否'}:
            return 'No'
        return ''
    return '' if _is_blank(value) else str(value).strip()


def _row_value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row and not _is_blank(row.get(name)):
            return row.get(name)
    for name in names:
        if name in row:
            return row.get(name)
    return None


def normalize_document_row(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row if isinstance(row, dict) else {}
    source_index = row.get('_source_index')
    if _is_blank(source_index):
        source_index = None
    else:
        try:
            source_index = int(source_index)
        except (TypeError, ValueError):
            source_index = None
    document_type = _row_value(row, DOCUMENT_ROW_FIELDS['document_type'])
    special_requirements = _row_value(row, DOCUMENT_ROW_FIELDS['special_requirements'])
    return {
        '_source_index': source_index,
        'document_type': '' if _is_blank(document_type) else str(document_type).strip(),
        'original_count': _row_value(row, DOCUMENT_ROW_FIELDS['original_count']),
        'copy_count': _row_value(row, DOCUMENT_ROW_FIELDS['copy_count']),
        'special_requirements': (
            '' if _is_blank(special_requirements) else str(special_requirements).strip()
        ),
    }


def normalize_document_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [normalize_document_row(row) for row in rows or []]


def validate_confirmation(
    values: dict[str, Any],
    document_rows: list[dict[str, Any]],
) -> list[str]:
    errors = []
    field_map = {
        field: (label, kind, required)
        for _, fields in FIELD_GROUPS
        for field, label, kind, required, _ in fields
    }
    for field in REQUIRED_FIELDS:
        label, _, _ = field_map[field]
        if _is_blank(values.get(field)):
            errors.append(f'{label}为必填项。')
    for field, (label, kind, _) in field_map.items():
        value = values.get(field)
        if _is_blank(value):
            continue
        if kind == 'date' and not parse_date(value):
            errors.append(f'{label}格式无效，请选择有效日期。')
        elif kind == 'number' and _numeric(value) is None:
            errors.append(f'{label}必须是有效数值。')
        elif kind == 'number' and _numeric(value) < 0:
            errors.append(f'{label}不能为负数。')
    for index, row in enumerate(normalize_document_rows(document_rows), start=1):
        if _is_blank(row.get('document_type')):
            errors.append(f'单据要求第 {index} 行必须填写单据类型。')
        for field, label in (
            ('original_count', '正本份数'),
            ('copy_count', '副本份数'),
        ):
            value = row.get(field)
            if _is_blank(value):
                continue
            number = _numeric(value)
            if number is None or number != number.to_integral_value():
                errors.append(f'单据要求第 {index} 行{label}必须是整数。')
            elif number < 0:
                errors.append(f'单据要求第 {index} 行{label}不能为负数。')
    return errors


def build_change_summary(
    ai_values: dict[str, Any],
    confirmed_values: dict[str, Any],
) -> list[dict[str, Any]]:
    summary = []
    for _, fields in FIELD_GROUPS:
        for field, label, kind, _, _ in fields:
            ai_value = normalize_field_value(field, kind, ai_values.get(field))
            confirmed_value = normalize_field_value(field, kind, confirmed_values.get(field))
            summary.append({
                '字段名': label,
                'AI识别值': ai_value if ai_value not in (None, '') else '未识别',
                '人工修改值': confirmed_value if confirmed_value not in (None, '') else '未填写',
                '是否修改': '是' if ai_value != confirmed_value else '否',
            })
    return summary


def merge_confirmed_values(
    ai_values: dict[str, Any],
    confirmed_values: dict[str, Any],
    document_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    merged = dict(ai_values)
    for _, fields in FIELD_GROUPS:
        for field, _, kind, _, _ in fields:
            value = confirmed_values.get(field)
            normalized = normalize_field_value(field, kind, value)
            if kind == 'number' and normalized is None and _is_blank(value):
                merged[field] = None
            elif kind == 'date':
                merged[field] = normalized
            elif kind == 'boolean':
                merged[field] = normalized
            else:
                merged[field] = normalized

    original_requirements = ai_values.get('documents_required') or []
    requirements = []
    for row in normalize_document_rows(document_rows):
        document_type = row.get('document_type') or ''
        if not document_type:
            continue
        source_index = row.get('_source_index')
        original = {}
        if source_index is not None:
            try:
                original = original_requirements[int(source_index)]
            except (ValueError, TypeError, IndexError):
                original = {}
        requirement = dict(original)
        requirement.update({
            'document_type': document_type,
            'original_count': _optional_nonnegative_int(row.get('original_count')),
            'copy_count': _optional_nonnegative_int(row.get('copy_count')),
            'special_requirements': row.get('special_requirements') or '',
        })
        requirements.append(requirement)
    merged['documents_required'] = requirements
    return merged


def _optional_nonnegative_int(value: Any) -> int | None:
    if _is_blank(value):
        return None
    number = _numeric(value)
    if number is None or number != number.to_integral_value() or number < 0:
        return None
    return int(number)


def _is_blank(value: Any) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return type(value).__name__ in {'NAType', 'NaTType'}


def _excerpt(text: str, aliases: tuple[str, ...], value: Any) -> str:
    if not text:
        return '未能定位对应内容，请对照全文核实。'
    for alias in aliases:
        match = re.search(re.escape(alias), text, flags=re.IGNORECASE)
        if match:
            start = text.rfind('\n', 0, match.start())
            end = text.find('\n', match.end())
            if end == -1:
                end = min(len(text), match.end() + 240)
            else:
                end = min(len(text), end + 1)
            if end <= match.end() + 1:
                end = min(len(text), match.end() + 240)
            excerpt = text[max(0, start + 1):end].strip()
            if excerpt:
                return excerpt
    value_text = str(value or '').strip()
    if value_text:
        match = re.search(re.escape(value_text), text, flags=re.IGNORECASE)
        if match:
            return text[max(0, match.start() - 100):min(len(text), match.end() + 140)].strip()
    return '未能定位对应内容，请对照全文核实。'


def source_excerpts(
    raw_text: str,
    translation_text: str,
    field: str,
    value: Any,
) -> tuple[str, str]:
    aliases = next(
        (
            aliases
            for _, fields in FIELD_GROUPS
            for candidate, _, _, _, aliases in fields
            if candidate == field
        ),
        (),
    )
    if field == 'documents_required':
        aliases = ('Documents Required', 'Documents to be presented', '单据要求', '单据份数')
    return (
        _excerpt(raw_text, aliases, value),
        _excerpt(translation_text, aliases, value),
    )
