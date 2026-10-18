from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.settings import settings
from database.db import get_connection
from database.init_db import create_tables
from modules.products import (
    STOCK_STATUS_LOW,
    STOCK_STATUS_NORMAL,
    STOCK_STATUS_OUT,
    STOCK_STATUS_SUFFICIENT,
    STOCK_STATUS_UNMAINTAINED,
    compute_stock_status,
    create_product,
    find_sku_conflicts,
    get_product_by_id,
    update_product,
    update_product_stock,
)

OWNER_ID = 7


def base_payload(**overrides) -> dict:
    payload = {
        'product_name_en': 'LDPE Resin',
        'product_name_cn': '低密度聚乙烯',
        'currency': 'USD',
        'unit_price': '1200',
    }
    payload.update(overrides)
    return payload


class ProductStockTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / 'product_stock.db'
        self.settings_patch = patch.object(settings, 'db_path', self.database_path)
        self.settings_patch.start()
        create_tables()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id, username, display_name, password_hash)
                VALUES (?, 'stock-user', 'Stock User', 'hash')
                """,
                (OWNER_ID,),
            )
            conn.commit()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.temp_dir.cleanup()


class ComputeStockStatusTests(unittest.TestCase):
    """库存状态为派生值，覆盖全部判定分支。"""

    def test_null_stock_qty_is_unmaintained(self) -> None:
        self.assertEqual(STOCK_STATUS_UNMAINTAINED, compute_stock_status(None, 10))
        self.assertEqual(STOCK_STATUS_UNMAINTAINED, compute_stock_status('', 10))

    def test_junk_string_is_treated_as_unmaintained(self) -> None:
        self.assertEqual(STOCK_STATUS_UNMAINTAINED, compute_stock_status('None', 10))
        self.assertEqual(STOCK_STATUS_UNMAINTAINED, compute_stock_status('  ', 10))

    def test_zero_stock_is_out_even_when_safety_is_zero(self) -> None:
        self.assertEqual(STOCK_STATUS_OUT, compute_stock_status(0, 0))
        self.assertEqual(STOCK_STATUS_OUT, compute_stock_status(0, 10))

    def test_negative_stock_is_out(self) -> None:
        self.assertEqual(STOCK_STATUS_OUT, compute_stock_status(-5, 10))

    def test_missing_safety_stock_and_positive_qty_is_normal(self) -> None:
        self.assertEqual(STOCK_STATUS_NORMAL, compute_stock_status(5, None))
        self.assertEqual(STOCK_STATUS_NORMAL, compute_stock_status(5, ''))
        # 安全库存为 0 且有库存时，0 是有效阈值而非“未维护”
        self.assertEqual(STOCK_STATUS_SUFFICIENT, compute_stock_status(5, 0))

    def test_below_safety_stock_is_low(self) -> None:
        self.assertEqual(STOCK_STATUS_LOW, compute_stock_status(4, 10))

    def test_equal_to_safety_stock_is_sufficient(self) -> None:
        self.assertEqual(STOCK_STATUS_SUFFICIENT, compute_stock_status(10, 10))

    def test_above_safety_stock_is_sufficient(self) -> None:
        self.assertEqual(STOCK_STATUS_SUFFICIENT, compute_stock_status(50, 10))

    def test_unmaintained_takes_priority_over_out(self) -> None:
        # 未填写库存时，不能因为 <= 0 就判定为缺货
        self.assertEqual(STOCK_STATUS_UNMAINTAINED, compute_stock_status(None, None))


class UpdateProductStockTests(ProductStockTestCase):
    def test_updates_stock_fields_and_stamps_actor(self) -> None:
        product_id = create_product(base_payload())

        update_product_stock(
            product_id,
            {'stock_qty': '120', 'unit': 'carton', 'safety_stock': '50', 'warehouse': '上海保税仓'},
            OWNER_ID,
        )

        product = get_product_by_id(product_id)
        self.assertEqual(120.0, product['stock_qty'])
        self.assertEqual('carton', product['unit'])
        self.assertEqual(50.0, product['safety_stock'])
        self.assertEqual('上海保税仓', product['warehouse'])
        self.assertEqual(OWNER_ID, product['stock_updated_by'])
        self.assertIsNotNone(product['stock_updated_at'])

    def test_does_not_change_other_product_fields(self) -> None:
        product_id = create_product(
            base_payload(
                product_name_en='Original Name',
                unit_price='1200',
                hs_code='390110',
                specification='Film grade',
            )
        )
        before = get_product_by_id(product_id)

        update_product_stock(product_id, {'stock_qty': '20'}, OWNER_ID)

        after = get_product_by_id(product_id)
        self.assertEqual(before['product_name_en'], after['product_name_en'])
        self.assertEqual(before['unit_price'], after['unit_price'])
        self.assertEqual(before['hs_code'], after['hs_code'])
        self.assertEqual(before['specification'], after['specification'])
        self.assertEqual(before['currency'], after['currency'])
        self.assertEqual(20.0, after['stock_qty'])

    def test_does_not_trigger_required_field_validation(self) -> None:
        """update_product 会因缺少 product_name_en / currency 报错，这里不应报错。"""
        product_id = create_product(base_payload())

        update_product_stock(product_id, {'stock_qty': '8'}, OWNER_ID)

        self.assertEqual(8.0, get_product_by_id(product_id)['stock_qty'])

    def test_partial_update_keeps_other_stock_fields_untouched(self) -> None:
        product_id = create_product(
            base_payload(stock_qty='30', unit='kg', warehouse='深圳仓'),
            OWNER_ID,
        )

        update_product_stock(product_id, {'stock_qty': '45'}, OWNER_ID)

        after = get_product_by_id(product_id)
        self.assertEqual(45.0, after['stock_qty'])
        self.assertEqual('kg', after['unit'], '仅更新库存数量时不应清空单位')
        self.assertEqual('深圳仓', after['warehouse'], '仅更新库存数量时不应清空仓库')

    def test_rejects_unknown_product(self) -> None:
        with self.assertRaises(ValueError):
            update_product_stock(9999, {'stock_qty': '1'}, OWNER_ID)

    def test_rejects_empty_payload(self) -> None:
        product_id = create_product(base_payload())
        with self.assertRaises(ValueError):
            update_product_stock(product_id, {}, OWNER_ID)

    def test_rejects_invalid_number(self) -> None:
        product_id = create_product(base_payload())
        with self.assertRaises(ValueError):
            update_product_stock(product_id, {'stock_qty': '一大箱'}, OWNER_ID)

    def test_clearing_stock_back_to_unmaintained(self) -> None:
        product_id = create_product(base_payload(stock_qty='30'), OWNER_ID)

        update_product_stock(product_id, {'stock_qty': ''}, OWNER_ID)

        after = get_product_by_id(product_id)
        self.assertIsNone(after['stock_qty'])
        self.assertEqual(STOCK_STATUS_UNMAINTAINED, compute_stock_status(after['stock_qty'], after['safety_stock']))


class ProductPersistenceTests(ProductStockTestCase):
    def test_create_persists_sku_and_stock(self) -> None:
        product_id = create_product(
            base_payload(sku='LDPE-001', stock_qty='15', unit='kg', safety_stock='20'),
            OWNER_ID,
        )

        product = get_product_by_id(product_id)
        self.assertEqual('LDPE-001', product['sku'])
        self.assertEqual(15.0, product['stock_qty'])
        self.assertEqual(20.0, product['safety_stock'])
        self.assertEqual(OWNER_ID, product['stock_updated_by'])

    def test_status_is_derived_not_stored(self) -> None:
        product_id = create_product(base_payload(stock_qty='15', safety_stock='20'), OWNER_ID)

        product = get_product_by_id(product_id)
        self.assertNotIn('stock_status', product, '库存状态不应作为列存储')
        self.assertEqual(STOCK_STATUS_LOW, compute_stock_status(product['stock_qty'], product['safety_stock']))

    def test_update_product_persists_stock_fields(self) -> None:
        product_id = create_product(base_payload())

        update_product(
            product_id,
            base_payload(sku='LDPE-002', stock_qty='100', unit='kg', safety_stock='80'),
            OWNER_ID,
        )

        product = get_product_by_id(product_id)
        self.assertEqual('LDPE-002', product['sku'])
        self.assertEqual(100.0, product['stock_qty'])
        self.assertEqual(OWNER_ID, product['stock_updated_by'])

    def test_blank_stock_is_stored_as_null_not_zero(self) -> None:
        product_id = create_product(base_payload(stock_qty=''), OWNER_ID)

        product = get_product_by_id(product_id)
        self.assertIsNone(product['stock_qty'], '留空库存必须存为 NULL，而不是 0')

    def test_literal_none_string_never_becomes_zero(self) -> None:
        """防止 'None' 字面量被当成有效数值（与 orders.py 的历史缺陷同源）。"""
        product_id = create_product(base_payload(stock_qty='None'), OWNER_ID)

        product = get_product_by_id(product_id)
        self.assertIsNone(product['stock_qty'])
        self.assertEqual(STOCK_STATUS_UNMAINTAINED, compute_stock_status(product['stock_qty'], None))


class SkuConflictTests(ProductStockTestCase):
    def test_empty_sku_never_conflicts(self) -> None:
        self.assertEqual([], find_sku_conflicts(''))
        self.assertEqual([], find_sku_conflicts(None))
        self.assertEqual([], find_sku_conflicts('   '))

    def test_detects_duplicate_sku(self) -> None:
        create_product(base_payload(product_name_en='Existing', sku='LDPE-001'), OWNER_ID)

        conflicts = find_sku_conflicts('LDPE-001')

        self.assertEqual(1, len(conflicts))
        self.assertEqual('Existing', conflicts[0]['product_name_en'])
        self.assertIn('created_at', conflicts[0])
        self.assertIn('specification', conflicts[0])

    def test_unique_sku_has_no_conflict(self) -> None:
        create_product(base_payload(product_name_en='Existing', sku='LDPE-001'), OWNER_ID)

        self.assertEqual([], find_sku_conflicts('LDPE-999'))

    def test_excludes_the_product_being_edited(self) -> None:
        product_id = create_product(base_payload(sku='LDPE-001'), OWNER_ID)

        self.assertEqual(1, len(find_sku_conflicts('LDPE-001')))
        self.assertEqual([], find_sku_conflicts('LDPE-001', exclude_product_id=product_id))

    def test_reports_every_conflicting_product(self) -> None:
        create_product(base_payload(product_name_en='A', sku='DUP'), OWNER_ID)
        create_product(base_payload(product_name_en='B', sku='DUP'), OWNER_ID)

        conflicts = find_sku_conflicts('DUP')

        self.assertEqual(2, len(conflicts))
        self.assertEqual({'A', 'B'}, {item['product_name_en'] for item in conflicts})


if __name__ == '__main__':
    unittest.main()
