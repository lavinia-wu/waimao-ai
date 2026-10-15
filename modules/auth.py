from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from typing import Any

from database.db import get_connection


PASSWORD_ITERATIONS = 310_000


def user_count() -> int:
    with get_connection() as conn:
        return int(conn.execute('SELECT COUNT(*) FROM users').fetchone()[0])


def require_authenticated_user() -> dict[str, Any]:
    import streamlit as st

    current = st.session_state.get('auth_user')
    active = get_active_user(int(current['id'])) if current else None
    if active is None:
        st.session_state.pop('auth_user', None)
        st.switch_page('app.py')
        st.stop()
    st.session_state['auth_user'] = active
    return active


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PASSWORD_ITERATIONS)
    return f'{salt.hex()}${digest.hex()}'


def create_user(username: str, display_name: str, password: str, role: str = 'sales') -> int:
    username = username.strip()
    display_name = display_name.strip()
    if len(username) < 3:
        raise ValueError('账号至少需要 3 个字符。')
    if len(display_name) < 1:
        raise ValueError('请填写姓名。')
    if len(password) < 10:
        raise ValueError('密码至少需要 10 个字符。')
    if role not in {'admin', 'sales'}:
        raise ValueError('用户角色无效。')

    with get_connection() as conn:
        try:
            cursor = conn.execute(
                'INSERT INTO users (username, display_name, password_hash, role, is_active) VALUES (?, ?, ?, ?, 1)',
                (username, display_name, _hash_password(password), role),
            )
        except sqlite3.IntegrityError as exc:
            if 'UNIQUE constraint failed' in str(exc):
                raise ValueError('该账号已存在。') from exc
            raise
        user_id = int(cursor.lastrowid)

        if role == 'admin':
            conn.execute('UPDATE customers SET user_id = ? WHERE user_id IS NULL', (user_id,))
            conn.execute(
                'UPDATE orders SET user_id = ? WHERE user_id IS NULL',
                (user_id,),
            )
            conn.execute(
                'UPDATE letters_of_credit SET user_id = ? WHERE user_id IS NULL',
                (user_id,),
            )
        conn.commit()
        return user_id


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            'SELECT id, username, display_name, password_hash, role, is_active FROM users WHERE username = ?',
            (username.strip(),),
        ).fetchone()
    if row is None or not row['is_active']:
        return None
    try:
        salt_hex, expected = str(row['password_hash']).split('$', 1)
        actual = _hash_password(password, bytes.fromhex(salt_hex)).split('$', 1)[1]
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, actual):
        return None
    return {
        'id': int(row['id']),
        'username': row['username'],
        'display_name': row['display_name'],
        'role': row['role'],
    }


def get_active_user(user_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            'SELECT id, username, display_name, role FROM users WHERE id = ? AND is_active = 1',
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            'SELECT id, username, display_name, role, is_active, created_at FROM users ORDER BY id'
        ).fetchall()
    return [dict(row) for row in rows]


def set_user_active(user_id: int, is_active: bool, acting_user_id: int) -> None:
    if user_id == acting_user_id and not is_active:
        raise ValueError('不能停用当前登录的管理员账号。')
    with get_connection() as conn:
        row = conn.execute('SELECT role FROM users WHERE id = ?', (user_id,)).fetchone()
        if row is None:
            raise ValueError('用户不存在。')
        if row['role'] == 'admin' and not is_active:
            active_admins = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0]
            if active_admins <= 1:
                raise ValueError('系统至少需要保留一个启用的管理员。')
        conn.execute('UPDATE users SET is_active = ? WHERE id = ?', (int(is_active), user_id))
        conn.commit()


def change_password(user_id: int, password: str) -> None:
    if len(password) < 10:
        raise ValueError('密码至少需要 10 个字符。')
    with get_connection() as conn:
        conn.execute(
            'UPDATE users SET password_hash = ? WHERE id = ?',
            (_hash_password(password), user_id),
        )
        conn.commit()


def assign_customer_owner(customer_id: int, owner_id: int) -> None:
    with get_connection() as conn:
        customer = conn.execute(
            'SELECT id FROM customers WHERE id = ?',
            (customer_id,),
        ).fetchone()
        owner = conn.execute(
            'SELECT id FROM users WHERE id = ? AND is_active = 1',
            (owner_id,),
        ).fetchone()
        if customer is None:
            raise ValueError('客户不存在。')
        if owner is None:
            raise ValueError('所选业务员账号不存在或已停用。')
        conn.execute(
            'UPDATE customers SET user_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (owner_id, customer_id),
        )
        order_rows = conn.execute(
            'SELECT id FROM orders WHERE customer_id = ?',
            (customer_id,),
        ).fetchall()
        order_ids = [int(row['id']) for row in order_rows]
        conn.execute('UPDATE orders SET user_id = ? WHERE customer_id = ?', (owner_id, customer_id))
        if order_ids:
            placeholders = ','.join('?' for _ in order_ids)
            conn.execute(
                f'UPDATE letters_of_credit SET user_id = ? WHERE order_id IN ({placeholders})',
                [owner_id, *order_ids],
            )
        conn.commit()
