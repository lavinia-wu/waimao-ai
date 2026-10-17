from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any, Dict, List, Optional

from database.db import get_connection


REQUIRED_FIELDS = ['order_no', 'customer_id', 'product_id', 'quantity', 'unit', 'unit_price', 'currency']


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_date_text(value: Any) -> str:
    if value is None or value == '':
        return ''
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if text.casefold() in {'none', 'nat', 'nan'}:
        return ''
    return text


def validate_order_payload(payload: Dict[str, Any]) -> None:
    missing = []
    for field in REQUIRED_FIELDS:
        value = payload.get(field)
        if field in ('customer_id', 'product_id') and value in (None, ''):
            missing.append(field)
        elif field == 'quantity' and _as_float(value) <= 0:
            missing.append(field)
        elif field == 'unit' and not str(value).strip():
            missing.append(field)
        elif field in ('unit_price', 'currency') and not str(value).strip():
            missing.append(field)
        elif field == 'order_no' and not str(value).strip():
            missing.append(field)
    if missing:
        raise ValueError(f'以下字段为必填：{", ".join(missing)}')


def calculate_totals(quantity: Any, unit_price: Any, gross_weight_per_carton: Any = 0, net_weight_per_carton: Any = 0, carton_volume_cbm: Any = 0) -> Dict[str, float]:
    qty = _as_float(quantity)
    price = _as_float(unit_price)
    gross = _as_float(gross_weight_per_carton)
    net = _as_float(net_weight_per_carton)
    volume = _as_float(carton_volume_cbm)

    total_amount = qty * price
    total_gross_weight = qty * gross
    total_net_weight = qty * net
    total_volume = qty * volume
    cartons = max(1, math.ceil(qty)) if qty > 0 else 0
    return {
        'quantity': qty,
        'unit_price': price,
        'total_amount': total_amount,
        'total_gross_weight': total_gross_weight,
        'total_net_weight': total_net_weight,
        'total_volume': total_volume,
        'carton_count': cartons,
    }


