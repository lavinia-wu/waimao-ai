from __future__ import annotations

import json
import hashlib

import pandas as pd
import streamlit as st
from PIL import UnidentifiedImageError

from modules.auth import require_authenticated_user
from modules.customers import get_customer_by_id
from modules.lc_deadlines import parse_date, render_lc_deadline_cards
from modules.lc_confirmation import (
    FIELD_GROUPS,
    build_change_summary,
    merge_confirmed_values,
    normalize_field_value,
    source_excerpts,
    validate_confirmation,
)
from modules.lc_parser import (
    RISK_HANDLING_STATUSES,
    analyze_lc_clauses,
    build_lc_summary,
    extract_lc_text,
    get_lc_by_id,
    get_lc_by_order,
    get_lc_risks,
    list_approved_lcs,
    parse_lc_text,
    save_lc_record,
    translate_lc_text,
    update_lc_risk_handling,
)
from modules.lc_workbench import (
    ALL_FIELD_INDEX,
    build_pending_items,
    build_pending_summary,
    lc_parsed_values,
    risk_target,
)
from modules.orders import get_order_by_id
from modules.ui_style import (
    page_header,
    render_data_table,
    section,
    subsection,
)
from modules.workflow_navigation import (
    build_workflow_statuses,
    consistency_state_key,
    invalidate_workflow_consistency,
    render_page_next_step,
    render_workflow_progress,
)


def risk_sort_key(item):
    level = str(item.get('risk_level', '')).strip().casefold()
    return {
        '高': 0, 'high': 0, 'critical': 0,
        '中': 1, 'medium': 1,
        '低': 2, 'low': 2,
    }.get(level, 1)


def risk_widget_key(item):
    clause = str(item.get('original_clause_en') or '')
    return hashlib.sha256(clause.encode('utf-8')).hexdigest()[:12]


def table_cell(value):
    return '' if pd.isna(value) else value


def normalized_count(value):
    value = table_cell(value)
    if value in (None, ''):
        return ''
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    return int(numeric) if numeric.is_integer() else numeric


def shown_count(value):
    normalized = normalized_count(value)
    return '未明确' if normalized == '' else normalized


def risks_for_save(risks):
    """汇总预览阶段的风险处理选择；只读取会话状态，不改写任何数据。"""
    updated = []
    for item in risks:
        if not isinstance(item, dict):
            continue
        risk = dict(item)
        key = f"{st.session_state.get('lc_upload_digest', 'preview')}_{risk_widget_key(risk)}"
        risk['handling_level'] = (
            '必须处理' if risk.get('risk_level') == '高'
            else '一般提示' if risk.get('risk_level') == '低'
            else '需确认'
        )
        risk['handling_status'] = st.session_state.get(
            f'preview_risk_status_{key}',
            risk.get('handling_status', '未处理'),
        )
        risk['handling_note'] = st.session_state.get(
            f'preview_risk_note_{key}',
            risk.get('handling_note', ''),
        )
        updated.append(risk)
    return updated


def preview_risks_with_handling(risks, form_digest):
    """把预览风险与用户在页面上的处理选择合并，仅用于统计与展示。"""
    merged = []
    for item in risks or []:
        if not isinstance(item, dict):
            continue
        risk = dict(item)
        key = f'{form_digest}_{risk_widget_key(risk)}'
        risk['handling_status'] = st.session_state.get(
            f'preview_risk_status_{key}',
            risk.get('handling_status', '未处理'),
        )
        merged.append(risk)
    return merged


def render_evidence(evidence):
    """第三层：按需展开的依据。默认不展示，不删除。"""
    for label, value in evidence.items():
        if value in (None, '', [], '—'):
            continue
        st.caption(f'{label}')
        st.text(value if isinstance(value, str) else '；'.join(map(str, value)))


owner_id = int(require_authenticated_user()['id'])

page_header(
    '信用证解析、条款分析与翻译',
    caption='先上传并确认信用证最终版本，再识别录入订单；信用证在订单确认时关联，并自动生成交单提醒。',
)
st.info('信用证文本会发送到 .env 配置的 AI 服务；若本机 OCR 不可用，图片也会发送给支持视觉的 AI 服务。分析结果请人工核对后再同步。')

