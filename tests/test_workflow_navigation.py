from modules.workflow_navigation import build_workflow_statuses


def test_workflow_statuses_reflect_order_lc_and_pdf_completion():
    statuses = build_workflow_statuses(
        {'workflow_status': 'pdf_confirmed'},
        {'id': 7},
    )

    assert statuses == {
        '信用证确认': '已完成',
        '订单录入': '已完成',
        '单证生成': '已完成',
        '一致性校验': '待确认',
        'PDF导出': '已完成',
    }


def test_workflow_statuses_flag_unresolved_risk_without_removing_navigation():
    statuses = build_workflow_statuses(
        {'workflow_status': 'documents_ready_for_review'},
        {'id': 7},
        high_risk_open=True,
        consistency={'blockers': [{'field': '数量'}]},
    )

    assert statuses['信用证确认'] == '有风险'
    assert statuses['一致性校验'] == '有风险'
    assert statuses['PDF导出'] == '有风险'


def test_unavailable_order_steps_remain_not_started():
    statuses = build_workflow_statuses(None, None, lc_preview=True)

    assert statuses['信用证确认'] == '进行中'
    assert statuses['订单录入'] == '未开始'
    assert statuses['单证生成'] == '未开始'
    assert statuses['一致性校验'] == '未开始'
    assert statuses['PDF导出'] == '未开始'
