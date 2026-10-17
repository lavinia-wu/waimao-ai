from __future__ import annotations

import unittest

from modules.workflow_navigation import build_workflow_statuses


class WorkflowNavigationTests(unittest.TestCase):
    def test_workflow_statuses_reflect_order_lc_and_pdf_completion(self) -> None:
        statuses = build_workflow_statuses(
            {'workflow_status': 'pdf_confirmed'},
            {'id': 7},
        )

        self.assertEqual(statuses, {
            '信用证确认': '已完成',
            '订单录入': '已完成',
            '单证生成': '已完成',
            '一致性校验': '待确认',
            'PDF导出': '已完成',
        })

    def test_workflow_statuses_flag_unresolved_risk_without_removing_navigation(self) -> None:
        statuses = build_workflow_statuses(
            {'workflow_status': 'documents_ready_for_review'},
            {'id': 7},
            high_risk_open=True,
            consistency={'blockers': [{'field': '数量'}]},
        )

        self.assertEqual(statuses['信用证确认'], '有风险')
        self.assertEqual(statuses['一致性校验'], '有风险')
        self.assertEqual(statuses['PDF导出'], '有风险')

    def test_unavailable_order_steps_remain_not_started(self) -> None:
        statuses = build_workflow_statuses(None, None, lc_preview=True)

        self.assertEqual(statuses['信用证确认'], '进行中')
        self.assertEqual(statuses['订单录入'], '未开始')
        self.assertEqual(statuses['单证生成'], '未开始')
        self.assertEqual(statuses['一致性校验'], '未开始')
        self.assertEqual(statuses['PDF导出'], '未开始')


if __name__ == '__main__':
    unittest.main()
