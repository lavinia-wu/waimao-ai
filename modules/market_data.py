"""贸易市场内置参考数据。

数据来源为公开节假日站点，仅用于安排沟通与交单时间参考：
- 宗教节日日期为「预计」，可能因观月前后移动一天
- 银行假日与公共假日分开记录，不混为一谈
- 地区性假日只影响部分地区，不代表全国休业
"""

from __future__ import annotations

from typing import Any, Dict, List

# 节日分类
CATEGORY_NATIONAL = '全国公共假日'
CATEGORY_RELIGIOUS = '宗教假日'
CATEGORY_REGIONAL = '地区假日'
CATEGORY_BANK = '银行假日'

# 日期状态
STATUS_CONFIRMED = '已确认'
STATUS_EXPECTED = '预计'
STATUS_UNVERIFIED = '待核对'

# 影响对象
IMPACT_ALL = '政府/银行/物流'
IMPACT_BANK = '银行'
IMPACT_REGIONAL = '部分地区政府/银行'
IMPACT_UNKNOWN = '未明确'

# 教历类节日的共同说明：依观月确定
MOON_SIGHTING_NOTE = '依 Ruet-e-Hilal 观月委员会公告确定，可能前后移动一天'

PAKISTAN_COUNTRY: Dict[str, Any] = {
    'country_code': 'PK',
    'country_name_cn': '巴基斯坦',
    'country_name_en': 'Pakistan',
    'timezone': 'Asia/Karachi',
    'currency_code': 'PKR',
    'business_language': '英语 / 乌尔都语',
    'workday_note': (
        '巴基斯坦为单一时区（PKT，UTC+5，全年无夏令时）。'
        '公开资料显示：周五为半工作日、周日为公休。'
        '具体营业时间请以客户与银行回复为准。'
    ),
}

# 数据来源与检索日期
PAKISTAN_SOURCE = 'Office Holidays 巴基斯坦年度页（交叉核对 PakistanCalendar）'
PAKISTAN_SOURCE_RETRIEVED = '2026-10-17'