approved_lcs = list_approved_lcs(owner_id)
current_order_id = st.session_state.get('workflow_current_order_id')
current_order = (
    get_order_by_id(current_order_id, owner_id)
    if current_order_id is not None
    else None
)
current_lc_id = st.session_state.get('workflow_current_lc_id')
current_lc = next(
    (item for item in approved_lcs if item.get('id') == current_lc_id),
    None,
)
if current_lc is None and current_order:
    linked_lc = get_lc_by_order(current_order['id'], owner_id)
    current_lc = next(
        (
            item for item in approved_lcs
            if linked_lc and item.get('id') == linked_lc.get('id')
        ),
        None,
    )

if approved_lcs:
    lc_options = {
        f"{item['lc_no']} · {item.get('applicant') or '申请人未填写'} · ID {item['id']}": item['id']
        for item in approved_lcs
    }
    selected_risk_lc = st.selectbox(
        '当前处理对象 · 已确认信用证',
        list(lc_options),
        key='risk_management_lc',
    )
    selected_lc_id = lc_options[selected_risk_lc]
    if selected_lc_id != current_lc_id:
        st.session_state['workflow_current_lc_id'] = selected_lc_id
        current_lc_id = selected_lc_id
        current_lc = next(
            (item for item in approved_lcs if item.get('id') == current_lc_id),
            None,
        )
        st.rerun()

# 处理对象状态：全部为只读取数
saved_record = get_lc_by_id(current_lc_id) if current_lc else None
saved_parsed = lc_parsed_values(saved_record)
saved_risks = sorted(get_lc_risks(current_lc_id), key=risk_sort_key) if current_lc else []
preview = st.session_state.get('lc_analysis_preview')
form_digest = st.session_state.get('lc_upload_digest', 'preview')
consistency = st.session_state.get(consistency_state_key(current_order_id))

# 预览态：字段取值与分组确认状态来自上一轮渲染，仅打开页面不会让字段变成已确认
preview_field_values = {
    field: st.session_state.get(f'lc_confirm_{form_digest}_{field}')
    for _group, field, _label, _kind, _required in ALL_FIELD_INDEX
}
confirmed_groups = [
    group_title
    for group_title, _fields in FIELD_GROUPS
    if st.session_state.get(f'lc_group_confirmed_{form_digest}_{group_title}')
]

if preview:
    preview_parsed = preview.get('parsed') or {}
    active_risks = preview_risks_with_handling(
        preview_parsed.get('adverse_clauses'), form_digest
    )
elif current_lc:
    preview_parsed = {}
    active_risks = saved_risks
else:
    preview_parsed = {}
    active_risks = []

if preview:
    active_documents = preview_parsed.get('documents_required') or []
    active_field_values = preview_field_values
    active_confirmed_groups = confirmed_groups
else:
    active_documents = saved_parsed.get('documents_required') or []
    active_field_values = saved_parsed
    # 已保存信用证没有逐组确认流程，缺失与无效字段仍要如实计入待确认
    active_confirmed_groups = []

summary = build_pending_summary(
    risks=active_risks,
    field_values=active_field_values,
    confirmed_groups=active_confirmed_groups,
    document_requirements=active_documents,
    consistency=consistency,
)
pending_items = build_pending_items(
    risks=active_risks,
    field_values=active_field_values,
    confirmed_groups=active_confirmed_groups,
    document_requirements=active_documents,
    consistency=consistency,
)
high_risk_open = summary['open_high_risk_count'] > 0

if 'lc_active_item' not in st.session_state:
    st.session_state['lc_active_item'] = None
if 'lc_active_group' not in st.session_state:
    st.session_state['lc_active_group'] = None

