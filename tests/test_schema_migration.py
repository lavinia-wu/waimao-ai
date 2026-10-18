from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.settings import settings
from database.db import get_connection
from database.init_db import create_tables

PRODUCT_STOCK_COLUMNS = (
    'sku',
    'stock_qty',
    'unit',
    'safety_stock',
    'warehouse',
    'stock_updated_at',
    'stock_updated_by',
)

# P0 之前的旧表结构，用于验证已有库的迁移路径
LEGACY_CUSTOMERS = """
CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name_cn TEXT,
    customer_name_en TEXT,
    company_address TEXT,
    contact_person TEXT,
    email TEXT,
    phone TEXT,
    destination_port TEXT,
    payment_terms TEXT,
    incoterm TEXT,
    remark TEXT,
    user_id INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

LEGACY_PRODUCTS = """
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name_en TEXT,
    product_name_cn TEXT,
    hs_code TEXT,
    cas_no TEXT,
    unit_price REAL,
    currency TEXT,
    packaging_method TEXT,
    gross_weight_per_carton REAL,
    net_weight_per_carton REAL,
    carton_volume_cbm REAL,
    specification TEXT,
    msds_file_path TEXT,
    product_description_en TEXT,
    transport_info TEXT,
    compliance_description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def _columns(table: str) -> set[str]:
    with get_connection() as conn:
        return {
            row['name']
            for row in conn.execute(f'PRAGMA table_info({table})').fetchall()
        }


class DatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / 'schema_test.db'
        self.settings_patch = patch.object(settings, 'db_path', self.database_path)
        self.settings_patch.start()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.temp_dir.cleanup()

    def create_legacy_schema(self, *, with_row: bool = False) -> None:
        """构造 P0 之前的旧库，模拟真实环境中已存在的数据库。"""
        with get_connection() as conn:
            conn.executescript(LEGACY_CUSTOMERS)
            conn.executescript(LEGACY_PRODUCTS)
            conn.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT, display_name TEXT, password_hash TEXT
                )
                """
            )
            if with_row:
                conn.execute(
                    'INSERT INTO products (id, product_name_en) VALUES (?, ?)',
                    (1, 'LDPE Resin'),
                )
            conn.commit()


class FreshDatabaseSchemaTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        create_tables()

    def test_products_has_all_stock_columns(self) -> None:
        columns = _columns('products')
        missing = [name for name in PRODUCT_STOCK_COLUMNS if name not in columns]
        self.assertEqual([], missing, f'新库缺少产品库存字段：{missing}')

    def test_stock_status_is_not_a_stored_column(self) -> None:
        self.assertNotIn(
            'stock_status',
            _columns('products'),
            'stock_status 应为派生显示字段，不应落库存储',
        )

    def test_customers_has_country_code(self) -> None:
        self.assertIn('country_code', _columns('customers'))


class LegacyDatabaseMigrationTests(DatabaseTestCase):
    def test_migration_adds_stock_columns_to_existing_products(self) -> None:
        self.create_legacy_schema(with_row=True)
        self.assertNotIn('stock_qty', _columns('products'))

        create_tables()

        columns = _columns('products')
        missing = [name for name in PRODUCT_STOCK_COLUMNS if name not in columns]
        self.assertEqual([], missing, f'迁移后仍缺少产品库存字段：{missing}')

    def test_migration_adds_country_code_to_existing_customers(self) -> None:
        self.create_legacy_schema(with_row=True)
        self.assertNotIn('country_code', _columns('customers'))

        create_tables()

        self.assertIn('country_code', _columns('customers'))

    def test_migration_is_idempotent(self) -> None:
        self.create_legacy_schema(with_row=True)

        create_tables()
        create_tables()

        product_columns = sorted(_columns('products'))
        expected = sorted(set(product_columns))
        self.assertEqual(expected, product_columns, '重复迁移产生了重复列')
        customer_columns = sorted(_columns('customers'))
        self.assertEqual(sorted(set(customer_columns)), customer_columns)

    def test_existing_rows_keep_null_stock_instead_of_zero(self) -> None:
        """存量产品不得被自动填 0，必须是 NULL（表示未维护）。"""
        self.create_legacy_schema(with_row=True)

        create_tables()

        with get_connection() as conn:
            row = conn.execute('SELECT * FROM products WHERE id = 1').fetchone()
        self.assertIsNone(row['stock_qty'], '存量产品的库存被写入了非 NULL 值')
        self.assertIsNone(row['safety_stock'], '存量产品的安全库存被写入了非 NULL 值')
        self.assertIsNone(row['sku'])


class RequirementsDeclarationTests(unittest.TestCase):
    def test_requests_is_declared(self) -> None:
        content = (Path(settings.base_dir) / 'requirements.txt').read_text(
            encoding='utf-8'
        )
        self.assertIn('requests', content, 'requests 已安装但未在 requirements.txt 中声明')


if __name__ == '__main__':
    unittest.main()
