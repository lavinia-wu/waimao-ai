from __future__ import annotations

from datetime import date, datetime, time

import streamlit as st

from modules.auth import require_authenticated_user
from modules.customers import list_customers
from modules.market_data import TIMEZONE_CHOICES
from modules.market_intelligence import (
    PLACEHOLDER_NONE,
    convert_moment,
    days_from_today,
    format_converted_moment,
    holiday_display_rows,
    list_holidays,
    list_market_countries,
    next_holiday,
    seed_builtin_market_data,
    upcoming_holidays,
)
from modules.ui_style import (
    page_header,
    render_data_table,
    section,
    subsection,
)

current_user = require_authenticated_user()
is_admin = current_user['role'] == 'admin'

page_header(
    '贸易市场助手',
    caption='查看目标市场的公共假日与时区，用于安排沟通时间和估算交单、清关进度。',
)
st.info(
    '节假日数据来自公开节假日站点，不是官方公告，仅供安排沟通与交单参考；'
    '客户或银行是否实际休业，请以对方回复为准。'
)

def render_builtin_import(button_label: str) -> None:
    if not is_admin:
        st.caption('仅管理员可导入内置参考数据。')
        return
    if st.button(button_label):
        try:
            imported = seed_builtin_market_data()
            st.success(f'已导入 {imported} 条巴基斯坦节假日数据。')
            st.rerun()
        except ValueError as exc:
            st.error(f'导入失败：{exc}')


countries = list_market_countries()

# ── 市场选择 ────────────────────────────────────────────────
section('目标市场')
if not countries:
    st.warning('暂无可靠数据：市场库还没有任何国家的节假日数据。')
    st.caption('导入内置数据后，即可查看该市场的时区换算与节假日。')
    render_builtin_import('导入内置巴基斯坦节假日数据（30 条）')
    st.stop()

with st.expander('内置参考数据维护（仅管理员）', expanded=False):
    st.caption(
        '内置的巴基斯坦节假日数据：按来源整体替换该国数据，'
        '不影响其他国家与手工录入的记录。'
    )
    render_builtin_import('重新导入 / 更新内置巴基斯坦节假日数据')

customers = list_customers('', None if is_admin else int(current_user['id']))
customer_options = {'不指定（手动选择市场）': ''}
for customer in customers:
    code = str(customer.get('country_code') or '').strip()
    if not code:
        continue
    label = (
        customer.get('customer_name_cn')
        or customer.get('customer_name_en')
        or f"客户 #{customer.get('id')}"
    )
    customer_options[f'{label}（{code}）'] = code

selected_customer_label = st.selectbox('按客户定位市场（可选）', list(customer_options))
if len(customer_options) == 1:
    st.caption('客户资料里还没有维护国家/地区，可先在客户管理页补充后再使用此功能。')

country_codes = {row['country_code']: row for row in countries}
default_country = customer_options[selected_customer_label]
if default_country and default_country not in country_codes:
    st.info(f'该客户所在国家（{default_country}）暂无可靠节假日数据，请手动选择市场。')

selected_code = st.selectbox(
    '目标市场',
    list(country_codes),
    index=(
        list(country_codes).index(default_country)
        if default_country in country_codes
        else 0
    ),
)
country = country_codes[selected_code]

info_columns = st.columns(4)
info_columns[0].metric('市场', country.get('country_name_cn') or selected_code)
info_columns[1].metric('时区', country.get('timezone') or '未维护')
info_columns[2].metric('主要币种', country.get('currency_code') or '未维护')
info_columns[3].metric('商务语言', country.get('business_language') or '未维护')
if country.get('workday_note'):
    st.caption(f"工作习惯：{country['workday_note']}")

# ── 时区换算：双方时区都必须显式选择 ─────────────────────────
subsection('沟通时间换算')
market_timezones = [
    item for item in str(country.get('timezone') or '').split('|') if item
]
my_timezone = st.selectbox(
    '我方所在地时区（必须选择）',
    [PLACEHOLDER_NONE] + TIMEZONE_CHOICES,
)
market_timezone = st.selectbox(
    '目标市场时区（必须选择）',
    [PLACEHOLDER_NONE] + market_timezones,
)
moment_columns = st.columns(2)
local_date = moment_columns[0].date_input('我方日期', value=date.today())
local_time = moment_columns[1].time_input('我方时间', value=time(9, 0))

if my_timezone == PLACEHOLDER_NONE or market_timezone == PLACEHOLDER_NONE:
    st.caption('请先选择我方与目标市场的时区，再进行换算（不按国家自动推断）。')
elif not market_timezones:
    st.caption('该市场未维护时区，无法换算，请先补充国家配置。')
else:
    try:
        converted, difference = convert_moment(
            datetime.combine(local_date, local_time),
            my_timezone,
            market_timezone,
        )
        st.metric('目标市场当地时间', format_converted_moment(converted, difference))
        if converted.hour < 8 or converted.hour >= 20:
            st.caption('目标市场当地处于清晨或夜间，建议改约工作时间（仅按时刻提示，不代表对方必然休业）。')
    except ValueError as exc:
        st.error(str(exc))

# ── 节假日 ──────────────────────────────────────────────────
section('公共假日')
all_holidays = list_holidays(selected_code)
if not all_holidays:
    st.warning('暂无可靠数据：该市场还没有节假日记录。')
else:
    upcoming = upcoming_holidays(selected_code, days=30)
    next_any = next_holiday(selected_code)
    next_nationwide = next_holiday(selected_code, nationwide_only=True)

    def holiday_metric_value(item):
        if not item:
            return '暂无记录'
        remaining = days_from_today(item.get('holiday_date'))
        return f"{item.get('holiday_date')}（{item.get('name_cn')}）"

    metric_columns = st.columns(3)
    metric_columns[0].metric('下一个节假日', holiday_metric_value(next_any))
    metric_columns[1].metric(
        '下一个全国公共假日', holiday_metric_value(next_nationwide)
    )
    metric_columns[2].metric('未来 30 天节假日', f'{len(upcoming)} 个')
    if next_any:
        remaining = days_from_today(next_any.get('holiday_date'))
        st.caption(
            f"下一个节假日：{next_any.get('name_cn')}（{next_any.get('holiday_date')}），"
            f"距今 {remaining} 天，适用范围：{next_any.get('scope')}。"
        )
    if next_nationwide and next_nationwide is not next_any:
        remaining = days_from_today(next_nationwide.get('holiday_date'))
        st.caption(
            f"下一个全国公共假日：{next_nationwide.get('name_cn')}"
            f"（{next_nationwide.get('holiday_date')}），距今 {remaining} 天。"
        )

    subsection(f'未来 30 天（{len(upcoming)} 个）')
    if upcoming:
        render_data_table(holiday_display_rows(upcoming))
    else:
        st.caption('未来 30 天内没有记录在案的节假日；不代表该期间客户或银行一定办公。')

    with st.expander(f'完整清单（{len(all_holidays)} 条）', expanded=False):
        render_data_table(holiday_display_rows(all_holidays))

    st.caption(
        '宗教节日日期为预计，可能因观月前后移动一天，请以官方公告为准；'
        '银行假日只影响银行，不是公共假日；'
        '地区性假日只影响标注的地区，不代表全国休业。'
    )
    sources = sorted(
        {str(item.get('source') or '') for item in all_holidays if item.get('source')}
    )
    if sources:
        st.caption(f"数据来源：{'；'.join(sources)}")
