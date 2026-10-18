from __future__ import annotations

import unittest

from modules.document_validation import _unresolved_high_risk_blockers
from modules.lc_workbench import (
    build_pending_items,
    build_pending_summary,
    pending_fields,
    risk_target,
    unresolved_document_requirements,
)


def risk(level: str, status: str = '未处理', risk_id: int | None = None, clause: str = '') -> dict:
    item = {
        'risk_level': level,
        'risk_type': f'{level}风险条款',
        'handling_status': status,
        'original_clause_en': clause or f'clause {level} {status}',
        'risk_explanation_cn': '取得文件依赖客户配合，当前未处理。',
        'suggested_action_cn': '建议要求开证行修改该条款。',
    }
    if risk_id is not None:
        item['id'] = risk_id
    return item


class HighRiskCountTestCase(unittest.TestCase):
    def test_counts_only_unhandled_high_risks(self) -> None:
        summary = build_pending_summary(risks=[
            risk('高'),
            risk('高', '已整改'),
            risk('高', '已确认可接受'),
            risk('中'),
            risk('低'),
        ])
        self.assertEqual(1, summary['open_high_risk_count'])

    def test_handling_one_risk_reduces_count(self) -> None:
        risks = [risk('高', risk_id=1), risk('高', risk_id=2)]
        self.assertEqual(2, build_pending_summary(risks=risks)['open_high_risk_count'])
        risks[0]['handling_status'] = '已整改'
        self.assertEqual(1, build_pending_summary(risks=risks)['open_high_risk_count'])

    def test_temporary_status_does_not_count_as_handled(self) -> None:
        """待客户确认 / 待修改信用证 都还不算处理完成。"""
        for status in ('未处理', '待客户确认', '待修改信用证'):
            with self.subTest(status=status):
                summary = build_pending_summary(risks=[risk('高', status)])
                self.assertEqual(1, summary['open_high_risk_count'])

    def test_matches_pdf_gate(self) -> None:
        """工作台统计必须与 PDF 服务端门禁口径一致，不能给出相反结论。"""
        risks = [risk('高'), risk('高', '已整改'), risk('中')]
        self.assertEqual(
            len(_unresolved_high_risk_blockers(risks)),
            build_pending_summary(risks=risks)['open_high_risk_count'],
        )


class PendingFieldTestCase(unittest.TestCase):
    def test_missing_required_field_is_pending(self) -> None:
        pending = pending_fields({})
        labels = [item['label'] for item in pending]
        self.assertIn('信用证编号', labels)
        self.assertIn('申请人', labels)
        self.assertIn('受益人', labels)

    def test_confirming_group_removes_its_fields(self) -> None:
        before = pending_fields({})
        after = pending_fields({}, confirmed_groups=['基本信息组'])
        self.assertLess(len(after), len(before))
        self.assertNotIn('基本信息组', [item['group'] for item in after])

    def test_viewing_without_confirming_keeps_pending(self) -> None:
        """只把值填上不算确认：未确认分组内的字段仍计入待确认。"""
        values = {'lc_no': 'LC-1', 'applicant': 'A', 'beneficiary': 'B'}
        self.assertEqual(
            len(pending_fields(values)),
            len(pending_fields(values, confirmed_groups=[])),
        )

    def test_invalid_date_is_pending(self) -> None:
        pending = pending_fields({'latest_shipment_date': '下一个月'})
        reasons = [item['reason'] for item in pending]
        self.assertTrue(any('无法识别' in reason for reason in reasons))

    def test_valid_date_is_not_pending(self) -> None:
        values = {
            'lc_no': 'LC-1', 'applicant': 'A', 'beneficiary': 'B',
            'lc_amount': 100, 'currency': 'USD', 'goods_description': 'PP',
            'latest_shipment_date': '2026-11-20',
            'transshipment_allowed': 'Yes',
            'partial_shipment_allowed': 'Yes',
        }
        self.assertEqual([], pending_fields(values, confirmed_groups=[
            '基本信息组', '金额与贸易条款组', '日期组', '港口与运输组', '货物描述组',
        ]))


class DocumentRequirementTestCase(unittest.TestCase):
    def test_unknown_counts_are_pending(self) -> None:
        requirements = [
            {'document_type': '商业发票', 'original_count': 3, 'copy_count': 1},
            {'document_type': '提单', 'original_count': None, 'copy_count': None},
            {'document_type': '产地证', 'original_count': 1, 'copy_count': None},
            {'document_type': '', 'original_count': None, 'copy_count': None},
        ]
        pending = unresolved_document_requirements(requirements)
        self.assertEqual(3, len(pending))
        # 份数与类型都明确的单据要求不再计入待核对
        self.assertEqual(0, build_pending_summary(
            document_requirements=[
                {'document_type': '商业发票', 'original_count': 3, 'copy_count': 1},
            ],
        )['pending_document_count'])

    def test_editor_rows_are_normalized(self) -> None:
        requirements = [{'单据类型': '提单', '正本份数': None, '副本份数': None}]
        self.assertEqual(1, len(unresolved_document_requirements(requirements)))


class PendingItemTestCase(unittest.TestCase):
    def test_priority_order(self) -> None:
        items = build_pending_items(
            risks=[risk('高', risk_id=1)],
            field_values={},
            document_requirements=[
                {'document_type': '提单', 'original_count': None, 'copy_count': None},
            ],
            consistency={'blockers': [{
                'field': '金额不一致',
                'status': 'error',
                'severity': 'high',
                'reasons': ['信用证金额与订单金额不一致'],
            }]},
        )
        priorities = [item['priority'] for item in items]
        self.assertEqual(priorities, sorted(priorities, key=['必须处理', '需确认', '一般提示'].index))

    def test_blocking_reasons_only_high_errors(self) -> None:
        summary = build_pending_summary(consistency={'blockers': [
            {'field': '阻断项', 'status': 'error', 'severity': 'high', 'reasons': ['金额不一致']},
            {'field': '提醒项', 'status': 'warning', 'severity': 'medium', 'reasons': ['建议核对']},
        ]})
        self.assertEqual(1, summary['blocking_count'])
        self.assertTrue(summary['blocking_reasons'])
        self.assertEqual(0, build_pending_summary(consistency={'blockers': []})['blocking_count'])

    def test_preview_risks_have_distinct_targets(self) -> None:
        targets = {risk_target(risk('高', clause=f'clause {index}')) for index in range(5)}
        self.assertEqual(5, len(targets))

    def test_saved_risk_target_uses_id(self) -> None:
        self.assertEqual('risk_12', risk_target(risk('高', risk_id=12)))


if __name__ == '__main__':
    unittest.main()
