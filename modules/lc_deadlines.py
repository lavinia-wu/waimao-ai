from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from typing import Any

import streamlit as st


def parse_date(value: Any) -> date | None:
    text = str(value or '').strip()
    if not text:
        return None
    for pattern in ('%Y-%m-%d', '%Y%m%d', '%Y/%m/%d', '%Y.%m.%d'):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    return None


def _presentation_days(parsed_lc: dict[str, Any]) -> int | None:
    value = parsed_lc.get('presentation_period_days')
    try:
        days = int(value)
        if days >= 0:
            return days
    except (TypeError, ValueError):
        pass
    match = re.search(
        r'(\d+)\s*(?:calendar\s*)?days?',
        str(parsed_lc.get('presentation_period') or ''),
        flags=re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def get_lc_deadlines(
    parsed_lc: dict[str, Any] | None,
    order: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    parsed_lc = parsed_lc or {}
    order = order or {}
    latest_shipment = (
        parse_date(parsed_lc.get('latest_shipment_date'))
        or parse_date(order.get('latest_shipment_date'))
    )
    expiry = (
        parse_date(parsed_lc.get('expiry_date'))
        or parse_date(order.get('lc_expiry_date'))
    )
    shipment = parse_date(order.get('shipment_date')) or parse_date(
        parsed_lc.get('shipment_date')
    )
    presentation = parse_date(
        parsed_lc.get('presentation_deadline')
        or order.get('presentation_deadline')
    )
    presentation_source = '人工确认的交单截止日'
    if not presentation:
        days = _presentation_days(parsed_lc)
        if shipment and days is not None:
            presentation = shipment + timedelta(days=days)
            presentation_source = (
                f'装运日 {shipment.isoformat()} + 信用证交单期限 {days} 天'
            )
            if expiry and expiry < presentation:
                presentation = expiry
                presentation_source += f'；受信用证有效期 {expiry.isoformat()} 限制'
        elif days is not None:
            presentation_source = (
                f'信用证规定装运后 {days} 天内交单，待确认装运日后计算'
            )
        else:
            presentation_source = '信用证未识别明确交单期限，待核对原文'

    return [
        {
            'label': '最迟装运日',
            'value': latest_shipment,
            'source': (
                '信用证最迟装运日'
                if parse_date(parsed_lc.get('latest_shipment_date'))
                else '订单记录'
            ),
        },
        {
            'label': '交单截止日',
            'value': presentation,
            'source': presentation_source,
        },
        {
            'label': '信用证有效期',
            'value': expiry,
            'source': (
                '信用证有效期'
                if parse_date(parsed_lc.get('expiry_date'))
                else '订单记录'
            ),
        },
    ]


def render_lc_deadline_cards(
    parsed_lc: dict[str, Any] | None,
    order: dict[str, Any] | None = None,
) -> None:
    cards = get_lc_deadlines(parsed_lc, order)
    columns = st.columns(len(cards))
    today = date.today()
    for column, card in zip(columns, cards):
        with column:
            deadline = card['value']
            if deadline is None:
                st.metric(card['label'], '待核对')
                st.caption(card['source'])
                continue

            days_remaining = (deadline - today).days
            st.metric(card['label'], deadline.isoformat())
            if days_remaining < 0:
                st.error(f'已逾期 {abs(days_remaining)} 天')
            elif days_remaining == 0:
                st.error('今天到期')
            elif days_remaining <= 3:
                st.error(f'剩余 {days_remaining} 天 · 紧急')
            elif days_remaining <= 7:
                st.warning(f'剩余 {days_remaining} 天 · 临近')
            elif days_remaining <= 30:
                st.info(f'剩余 {days_remaining} 天')
            else:
                st.success(f'剩余 {days_remaining} 天')
            st.caption(f'来源：{card["source"]}')
