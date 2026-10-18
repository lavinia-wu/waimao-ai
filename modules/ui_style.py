"""统一的 UI 基础组件与全局样式。

仅提供渲染原语：页面标题、分区标题、状态标签、表格、空状态、卡片、风险标签。
本模块只做展示，**不包含任何业务计算、权限判断或校验逻辑**，
也不直接读取数据库。

颜色以 `.streamlit/config.toml` 的 `[theme]` 为唯一来源；
组件一律优先使用原生 Streamlit API。

仅当原生主题无法表达（次要文字色、边框色、圆角）时才使用 CSS，
且 CSS 全部集中在 `inject_base_css()` 一处，只依赖稳定的 `data-testid`，
**不依赖自动生成的 class 名**。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Literal, Mapping

import streamlit as st


# 与 .streamlit/config.toml [theme] 保持一致
THEME_PRIMARY = '#2447A8'
THEME_BACKGROUND = '#F6F8FC'
THEME_SECONDARY_BACKGROUND = '#FFFFFF'
THEME_TEXT = '#182230'
THEME_TEXT_MUTED = '#667085'
THEME_BORDER = '#E4E7EC'

# 语义色。st.badge 不接受十六进制，只接受固定枚举，
# 因此语义色通过原生 st.success/warning/error 与下方 tone 映射共同表达。
SEMANTIC_SUCCESS = '#15803D'
SEMANTIC_WARNING = '#B45309'
SEMANTIC_ERROR = '#B42318'

# st.badge 仅接受固定的 color 取值
RISK_COLOR_HIGH = 'red'
RISK_COLOR_MEDIUM = 'orange'
RISK_COLOR_LOW = 'blue'
RISK_COLOR_UNKNOWN = 'gray'

UNKNOWN_RISK_LABEL = '待确认'

StatusTone = Literal['success', 'warning', 'error', 'info', 'neutral']
STATUS_TONE_COLORS: dict[str, str] = {
    'success': 'green',
    'warning': 'orange',
    'error': 'red',
    'info': 'blue',
    'neutral': 'gray',
}

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

# 只在原生主题无法表达的范围内使用 CSS；选择器仅限稳定 data-testid
_BASE_CSS = """
<style>
  [data-testid="stCaptionContainer"] p { color: #667085; }
  [data-testid="stVerticalBlockBorderWrapper"] {
      border: 1px solid #E4E7EC;
      border-radius: 8px;
  }
  [data-testid="stBaseButton-primary"],
  [data-testid="stBaseButton-secondary"] { border-radius: 8px; }
</style>
"""


def inject_base_css() -> None:
    """注入全站基础样式。整个项目只允许在这一个函数里写 CSS。"""
    st.markdown(_BASE_CSS, unsafe_allow_html=True)


def page_header(title: str, *, caption: str | None = None) -> None:
    """统一页面 H1：每页只允许一次，配一条说明文字。"""
    st.title(title)
    if caption:
        st.caption(caption)


def section(title: str, *, caption: str | None = None) -> None:
    """统一分区标题 H2：自带分隔线，避免再单独调用 st.divider()。"""
    st.subheader(title, divider=True)
    if caption:
        st.caption(caption)


def subsection(title: str) -> None:
    """统一分区内小标题 H3。禁止使用 st.header，避免层级错乱。"""
    st.markdown(f'**{title}**')


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


def status_badge_color(tone: Any) -> str:
    """状态语气 → st.badge 颜色；未知语气返回灰色而不是猜测。"""
    return STATUS_TONE_COLORS.get(str(tone or '').strip(), RISK_COLOR_UNKNOWN)


def render_status_badge(
    label: str,
    tone: str = 'neutral',
    *,
    icon: str | None = None,
) -> None:
    """统一状态标签：状态必须同时用文字和颜色表达。

    tone: success / warning / error / info / neutral；未知 tone 退化为灰色。
    """
    st.badge(label, color=status_badge_color(tone), icon=icon)


# 库存状态展示。状态值与派生规则由 modules.products 定义，
# 这里只维护「状态 → 徽标颜色」的映射，避免各页面重复一份。
StockStatusColor = Literal[
    'red', 'orange', 'yellow', 'blue', 'green', 'violet', 'gray', 'grey', 'primary'
]
STOCK_STATUS_COLORS: dict[str, StockStatusColor] = {
    '缺货': 'red',
    '偏低': 'orange',
    '充足': 'green',
    '正常': 'blue',
    '未维护': 'gray',
}

STOCK_UNMAINTAINED_TEXT = '未维护'


def stock_display_value(value: Any) -> str:
    """库存数值展示：NULL / 空显示「未维护」，**不得伪装成 0**。

    整数小数位去掉，避免出现「500.0 MT」这种观感；0 仍如实显示为「0」。
    """
    if value is None or str(value).strip() == '':
        return STOCK_UNMAINTAINED_TEXT
    text = str(value).strip()
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    if number.is_integer():
        return str(int(number))
    return text


def stock_status_color(status: Any) -> StockStatusColor:
    """库存状态 → 徽标颜色；未知状态返回灰色而非猜测。"""
    return STOCK_STATUS_COLORS.get(str(status or '').strip(), RISK_COLOR_UNKNOWN)


def render_data_table(
    rows: Sequence[Mapping[str, Any]],
    *,
    column_config: Any = None,
    height: int | None = None,
    empty_message: str = '暂无可比较的数据',
) -> None:
    """统一表格。可比较的数据一律用表格，且同一份数据只出现一次。"""
    if not rows:
        render_empty_state(empty_message)
        return
    options: dict[str, Any] = {
        'hide_index': True,
        'width': 'stretch',
        'column_config': column_config,
    }
    # height=None 会被 Streamlit 判定为非法值，必须省略该参数
    if height is not None:
        options['height'] = height
    st.dataframe(list(rows), **options)


def render_empty_state(
    message: str,
    *,
    hint: str | None = None,
    variant: str = 'empty',
) -> None:
    """统一空状态。禁止用「暂无数据」掩盖「数据不可用」的场景差异。

    variant:
        empty       —— 确实没有数据（灰/信息）
        unavailable —— 数据不可用（网络/服务异常），必须区别于空
        missing     —— 关键字段缺失，需要补全
    """
    if variant == 'unavailable':
        st.warning(message)
    elif variant == 'missing':
        st.error(message)
    else:
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
