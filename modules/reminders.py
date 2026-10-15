from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from database.db import get_connection


def create_reminder(order_id: int, lc_id: int | None, reminder_type: str, reminder_date: str, title: str, message: str) -> int:
    with get_connection() as conn:
        if lc_id is None:
            existing = conn.execute(
                'SELECT id, reminder_date, title, message, is_completed FROM reminders WHERE order_id = ? AND lc_id IS NULL AND reminder_type = ?',
                (order_id, reminder_type),
            ).fetchone()
        else:
            existing = conn.execute(
                'SELECT id, reminder_date, title, message, is_completed FROM reminders WHERE order_id = ? AND lc_id = ? AND reminder_type = ?',
                (order_id, lc_id, reminder_type),
            ).fetchone()
        if existing:
            changed = any(
                existing[field] != value
                for field, value in (
                    ('reminder_date', reminder_date),
                    ('title', title),
                    ('message', message),
                )
            )
            conn.execute(
                """
                UPDATE reminders
                SET reminder_date = ?, title = ?, message = ?,
                    is_completed = CASE WHEN ? THEN 0 ELSE is_completed END
                WHERE id = ?
                """,
                (reminder_date, title, message, int(changed), existing['id']),
            )
            conn.commit()
            return int(existing['id'])
        cursor = conn.execute(
            """
            INSERT INTO reminders (order_id, lc_id, reminder_type, reminder_date, title, message, is_completed)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (order_id, lc_id, reminder_type, reminder_date, title, message),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_reminders(order_id: int | None = None, owner_id: int | None = None) -> List[Dict[str, Any]]:
    query = """
        SELECT r.*, o.order_no, c.customer_name_cn, c.customer_name_en
        FROM reminders r
        LEFT JOIN orders o ON o.id = r.order_id
        LEFT JOIN customers c ON c.id = o.customer_id
        WHERE 1 = 1
    """
    params = []
    if order_id is not None:
        query += ' AND r.order_id = ?'
        params.append(order_id)
    if owner_id is not None:
        query += ' AND o.user_id = ?'
        params.append(owner_id)
    query += ' ORDER BY r.reminder_date ASC, r.id DESC'
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def mark_reminder_done(reminder_id: int, owner_id: int | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE reminders SET is_completed = 1
            WHERE id = ? AND (
                ? IS NULL OR EXISTS (
                    SELECT 1 FROM orders o WHERE o.id = reminders.order_id AND o.user_id = ?
                )
            )
            """,
            (reminder_id, owner_id, owner_id),
        )
        conn.commit()


def build_order_reminders(order_id: int, lc_expiry_date: str | None = None, latest_shipment_date: str | None = None, presentation_deadline: str | None = None) -> List[Dict[str, Any]]:
    reminders: List[Dict[str, Any]] = []
    expiry = _parse_date(lc_expiry_date)
    latest_shipment = _parse_date(latest_shipment_date)
    presentation = _parse_date(presentation_deadline)
    if expiry:
        due = datetime.combine(expiry, datetime.min.time())
        reminders.append({
            'reminder_type': 'lc_expiry',
            'reminder_date': (due - timedelta(days=7)).strftime('%Y-%m-%d'),
            'title': '信用证到期前7天',
            'message': '请核对信用证有效期，准备交单并确认可接受条款。',
        })
    if latest_shipment:
        due = datetime.combine(latest_shipment, datetime.min.time())
        reminders.append({
            'reminder_type': 'latest_shipment',
            'reminder_date': (due - timedelta(days=3)).strftime('%Y-%m-%d'),
            'title': '最迟装运日前3天',
            'message': '船期预警，避免迟装。',
        })
    if presentation:
        due = datetime.combine(presentation, datetime.min.time())
        reminders.append({
            'reminder_type': 'presentation',
            'reminder_date': (due - timedelta(days=3)).strftime('%Y-%m-%d'),
            'title': '交单截止日前3天',
            'message': '交单截止日前3天强预警，避免逾期交单扣汇。',
        })
    return reminders


