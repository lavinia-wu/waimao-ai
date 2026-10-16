from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.document_validation import (
    _artifact_values,
    _compare_values,
    _count_status,
    _document_count_requirements,
    _is_blocking_issue,
    _unresolved_high_risk_blockers,
    assert_pdf_consistency,
)


class DocumentValidationTests(unittest.TestCase):
    def test_normal_values_pass(self) -> None:
        self.assertIs(_compare_values('currency', 'USD', 'usd'), True)
        self.assertIs(
            _compare_values('incoterm', 'FOB\tShanghai\n', 'fob, Shanghai'),
            True,
        )
        self.assertIs(_compare_values('quantity', '1,200 MT', 1200), True)

    def test_amount_formats_compare_as_numbers(self) -> None:
        self.assertIs(_compare_values('total_amount', '$1,200.00', 'USD 1200'), True)
        self.assertIs(_compare_values('total_amount', 'US$1,200.00', 1200), True)

    def test_date_formats_compare_as_dates(self) -> None:
        self.assertIs(_compare_values('latest_shipment_date', '2026-10-16', '20261016'), True)

    def test_port_aliases_compare_as_same_port(self) -> None:
        self.assertIs(_compare_values('loading_port', 'Shanghai', 'Shanghai, China'), True)
        self.assertIs(_compare_values('destination_port', 'Jebel Ali', 'Jebel Ali, Dubai'), True)
        self.assertIs(_compare_values('destination_port', 'Rotterdam', 'Rotterdam, Netherlands'), True)

    def test_goods_description_may_include_supplementary_details(self) -> None:
        self.assertIs(
            _compare_values(
                'goods_description',
                'LDPE Resin',
                'LDPE RESIN, packed in 25 kg bags; HS Code 3901.10',
                core_product_name='LDPE Resin',
            ),
            True,
        )

    def test_unlabeled_template_fields_are_not_guessed(self) -> None:
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'custom.xlsx'
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(['LDPE Resin', '1,200', 'Shanghai'])
            workbook.save(path)
            workbook.close()

            extracted = _artifact_values(str(path))

        self.assertEqual(extracted, {})
        self.assertIsNone(_compare_values('quantity', '1,200', 'one thousand two hundred'))
        self.assertIsNone(
            _compare_values('latest_shipment_date', '16/10/2026', '2026-10-16')
        )

    def test_insufficient_document_counts_are_error(self) -> None:
        requirements = _document_count_requirements(
            {'id': 7},
            {'documents_required': [{
                'document_type': 'Commercial Invoice',
                'original_count': 3,
                'copy_count': 2,
            }]},
        )
        status, issues = _count_status(
            requirements,
            {'0': {'original_count': 2, 'copy_count': 2}},
        )
        self.assertEqual(status, 'error')
        self.assertTrue(issues)
        self.assertTrue(_is_blocking_issue({'status': status, 'severity': 'high'}))
        status, issues = _count_status(
            requirements,
            {'0': {'original_count': 3, 'copy_count': 2}},
        )
        self.assertEqual(status, 'passed')
        self.assertFalse(issues)

    def test_only_explicit_high_risk_error_blocks_pdf(self) -> None:
        self.assertTrue(_is_blocking_issue({'status': 'error', 'severity': 'high'}))
        self.assertFalse(_is_blocking_issue({'status': 'needs_review', 'severity': 'high'}))
        self.assertFalse(_is_blocking_issue({'status': 'error', 'severity': 'medium'}))

    def test_high_lc_risk_blocks_until_accepted_or_rectified(self) -> None:
        risk = {'risk_level': '高', 'risk_type': '付款条款', 'handling_status': '未处理'}
        self.assertEqual(len(_unresolved_high_risk_blockers([risk])), 1)
        for status in ('已确认可接受', '已整改'):
            risk['handling_status'] = status
            self.assertEqual(_unresolved_high_risk_blockers([risk]), [])
        for status in ('待客户确认', '待修改信用证'):
            risk['handling_status'] = status
            self.assertEqual(len(_unresolved_high_risk_blockers([risk])), 1)

    def test_pdf_gate_blocks_high_error_but_allows_needs_review(self) -> None:
        with patch(
            'modules.document_validation.validate_order_consistency',
            return_value={'blockers': [{
                'field': '总金额',
                'status': 'error',
                'severity': 'high',
                'reasons': ['信用证金额与订单金额明确不一致'],
            }]},
        ):
            with self.assertRaisesRegex(ValueError, '阻止生成 PDF'):
                assert_pdf_consistency(1)

        review_result = {
            'blockers': [],
            'needs_review': [{'field': 'CI · 数量', 'reasons': ['无法从模板可靠提取']}],
        }
        with patch(
            'modules.document_validation.validate_order_consistency',
            return_value=review_result,
        ):
            self.assertEqual(assert_pdf_consistency(1), review_result)


if __name__ == '__main__':
    unittest.main()