# ── 第一层：当前对象与处理概况 ───────────────────────────────
with st.container(border=True):
    subsection('当前对象')
    if current_lc:
        customer_name = '—'
        if current_order:
            customer = get_customer_by_id(int(current_order['customer_id']), None) if current_order.get('customer_id') else None
            customer_name = (
                (customer or {}).get('customer_name_cn')
                or (customer or {}).get('customer_name_en')
                or '—'
            )
        object_columns = st.columns(3)
        object_columns[0].metric(
            '订单', current_order['order_no'] if current_order else '未关联订单'
        )
        object_columns[1].metric('客户', customer_name)
        object_columns[2].metric(
            '信用证号', current_lc.get('lc_no') or f"ID {current_lc.get('id')}"
        )
        if not current_order:
            st.caption('该信用证尚未关联订单，关联后才能参与交单与 PDF 门禁校验。')
            render_page_next_step(
                '前往订单录入并关联该信用证', 'pages/4_订单录入与计算.py'
            )
    elif preview:
        st.metric('本次分析文件', preview.get('filename') or '—')
        st.caption('尚未保存为已确认信用证，确认并保存后才能关联订单。')
    else:
        st.caption('尚未选择信用证，也没有正在进行的分析。请先上传信用证文件。')

    render_lc_deadline_cards(preview_parsed or saved_parsed, current_order)

    subsection('处理概况')
    metric_columns = st.columns(4)
    metric_columns[0].metric('待确认字段', summary['pending_field_count'])
    metric_columns[1].metric('未处理高风险', summary['open_high_risk_count'])
    metric_columns[2].metric('待核对单据要求', summary['pending_document_count'])
    metric_columns[3].metric(
        'PDF 阻断',
        '未运行校验' if not summary['has_consistency']
        else f"{summary['blocking_count']} 项" if summary['blocking_count'] else '无',
    )
    if summary['blocking_reasons']:
        for reason in summary['blocking_reasons'][:2]:
            st.caption(f'阻断原因：{reason}')

    render_workflow_progress(
        build_workflow_statuses(
            current_order,
            current_lc,
            high_risk_open=high_risk_open,
            consistency=consistency,
            lc_preview=bool(preview),
        ),
        '当前信用证存在未处理的高风险条款；可继续前往订单录入，建议先核对并处理风险。'
        if high_risk_open else None,
    )

# ── 上传区：产生待办的入口 ──────────────────────────────────
section('上传信用证文件', caption='上传后点击识别；识别结果与译文均需人工核对后再保存。')
uploaded_file = st.file_uploader('上传信用证文件或图片', type=['pdf', 'png', 'jpg', 'jpeg'])
if 'lc_analysis_preview' not in st.session_state:
    st.session_state['lc_analysis_preview'] = None
if uploaded_file is not None:
    upload_digest = hashlib.sha256(uploaded_file.getvalue()).hexdigest()
    if st.session_state.get('lc_upload_digest') != upload_digest:
        st.session_state['lc_analysis_preview'] = None
        st.session_state['lc_upload_digest'] = upload_digest

if uploaded_file is not None and st.button('识别、分析并翻译', type='primary'):
    try:
        with st.spinner('正在提取信用证内容…'):
            raw_text = extract_lc_text(uploaded_file.name, uploaded_file.getvalue())
        if not raw_text.strip():
            st.error('未能从文件中识别出文字。若这是扫描件，请确认已安装 Tesseract，或配置支持视觉的 AI 服务。')
        else:
            parsed = parse_lc_text(raw_text)
            st.session_state['lc_analysis_preview'] = {
                'filename': uploaded_file.name,
                'raw_text': raw_text,
                'parsed': parsed,
            }
            with st.spinner('正在分析不利条款和单据要求…'):
                analysis = analyze_lc_clauses(raw_text)
            parsed['documents_required'] = analysis['document_requirements']
            parsed['adverse_clauses'] = analysis['adverse_clauses']
            parsed['presentation_period_days'] = analysis['presentation_period_days']
            parsed['dispatch_days_after_shipment'] = analysis['dispatch_days_after_shipment']
            parsed['dispatch_instruction'] = analysis['dispatch_instruction']
            st.session_state['lc_analysis_preview']['parsed'] = parsed
            st.session_state['lc_analysis_preview']['analysis'] = analysis
            with st.spinner('正在翻译信用证全文…'):
                translation = translate_lc_text(raw_text)
            st.session_state['lc_analysis_preview']['translation'] = translation
            st.session_state['lc_active_item'] = None
            st.rerun()
    except (ValueError, RuntimeError, OSError, UnidentifiedImageError) as exc:
        st.error(f'处理失败：{exc}')