def create_order(payload: Dict[str, Any]) -> int:
    validate_order_payload(payload)
    with get_connection() as conn:
        order_no = str(payload['order_no']).strip()
        customer_id = int(payload['customer_id'])
        product_id = int(payload['product_id'])
        customer = conn.execute(
            'SELECT user_id FROM customers WHERE id = ?',
            (customer_id,),
        ).fetchone()
        if customer is None:
            raise ValueError('所选客户不存在。')
        owner_id = payload.get('user_id', customer['user_id'])
        if customer['user_id'] != owner_id:
            raise ValueError('订单必须归属于客户的业务员。')
        quantity = _as_float(payload.get('quantity'))
        unit = str(payload.get('unit', '')).strip()
        unit_price = _as_float(payload.get('unit_price'))
        currency = str(payload.get('currency', '')).strip()
        loading_port = str(payload.get('loading_port', '')).strip()
        destination_port = str(payload.get('destination_port', '')).strip()
        incoterm = str(payload.get('incoterm', '')).strip()
        payment_terms = str(payload.get('payment_terms', '')).strip()
        shipment_date = _as_date_text(payload.get('shipment_date', ''))
        latest_shipment_date = _as_date_text(payload.get('latest_shipment_date', ''))
        presentation_deadline = _as_date_text(payload.get('presentation_deadline', ''))
        lc_expiry_date = _as_date_text(payload.get('lc_expiry_date', ''))
        marks_and_numbers = str(payload.get('marks_and_numbers', '')).strip()
        special_requirements = str(payload.get('special_requirements', '')).strip()

        product_row = conn.execute('SELECT gross_weight_per_carton, net_weight_per_carton, carton_volume_cbm FROM products WHERE id = ?', (product_id,)).fetchone()
        totals = calculate_totals(
            quantity,
            unit_price,
            product_row['gross_weight_per_carton'] if product_row else 0,
            product_row['net_weight_per_carton'] if product_row else 0,
            product_row['carton_volume_cbm'] if product_row else 0,
        )

        cursor = conn.execute(
            """
            INSERT INTO orders (
                order_no,
                customer_id,
                product_id,
                quantity,
                unit,
                unit_price,
                currency,
                total_amount,
                total_gross_weight,
                total_net_weight,
                total_volume,
                loading_port,
                destination_port,
                incoterm,
                payment_terms,
                shipment_date,
                latest_shipment_date,
                presentation_deadline,
                lc_expiry_date,
                marks_and_numbers,
                special_requirements,
                status,
                user_id,
                source_file_name,
                workflow_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, 'order_confirmed')
            """,
            (
                order_no,
                customer_id,
                product_id,
                quantity,
                unit,
                unit_price,
                currency,
                totals['total_amount'],
                totals['total_gross_weight'],
                totals['total_net_weight'],
                totals['total_volume'],
                loading_port,
                destination_port,
                incoterm,
                payment_terms,
                shipment_date,
                latest_shipment_date,
                presentation_deadline,
                lc_expiry_date,
                marks_and_numbers,
                special_requirements,
                owner_id,
                payload.get('source_file_name'),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_orders(search_text: str = '', owner_id: int | None = None) -> List[Dict[str, Any]]:
    query = '''
        SELECT o.*, c.customer_name_cn, c.customer_name_en, p.product_name_en, p.product_name_cn
        FROM orders o
        LEFT JOIN customers c ON c.id = o.customer_id
        LEFT JOIN products p ON p.id = o.product_id
        WHERE 1 = 1
    '''
    params: List[Any] = []
    if owner_id is not None:
        query += ' AND o.user_id = ?'
        params.append(owner_id)
    if search_text and search_text.strip():
        keyword = f"%{search_text.strip()}%"
        query += ' AND (o.order_no LIKE ? OR c.customer_name_cn LIKE ? OR p.product_name_en LIKE ? OR p.product_name_cn LIKE ?)'
        params.extend([keyword, keyword, keyword, keyword])
    query += ' ORDER BY o.updated_at DESC, o.id DESC'
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_order_by_id(order_id: int, owner_id: int | None = None) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        query = 'SELECT * FROM orders WHERE id = ?'
        params: list[Any] = [order_id]
        if owner_id is not None:
            query += ' AND user_id = ?'
            params.append(owner_id)
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None


def update_order(order_id: int, payload: Dict[str, Any]) -> None:
    validate_order_payload(payload)
    with get_connection() as conn:
        owner_id = payload.get('user_id')
        customer = conn.execute(
            'SELECT user_id FROM customers WHERE id = ?',
            (int(payload['customer_id']),),
        ).fetchone()
        if customer is None:
            raise ValueError('所选客户不存在。')
        if owner_id is not None and customer['user_id'] != owner_id:
            raise ValueError('订单必须归属于客户的业务员。')
        existing = conn.execute(
            'SELECT user_id FROM orders WHERE id = ? AND (? IS NULL OR user_id = ?)',
            (order_id, owner_id, owner_id),
        ).fetchone()
        if existing is None:
            raise ValueError('订单不存在或不属于当前业务员。')
        product_row = conn.execute('SELECT gross_weight_per_carton, net_weight_per_carton, carton_volume_cbm FROM products WHERE id = ?', (int(payload['product_id']),)).fetchone()
        totals = calculate_totals(
            payload.get('quantity'),
            payload.get('unit_price'),
            product_row['gross_weight_per_carton'] if product_row else 0,
            product_row['net_weight_per_carton'] if product_row else 0,
            product_row['carton_volume_cbm'] if product_row else 0,
        )
        conn.execute(
            """
            UPDATE orders SET
                order_no = ?,
                customer_id = ?,
                product_id = ?,
                quantity = ?,
                unit = ?,
                unit_price = ?,
                currency = ?,
                total_amount = ?,
                total_gross_weight = ?,
                total_net_weight = ?,
                total_volume = ?,
                loading_port = ?,
                destination_port = ?,
                incoterm = ?,
                payment_terms = ?,
                shipment_date = ?,
                latest_shipment_date = ?,
                presentation_deadline = ?,
                lc_expiry_date = ?,
                marks_and_numbers = ?,
                special_requirements = ?,
                status = ?,
                source_file_name = COALESCE(?, source_file_name),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND (? IS NULL OR user_id = ?)
            """,
            (
                str(payload['order_no']).strip(),
                int(payload['customer_id']),
                int(payload['product_id']),
                _as_float(payload.get('quantity')),
                str(payload.get('unit', '')).strip(),
                _as_float(payload.get('unit_price')),
                str(payload.get('currency', '')).strip(),
                totals['total_amount'],
                totals['total_gross_weight'],
                totals['total_net_weight'],
                totals['total_volume'],
                str(payload.get('loading_port', '')).strip(),
                str(payload.get('destination_port', '')).strip(),
                str(payload.get('incoterm', '')).strip(),
                str(payload.get('payment_terms', '')).strip(),
                str(payload.get('shipment_date', '')).strip(),
                str(payload.get('latest_shipment_date', '')).strip(),
                str(payload.get('presentation_deadline', '')).strip(),
                str(payload.get('lc_expiry_date', '')).strip(),
                str(payload.get('marks_and_numbers', '')).strip(),
                str(payload.get('special_requirements', '')).strip(),
                str(payload.get('status', 'draft')).strip() or 'draft',
                payload.get('source_file_name'),
                order_id,
                owner_id,
                owner_id,
            ),
        )
        conn.commit()


def delete_order(order_id: int, owner_id: int | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            'DELETE FROM orders WHERE id = ? AND (? IS NULL OR user_id = ?)',
            (order_id, owner_id, owner_id),
        )
        conn.commit()


def duplicate_order(order_id: int, owner_id: int | None = None) -> int:
    with get_connection() as conn:
        row = conn.execute(
            'SELECT * FROM orders WHERE id = ? AND (? IS NULL OR user_id = ?)',
            (order_id, owner_id, owner_id),
        ).fetchone()
        if row is None:
            raise ValueError('订单不存在')
        payload = dict(row)
        payload.pop('id', None)
        payload['order_no'] = f"{payload['order_no']}_COPY"
        payload['status'] = 'draft'
        return create_order(payload)


if __name__ == '__main__':
    print('orders module loaded')
