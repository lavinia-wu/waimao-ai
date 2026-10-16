from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.settings import settings
from database.init_db import create_tables
from database.db import get_connection
from modules.lc_parser import (
    get_lc_risks,
    save_lc_record,
    update_lc_risk_handling,
)


class LcRiskHandlingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / 'risk_test.db'
        conn = sqlite3.connect(self.database_path)
        try:
            conn.execute(
                """
                CREATE TABLE lc_risks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lc_id INTEGER,
                    risk_level TEXT,
                    risk_type TEXT,
                    original_clause_en TEXT,
                    clause_translation_cn TEXT,
                    risk_explanation_cn TEXT,
                    suggested_action_cn TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()
        self.settings_patch = patch.object(settings, 'db_path', self.database_path)
        self.settings_patch.start()
        create_tables()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (username, display_name, password_hash)
                VALUES ('sales-test', 'Sales Test', 'test-hash')
                """
            )
            conn.commit()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.temp_dir.cleanup()

    def test_risk_status_and_note_are_persisted(self) -> None:
        lc_id = save_lc_record(
            None,
            {'lc_no': 'LC-TEST', 'adverse_clauses': []},
            'test LC text',
            [{
                'risk_level': '高',
                'risk_type': '付款条款',
                'original_clause_en': 'Payment against documents not listed.',
                'clause_translation_cn': '按未列明单据付款。',
                'risk_explanation_cn': '付款条件不清晰。',
                'suggested_action_cn': '要求银行澄清。',
                'affected_documents': ['Commercial Invoice'],
            }],
            owner_id=1,
            approved_by=1,
        )
        risk = get_lc_risks(lc_id)[0]
        self.assertEqual(risk['handling_status'], '未处理')
        self.assertEqual(risk['handling_level'], '必须处理')
        self.assertIsNone(risk['handled_at'])

        update_lc_risk_handling(risk['id'], '待客户确认', '已发邮件等待确认。', 1)
        updated = get_lc_risks(lc_id)[0]
        self.assertEqual(updated['handling_status'], '待客户确认')
        self.assertEqual(updated['handling_note'], '已发邮件等待确认。')
        self.assertTrue(updated['handled_at'])

        update_lc_risk_handling(risk['id'], '未处理', '', 1)
        reset = get_lc_risks(lc_id)[0]
        self.assertEqual(reset['handling_status'], '未处理')
        self.assertIsNone(reset['handled_at'])

    def test_existing_risk_table_gets_handling_columns(self) -> None:
        with get_connection() as conn:
            columns = {row['name'] for row in conn.execute('PRAGMA table_info(lc_risks)')}
        self.assertTrue({
            'handling_level',
            'handling_status',
            'handling_note',
            'handled_at',
        }.issubset(columns))

    def test_legacy_risk_json_is_imported_as_unprocessed(self) -> None:
        risk = {
            'risk_level': '高',
            'risk_type': '单据要求',
            'original_clause_en': 'Signed invoice required.',
            'clause_translation_cn': '需要签署的发票。',
            'risk_explanation_cn': '签字要求需确认。',
            'suggested_action_cn': '确认签署人要求。',
            'affected_documents': ['Commercial Invoice'],
        }
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO letters_of_credit (
                    lc_no, user_id, is_approved, parsed_json, risk_report_json
                ) VALUES ('LC-LEGACY', 1, 1, ?, ?)
                """,
                (
                    json.dumps({'adverse_clauses': [risk]}, ensure_ascii=False),
                    json.dumps([risk], ensure_ascii=False),
                ),
            )
            lc_id = int(cursor.lastrowid)

        imported = get_lc_risks(lc_id)[0]
        self.assertEqual(imported['handling_status'], '未处理')
        self.assertEqual(imported['handling_level'], '必须处理')
        self.assertEqual(imported['affected_documents'], ['Commercial Invoice'])


if __name__ == '__main__':
    unittest.main()