# ── 第二层：待办处理区（第三层依据按需展开） ─────────────────
section(
    '待处理事项',
    caption='按业务优先级排列：先处理必须处理项，再确认字段与单据要求。',
)
if not pending_items:
    st.success('当前处理对象没有待处理事项。')
    st.caption(
        '本页待办处理完成，不等于全部单据已符合交单要求；'
        '交单请以单证生成与导出页的一致性校验和 PDF 门禁结果为准。'
    )
for index, item in enumerate(pending_items):
    target = item['target']
    with st.container(border=True):
        title_column, status_column, action_column = st.columns([5, 3, 2])
        with title_column:
            st.markdown(f"**{item['title']}**")
            st.caption(item['summary'])
        with status_column:
            st.caption(f"优先级：{item['priority']}")
            st.caption(f"当前状态：{item['status']}")
        with action_column:
            is_active = st.session_state.get('lc_active_item') == target
            if st.button(
                '收起依据' if is_active else '查看并处理',
                key=f'pending_toggle_{target}_{index}',
                use_container_width=True,
            ):
                st.session_state['lc_active_item'] = None if is_active else target
                if not is_active:
                    if item['kind'] == 'field':
                        st.session_state['lc_active_group'] = item['evidence'].get('所属分组')
                    elif item['kind'] == 'high_risk':
                        st.session_state['lc_active_group'] = target
                st.rerun()
        if st.session_state.get('lc_active_item') == target:
            render_evidence(item['evidence'])

st.caption(
    '本页待办处理完成，不等于全部单据已符合交单要求；'
    '交单请以单证生成与导出页的一致性校验和 PDF 门禁结果为准。'
)

# ── 第四层：处理操作 ────────────────────────────────────────
if saved_risks and not preview:
    section('高风险条款处理（已确认信用证）')
    for risk in saved_risks:
        level = str(risk.get('risk_level') or '中')
        status = str(risk.get('handling_status') or '未处理')
        with st.expander(
            f"[{level}风险] {risk.get('risk_type') or '信用证条款风险'} · {status}",
            expanded=st.session_state.get('lc_active_group') == risk_target(risk),
        ):
            st.caption(
                f"当前状态：{status} · 处理时间：{risk.get('handled_at') or '尚未处理'}"
            )
            with st.form(f"save_lc_risk_{risk['id']}"):
                current_status = status
                status_index = (
                    RISK_HANDLING_STATUSES.index(current_status)
                    if current_status in RISK_HANDLING_STATUSES else 0
                )
                updated_status = st.selectbox(
                    '处理状态',
                    RISK_HANDLING_STATUSES,
                    index=status_index,
                    key=f"risk_status_{risk['id']}",
                )
                updated_note = st.text_area(
                    '处理备注',
                    value=risk.get('handling_note') or '',
                    key=f"risk_note_{risk['id']}",
                )
                st.caption(
                    '「已确认可接受」表示人工接受该风险，不代表信用证风险已消除；'
                    '处理一条风险不会绕过其他风险与一致性门禁。'
                )
                save_risk = st.form_submit_button('保存该条款的处理记录')
            if save_risk:
                try:
                    update_lc_risk_handling(
                        risk['id'],
                        updated_status,
                        updated_note,
                        owner_id,
                    )
                    invalidate_workflow_consistency(current_order_id)
                    st.session_state['lc_active_group'] = None
                    st.success('该条款的处理状态、备注和处理时间已保存；相关旧校验结果已失效。')
                    st.rerun()
                except ValueError as exc:
                    st.error(f'保存风险处理记录失败：{exc}')