# （日期, 中文名, 英文名, 分类, 适用范围, 是否全国, 是否银行假日, 日期状态, 影响对象, 备注）
_PAKISTAN_HOLIDAY_ROWS: List[tuple] = [
    ('2026-10-24', '建国日', 'Founding Day', CATEGORY_REGIONAL, '阿扎德克什米尔', 0, 0, STATUS_CONFIRMED, IMPACT_REGIONAL, ''),
    ('2026-11-09', '伊克巴尔日', 'Iqbal Day', CATEGORY_NATIONAL, '全国', 1, 0, STATUS_CONFIRMED, IMPACT_ALL, ''),
    ('2026-12-25', '真纳日（国父诞辰）', 'Quaid-e-Azam Day', CATEGORY_NATIONAL, '全国', 1, 0, STATUS_CONFIRMED, IMPACT_ALL, ''),
    ('2026-12-27', '贝·布托逝世纪念日', "Anniversary of Benazir Bhutto's Death", CATEGORY_REGIONAL, '信德省', 0, 0, STATUS_CONFIRMED, IMPACT_REGIONAL, ''),

    ('2027-01-01', '银行假日（年度结算）', 'Bank Holiday', CATEGORY_BANK, '银行', 0, 1, STATUS_CONFIRMED, IMPACT_BANK, '银行为年度结算停业，不是公共假日'),
    ('2027-01-05', '登霄夜', 'Israa & Miaraj Night', CATEGORY_RELIGIOUS, '信德省', 0, 0, STATUS_EXPECTED, IMPACT_REGIONAL, MOON_SIGHTING_NOTE),
    ('2027-02-05', '克什米尔团结日', 'Kashmir Solidarity Day', CATEGORY_NATIONAL, '全国', 1, 0, STATUS_CONFIRMED, IMPACT_ALL, ''),
    ('2027-02-08', '银行假日（年度结算）', 'Bank Holiday', CATEGORY_BANK, '银行', 0, 1, STATUS_CONFIRMED, IMPACT_BANK, '银行为年度结算停业，不是公共假日'),
    ('2027-03-09', '开斋节', 'Eid ul-Fitr', CATEGORY_RELIGIOUS, '全国', 1, 0, STATUS_EXPECTED, IMPACT_ALL, MOON_SIGHTING_NOTE),
    ('2027-03-10', '开斋节假期（第 2 天）', 'Eid ul-Fitr Holiday', CATEGORY_RELIGIOUS, '全国', 1, 0, STATUS_EXPECTED, IMPACT_ALL, MOON_SIGHTING_NOTE),
    ('2027-03-11', '开斋节假期（第 3 天）', 'Eid ul-Fitr Holiday', CATEGORY_RELIGIOUS, '全国', 1, 0, STATUS_EXPECTED, IMPACT_ALL, MOON_SIGHTING_NOTE),
    ('2027-03-22', '洒红节', 'Holi', CATEGORY_RELIGIOUS, '信德省印度教群体', 0, 0, STATUS_EXPECTED, IMPACT_REGIONAL, '印度教节日，仅部分地区与特定群体'),
    ('2027-03-23', '巴基斯坦日', 'Pakistan Day', CATEGORY_NATIONAL, '全国', 1, 0, STATUS_CONFIRMED, IMPACT_ALL, ''),
    ('2027-04-04', '公共假日（事由未注明）', 'Public Holiday', CATEGORY_REGIONAL, '信德省', 0, 0, STATUS_UNVERIFIED, IMPACT_UNKNOWN, '来源仅写 Public Holiday、未注明事由，未核实'),
    ('2027-05-01', '劳动节', 'Labour Day', CATEGORY_NATIONAL, '全国', 1, 0, STATUS_CONFIRMED, IMPACT_ALL, ''),
    ('2027-05-16', '宰牲节', 'Eid ul-Azha', CATEGORY_RELIGIOUS, '全国', 1, 0, STATUS_EXPECTED, IMPACT_ALL, MOON_SIGHTING_NOTE),
    ('2027-05-17', '宰牲节（第 2 天）', 'Eid ul-Azha Day 2', CATEGORY_RELIGIOUS, '全国', 1, 0, STATUS_EXPECTED, IMPACT_ALL, MOON_SIGHTING_NOTE),
    ('2027-05-18', '宰牲节（第 3 天）', 'Eid ul-Azha Day 3', CATEGORY_RELIGIOUS, '全国', 1, 0, STATUS_EXPECTED, IMPACT_ALL, MOON_SIGHTING_NOTE),
    ('2027-05-28', '大赞日', 'Youm-e-Takbeer', CATEGORY_NATIONAL, '全国', 1, 0, STATUS_CONFIRMED, IMPACT_ALL, ''),
    ('2027-06-14', '阿舒拉（9 日）', 'Ashoora (9 Muharram)', CATEGORY_RELIGIOUS, '全国', 1, 0, STATUS_EXPECTED, IMPACT_ALL, MOON_SIGHTING_NOTE),
    ('2027-06-15', '阿舒拉（10 日）', 'Ashoora (10 Muharram)', CATEGORY_RELIGIOUS, '全国', 1, 0, STATUS_EXPECTED, IMPACT_ALL, MOON_SIGHTING_NOTE),
    ('2027-07-01', '银行假日（年度结算）', 'Bank Holiday', CATEGORY_BANK, '银行', 0, 1, STATUS_CONFIRMED, IMPACT_BANK, '银行为年度结算停业，不是公共假日'),
    ('2027-07-19', '比泰忌辰', 'Urs of Shah Abdul Latif Bhitai', CATEGORY_RELIGIOUS, '信德省', 0, 0, STATUS_EXPECTED, IMPACT_REGIONAL, MOON_SIGHTING_NOTE),
    ('2027-08-14', '独立日', 'Independence Day', CATEGORY_NATIONAL, '全国', 1, 0, STATUS_CONFIRMED, IMPACT_ALL, ''),
    ('2027-08-15', '圣纪节', 'Eid Milad-un-Nabi', CATEGORY_RELIGIOUS, '全国', 1, 0, STATUS_EXPECTED, IMPACT_ALL, '来源本身标注 Date to be confirmed'),
    ('2027-10-24', '建国日', 'Founding Day', CATEGORY_REGIONAL, '阿扎德克什米尔', 0, 0, STATUS_CONFIRMED, IMPACT_REGIONAL, ''),
    ('2027-11-09', '伊克巴尔日', 'Iqbal Day', CATEGORY_NATIONAL, '全国', 1, 0, STATUS_CONFIRMED, IMPACT_ALL, ''),
    ('2027-12-25', '真纳日', 'Quaid-e-Azam Day', CATEGORY_NATIONAL, '全国', 1, 0, STATUS_CONFIRMED, IMPACT_ALL, ''),
    ('2027-12-25', '登霄夜', 'Shab e-Meraj', CATEGORY_RELIGIOUS, '信德省', 0, 0, STATUS_EXPECTED, IMPACT_REGIONAL, MOON_SIGHTING_NOTE),
    ('2027-12-27', '贝·布托逝世纪念日', "Anniversary of Benazir Bhutto's Death", CATEGORY_REGIONAL, '信德省', 0, 0, STATUS_CONFIRMED, IMPACT_REGIONAL, ''),
]

# 常用贸易往来时区：只列主要往来国家，时区必须由使用者显式选择
TIMEZONE_CHOICES: List[str] = [
    'Asia/Shanghai',
    'Asia/Hong_Kong',
    'Asia/Tokyo',
    'Asia/Seoul',
    'Asia/Singapore',
    'Asia/Bangkok',
    'Asia/Ho_Chi_Minh',
    'Asia/Jakarta',
    'Asia/Kuala_Lumpur',
    'Asia/Karachi',
    'Asia/Kolkata',
    'Asia/Dhaka',
    'Asia/Dubai',
    'Asia/Riyadh',
    'Asia/Tehran',
    'Asia/Istanbul',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Madrid',
    'Europe/Moscow',
    'Africa/Cairo',
    'Africa/Lagos',
    'Africa/Nairobi',
    'America/New_York',
    'America/Chicago',
    'America/Los_Angeles',
    'America/Sao_Paulo',
    'America/Mexico_City',
    'Australia/Sydney',
]


def pakistan_holidays() -> List[Dict[str, Any]]:
    """内置巴基斯坦节假日，字典形式供入库使用。"""
    return [
        {
            'country_code': PAKISTAN_COUNTRY['country_code'],
            'holiday_date': row[0],
            'name_cn': row[1],
            'name_en': row[2],
            'category': row[3],
            'scope': row[4],
            'is_nationwide': row[5],
            'is_bank_holiday': row[6],
            'date_status': row[7],
            'impact': row[8],
            'source_note': row[9],
        }
        for row in _PAKISTAN_HOLIDAY_ROWS
    ]