def generate_and_store_reminders(order_id: int, lc_data: Dict[str, Any] | None = None, lc_id: int | None = None) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if row is None:
            return []
        lc_record = lc_data or {}
        latest_shipment_date = lc_record.get('latest_shipment_date') or row['latest_shipment_date']
        presentation_deadline = lc_record.get('presentation_deadline') or row['presentation_deadline']
        lc_expiry_date = lc_record.get('expiry_date') or row['lc_expiry_date']
        generated = build_order_reminders(order_id, lc_expiry_date, latest_shipment_date, presentation_deadline)

        requirements = lc_record.get('documents_required') or lc_record.get('document_requirements') or []
        dispatch_message = _build_document_dispatch_message(requirements, lc_record.get('dispatch_instruction', ''))
        planned_shipment_date = row['shipment_date'] or latest_shipment_date
        planned_shipment = _parse_date(planned_shipment_date)
        presentation_days = _coerce_days(
            lc_record.get('presentation_period_days'),
            lc_record.get('presentation_period', ''),
        )
        expiry = _parse_date(lc_expiry_date)
        presentation_due = _parse_date(presentation_deadline)
        if planned_shipment and presentation_days is not None:
            presentation_due = planned_shipment + timedelta(days=presentation_days)
            if expiry and expiry < presentation_due:
                presentation_due = expiry
        dispatch_days = _coerce_days(lc_record.get('dispatch_days_after_shipment'))
        if planned_shipment and (presentation_due or dispatch_days is not None):
            if dispatch_days is not None:
                dispatch_date = planned_shipment + timedelta(days=dispatch_days)
                dispatch_title = f'信用证要求装运后{dispatch_days}天内寄出正本'
                if presentation_due and dispatch_date > presentation_due:
                    dispatch_date = presentation_due - timedelta(days=3)
                    dispatch_title = '交单截止前3天寄出正本（请核对信用证期限）'
            else:
                dispatch_date = (presentation_due or planned_shipment) - timedelta(days=3)
                dispatch_title = '交单截止前3天寄出正本'
            generated.append({
                'reminder_type': 'lc_document_dispatch',
                'reminder_date': dispatch_date.isoformat(),
                'title': dispatch_title,
                'message': dispatch_message or '请核对信用证要求的正本、副本份数，并预留快递和银行审单时间。',
            })
        elif presentation_due:
            generated.append({
                'reminder_type': 'lc_document_dispatch',
                'reminder_date': (presentation_due - timedelta(days=3)).isoformat(),
                'title': '交单截止前3天寄出正本',
                'message': dispatch_message or '请核对信用证要求的正本、副本份数，并预留快递和银行审单时间。',
            })
        elif planned_shipment and dispatch_message:
            generated.append({
                'reminder_type': 'lc_document_dispatch',
                'reminder_date': (planned_shipment - timedelta(days=3)).isoformat(),
                'title': '装运前核对信用证单据份数',
                'message': f'请按计划装运日期准备寄单。{dispatch_message}',
            })

        for reminder in generated:
            create_reminder(
                order_id=order_id,
                lc_id=lc_id,
                reminder_type=reminder['reminder_type'],
                reminder_date=reminder['reminder_date'],
                title=reminder['title'],
                message=reminder['message'],
            )
        return list_reminders(order_id)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _extract_days(value: Any) -> int | None:
    match = re.search(r'(\d+)\s*(?:days?|天)', str(value or ''), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _coerce_days(value: Any, fallback: Any = '') -> int | None:
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = _extract_days(value) or _extract_days(fallback)
    return days if days is not None and days >= 0 else None


def _build_document_dispatch_message(requirements: List[Dict[str, Any]], dispatch_instruction: str) -> str:
    lines = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        doc_type = item.get('document_type', '信用证单据')
        original_count = item.get('original_count')
        copy_count = item.get('copy_count')
        counts = []
        if original_count is not None:
            counts.append(f'{original_count}份正本')
        if copy_count is not None:
            counts.append(f'{copy_count}份副本')
        count_text = '、'.join(counts) or '份数按信用证要求'
        requirements_text = item.get('special_requirements') or item.get('requirements', '')
        line = f'{doc_type}：{count_text}'
        if requirements_text:
            line += f'；{requirements_text}'
        lines.append(line)
    if dispatch_instruction:
        lines.append(f'寄单要求：{dispatch_instruction}')
    return '信用证单据寄送核对：' + '；'.join(lines) if lines else ''


def get_dashboard_snapshot(owner_id: int | None = None) -> Dict[str, Any]:
    with get_connection() as conn:
        if owner_id is None:
            order_rows = conn.execute('SELECT * FROM orders ORDER BY created_at DESC').fetchall()
            reminders = conn.execute('SELECT * FROM reminders WHERE is_completed = 0 ORDER BY reminder_date ASC LIMIT 10').fetchall()
        else:
            order_rows = conn.execute(
                'SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC',
                (owner_id,),
            ).fetchall()
            reminders = conn.execute(
                """
                SELECT r.* FROM reminders r JOIN orders o ON o.id = r.order_id
                WHERE o.user_id = ? AND r.is_completed = 0
                ORDER BY r.reminder_date ASC LIMIT 10
                """,
                (owner_id,),
            ).fetchall()
    snapshot = {
        'total_orders': len(order_rows),
        'pending_reminders': len(reminders),
        'recent_reminders': [dict(r) for r in reminders],
    }
    return snapshot
