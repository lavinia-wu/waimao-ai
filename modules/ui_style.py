"""统一的 UI 基础组件。

仅提供三类最小渲染原语：空状态、风险标签、卡片。
本模块只做展示，**不包含任何业务计算、权限判断或校验逻辑**，
也不直接读取数据库。

颜色以 `.streamlit/config.toml` 的 `[theme]` 为唯一来源；
组件一律优先使用原生 Streamlit API，不使用自定义 CSS/HTML。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import streamlit as st


# 与 .streamlit/config.toml [theme] 保持一致
THEME_PRIMARY = '#1F4E79'
THEME_BACKGROUND = '#F5F7FA'
THEME_SECONDARY_BACKGROUND = '#FFFFFF'

# st.badge 仅接受固定的 color 取值
RISK_COLOR_HIGH = 'red'
RISK_COLOR_MEDIUM = 'orange'
RISK_COLOR_LOW = 'blue'
RISK_COLOR_UNKNOWN = 'gray'

UNKNOWN_RISK_LABEL = '待确认'

_ENGLISH_RISK_COLORS = {
    'high': RISK_COLOR_HIGH,
    'critical': RISK_COLOR_HIGH,
    'medium': RISK_COLOR_MEDIUM,
    'low': RISK_COLOR_LOW,
    'minor': RISK_COLOR_LOW,
}
_CHINESE_RISK_COLORS = {
    '高': RISK_COLOR_HIGH,
    '中': RISK_COLOR_MEDIUM,
    '低': RISK_COLOR_LOW,
}


def risk_badge_color(level: Any) -> str:
    """把风险等级映射为 st.badge 的颜色取值；未知等级一律返回灰色。"""
    text = str(level or '').strip()
    if not text:
        return RISK_COLOR_UNKNOWN
    english = _ENGLISH_RISK_COLORS.get(text.casefold())
    if english is not None:
        return english
    return _CHINESE_RISK_COLORS.get(text, RISK_COLOR_UNKNOWN)


def risk_label_text(level: Any) -> str:
    """返回风险等级的展示文案；缺失时不猜测，统一显示待确认。"""
    text = str(level or '').strip()
    return text or UNKNOWN_RISK_LABEL


def render_risk_badge(
    level: Any,
    *,
    label: str | None = None,
    icon: str | None = None,
) -> None:
    """渲染风险等级标签（原生 st.badge）。"""
    st.badge(
        label or risk_label_text(level),
        color=risk_badge_color(level),
        icon=icon,
    )


def render_empty_state(message: str, *, hint: str | None = None) -> None:
    """统一空状态。禁止用「暂无数据」掩盖「数据不可用」的场景差异。"""
    st.info(message)
    if hint:
        st.caption(hint)


@contextmanager
def render_card(
    title: str | None = None,
    *,
    caption: str | None = None,
    key: str | None = None,
) -> Iterator[None]:
    """统一卡片容器，配合标题与说明文字使用。

    用法::

        with render_card('信用证关键期限', caption='来源：信用证原文'):
            st.metric('最迟装运日', '2026-11-30')
    """
    with st.container(border=True, key=key):
        if title:
            st.markdown(f'**{title}**')
        if caption:
            st.caption(caption)
        yield
