"""目标市场数据读写：国家配置与公共假日。

数据为公开来源的参考信息，只用于安排沟通与交单时间参考，
不判断客户或银行必然休业。看板的贸易国时间与当周节假日也取自本模块。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database.db import get_connection
from modules.market_data import (
    PAKISTAN_COUNTRY,
    PAKISTAN_SOURCE,
    PAKISTAN_SOURCE_RETRIEVED,
    pakistan_holidays,
)

WEEKDAY_LABELS = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
PLACEHOLDER_NONE = '未选择'


def parse_iso_date(value: Any):
    """把 YYYY-MM-DD 文本转为日期；无法识别时返回 None。"""
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def weekday_cn(value: Any) -> str:
    """星期几的中文标签；日期无法识别时返回空串。"""
    moment = parse_iso_date(value)
    return WEEKDAY_LABELS[moment.weekday()] if moment else ''


def days_from_today(value: Any, today: date | None = None) -> int | None:
    """距离今天的天数；负数表示已过去。"""
    moment = parse_iso_date(value)
    if moment is None:
        return None
    return (moment - (today or date.today())).days


# ── 国家配置 ────────────────────────────────────────────────
def list_market_countries(active_only: bool = True) -> List[Dict[str, Any]]:
    """有节假日数据的国家列表。"""
    with get_connection() as conn:
        rows = conn.execute(
            'SELECT * FROM market_countries WHERE country_code IN'
            ' (SELECT DISTINCT country_code FROM country_holidays)'
            ' ORDER BY country_name_cn'
        ).fetchall()
    countries = [dict(row) for row in rows]
    if active_only:
        countries = [row for row in countries if int(row.get('is_active') or 0) == 1]
    return countries


def get_market_country(country_code: str) -> Dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            'SELECT * FROM market_countries WHERE country_code = ?',
            (str(country_code or '').strip(),),
        ).fetchone()
    return dict(row) if row else None


def save_market_country(
    country_code: str,
    country_name_cn: str,
    country_name_en: str,
    timezone: str = '',
    currency_code: str = '',
    business_language: str = '',
    workday_note: str = '',
    is_active: int = 1,
) -> int:
    """新增或更新国家配置，时区必须显式传入，不按国家推断。"""
    code = str(country_code or '').strip()
    if not code:
        raise ValueError('国家代码不能为空')
    with get_connection() as conn:
        existing = conn.execute(
            'SELECT id FROM market_countries WHERE country_code = ?', (code,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE market_countries
                SET country_name_cn = ?, country_name_en = ?, timezone = ?,
                    currency_code = ?, business_language = ?, workday_note = ?,
                    is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE country_code = ?
                """,
                (
                    country_name_cn, country_name_en, timezone, currency_code,
                    business_language, workday_note, is_active, code,
                ),
            )
            conn.commit()
            return int(existing['id'])
        cursor = conn.execute(
            """
            INSERT INTO market_countries (
                country_code, country_name_cn, country_name_en, timezone,
                currency_code, business_language, workday_note, is_active,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                code, country_name_cn, country_name_en, timezone,
                currency_code, business_language, workday_note, is_active,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


# ── 节假日读取 ──────────────────────────────────────────────
def list_holidays(
    country_code: str,
    start_date: str = '',
    end_date: str = '',
) -> List[Dict[str, Any]]:
    """按日期升序返回公共假日。"""
    sql = 'SELECT * FROM country_holidays WHERE country_code = ?'
    parameters: List[Any] = [str(country_code or '').strip()]
    if start_date:
        sql += ' AND holiday_date >= ?'
        parameters.append(start_date)
    if end_date:
        sql += ' AND holiday_date <= ?'
        parameters.append(end_date)
    sql += ' ORDER BY holiday_date, name_cn'
    with get_connection() as conn:
        rows = conn.execute(sql, parameters).fetchall()
    return [dict(row) for row in rows]


def upcoming_holidays(
    country_code: str,
    today: date | None = None,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """未来若干天内的公共假日（含今天）。"""
    base = today or date.today()
    result: List[Dict[str, Any]] = []
    for holiday in list_holidays(country_code, base.isoformat()):
        remaining = days_from_today(holiday.get('holiday_date'), base)
        if remaining is not None and 0 <= remaining <= days:
            result.append(holiday)
    return result


def next_holiday(
    country_code: str,
    today: date | None = None,
    nationwide_only: bool = False,
):
    """下一个（全国性）公共假日。"""
    base = today or date.today()
    for holiday in list_holidays(country_code, base.isoformat()):
        if nationwide_only and not int(holiday.get('is_nationwide') or 0):
            continue
        return holiday
    return None


def holiday_display_rows(
    holidays: List[Dict[str, Any]],
    today: date | None = None,
) -> List[Dict[str, str]]:
    """节假日表格行：日期、星期、名称、分类、适用范围、日期状态、距今天数。"""
    base = today or date.today()
    rows: List[Dict[str, str]] = []
    for holiday in holidays:
        remaining = days_from_today(holiday.get('holiday_date'), base)
        rows.append({
            '日期': str(holiday.get('holiday_date') or ''),
            '星期': weekday_cn(holiday.get('holiday_date')),
            '节日（中文）': str(holiday.get('name_cn') or ''),
            '节日（英文）': str(holiday.get('name_en') or ''),
            '分类': str(holiday.get('category') or ''),
            '适用范围': str(holiday.get('scope') or ''),
            '影响对象': str(holiday.get('impact') or ''),
            '日期状态': str(holiday.get('date_status') or ''),
            '距今天数': '—' if remaining is None else f'{remaining} 天',
        })
    return rows


# ── 节假日维护 ──────────────────────────────────────────────
def replace_country_holidays(
    country_code: str,
    holidays: List[Dict[str, Any]],
    source: str,
) -> int:
    """按来源整体替换某国的节假日，其他来源的记录保留。"""
    code = str(country_code or '').strip()
    if not code:
        raise ValueError('国家代码不能为空')
    with get_connection() as conn:
        conn.execute(
            'DELETE FROM country_holidays WHERE country_code = ? AND source = ?',
            (code, source),
        )
        for holiday in holidays:
            conn.execute(
                """
                INSERT INTO country_holidays (
                    country_code, holiday_date, name_cn, name_en, category,
                    scope, is_nationwide, is_bank_holiday, date_status,
                    impact, source, source_note, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    code,
                    holiday.get('holiday_date') or '',
                    holiday.get('name_cn') or '',
                    holiday.get('name_en') or '',
                    holiday.get('category') or '',
                    holiday.get('scope') or '全国',
                    int(holiday.get('is_nationwide') or 0),
                    int(holiday.get('is_bank_holiday') or 0),
                    holiday.get('date_status') or '预计',
                    holiday.get('impact') or '',
                    holiday.get('source') or source,
                    holiday.get('source_note') or '',
                ),
            )
        conn.commit()
    return len(holidays)


