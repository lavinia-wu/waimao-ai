CREATE_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'sales',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS customers (
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
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
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
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT UNIQUE,
        customer_id INTEGER,
        product_id INTEGER,
        quantity REAL,
        unit TEXT,
        unit_price REAL,
        currency TEXT,
        total_amount REAL,
        total_gross_weight REAL,
        total_net_weight REAL,
        total_volume REAL,
        loading_port TEXT,
        destination_port TEXT,
        incoterm TEXT,
        payment_terms TEXT,
        shipment_date TEXT,
        latest_shipment_date TEXT,
        presentation_deadline TEXT,
        lc_expiry_date TEXT,
        marks_and_numbers TEXT,
        special_requirements TEXT,
        user_id INTEGER REFERENCES users(id),
        workflow_status TEXT DEFAULT 'order_confirmed',
        source_file_name TEXT,
        status TEXT DEFAULT 'draft',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        document_type TEXT,
        document_no TEXT,
        issue_date TEXT,
        file_path_word TEXT,
        file_path_pdf TEXT,
        file_path_excel TEXT,
        content_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS letters_of_credit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        lc_no TEXT,
        issuing_bank TEXT,
        applicant TEXT,
        beneficiary TEXT,
        lc_amount REAL,
        currency TEXT,
        tolerance_percentage REAL,
        issue_date TEXT,
        expiry_date TEXT,
        latest_shipment_date TEXT,
        presentation_period TEXT,
        loading_port TEXT,
        discharge_port TEXT,
        transshipment_allowed INTEGER,
        partial_shipment_allowed INTEGER,
        goods_description TEXT,
        documents_required_json TEXT,
        raw_text TEXT,
        parsed_json TEXT,
        risk_report_json TEXT,
        user_id INTEGER REFERENCES users(id),
        translation_text TEXT,
        is_approved INTEGER NOT NULL DEFAULT 0,
        approved_at TEXT,
        approved_by INTEGER REFERENCES users(id),
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS lc_risks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lc_id INTEGER,
        risk_level TEXT,
        risk_type TEXT,
        original_clause_en TEXT,
        clause_translation_cn TEXT,
        risk_explanation_cn TEXT,
        suggested_action_cn TEXT,
        handling_level TEXT NOT NULL DEFAULT '需确认',
        handling_status TEXT NOT NULL DEFAULT '未处理',
        handling_note TEXT NOT NULL DEFAULT '',
        handled_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        lc_id INTEGER,
        reminder_type TEXT,
        reminder_date TEXT,
        title TEXT,
        message TEXT,
        is_completed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(customer_name_cn, customer_name_en);
    CREATE INDEX IF NOT EXISTS idx_orders_order_no ON orders(order_no);
    CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
    CREATE INDEX IF NOT EXISTS idx_documents_order ON documents(order_id);
    CREATE INDEX IF NOT EXISTS idx_lc_order ON letters_of_credit(order_id);
    CREATE INDEX IF NOT EXISTS idx_reminders_order ON reminders(order_id);

    """
]
