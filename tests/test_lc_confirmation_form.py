from __future__ import annotations

import unittest

from modules.lc_confirmation import (
    build_change_summary,
    merge_confirmed_values,
    source_excerpts,
    validate_confirmation,
)


class LcConfirmationFormTests(unittest.TestCase):
    def valid_values(self) -> dict:
        return {
            'lc_no': 'LC-2026-01',
            'applicant': 'Buyer Ltd.',
            'beneficiary': 'Seller Ltd.',
            'lc_amount': 1200.0,
            'currency': 'USD',
        }

    def test_required_fields_are_checked(self) -> None:
        values = self.valid_values()
        values['lc_no'] = ''
        errors = validate_confirmation(values, [])
        self.assertTrue(any('信用证编号' in error for error in errors))

    def test_invalid_date_and_negative_numeric_values_are_rejected(self) -> None:
        values = self.valid_values()
        values['expiry_date'] = 'not-a-date'
        values['lc_amount'] = -1
        errors = validate_confirmation(values, [])
        self.assertTrue(any('信用证有效期' in error for error in errors))
        self.assertTrue(any('信用证金额不能为负数' in error for error in errors))

    def test_negative_document_counts_are_rejected(self) -> None:
        errors = validate_confirmation(
            self.valid_values(),
            [{
                'document_type': 'Commercial Invoice',
                'original_count': -1,
                'copy_count': 2,
            }],
        )
        self.assertTrue(any('正本份数不能为负数' in error for error in errors))

    def test_change_summary_marks_manual_edits(self) -> None:
        ai = self.valid_values()
        confirmed = dict(ai, lc_amount=1250.0)
        summary = build_change_summary(ai, confirmed)
        amount_row = next(row for row in summary if row['字段名'] == '信用证金额')
        self.assertEqual(amount_row['是否修改'], '是')
        self.assertEqual(amount_row['AI识别值'], 1200.0)
        self.assertEqual(amount_row['人工修改值'], 1250.0)

    def test_merge_preserves_unknown_fields_and_document_metadata(self) -> None:
        ai = {
            **self.valid_values(),
            'unknown_future_field': 'preserve me',
            'documents_required': [{
                'document_type': 'Commercial Invoice',
                'original_count': 2,
                'copy_count': 1,
                'special_requirements': 'Signed',
                'affected_documents': ['Commercial Invoice'],
            }],
        }
        confirmed = dict(self.valid_values(), lc_amount=1250, expiry_date='2026-12-31')
        result = merge_confirmed_values(
            ai,
            confirmed,
            [{
                '_source_index': 0,
                'document_type': 'Commercial Invoice',
                'original_count': 3,
                'copy_count': 1,
                'special_requirements': 'Signed and stamped',
            }],
        )
        self.assertEqual(result['unknown_future_field'], 'preserve me')
        self.assertEqual(result['lc_amount'], 1250)
        self.assertEqual(result['expiry_date'], '2026-12-31')
        self.assertEqual(
            result['documents_required'][0]['affected_documents'],
            ['Commercial Invoice'],
        )
        self.assertEqual(result['documents_required'][0]['original_count'], 3)

    def test_merge_accepts_chinese_editor_columns_and_new_rows(self) -> None:
        ai = {
            **self.valid_values(),
            'documents_required': [{
                'document_type': 'Commercial Invoice',
                'original_count': 2,
                'copy_count': 1,
                'special_requirements': 'Signed',
                'affected_documents': ['Commercial Invoice'],
                'source_clause': 'keep-me',
            }],
        }
        result = merge_confirmed_values(
            ai,
            self.valid_values(),
            [
                {
                    '_source_index': 0.0,
                    '单据类型': 'Commercial Invoice',
                    '正本份数': 3,
                    '副本份数': 1,
                    '特殊要求': 'Signed and stamped',
                },
                {
                    '_source_index': float('nan'),
                    '单据类型': 'Packing List',
                    '正本份数': 1,
                    '副本份数': 0,
                    '特殊要求': '',
                },
            ],
        )
        self.assertEqual(len(result['documents_required']), 2)
        self.assertEqual(result['documents_required'][0]['original_count'], 3)
        self.assertEqual(result['documents_required'][0]['affected_documents'], ['Commercial Invoice'])
        self.assertEqual(result['documents_required'][0]['source_clause'], 'keep-me')
        self.assertEqual(result['documents_required'][1]['document_type'], 'Packing List')
        self.assertEqual(result['documents_required'][1]['original_count'], 1)
        errors = validate_confirmation(
            self.valid_values(),
            [{'单据类型': 'Bill of Lading', '正本份数': -2, '副本份数': 1}],
        )
        self.assertTrue(any('正本份数不能为负数' in error for error in errors))

    def test_source_excerpt_reports_unlocated_text_instead_of_guessing(self) -> None:
        original, translation = source_excerpts(
            'MT700 has no field label here.',
            '',
            'lc_no',
            'LC-01',
        )
        self.assertIn('未能定位', original)
        self.assertIn('未能定位', translation)


if __name__ == '__main__':
    unittest.main()