def seed_builtin_market_data() -> int:
    """导入内置的巴基斯坦市场与节假日数据，返回导入条数。"""
    source = f'{PAKISTAN_SOURCE}（检索日期 {PAKISTAN_SOURCE_RETRIEVED}）'
    save_market_country(
        PAKISTAN_COUNTRY['country_code'],
        PAKISTAN_COUNTRY['country_name_cn'],
        PAKISTAN_COUNTRY['country_name_en'],
        PAKISTAN_COUNTRY['timezone'],
        PAKISTAN_COUNTRY['currency_code'],
        PAKISTAN_COUNTRY['business_language'],
        PAKISTAN_COUNTRY['workday_note'],
    )
    return replace_country_holidays('PK', pakistan_holidays(), source)


# ── 时区换算 ────────────────────────────────────────────────
def convert_moment(
    moment: datetime,
    source_timezone: str,
    target_timezone: str,
) -> Tuple[datetime, float]:
    """把某一时刻从源时区换算到目标时区，返回（目标时刻, 小时差）。

    两侧时区都必须显式给出，不做任何推断。
    """
    if source_timezone in (None, '', PLACEHOLDER_NONE) or target_timezone in (None, '', PLACEHOLDER_NONE):
        raise ValueError('请先选择我方时区与目标市场时区')
    try:
        source = ZoneInfo(source_timezone)
        target = ZoneInfo(target_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f'时区无法识别：{exc}') from exc
    aware = moment.replace(tzinfo=source)
    converted = aware.astimezone(target)
    difference = (
        converted.utcoffset() - aware.utcoffset()
    ).total_seconds() / 3600
    return converted, difference


BEIJING_TIMEZONE = 'Asia/Shanghai'


def utc_offset_text(moment: datetime) -> str:
    """时刻的 UTC 偏移文案，例如 UTC+5。"""
    total = moment.utcoffset().total_seconds() / 3600
    sign = '+' if total >= 0 else '-'
    value = abs(total)
    return f'UTC{sign}{int(value)}' if value.is_integer() else f'UTC{sign}{value:.1f}'


def market_clock_text(country_code: str) -> str | None:
    """该国当前当地时间文案；未维护时区或国家不存在时返回 None。

    时差以北京时间标注，不假定使用者所在地。
    """
    country = get_market_country(country_code)
    timezone = str((country or {}).get('timezone') or '')
    if not timezone:
        return None
    try:
        target = ZoneInfo(timezone)
        beijing = ZoneInfo(BEIJING_TIMEZONE)
    except ZoneInfoNotFoundError:
        return None
    now = datetime.now(tz=target)
    difference = (
        now.utcoffset() - datetime.now(tz=beijing).utcoffset()
    ).total_seconds() / 3600
    sign = '+' if difference >= 0 else '-'
    hours = abs(difference)
    gap = f'{int(hours)}' if hours.is_integer() else f'{hours:.1f}'
    return (
        f"{now:%m-%d %H:%M} · {utc_offset_text(now)}"
        f" · 与北京时间相差 {sign}{gap} 小时"
    )


def market_clock_compact(country_code: str) -> str | None:
    """紧凑文案：HH:MM · 北京±Nh，用于看板顶部指标位（完整文案见 market_clock_text）。"""
    country = get_market_country(country_code)
    timezone = str((country or {}).get('timezone') or '')
    if not timezone:
        return None
    try:
        target = ZoneInfo(timezone)
        beijing = ZoneInfo(BEIJING_TIMEZONE)
    except ZoneInfoNotFoundError:
        return None
    now = datetime.now(tz=target)
    difference = (
        now.utcoffset() - datetime.now(tz=beijing).utcoffset()
    ).total_seconds() / 3600
    sign = '+' if difference >= 0 else '-'
    hours = abs(difference)
    gap = f'{int(hours)}' if hours.is_integer() else f'{hours:.1f}'
    return f'{now:%H:%M} · 北京{sign}{gap}h'


def format_converted_moment(converted: datetime, difference: float) -> str:
    """换算结果文案：目标时刻与小时差。"""
    sign = '+' if difference >= 0 else '-'
    hours = abs(difference)
    label = f'{int(hours)} 小时' if hours.is_integer() else f'{hours:.1f} 小时'
    return (
        f"{converted.strftime('%Y-%m-%d %H:%M')}（{converted.tzname()}）"
        f" · 与本地相差 {sign}{label}"
    )