if preview:
    st.caption(f"当前分析文件：{preview['filename']}")
    analysis = preview.get('analysis')
    if analysis:
        parsed = preview['parsed']

        section('处理与保存本次分析')
        subsection('高风险条款处理')
        adverse_clauses = sorted(analysis['adverse_clauses'], key=risk_sort_key)
        if adverse_clauses:
            for item in adverse_clauses:
                item['handling_level'] = (
                    '必须处理' if item.get('risk_level') == '高'
                    else '一般提示' if item.get('risk_level') == '低'
                    else '需确认'
                )
                risk_key = f'{form_digest}_{risk_widget_key(item)}'
                current_status = st.session_state.get(
                    f'preview_risk_status_{risk_key}', '未处理'
                )
                with st.expander(
                    f"[{item.get('risk_level', '中')}风险] "
                    f"{item.get('risk_type') or '信用证条款风险'} · {current_status}",
                    expanded=st.session_state.get('lc_active_group') == risk_target(item)
                    or (
                        item.get('risk_level') == '高'
                        and current_status == '未处理'
                    ),
                ):
                    st.caption(f"**英文原文：** {item.get('original_clause_en') or '—'}")
                    st.caption(f"**中文翻译：** {item.get('clause_translation_cn') or '—'}")
                    st.caption(f"**风险解释：** {item.get('risk_explanation_cn') or '—'}")
                    st.caption(f"**整改建议：** {item.get('suggested_action_cn') or '—'}")
                    st.selectbox(
                        '处理状态',
                        RISK_HANDLING_STATUSES,
                        index=(
                            RISK_HANDLING_STATUSES.index(current_status)
                            if current_status in RISK_HANDLING_STATUSES else 0
                        ),
                        key=f'preview_risk_status_{risk_key}',
                    )
                    st.text_area(
                        '处理备注',
                        key=f'preview_risk_note_{risk_key}',
                        placeholder='记录核对结论、客户反馈或信用证修改情况',
                    )
                    st.caption(
                        '「已确认可接受」表示人工接受该风险，不代表信用证风险已消除。'
                    )
        else:
            st.success('未识别到明显不利条款；仍建议人工核对信用证原文。')

        subsection('逐组确认字段')
        confirmed_values = {}
        for group_title, fields in FIELD_GROUPS:
            group_confirmed = bool(
                st.session_state.get(f'lc_group_confirmed_{form_digest}_{group_title}')
            )
            with st.expander(
                f'{group_title}（{"已确认" if group_confirmed else "待确认"}）',
                expanded=st.session_state.get('lc_active_group') == group_title
                or not group_confirmed,
            ):
                for field, label, kind, required, aliases in fields:
                    ai_value = parsed.get(field)
                    widget_key = f'lc_confirm_{form_digest}_{field}'
                    st.markdown(f"**{label}{'（必填）' if required else ''}**")
                    ai_col, confirmed_col, state_col = st.columns([1, 1, 1])
                    normalized_ai = normalize_field_value(field, kind, ai_value)
                    with ai_col:
                        st.caption('AI识别值')
                        st.write(
                            normalized_ai
                            if normalized_ai not in (None, '')
                            else '未识别'
                        )
                    with confirmed_col:
                        st.caption('人工确认值')
                        if kind == 'date':
                            initial_date = parse_date(ai_value)
                            if ai_value not in (None, '') and initial_date is None:
                                st.warning(f'AI 日期无法识别：{ai_value}')
                            human_value = st.date_input(
                                label,
                                value=initial_date,
                                key=widget_key,
                                format='YYYY/MM/DD',
                                label_visibility='collapsed',
                            )
                        elif kind == 'number':
                            initial_number = (
                                float(normalized_ai)
                                if isinstance(normalized_ai, (int, float))
                                else None
                            )
                            human_value = st.number_input(
                                label,
                                value=initial_number,
                                min_value=0.0,
                                step=0.01 if field in {'lc_amount', 'unit_price', 'tolerance_percentage'} else 1.0,
                                key=widget_key,
                                placeholder='请输入数值',
                                label_visibility='collapsed',
                            )
                        elif kind == 'boolean':
                            boolean_options = (
                                ['待核对', 'Yes', 'No']
                                if normalized_ai == ''
                                else ['Yes', 'No']
                            )
                            initial_boolean = (
                                normalized_ai if normalized_ai else '待核对'
                            )
                            selected_boolean = st.selectbox(
                                label,
                                boolean_options,
                                index=boolean_options.index(initial_boolean),
                                key=widget_key,
                                label_visibility='collapsed',
                            )
                            human_value = selected_boolean
                        elif kind == 'multiline':
                            human_value = st.text_area(
                                label,
                                value=str(ai_value or ''),
                                key=widget_key,
                                label_visibility='collapsed',
                                height=90,
                            )
                        else:
                            human_value = st.text_input(
                                label,
                                value=str(ai_value or ''),
                                key=widget_key,
                                label_visibility='collapsed',
                            )
                    confirmed_values[field] = human_value
                    normalized_human = normalize_field_value(field, kind, human_value)
                    if required and normalized_human in (None, ''):
                        field_status = '缺少必填值'
                    elif (
                        kind == 'date'
                        and human_value not in (None, '')
                        and not parse_date(human_value)
                    ):
                        field_status = '日期格式无效'
                    elif (
                        kind == 'number'
                        and normalized_ai not in (None, '')
                        and not isinstance(normalized_ai, (int, float))
                        and human_value is None
                    ):
                        field_status = 'AI数值无法识别，待人工填写'
                    elif kind == 'number' and human_value is not None and normalize_field_value(field, kind, human_value) == human_value and not isinstance(human_value, (int, float)):
                        field_status = '数值格式无效'
                    elif normalized_human != normalized_ai:
                        field_status = '已人工修改'
                    else:
                        field_status = '格式有效，待确认'
                    original_excerpt, translated_excerpt = source_excerpts(
                        preview.get('raw_text', ''),
                        preview.get('translation', ''),
                        field,
                        ai_value,
                    )
                    with state_col:
                        st.caption('字段校验状态')
                        st.write(field_status)
                        st.caption(
                            '数据来源：人工确认值'
                            if normalized_human != normalized_ai
                            else '数据来源：AI识别 / 信用证原文'
                        )
                    with st.expander(f'{label} · 原文与中文翻译', expanded=False):
                        source_col, translation_col = st.columns(2)
                        with source_col:
                            st.caption('英文原文')
                            st.text(original_excerpt)
                        with translation_col:
                            st.caption('中文翻译')
                            st.text(translated_excerpt)
                if st.button(f'确认本组：{group_title}', key=f'group_confirm_{form_digest}_{group_title}'):
                    st.session_state[f'lc_group_confirmed_{form_digest}_{group_title}'] = True
                    st.session_state['lc_active_group'] = None
                    st.rerun()

        deadline_values = merge_confirmed_values(parsed, confirmed_values, [])
        subsection('信用证关键期限')
        render_lc_deadline_cards(deadline_values, current_order)

        subsection('单据要求（可编辑）')
        source_requirements = parsed.get('documents_required') or []
        if not source_requirements:
            st.warning('未从信用证中识别到明确的单据份数要求，请人工核对原文后手工补充。')
        document_editor_rows = [
            {
                '_source_index': index,
                '单据类型': item.get('document_type', ''),
                '正本份数': item.get('original_count'),
                '副本份数': item.get('copy_count'),
                '特殊要求': item.get('special_requirements') or item.get('requirements') or '',
            }
            for index, item in enumerate(source_requirements)
            if isinstance(item, dict)
        ]
        document_editor_data = st.data_editor(
            pd.DataFrame(
                document_editor_rows,
                columns=['_source_index', '单据类型', '正本份数', '副本份数', '特殊要求'],
            ),
            column_config={
                '_source_index': None,
                '单据类型': st.column_config.TextColumn('单据类型', required=True),
                '正本份数': st.column_config.NumberColumn(
                    '正本份数', min_value=0, step=1, format='%d'
                ),
                '副本份数': st.column_config.NumberColumn(
                    '副本份数', min_value=0, step=1, format='%d'
                ),
                '特殊要求': st.column_config.TextColumn('特殊要求'),
            },
            num_rows='dynamic',
            hide_index=True,
            key=f'lc_document_requirements_{form_digest}',
        )
        document_rows = document_editor_data.to_dict(orient='records')
        st.caption('数据来源：信用证原文及 AI 条款分析；空白份数表示原文未明确。')
        document_source_rows = []
        for row_index, row in enumerate(document_rows):
            source_index = row.get('_source_index')
            try:
                ai_requirement = source_requirements[int(source_index)]
            except (ValueError, TypeError, IndexError):
                ai_requirement = {}
            original_excerpt, translated_excerpt = source_excerpts(
                preview.get('raw_text', ''),
                preview.get('translation', ''),
                'documents_required',
                ai_requirement.get('document_type'),
            )
            ai_values = (
                f"{ai_requirement.get('document_type', '未识别')} · "
                f"正本 {ai_requirement.get('original_count', '未明确')} / "
                f"副本 {ai_requirement.get('copy_count', '未明确')} · "
                f"{ai_requirement.get('special_requirements') or ai_requirement.get('requirements') or ''}"
            )
            confirmed_doc_type = str(table_cell(row.get('单据类型')) or '').strip()
            changed = (
                confirmed_doc_type != str(ai_requirement.get('document_type') or '')
                or normalized_count(row.get('正本份数')) != normalized_count(ai_requirement.get('original_count'))
                or normalized_count(row.get('副本份数')) != normalized_count(ai_requirement.get('copy_count'))
                or str(table_cell(row.get('特殊要求')) or '') != str(
                    ai_requirement.get('special_requirements')
                    or ai_requirement.get('requirements')
                    or ''
                )
            )
            row_errors = [
                error for error in validate_confirmation({}, [row])
                if error.startswith('单据要求第')
            ]
            document_status = (
                '校验错误：' + '；'.join(row_errors)
                if row_errors
                else '已修改' if changed else '格式有效，未修改'
            )
            document_source_rows.append({
                '字段名': f"单据要求 · {confirmed_doc_type or f'第{row_index + 1}行'}",
                '英文原文': original_excerpt,
                '中文翻译': translated_excerpt,
                'AI识别值': ai_values if ai_requirement else '未识别',
                '人工确认值': (
                    f"{confirmed_doc_type} · 正本 {shown_count(row.get('正本份数'))} / "
                    f"副本 {shown_count(row.get('副本份数'))} · "
                    f"{table_cell(row.get('特殊要求')) or ''}"
                ),
                '字段校验状态': document_status,
                '数据来源': '人工确认值' if changed else 'AI条款分析 / 信用证原文',
            })
        if document_source_rows:
            with st.expander(f'逐行来源对照（{len(document_source_rows)} 行）', expanded=False):
                render_data_table([dict(row) for row in document_source_rows])
        final_translation = st.text_area(
            '信用证中文翻译（可修改）',
            value=preview.get('translation') or '',
            key=f'lc_translation_{form_digest}',
            height=220,
        )
        final_parsed_preview = merge_confirmed_values(
            parsed,
            confirmed_values,
            document_rows,
        )
        final_parsed_preview['adverse_clauses'] = risks_for_save(
            parsed.get('adverse_clauses', adverse_clauses)
        )

        change_summary = build_change_summary(parsed, confirmed_values)
        for row_index, row in enumerate(document_rows):
            source_index = row.get('_source_index')
            try:
                ai_requirement = source_requirements[int(source_index)]
            except (ValueError, TypeError, IndexError):
                ai_requirement = {}
            current_doc_type = str(table_cell(row.get('单据类型')) or '').strip()
            ai_doc = ai_requirement.get('document_type', '')
            ai_count = (
                f"{normalized_count(ai_requirement.get('original_count'))} / "
                f"{normalized_count(ai_requirement.get('copy_count'))}"
            )
            human_count = (
                f"{normalized_count(row.get('正本份数'))} / "
                f"{normalized_count(row.get('副本份数'))}"
            )
            changed = (
                current_doc_type != ai_doc
                or normalized_count(row.get('正本份数')) != normalized_count(ai_requirement.get('original_count'))
                or normalized_count(row.get('副本份数')) != normalized_count(ai_requirement.get('copy_count'))
                or str(table_cell(row.get('特殊要求')) or '') != str(
                    ai_requirement.get('special_requirements')
                    or ai_requirement.get('requirements')
                    or ''
                )
            )
            change_summary.append({
                '字段名': f'单据要求 · {current_doc_type or f"第{row_index + 1}行"}',
                'AI识别值': f'{ai_doc} · 正本/副本 {ai_count}',
                '人工修改值': (
                    f"{current_doc_type} · 正本/副本 {human_count} · "
                    f"{table_cell(row.get('特殊要求')) or ''}"
                ),
                '是否修改': '是' if changed else '否',
            })
        with st.expander(f'保存前变更摘要（{len(change_summary)} 项）', expanded=False):
            render_data_table([dict(row) for row in change_summary])

        validation_errors = validate_confirmation(confirmed_values, document_rows)
        if not final_translation.strip():
            validation_errors.append('请确认并保存信用证中文翻译。')
        if validation_errors:
            st.error('结构化校验未通过：\n\n' + '\n'.join(f'- {error}' for error in validation_errors))

        confirmed = st.checkbox(
            '我已逐项核对信用证原文、翻译、分组字段和单据要求，确认该版本可用于订单执行。',
            key=f'lc_final_confirmed_{form_digest}',
        )
        save_final = st.button(
            '确认最终版本并保存待关联信用证',
            type='primary',
            disabled=bool(validation_errors),
        )
        if save_final:
            if not confirmed:
                st.error('请先勾选确认。')
            else:
                try:
                    lc_id = save_lc_record(
                        None,
                        final_parsed_preview,
                        preview['raw_text'],
                        final_parsed_preview['adverse_clauses'],
                        translation_text=final_translation,
                        owner_id=owner_id,
                        approved_by=owner_id,
                    )
                    st.session_state['workflow_current_lc_id'] = lc_id
                    invalidate_workflow_consistency(
                        st.session_state.get('workflow_current_order_id')
                    )
                    for key in list(st.session_state.keys()):
                        if str(key).startswith(f'lc_confirm_{form_digest}_') or str(key).startswith(
                            f'lc_group_confirmed_{form_digest}_'
                        ) or str(key).startswith('preview_risk_'):
                            st.session_state.pop(key, None)
                    st.session_state.pop(f'lc_document_requirements_{form_digest}', None)
                    st.session_state.pop(f'lc_translation_{form_digest}', None)
                    st.session_state.pop(f'lc_final_confirmed_{form_digest}', None)
                    st.session_state.pop('lc_analysis_preview', None)
                    st.session_state.pop('lc_upload_digest', None)
                    st.session_state['lc_active_item'] = None
                    st.session_state['lc_active_group'] = None
                    st.success(f'信用证最终版本已确认保存（记录 ID：{lc_id}）。下一步请识别录入订单并关联该信用证。')
                    st.rerun()
                except (ValueError, TypeError) as exc:
                    st.error(f'无法保存信用证最终版本：{exc}')
    else:
        st.info('原文已提取。请配置 AI 服务后点击“识别、分析并翻译”以继续分析。')

