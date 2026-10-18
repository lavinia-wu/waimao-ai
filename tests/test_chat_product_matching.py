from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.settings import settings
from database.db import get_connection
from database.init_db import create_tables
from modules.products import (
    MATCH_LEVEL_FUZZY,
    MATCH_LEVEL_NAME,
    MATCH_LEVEL_NAME_SPEC,
    MATCH_LEVEL_SKU,
    STOCK_STATUS_LOW,
    STOCK_STATUS_OUT,
    STOCK_STATUS_SUFFICIENT,
    STOCK_STATUS_UNMAINTAINED,
    build_product_payload_from_request,
    compute_stock_status,
    create_product,
    evaluate_demand_vs_stock,
    find_sku_conflicts,
    get_product_by_id,
    match_products_for_request,
    parse_chat_product_requests,
    single_match_id,
)
from modules.ui_style import STOCK_STATUS_COLORS, stock_display_value, stock_status_color

OWNER_ID = 7


class ChatRecognitionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / 'chat_match.db'
        self.settings_patch = patch.object(settings, 'db_path', self.database_path)
        self.settings_patch.start()
        create_tables()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id, username, display_name, password_hash)
                VALUES (?, 'seller', 'Seller', 'hash')
                """,
                (OWNER_ID,),
            )
            conn.commit()
        self.polypropylene_id = create_product(
            {
                'product_name_en': 'PP 550J',
                'product_name_cn': '聚丙烯 550J',
                'sku': 'PP-550J',
                'specification': 'Film grade',
                'currency': 'USD',
                'stock_qty': '500',
                'unit': 'MT',
                'safety_stock': '200',
                'warehouse': '上海保税仓',
            },
            OWNER_ID,
        )
        self.empty_stock_id = create_product(
            {
                'product_name_en': 'HDPE 6098H',
                'sku': 'HDPE-6098',
                'currency': 'USD',
                'stock_qty': '0',
                'unit': 'MT',
                'safety_stock': '0',
            },
            OWNER_ID,
        )
        self.unmaintained_id = create_product(
            {
                'product_name_en': 'LDPE Resin',
                'specification': 'Film grade',
                'currency': 'USD',
            },
            OWNER_ID,
        )
        self.other_pp_id = create_product(
            {
                'product_name_en': 'PP Resin',
                'specification': 'Injection',
                'currency': 'USD',
                'stock_qty': '30',
                'unit': 'MT',
                'safety_stock': '10',
            },
            OWNER_ID,
        )

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.temp_dir.cleanup()

    def products_count(self) -> int:
        with get_connection() as conn:
            return int(conn.execute('SELECT COUNT(*) FROM products').fetchone()[0])


class ParseChatRequestsTests(unittest.TestCase):
    """纯解析，不依赖数据库。"""

    def test_single_request_extracts_name_quantity_and_unit(self) -> None:
        items = parse_chat_product_requests('我们需要 PP 550J，25 吨')

        self.assertEqual(1, len(items))
        self.assertEqual('PP 550J', items[0]['product_name_en'])
        self.assertEqual(25.0, items[0]['requested_qty'])
        self.assertEqual('MT', items[0]['requested_unit'])
        self.assertIn('PP 550J', items[0]['raw_snippet'])

    def test_english_unit_is_normalized_like_chinese(self) -> None:
        items = parse_chat_product_requests('we need LDPE Resin 500 cartons')

        self.assertEqual(1, len(items))
        self.assertEqual('LDPE Resin', items[0]['product_name_en'])
        self.assertEqual(500.0, items[0]['requested_qty'])
        self.assertEqual('carton', items[0]['requested_unit'])

    def test_multiple_products_are_separated(self) -> None:
        text = '我们需要 PP 550J，25 吨\n另外 HDPE 6098H 有库存吗？'

        items = parse_chat_product_requests(text)

        self.assertEqual(2, len(items))
        self.assertEqual('PP 550J', items[0]['product_name_en'])
        self.assertEqual('HDPE 6098H', items[1]['product_name_en'])
        self.assertEqual(25.0, items[0]['requested_qty'])

    def test_unmentioned_fields_stay_empty(self) -> None:
        items = parse_chat_product_requests('HDPE 6098H 有库存吗？')

        self.assertEqual(1, len(items))
        self.assertIsNone(items[0]['requested_qty'])
        self.assertEqual('', items[0]['requested_unit'])
        self.assertEqual('', items[0]['sku_hint'])
        self.assertEqual('', items[0]['specification'])

    def test_labeled_fields_are_read(self) -> None:
        text = '产品：LDPE Resin；SKU: LDPE-001；规格：Film grade；数量：500 cartons'

        items = parse_chat_product_requests(text)

        self.assertEqual(1, len(items))
        self.assertEqual('LDPE Resin', items[0]['product_name_en'])
        self.assertEqual('LDPE-001', items[0]['sku_hint'])
        self.assertEqual('Film grade', items[0]['specification'])
        self.assertEqual(500.0, items[0]['requested_qty'])
        self.assertEqual('carton', items[0]['requested_unit'])

    def test_text_without_any_product_returns_nothing(self) -> None:
        self.assertEqual([], parse_chat_product_requests('请尽快报价谢谢'))
        self.assertEqual([], parse_chat_product_requests(''))

    def test_repeated_same_request_is_collapsed(self) -> None:
        items = parse_chat_product_requests('PP 550J 25 吨\nPP 550J 25 吨')

        self.assertEqual(1, len(items))


class MatchProductTests(ChatRecognitionTestCase):
    def test_sku_exact_match_has_highest_priority(self) -> None:
        item = {'product_name_en': '随便写的名字', 'sku_hint': 'PP-550J', 'specification': ''}

        candidates = match_products_for_request(item)

        self.assertEqual(1, len(candidates))
        self.assertEqual(self.polypropylene_id, candidates[0]['id'])
        self.assertEqual(MATCH_LEVEL_SKU, candidates[0]['match_level'])
        self.assertIn('SKU', candidates[0]['match_basis'])

    def test_name_plus_specification_match(self) -> None:
        item = {'product_name_en': 'PP', 'sku_hint': '', 'specification': 'Film grade'}

        candidates = match_products_for_request(item)

        self.assertEqual(1, len(candidates))
        self.assertEqual(self.polypropylene_id, candidates[0]['id'])
        self.assertEqual(MATCH_LEVEL_NAME_SPEC, candidates[0]['match_level'])

    def test_partial_name_is_marked_as_fuzzy(self) -> None:
        item = {'product_name_en': 'PP', 'sku_hint': '', 'specification': ''}

        candidates = match_products_for_request(item)

        self.assertEqual(2, len(candidates))
        for candidate in candidates:
            self.assertEqual(MATCH_LEVEL_FUZZY, candidate['match_level'])

    def test_exact_name_match_is_explicit(self) -> None:
        item = {'product_name_en': 'PP Resin', 'sku_hint': '', 'specification': ''}

        candidates = match_products_for_request(item)

        self.assertEqual(1, len(candidates))
        self.assertEqual(self.other_pp_id, candidates[0]['id'])
        self.assertEqual(MATCH_LEVEL_NAME, candidates[0]['match_level'])

    def test_single_candidate_can_be_auto_selected(self) -> None:
        candidates = match_products_for_request({'product_name_en': 'PP Resin'})

        self.assertEqual(self.other_pp_id, single_match_id(candidates))

    def test_multiple_candidates_are_never_auto_selected(self) -> None:
        candidates = match_products_for_request({'product_name_en': 'PP'})

        self.assertGreater(len(candidates), 1)
        self.assertIsNone(single_match_id(candidates), '多条候选必须人工选择')

    def test_no_candidate_returns_empty(self) -> None:
        candidates = match_products_for_request({'product_name_en': 'ZZZ-NOT-EXIST'})

        self.assertEqual([], candidates)
        self.assertIsNone(single_match_id(candidates))

    def test_match_result_follows_edited_fields(self) -> None:
        """用户改了字段后必须得到新的候选，不能沿用旧结果。"""
        exact = match_products_for_request({'product_name_en': 'PP 550J'})
        widened = match_products_for_request({'product_name_en': 'PP'})
        renamed = match_products_for_request({'product_name_en': 'HDPE 6098H'})

        self.assertEqual([self.polypropylene_id], [row['id'] for row in exact])
        self.assertEqual(2, len(widened))
        self.assertEqual([self.empty_stock_id], [row['id'] for row in renamed])

    def test_reading_and_matching_do_not_write_any_row(self) -> None:
        before = self.products_count()

        parse_chat_product_requests('PP 550J 25 吨')
        for _ in range(3):
            match_products_for_request({'product_name_en': 'PP'})
            match_products_for_request({'sku_hint': 'PP-550J'})

        self.assertEqual(before, self.products_count(), '识别与查询不得写入数据库')


class DemandVersusStockTests(ChatRecognitionTestCase):
    def test_unmaintained_stock_is_not_comparable(self) -> None:
        product = get_product_by_id(self.unmaintained_id)

        result = evaluate_demand_vs_stock(product, 10, 'MT')

        self.assertFalse(result['comparable'])
        self.assertIsNone(result['enough'])
        self.assertIn('库存未维护', result['reason'])

    def test_unit_mismatch_is_not_compared(self) -> None:
        product = get_product_by_id(self.polypropylene_id)

        result = evaluate_demand_vs_stock(product, 10, 'kg')

        self.assertFalse(result['comparable'])
        self.assertIn('单位不一致', result['reason'])

    def test_same_unit_enough_stock(self) -> None:
        product = get_product_by_id(self.polypropylene_id)

        result = evaluate_demand_vs_stock(product, 200, 'MT')

        self.assertTrue(result['comparable'])
        self.assertTrue(result['enough'])

    def test_same_unit_insufficient_stock(self) -> None:
        product = get_product_by_id(self.polypropylene_id)

        result = evaluate_demand_vs_stock(product, 999999, 'MT')

        self.assertTrue(result['comparable'])
        self.assertFalse(result['enough'])

    def test_missing_demand_quantity_is_not_compared(self) -> None:
        product = get_product_by_id(self.polypropylene_id)

        result = evaluate_demand_vs_stock(product, None, 'MT')

        self.assertFalse(result['comparable'])
        self.assertIn('需求数量未明确', result['reason'])


class StockDisplayTests(ChatRecognitionTestCase):
    def test_null_and_zero_stock_are_displayed_differently(self) -> None:
        unmaintained = get_product_by_id(self.unmaintained_id)
        empty = get_product_by_id(self.empty_stock_id)

        self.assertEqual('未维护', stock_display_value(unmaintained['stock_qty']))
        self.assertEqual('0', stock_display_value(empty['stock_qty']))
        self.assertNotEqual(
            stock_display_value(unmaintained['stock_qty']),
            stock_display_value(empty['stock_qty']),
        )
        self.assertEqual(
            STOCK_STATUS_UNMAINTAINED,
            compute_stock_status(unmaintained['stock_qty'], unmaintained['safety_stock']),
        )
        self.assertEqual(
            STOCK_STATUS_OUT,
            compute_stock_status(empty['stock_qty'], empty['safety_stock']),
        )
        self.assertNotEqual(
            stock_status_color(STOCK_STATUS_UNMAINTAINED),
            stock_status_color(STOCK_STATUS_OUT),
        )

    def test_badge_colors_cover_every_status(self) -> None:
        statuses = {
            STOCK_STATUS_UNMAINTAINED,
            STOCK_STATUS_OUT,
            STOCK_STATUS_LOW,
            STOCK_STATUS_SUFFICIENT,
            '正常',
        }
        self.assertEqual(statuses, set(STOCK_STATUS_COLORS))


class NewProductFromRequestTests(ChatRecognitionTestCase):
    def test_payload_excludes_every_stock_field(self) -> None:
        payload = build_product_payload_from_request(
            {
                'product_name_en': 'PP 550J',
                'product_name_cn': '聚丙烯',
                'specification': 'Film grade',
                'sku_hint': 'NEW-001',
                'requested_qty': 999,
                'requested_unit': 'MT',
            }
        )

        self.assertEqual(
            {
                'product_name_en': 'PP 550J',
                'product_name_cn': '聚丙烯',
                'specification': 'Film grade',
                'sku': 'NEW-001',
                'currency': 'USD',
            },
            payload,
        )
        for stock_field in ('stock_qty', 'safety_stock', 'unit', 'warehouse'):
            self.assertNotIn(stock_field, payload)

    def test_confirmed_new_product_keeps_stock_unmaintained(self) -> None:
        before = self.products_count()
        payload = build_product_payload_from_request(
            {'product_name_en': 'New PP Grade', 'sku_hint': 'NEW-002', 'requested_qty': 999}
        )

        new_id = create_product(payload, OWNER_ID)
        product = get_product_by_id(new_id)

        self.assertEqual(before + 1, self.products_count())
        self.assertIsNone(product['stock_qty'], '客户需求数量不得变成库存')
        self.assertIsNone(product['safety_stock'])
        self.assertEqual('', product['unit'])
        self.assertEqual(
            STOCK_STATUS_UNMAINTAINED,
            compute_stock_status(product['stock_qty'], product['safety_stock']),
        )

    def test_sku_conflict_is_detected_before_saving(self) -> None:
        conflicts = find_sku_conflicts('PP-550J')

        self.assertEqual(1, len(conflicts))
        self.assertEqual(self.polypropylene_id, conflicts[0]['id'])
        self.assertIn('created_at', conflicts[0])
        self.assertIn('specification', conflicts[0])

    def test_unmatched_request_does_not_create_anything_until_confirmed(self) -> None:
        before = self.products_count()

        items = parse_chat_product_requests('我们需要 XYZ-Unknown-Grade，80 吨')
        candidates = match_products_for_request(items[0])

        self.assertEqual(1, len(items))
        self.assertEqual([], candidates)
        self.assertEqual(before, self.products_count(), '未匹配且未确认时不得新增产品')


if __name__ == '__main__':
    unittest.main()
