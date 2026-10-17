from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import modules.workflow_navigation
from modules.workflow_navigation import (
    build_workflow_statuses,
    consistency_state_key,
    invalidate_workflow_consistency,
)


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


class WorkflowConsistencyInvalidationTests(unittest.TestCase):
    """Saving a LC or regenerating documents must drop the cached consistency result."""

    def setUp(self) -> None:
        self.fake_state: dict = {}
        self.patcher = patch.object(
            modules.workflow_navigation,
            'st',
            SimpleNamespace(session_state=self.fake_state),
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()

    def test_state_key_matches_page_convention(self) -> None:
        self.assertEqual(
            'workflow_consistency_12',
            consistency_state_key(12),
        )

    def test_invalidate_removes_the_cached_consistency_result(self) -> None:
        key = consistency_state_key(12)
        self.fake_state[key] = {
            'blockers': [{'field': '数量'}],
            'needs_review': [],
            'warnings': [],
        }

        invalidate_workflow_consistency(12)

        self.assertNotIn(key, self.fake_state)

    def test_invalidate_leaves_other_orders_untouched(self) -> None:
        self.fake_state[consistency_state_key(12)] = {'blockers': []}
        self.fake_state[consistency_state_key(13)] = {'blockers': []}

        invalidate_workflow_consistency(12)

        self.assertNotIn(consistency_state_key(12), self.fake_state)
        self.assertIn(consistency_state_key(13), self.fake_state)

    def test_invalidate_without_order_id_is_a_safe_noop(self) -> None:
        # A None order_id must return early instead of touching/creating the
        # "workflow_consistency_None" key or any other entry.
        self.fake_state[consistency_state_key(None)] = {'blockers': []}
        self.fake_state[consistency_state_key(12)] = {'blockers': []}

        invalidate_workflow_consistency(None)

        self.assertIn(consistency_state_key(None), self.fake_state)
        self.assertIn(consistency_state_key(12), self.fake_state)
        self.assertEqual(2, len(self.fake_state))

    def test_invalidate_on_missing_key_does_not_raise(self) -> None:
        invalidate_workflow_consistency(999)
        self.assertEqual({}, self.fake_state)


if __name__ == '__main__':
    unittest.main()
