from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from database.db import get_connection
from modules.auth import require_authenticated_user
from modules.reminders import list_reminders, mark_reminder_done

user = require_authenticated_user()
owner_id = int(user['id'])
today = date.today()
week_start = today - timedelta(days=today.weekday())
week_end = week_start + timedelta(days=6)
reminders = list_reminders(owner_id=owner_id)
pending = [item for item in reminders if not item['is_completed']]


def reminder_day(item):
    try:
        return date.fromisoformat(str(item['reminder_date'])[:10])
    except ValueError:
        return None


st.title(f'业务看板 · {user["display_name"]}')
st.caption('个人客户与订单概况、今日寄单提醒和本周跟单日历')

with get_connection() as conn:
    customer_count = conn.execute(
        'SELECT COUNT(*) FROM customers WHERE user_id = ?',
        (owner_id,),
    ).fetchone()[0]
    order_count = conn.execute(
        'SELECT COUNT(*) FROM orders WHERE user_id = ?',
        (owner_id,),
    ).fetchone()[0]
    lc_count = conn.execute(
        'SELECT COUNT(*) FROM letters_of_credit WHERE user_id = ? AND is_approved = 1',
        (owner_id,),
    ).fetchone()[0]
    unlinked_lc_count = conn.execute(
        'SELECT COUNT(*) FROM letters_of_credit WHERE user_id = ? AND is_approved = 1 AND order_id IS NULL',
        (owner_id,),
    ).fetchone()[0]

metrics = st.columns(4)
metrics[0].metric('我的客户', customer_count)
metrics[1].metric('我的订单', order_count)
metrics[2].metric('已确认信用证', lc_count, f'{unlinked_lc_count} 份待关联订单')
metrics[3].metric('未完成事项', len(pending))

due_today = [item for item in pending if reminder_day(item) == today]
overdue = [item for item in pending if reminder_day(item) and reminder_day(item) < today]
upcoming = [item for item in pending if reminder_day(item) and today < reminder_day(item) <= today + timedelta(days=7)]

st.subheader(f'今日事项 · {today:%Y年%m月%d日}')
if due_today:
    for item in due_today:
        order_label = f"订单 {item.get('order_no')}" if item.get('order_no') else '订单待关联'
        st.warning(f"**{item['title']}** · {order_label}\n\n{item['message']}")
        if st.button('标记已完成', key=f"done_today_{item['id']}"):
            mark_reminder_done(item['id'], owner_id)
            st.rerun()
else:
    st.success('今天没有待处理节点。')

if overdue:
    st.subheader('逾期事项')
    for item in overdue:
        st.error(
            f"{item['reminder_date']} · {item['title']} · 订单 {item.get('order_no') or '待关联'}\n\n"
            f"{item['message']}"
        )

st.subheader('本周计划表')
st.caption(f'{week_start:%Y-%m-%d} 至 {week_end:%Y-%m-%d} · 按信用证、装运和寄单节点自动排期')
week_columns = st.columns(7)
for offset, column in enumerate(week_columns):
    day = week_start + timedelta(days=offset)
    items = [item for item in pending if reminder_day(item) == day]
    with column:
        st.markdown(f'**{day:%a}**  \n{day:%m-%d}')
        if day == today:
            st.caption('今天')
        if not items:
            st.caption('—')
        for item in items:
            with st.expander(item['title'], expanded=day == today):
                st.caption(f"订单：{item.get('order_no') or '待关联'}")
                st.write(item['message'])
                if st.button('完成', key=f"done_week_{item['id']}"):
                    mark_reminder_done(item['id'], owner_id)
                    st.rerun()

st.subheader('未来 7 天待办')
if upcoming:
    for item in upcoming:
        st.info(
            f"{item['reminder_date']} · {item['title']} · 订单 {item.get('order_no') or '待关联'}\n\n"
            f"{item['message']}"
        )
else:
    st.caption('未来 7 天暂无新的待办节点。')

with get_connection() as conn:
    recent_orders = conn.execute(
        """
        SELECT o.order_no, o.workflow_status, o.status, o.updated_at,
               c.customer_name_cn, p.product_name_en
        FROM orders o
        LEFT JOIN customers c ON c.id = o.customer_id
        LEFT JOIN products p ON p.id = o.product_id
        WHERE o.user_id = ?
        ORDER BY o.updated_at DESC, o.id DESC LIMIT 8
        """,
        (owner_id,),
    ).fetchall()
if recent_orders:
    st.subheader('最近跟进订单')
    st.dataframe([dict(row) for row in recent_orders], hide_index=True, use_container_width=True)

with get_connection() as conn:
    personal_customers = conn.execute(
        """
        SELECT c.customer_name_cn, c.customer_name_en, c.contact_person,
               c.email, c.phone, COUNT(o.id) AS order_count
        FROM customers c
        LEFT JOIN orders o ON o.customer_id = c.id AND o.user_id = c.user_id
        WHERE c.user_id = ?
        GROUP BY c.id
        ORDER BY c.updated_at DESC, c.id DESC LIMIT 12
        """,
        (owner_id,),
    ).fetchall()
if personal_customers:
    st.subheader('我的客户')
    st.dataframe([dict(row) for row in personal_customers], hide_index=True, use_container_width=True)