# ── 第五层：下一步入口 ──────────────────────────────────────
section('下一步')
next_columns = st.columns(3)
with next_columns[0]:
    if not current_order:
        render_page_next_step('关联订单：前往订单录入', 'pages/4_订单录入与计算.py')
    else:
        render_page_next_step('前往单证生成与导出', 'pages/5_单证生成与导出.py')
with next_columns[1]:
    if summary['open_high_risk_count']:
        st.caption(f"还有 {summary['open_high_risk_count']} 条高风险条款未处理，请先处理。")
    elif summary['pending_field_count']:
        st.caption(f"还有 {summary['pending_field_count']} 个字段待确认，请先确认。")
    else:
        st.caption('当前没有待处理事项，可继续下一步。')
with next_columns[2]:
    if summary['blocking_reasons']:
        st.caption(f"存在 {summary['blocking_count']} 项 PDF 阻断，需在单证生成页重新运行一致性校验。")
    elif not summary['has_consistency']:
        st.caption('尚未运行一致性校验。')

# ── 第三层的完整依据：原文与结构化视图（折叠保留，不常驻展开）──
if preview:
    with st.expander('识别出的信用证原文（只读）', expanded=False):
        st.text_area(
            '原文',
            preview['raw_text'],
            height=220,
            disabled=True,
            label_visibility='collapsed',
        )
    with st.expander('关键信息摘要（AI 生成）', expanded=False):
        st.text(build_lc_summary(preview['parsed']))
    with st.expander('结构化字段（AI 识别结果）', expanded=False):
        st.json(preview['parsed'])
    with st.expander('高级 JSON 视图（保存前预览）', expanded=False):
        st.code(
            json.dumps(
                {
                    'parsed': preview['parsed'],
                    'analysis': preview.get('analysis') or {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            language='json',
        )
