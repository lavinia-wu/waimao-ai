from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from config.settings import settings
from database.init_db import create_tables
from database.db import get_connection
from modules.market_data import (
    CATEGORY_BANK,
    CATEGORY_REGIONAL,
    PAKISTAN_SOURCE_RETRIEVED,
)
from modules.market_intelligence import (
    PLACEHOLDER_NONE,
    convert_moment,
    holiday_display_rows,
    list_holidays,
    list_market_countries,
    market_clock_text,
    next_holiday,
    replace_country_holidays,
    save_market_country,
    seed_builtin_market_data,
    upcoming_holidays,
    weekday_cn,
)

TODAY = date(2026, 10, 17)


def find_holiday(holidays, name_cn, holiday_date):
    for holiday in holidays:
        if holiday['name_cn'] == name_cn and holiday['holiday_date'] == holiday_date:
            return holiday
    raise AssertionError(f'未找到节假日：{name_cn} {holiday_date}')


class MarketDataTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / 'market.db'
        self.settings_patch = patch.object(settings, 'db_path', self.database_path)
        self.settings_patch.start()
        create_tables()
        seed_builtin_market_data()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.temp_dir.cleanup()

    def test_seeded_country_and_holidays(self) -> None:
        countries = list_market_countries()
        self.assertEqual(1, len(countries))
        self.assertEqual('Asia/Karachi', countries[0]['timezone'])
        self.assertEqual(30, len(list_holidays('PK')))

    def test_holidays_sorted_by_date(self) -> None:
        dates = [item['holiday_date'] for item in list_holidays('PK')]
        self.assertEqual(sorted(dates), dates)

    def test_nationwide_regional_and_bank_are_separated(self) -> None:
        holidays = list_holidays('PK')
        self.assertEqual(1, find_holiday(holidays, '伊克巴尔日', '2026-11-09')['is_nationwide'])
        founding = find_holiday(holidays, '建国日', '2026-10-24')
        self.assertEqual(0, founding['is_nationwide'])
        self.assertEqual('阿扎德克什米尔', founding['scope'])
        self.assertEqual(CATEGORY_REGIONAL, founding['category'])
        bank = find_holiday(holidays, '银行假日（年度结算）', '2027-01-01')
        self.assertEqual(1, bank['is_bank_holiday'])
        self.assertEqual(CATEGORY_BANK, bank['category'])
        self.assertEqual(0, bank['is_nationwide'])

    def test_religious_holidays_are_expected_not_confirmed(self) -> None:
        eid = find_holiday(list_holidays('PK'), '开斋节', '2027-03-09')
        self.assertEqual('预计', eid['date_status'])
        self.assertTrue(eid['source_note'])

    def test_unknown_reason_entry_is_unverified(self) -> None:
        unknown = find_holiday(list_holidays('PK'), '公共假日（事由未注明）', '2027-04-04')
        self.assertEqual('待核对', unknown['date_status'])
        self.assertEqual('未明确', unknown['impact'])

    def test_source_records_retrieval_date(self) -> None:
        sources = {item['source'] for item in list_holidays('PK')}
        self.assertEqual(1, len(sources))
        self.assertIn(PAKISTAN_SOURCE_RETRIEVED, sources.pop())

    def test_reimport_is_idempotent(self) -> None:
        seed_builtin_market_data()
        self.assertEqual(30, len(list_holidays('PK')))

    def test_replace_keeps_other_sources(self) -> None:
        manual = {
            'holiday_date': '2027-09-01',
            'name_cn': '手工录入假日',
            'name_en': 'Manual Holiday',
            'category': CATEGORY_REGIONAL,
            'scope': '全国',
            'is_nationwide': 1,
            'is_bank_holiday': 0,
            'date_status': '已确认',
            'impact': '政府/银行/物流',
            'source_note': '',
        }
        replace_country_holidays('PK', [manual], '手工录入')
        seed_builtin_market_data()
        sources = {item['source'] for item in list_holidays('PK')}
        self.assertIn('手工录入', sources)
        self.assertTrue(
            any(item['name_cn'] == '手工录入假日' for item in list_holidays('PK'))
        )

    def test_upcoming_thirty_days(self) -> None:
        upcoming = upcoming_holidays('PK', TODAY, 30)
        self.assertEqual(
            ['2026-10-24', '2026-11-09'], [item['holiday_date'] for item in upcoming]
        )

    def test_next_holiday_distinguishes_nationwide(self) -> None:
        following = next_holiday('PK', TODAY)
        self.assertEqual('建国日', following['name_cn'])
        nationwide = next_holiday('PK', TODAY, nationwide_only=True)
        self.assertEqual('伊克巴尔日', nationwide['name_cn'])

    def test_market_clock_uses_beijing_as_reference(self) -> None:
        """时钟以北京时间标注时差，不假定使用者所在地。"""
        text = market_clock_text('PK')
        self.assertIsNotNone(text)
        self.assertIn('UTC+5', text or '')
        self.assertIn('与北京时间相差 -3 小时', text or '')

    def test_market_clock_none_without_data(self) -> None:
        self.assertIsNone(market_clock_text('ZZ'))

    def test_market_clock_none_without_timezone(self) -> None:
        save_market_country('ZZ', '测试国', 'Testland', '', '', '', '')
        self.assertIsNone(market_clock_text('ZZ'))

    def test_holidays_in_week_range(self) -> None:
        week = list_holidays('PK', '2026-11-09', '2026-11-15')
        self.assertEqual(['2026-11-09'], [item['holiday_date'] for item in week])

    def test_weekday_label(self) -> None:
        self.assertEqual('星期一', weekday_cn('2026-11-09'))
        self.assertEqual('星期六', weekday_cn('2026-10-24'))

    def test_display_rows_include_status_and_scope(self) -> None:
        rows = holiday_display_rows(upcoming_holidays('PK', TODAY, 30), TODAY)
        self.assertEqual(2, len(rows))
        self.assertEqual('7 天', rows[0]['距今天数'])
        self.assertEqual('阿扎德克什米尔', rows[0]['适用范围'])
        self.assertEqual('23 天', rows[1]['距今天数'])


class EmptyMarketTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / 'market_empty.db'
        self.settings_patch = patch.object(settings, 'db_path', self.database_path)
        self.settings_patch.start()
        create_tables()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.temp_dir.cleanup()

    def test_no_countries_and_no_holidays(self) -> None:
        """无可用数据时返回空，页面据此显示「暂无可靠数据」。"""
        self.assertEqual([], list_market_countries())
        self.assertEqual([], list_holidays('CN'))


class TimezoneConversionTestCase(unittest.TestCase):
    def test_shanghai_to_karachi(self) -> None:
        converted, difference = convert_moment(
            datetime(2026, 10, 17, 12, 0), 'Asia/Shanghai', 'Asia/Karachi'
        )
        self.assertEqual(9, converted.hour)
        self.assertEqual(-3.0, difference)

    def test_karachi_to_shanghai(self) -> None:
        converted, difference = convert_moment(
            datetime(2026, 11, 9, 9, 0), 'Asia/Karachi', 'Asia/Shanghai'
        )
        self.assertEqual(12, converted.hour)
        self.assertEqual(3.0, difference)

    def test_timezone_must_be_chosen_explicitly(self) -> None:
        """不按国家推断时区：未选择时必须报错。"""
        with self.assertRaises(ValueError):
            convert_moment(datetime(2026, 10, 17, 9, 0), PLACEHOLDER_NONE, 'Asia/Karachi')
        with self.assertRaises(ValueError):
            convert_moment(datetime(2026, 10, 17, 9, 0), 'Asia/Shanghai', PLACEHOLDER_NONE)

    def test_unknown_timezone_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            convert_moment(
                datetime(2026, 10, 17, 9, 0), 'Asia/Shanghai', 'Asia/Nowhere'
            )


class SchemaTestCase(unittest.TestCase):
    def test_new_tables_exist(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / 'market_schema.db'
        self.settings_patch = patch.object(settings, 'db_path', self.database_path)
        self.settings_patch.start()
        try:
            create_tables()
            with get_connection() as conn:
                tables = {
                    row['name']
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            self.assertIn('market_countries', tables)
            self.assertIn('country_holidays', tables)
        finally:
            self.settings_patch.stop()
            self.temp_dir.cleanup()


if __name__ == '__main__':
    unittest.main()
