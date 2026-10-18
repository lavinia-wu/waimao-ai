from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

import streamlit as st

from database.db import get_connection
from modules.auth import require_authenticated_user
from modules.market_intelligence import (
    list_holidays,
    list_market_countries,
    market_clock_compact,
)
from modules.reminders import list_reminders, mark_reminder_done
from modules.ui_style import page_header, render_data_table, section

user = require_authenticated_user()
owner_id = int(user['id'])
today = date.today()
week_start = today - timedelta(days=today.weekday())
week_end = week_start + timedelta(days=6)
reminders = list_reminders(owner_id=owner_id)
pending = [item for item in reminders if not item['is_completed']]


def reminder_day(item) -> date | None:
    try:
        return date.fromisoformat(str(item['reminder_date'])[:10])
    except ValueError:
        return None


def reminder_text(item) -> str:
    order_label = f"订单 {item.get('order_no')}" if item.get('order_no') else '订单待关联'
    return f"**{item['title']}** · {order_label}\n\n{item['message']}"


page_header(
    f'业务看板 · {user["display_name"]}',
    caption='个人客户与订单概况；提醒事项按逾期、交单与装运节点排序，逾期优先。',
)

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
    customer_country_rows = conn.execute(
        """
        SELECT DISTINCT country_code FROM customers
        WHERE user_id = ? AND country_code IS NOT NULL AND TRIM(country_code) <> ''
        """,
        (owner_id,),
    ).fetchall()

# 我的客户所属的国家/地区，用于周计划表默认定位贸易国
customer_country_codes = [row['country_code'] for row in customer_country_rows]

# 贸易国为页面级选择：顶部指标与本周计划表共用同一个市场
market_rows = list_market_countries()
active_market: str | None = None
market_names: Dict[str, str] = {}
if market_rows:
    market_names = {
        row['country_code']: row['country_name_cn'] for row in market_rows
    }
    market_codes = list(market_names)
    default_market = next(
        (code for code in customer_country_codes if code in market_codes),
        market_codes[0],
    )
    control_columns = st.columns([1, 3])
    with control_columns[0]:
        active_market = st.selectbox(
            '贸易国',
            market_codes,
            index=market_codes.index(default_market),
            format_func=lambda code: market_names[code],
            key='dashboard_market',
        )
    with control_columns[1]:
        st.caption('切换贸易国后，下方本周计划表会同步显示该国的当周节假日。')

metrics = st.columns(5)
metrics[0].metric('我的客户', customer_count)
metrics[1].metric('我的订单', order_count)
metrics[2].metric(
    '已确认信用证',
    lc_count,
    f'{unlinked_lc_count} 份待关联订单' if unlinked_lc_count else None,
)
metrics[3].metric('未完成事项', len(pending))
if active_market:
    clock = market_clock_compact(active_market)
    metrics[4].metric(
        f'{market_names[active_market]}时间',
        clock or '未维护时区',
    )
else:
    metrics[4].metric('贸易国时间', '暂无可靠数据')

overdue = [
    item for item in pending
    if reminder_day(item) and reminder_day(item) < today
]
due_today = [item for item in pending if reminder_day(item) == today]
upcoming = [
    item for item in pending
    if reminder_day(item) and today < reminder_day(item) <= today + timedelta(days=7)
]

if overdue:
    section('逾期事项', caption='超过提醒日期的节点，建议优先处理')
    for item in overdue:
        st.error(
            f"{item['reminder_date']} · {item['title']} · 订单 {item.get('order_no') or '待关联'}\n\n"
            f"{item['message']}"
        )

section(f'今日事项 · {today:%Y年%m月%d日}')
if due_today:
    for item in due_today:
        st.warning(reminder_text(item))
        if st.button('标记已完成', key=f"done_today_{item['id']}"):
            mark_reminder_done(item['id'], owner_id)
            st.rerun()
else:
    st.success('今天没有待处理节点。')

section('未来 7 天待办')
if upcoming:
    for item in upcoming:
        st.info(
            f"{item['reminder_date']} · {item['title']} · 订单 {item.get('order_no') or '待关联'}\n\n"
            f"{item['message']}"
        )
else:
    st.caption('未来 7 天暂无新的待办节点。')

with st.expander('本周计划表', expanded=False):
    week_holidays: List[Dict[str, Any]] = []
    if not active_market:
        st.caption(
            '暂无可靠数据：市场库还没有任何国家的节假日数据，'
            '周计划表暂不显示当周节假日。'
        )
    else:
        # 跟随顶部选择的贸易国，不在两处各放一个下拉
        week_holidays = list_holidays(
            active_market, week_start.isoformat(), week_end.isoformat()
        )
        if week_holidays:
            st.caption(
                '本周节假日：'
                + '、'.join(
                    f"{item['name_cn']}（{item['holiday_date'][5:]}）"
                    for item in week_holidays
                )
            )
        else:
            st.caption('本周该市场无记录在案的节假日。')

    st.caption(f'{week_start:%Y-%m-%d} 至 {week_end:%Y-%m-%d} · 按信用证、装运和寄单节点自动排期')
    week_columns = st.columns(7)
    for offset, column in enumerate(week_columns):
        day = week_start + timedelta(days=offset)
        items = [item for item in pending if reminder_day(item) == day]
        day_holidays = [
            holiday
            for holiday in week_holidays
            if holiday['holiday_date'] == day.isoformat()
        ]
        with column:
            st.markdown(f'**{day:%a}**  \n{day:%m-%d}')
            if day == today:
                st.caption('今天')
            for holiday in day_holidays:
                st.markdown(f"**假日** {holiday['name_cn']}")
                st.caption(
                    f"{holiday['category']} · {holiday['scope']}"
                    f" · 日期{holiday['date_status']}"
                )
            if not items and not day_holidays:
                st.caption('—')
            for item in items:
                with st.expander(item['title'], expanded=day == today):
                    st.caption(f"订单：{item.get('order_no') or '待关联'}")
                    st.write(item['message'])
                    if st.button('完成', key=f"done_week_{item['id']}"):
                        mark_reminder_done(item['id'], owner_id)
                        st.rerun()

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

section('最近跟进订单')
render_data_table(
    [
        {
            '订单编号': row['order_no'],
            '客户': row['customer_name_cn'] or '未关联',
            '产品': row['product_name_en'] or '未关联',
            '工作流状态': row['workflow_status'] or '—',
            '订单状态': row['status'],
            '更新时间': row['updated_at'],
        }
        for row in recent_orders
    ],
    empty_message='暂无订单记录',
)

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

section('我的客户')
render_data_table(
    [
        {
            '客户中文名': row['customer_name_cn'],
            '客户英文名': row['customer_name_en'],
            '联系人': row['contact_person'],
            '邮箱': row['email'],
            '电话': row['phone'],
            '订单数': row['order_count'],
        }
        for row in personal_customers
    ],
    empty_message='暂无客户记录',
)
