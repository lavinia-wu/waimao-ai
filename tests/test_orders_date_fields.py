from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from config.settings import settings
from database.db import get_connection
from database.init_db import create_tables
from modules.orders import create_order, update_order

DATE_FIELDS = (
    'shipment_date',
    'latest_shipment_date',
    'presentation_deadline',
    'lc_expiry_date',
)


def base_payload() -> dict:
    return {
        'order_no': 'PO-DATE-TEST',
        'customer_id': 1,
        'product_id': 1,
        'quantity': '10',
        'unit': 'carton',
        'unit_price': '100',
        'currency': 'USD',
        'shipment_date': '2026-11-30',
        'latest_shipment_date': '2026-12-01',
        'presentation_deadline': '2026-12-10',
        'lc_expiry_date': '2026-12-31',
    }


class OrderDateFieldTests(unittest.TestCase):
    """Date fields must never be persisted as the literal string 'None'."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / 'order_date_test.db'
        self.settings_patch = patch.object(settings, 'db_path', self.database_path)
        self.settings_patch.start()
        create_tables()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (username, display_name, password_hash)
                VALUES ('sales-date', 'Sales Date', 'hash')
                """
            )
            conn.execute(
                """
                INSERT INTO customers (id, customer_name_cn, customer_name_en, user_id)
                VALUES (1, '测试客户', 'Test Customer', 1)
                """
            )
            conn.execute(
                """
                INSERT INTO products (id, product_name_en, product_name_cn, unit_price, currency)
                VALUES (1, 'LDPE Resin', '低密度聚乙烯', 1200.0, 'USD')
                """
            )
            conn.commit()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.temp_dir.cleanup()

    def _stored_dates(self, order_id: int) -> dict:
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT {', '.join(DATE_FIELDS)} FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
        return dict(row)

    def _assert_no_junk(self, stored: dict) -> None:
        for field, value in stored.items():
            self.assertNotEqual(
                'None',
                value,
                f'{field} 被写入了字面量 "None"，应为空字符串。',
            )

    def test_update_order_does_not_persist_none_literal(self) -> None:
        order_id = create_order(base_payload())

        payload = base_payload()
        for field in DATE_FIELDS:
            payload[field] = None
        update_order(order_id, payload)

        stored = self._stored_dates(order_id)
        self._assert_no_junk(stored)
        for field in DATE_FIELDS:
            self.assertEqual('', stored[field], f'{field} 留空后应为空字符串')

    def test_update_order_accepts_date_and_datetime_objects(self) -> None:
        order_id = create_order(base_payload())

        payload = base_payload()
        payload['shipment_date'] = date(2026, 10, 20)
        payload['latest_shipment_date'] = datetime(2026, 10, 25, 15, 30)
        update_order(order_id, payload)

        stored = self._stored_dates(order_id)
        self._assert_no_junk(stored)
        self.assertEqual('2026-10-20', stored['shipment_date'])
        self.assertEqual('2026-10-25', stored['latest_shipment_date'])

    def test_create_order_does_not_persist_none_literal(self) -> None:
        payload = base_payload()
        for field in DATE_FIELDS:
            payload[field] = None
        order_id = create_order(payload)

        stored = self._stored_dates(order_id)
        self._assert_no_junk(stored)
        for field in DATE_FIELDS:
            self.assertEqual('', stored[field], f'{field} 留空后应为空字符串')

    def test_previously_stored_none_literal_is_cleaned_on_update(self) -> None:
        order_id = create_order(base_payload())
        with get_connection() as conn:
            conn.execute(
                'UPDATE orders SET shipment_date = ?, lc_expiry_date = ? WHERE id = ?',
                ('None', 'NaT', order_id),
            )
            conn.commit()

        update_order(order_id, base_payload())

        stored = self._stored_dates(order_id)
        self._assert_no_junk(stored)


if __name__ == '__main__':
    unittest.main()
