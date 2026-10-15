from __future__ import annotations

from database.db import get_connection
from database.models import CREATE_TABLES
from config.settings import ensure_directories
from modules.documents import ensure_default_templates


def create_tables() -> None:
    with get_connection() as conn:
        conn.executescript('\n'.join(CREATE_TABLES))
        migrations = {
            'customers': {'user_id': 'INTEGER REFERENCES users(id)'},
            'orders': {
                'user_id': 'INTEGER REFERENCES users(id)',
                'workflow_status': "TEXT DEFAULT 'order_confirmed'",
                'source_file_name': 'TEXT',
            },
            'letters_of_credit': {
                'user_id': 'INTEGER REFERENCES users(id)',
                'translation_text': 'TEXT',
                'is_approved': 'INTEGER NOT NULL DEFAULT 0',
                'approved_at': 'TEXT',
                'approved_by': 'INTEGER REFERENCES users(id)',
            },
        }
        for table, columns in migrations.items():
            existing = {
                row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()
            }
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_customers_owner ON customers(user_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_orders_owner ON orders(user_id)')
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_lc_owner_approval ON letters_of_credit(user_id, is_approved)'
        )
        conn.commit()


def seed_demo_data() -> None:
    with get_connection() as conn:
        customer_count = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
        if customer_count == 0:
            conn.execute(
                """
                INSERT INTO customers (
                    customer_name_cn,
                    customer_name_en,
                    company_address,
                    contact_person,
                    email,
                    phone,
                    destination_port,
                    payment_terms,
                    incoterm,
                    remark
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    '上海美达贸易有限公司',
                    'Shanghai Meida Trading Co., Ltd.',
                    'Shanghai, China',
                    'Alice Chen',
                    'alice@meida-trading.com',
                    '+86 13800000000',
                    'Qingdao',
                    'T/T 30% Advance',
                    'FOB',
                    '长期合作客户，付款条件稳定'
                ),
            )

        product_count = conn.execute('SELECT COUNT(*) FROM products').fetchone()[0]
        if product_count == 0:
            conn.execute(
                """
                INSERT INTO products (
                    product_name_en,
                    product_name_cn,
                    hs_code,
                    cas_no,
                    unit_price,
                    currency,
                    packaging_method,
                    gross_weight_per_carton,
                    net_weight_per_carton,
                    carton_volume_cbm,
                    specification,
                    product_description_en,
                    transport_info,
                    compliance_description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    'LDPE Resin',
                    '低密度聚乙烯树脂',
                    '390110',
                    '9002-88-4',
                    1200.0,
                    'USD',
                    '25kg/bag, 40 bags/pallet',
                    25.0,
                    24.0,
                    0.05,
                    'Film grade',
                    'LDPE resin for packaging and film production',
                    'Non-hazardous, keep dry and away from heat.',
                    'Compliant with export packaging and chemical safety requirements.'
                ),
            )

        conn.commit()


def init_db() -> None:
    ensure_directories()
    create_tables()
    ensure_default_templates()
    seed_demo_data()


if __name__ == '__main__':
    init_db()
    print('数据库初始化完成')
