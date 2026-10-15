from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from database.db import get_connection


CUSTOMER_FIELDS = [
    'customer_name_cn',
    'customer_name_en',
    'company_address',
    'contact_person',
    'email',
    'phone',
    'destination_port',
    'payment_terms',
    'incoterm',
]


def _normalize_customer(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {}
    for key in CUSTOMER_FIELDS + ['remark']:
        value = payload.get(key, '')
        normalized[key] = str(value).strip() if value is not None else ''
    return normalized


def validate_customer_payload(payload: Dict[str, Any]) -> None:
    normalized = _normalize_customer(payload)
    if not normalized['customer_name_cn'] and not normalized['customer_name_en']:
        raise ValueError('客户中文名和英文名至少填写一项。')


def find_matching_customer(payload: Dict[str, Any], owner_id: int | None = None) -> Optional[Dict[str, Any]]:
    item = _normalize_customer(payload)
    names = {
        value.casefold()
        for value in (item['customer_name_cn'], item['customer_name_en'])
        if value
    }
    if not names:
        return None
    customers = list_customers(owner_id=owner_id)
    matches = [
        customer for customer in customers
        if names.intersection({
            str(customer.get('customer_name_cn') or '').strip().casefold(),
            str(customer.get('customer_name_en') or '').strip().casefold(),
        })
    ]
    if len(matches) > 1:
        raise ValueError('客户名称匹配到多条记录，请在客户列表中先确认正确的客户。')
    return matches[0] if matches else None


def get_or_create_customer(payload: Dict[str, Any], owner_id: int | None = None) -> tuple[int, bool]:
    validate_customer_payload(payload)
    existing = find_matching_customer(payload, owner_id)
    if existing:
        return int(existing['id']), False
    if owner_id is not None:
        assigned_elsewhere = find_matching_customer(payload)
        if assigned_elsewhere:
            raise ValueError('该客户已分配给其他业务员，请联系管理员调整客户归属。')
    return create_customer(payload, owner_id), True


def create_customer(payload: Dict[str, Any], owner_id: int | None = None) -> int:
    validate_customer_payload(payload)
    item = _normalize_customer(payload)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO customers (
                customer_name_cn,
                customer_name_en,
                company_address,
                contact_person,
                email,
                phone,
                destination_port,
                payment_terms,
                incoterm,
                remark,
                user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item['customer_name_cn'],
                item['customer_name_en'],
                item['company_address'],
                item['contact_person'],
                item['email'],
                item['phone'],
                item['destination_port'],
                item['payment_terms'],
                item['incoterm'],
                item['remark'],
                owner_id,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_customers(search_text: str = '', owner_id: int | None = None) -> List[Dict[str, Any]]:
    query = """
        SELECT * FROM customers
        WHERE 1 = 1
    """
    params: list[Any] = []
    if owner_id is not None:
        query += ' AND user_id = ?'
        params.append(owner_id)
    if search_text and search_text.strip():
        query += """
            AND (
                customer_name_cn LIKE ? OR
                customer_name_en LIKE ? OR
                company_address LIKE ? OR
                contact_person LIKE ? OR
                email LIKE ? OR
                phone LIKE ?
            )
        """
        keyword = f'%{search_text.strip()}%'
        params.extend([keyword] * 6)
    query += ' ORDER BY updated_at DESC, id DESC'

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_customer_by_id(customer_id: int, owner_id: int | None = None) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        query = 'SELECT * FROM customers WHERE id = ?'
        params: list[Any] = [customer_id]
        if owner_id is not None:
            query += ' AND user_id = ?'
            params.append(owner_id)
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None


def update_customer(customer_id: int, payload: Dict[str, Any], owner_id: int | None = None) -> None:
    validate_customer_payload(payload)
    item = _normalize_customer(payload)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE customers SET
                customer_name_cn = ?,
                customer_name_en = ?,
                company_address = ?,
                contact_person = ?,
                email = ?,
                phone = ?,
                destination_port = ?,
                payment_terms = ?,
                incoterm = ?,
                remark = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND (? IS NULL OR user_id = ?)
            """,
            (
                item['customer_name_cn'],
                item['customer_name_en'],
                item['company_address'],
                item['contact_person'],
                item['email'],
                item['phone'],
                item['destination_port'],
                item['payment_terms'],
                item['incoterm'],
                item['remark'],
                customer_id,
                owner_id,
                owner_id,
            ),
        )
        if conn.execute('SELECT changes()').fetchone()[0] == 0:
            raise ValueError('客户不存在或不属于当前业务员。')
        conn.commit()


def delete_customer(customer_id: int, owner_id: int | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            'DELETE FROM customers WHERE id = ? AND (? IS NULL OR user_id = ?)',
            (customer_id, owner_id, owner_id),
        )
        if conn.execute('SELECT changes()').fetchone()[0] == 0:
            raise ValueError('客户不存在或不属于当前业务员。')
        conn.commit()


def export_customers_excel(file_path: str, search_text: str = '', owner_id: int | None = None) -> str:
    import pandas as pd

    data = list_customers(search_text, owner_id)
    df = pd.DataFrame(data)
    if not df.empty:
        df = df[[
            'id', 'customer_name_cn', 'customer_name_en', 'company_address', 'contact_person',
            'email', 'phone', 'destination_port', 'payment_terms', 'incoterm', 'remark',
            'created_at', 'updated_at'
        ]]
    df.to_excel(file_path, index=False)
    return file_path


def import_customers_excel(content: bytes, owner_id: int | None) -> Dict[str, Any]:
    import pandas as pd
    from io import BytesIO

    try:
        frame = pd.read_excel(BytesIO(content), dtype=str).fillna('')
    except Exception as exc:
        raise ValueError(f'无法读取 Excel 文件：{exc}') from exc
    if frame.empty:
        raise ValueError('Excel 文件没有可导入的客户数据。')

    aliases = {
        'customer_name_cn': {'客户中文名', '中文名', '客户名称中文', '公司中文名', 'customernamecn', 'chinesename'},
        'customer_name_en': {'客户英文名', '英文名', '客户名称英文', '公司英文名', 'customernameen', 'englishname'},
        'company_address': {'公司地址', '地址', 'companyaddress', 'address'},
        'contact_person': {'联系人', '联系人姓名', 'contactperson', 'contact'},
        'email': {'邮箱', '电子邮箱', 'email', 'mail'},
        'phone': {'电话', '联系电话', '手机号', 'phone', 'telephone'},
        'destination_port': {'目的港', '常用目的港', 'destinationport'},
        'payment_terms': {'付款方式', '付款条款', 'paymentterms'},
        'incoterm': {'贸易条款', '贸易术语', 'incoterm'},
        'remark': {'备注', '说明', 'remark', 'note'},
    }
    normalized_headers = {
        re.sub(r'[\s_\-（）()]+', '', str(column)).casefold(): column
        for column in frame.columns
    }
    column_map: Dict[str, Any] = {}
    for field, field_aliases in aliases.items():
        for alias in field_aliases:
            normalized_alias = re.sub(r'[\s_\-（）()]+', '', alias).casefold()
            if normalized_alias in normalized_headers:
                column_map[field] = normalized_headers[normalized_alias]
                break
    if not {'customer_name_cn', 'customer_name_en'}.intersection(column_map):
        raise ValueError('未识别客户名称列。请使用“客户中文名”和/或“客户英文名”作为表头。')

    imported = 0
    duplicates = 0
    errors: List[str] = []
    seen: set[tuple[str, str]] = set()
    for index, row in frame.iterrows():
        payload = {
            field: str(row[column]).strip() if row[column] else ''
            for field, column in column_map.items()
        }
        if not payload.get('customer_name_cn') and not payload.get('customer_name_en'):
            if any(value for value in payload.values()):
                errors.append(f'第 {index + 2} 行：缺少客户中文名和英文名。')
            continue
        key = (
            payload.get('customer_name_cn', '').casefold(),
            payload.get('customer_name_en', '').casefold(),
        )
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        try:
            _, created = get_or_create_customer(payload, owner_id)
            if not created:
                duplicates += 1
                continue
            imported += 1
        except ValueError as exc:
            errors.append(f'第 {index + 2} 行：{exc}')
    return {'imported': imported, 'duplicates': duplicates, 'errors': errors}
