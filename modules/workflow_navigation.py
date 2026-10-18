from __future__ import annotations

from collections.abc import Mapping

import streamlit as st

from modules.ui_style import subsection


STAGES = (
    '信用证确认',
    '订单录入',
    '单证生成',
    '一致性校验',
    'PDF导出',
)

_STATUS_MARKS = {
    '未开始': '○',
    '进行中': '◉',
    '待确认': '◷',
    '已完成': '✓',
    '有风险': '⚠',
}


def render_workflow_progress(
    statuses: Mapping[str, str],
    warning: str | None = None,
) -> None:
    """Render a compact, read-only view of the order workflow."""
    subsection('当前订单进度')
    columns = st.columns(len(STAGES))
    for column, stage in zip(columns, STAGES):
        status = statuses.get(stage, '未开始')
        mark = _STATUS_MARKS.get(status, _STATUS_MARKS['未开始'])
        with column:
            st.markdown(f'**{mark} {stage}**')
            st.caption(status)

    completed = sum(statuses.get(stage) == '已完成' for stage in STAGES)
    st.progress(completed / len(STAGES))
    if warning:
        st.warning(warning)


def build_workflow_statuses(
    order: Mapping | None,
    lc: Mapping | None,
    high_risk_open: bool = False,
    consistency: Mapping | None = None,
    lc_preview: bool = False,
) -> dict[str, str]:
    statuses = {stage: '未开始' for stage in STAGES}
    if lc:
        statuses['信用证确认'] = '已完成'
    elif lc_preview:
        statuses['信用证确认'] = '进行中'
    if order:
        statuses['订单录入'] = '已完成'
    workflow = (order or {}).get('workflow_status')
    documents_ready = workflow in {
        'documents_ready_for_review',
        'pdf_confirmed',
    }
    if documents_ready:
        statuses['单证生成'] = '已完成'
    elif workflow == 'documents_in_progress':
        statuses['单证生成'] = '进行中'

    if consistency:
        if consistency.get('blockers'):
            statuses['一致性校验'] = '有风险'
        elif consistency.get('needs_review') or consistency.get('warnings'):
            statuses['一致性校验'] = '待确认'
        elif documents_ready:
            statuses['一致性校验'] = '已完成'
        else:
            statuses['一致性校验'] = '进行中'
    elif documents_ready:
        statuses['一致性校验'] = '待确认'

    if workflow == 'pdf_confirmed':
        statuses['PDF导出'] = '已完成'
    elif consistency and consistency.get('blockers'):
        statuses['PDF导出'] = '有风险'
    elif documents_ready:
        statuses['PDF导出'] = '待确认'
    elif workflow == 'documents_in_progress':
        statuses['PDF导出'] = '未开始'

    if high_risk_open:
        statuses['信用证确认'] = '有风险'
    return statuses


def consistency_state_key(order_id: int | None) -> str:
    return f'workflow_consistency_{order_id}'


def invalidate_workflow_consistency(order_id: int | None) -> None:
    if order_id is None:
        return
    st.session_state.pop(consistency_state_key(order_id), None)


def render_page_next_step(label: str, target: str) -> None:
    if st.button(label, type='primary', use_container_width=True):
        st.switch_page(target)
