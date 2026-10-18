from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from datetime import datetime

import streamlit as st

from config.settings import settings
from database.db import get_connection
from modules.auth import require_authenticated_user
from modules.documents import (
    DOCUMENT_TYPES,
    generate_all_documents_for_order,
    generate_document,
    generate_pdfs_for_order,
    get_document_lc_instructions,
    get_excel_template_sheets,
    get_order_output_dir,
    list_excel_templates,
    list_word_templates,
)
from modules.document_validation import (
    get_document_count_requirements,
    validate_order_consistency,
)
from modules.lc_deadlines import render_lc_deadline_cards
from modules.lc_parser import get_lc_by_order, get_lc_risks
from modules.orders import list_orders
from services.word_service import ensure_default_template
from modules.ui_style import (
    page_header,
    render_data_table,
    render_status_badge,
    section,
    subsection,
)
from modules.workflow_navigation import (
    build_workflow_statuses,
    invalidate_workflow_consistency,
    render_workflow_progress,
)


owner_id = int(require_authenticated_user()['id'])


def save_uploaded_template(uploaded_file):
    if uploaded_file is None:
        return None
    settings.templates_dir.mkdir(parents=True, exist_ok=True)
    original_name = Path(uploaded_file.name).name
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', original_name).replace(' ', '_')
    content = uploaded_file.getvalue()
    digest = hashlib.sha256(content).hexdigest()[:12]
    target = settings.templates_dir / f'custom_{Path(safe_name).stem}_{digest}{Path(safe_name).suffix.lower()}'
    if not target.exists():
        target.write_bytes(content)
    return str(target)


def suggested_word_template(paths, document_type, fallback):
    preferred_tokens = {
        'PI': ('proforma', 'pi', '形式发票'),
        'Commercial Invoice': ('commercial invoice',),
        'Packing List': ('packing list',),
        'Sales Contract': ('sales contract',),
    }
    for path in paths:
        filename = Path(path).stem.lower().replace('_', ' ').replace('-', ' ')
        if any(token in filename for token in preferred_tokens[document_type]):
            return path
    return fallback


def templates_for_document(document_type):
    templates = list_word_templates()
    default_path = str(Path(ensure_default_template(document_type)))
    if default_path not in templates:
        templates.append(default_path)
    if document_type in {'Commercial Invoice', 'Packing List'}:
        expected_sheet = 'COMMERCIAL INVOICE' if document_type == 'Commercial Invoice' else 'PACKING LIST'
        for excel_path in list_excel_templates():
            sheets = get_excel_template_sheets(excel_path)
            if any(expected_sheet in sheet.upper() for sheet in sheets):
                templates.append(excel_path)
    return templates, default_path


def suggested_template(paths, document_type, fallback):
    if document_type in {'Commercial Invoice', 'Packing List'}:
        expected_tokens = (
            ('commercial invoice', 'invoice', 'ci')
            if document_type == 'Commercial Invoice'
            else ('packing list', 'packing', 'pl')
        )
        excel_paths = [path for path in paths if Path(path).suffix.lower() == '.xlsx']
        for path in excel_paths:
            stem = Path(path).stem.lower().replace('_', ' ').replace('-', ' ')
            if any(token in stem for token in expected_tokens):
                return path
        if excel_paths:
            return excel_paths[0]
    return fallback


def template_format_label(path):
    suffix = Path(path).suffix.lower()
    format_name = 'Excel' if suffix == '.xlsx' else 'Word'
    return f'{Path(path).name}（{format_name}）'


def document_status_rows(order_id: int) -> list[dict]:
    """只读读取 documents 表，展示四单实际生成情况（不做任何写入）。"""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT document_type, file_path_word, file_path_pdf, file_path_excel, updated_at
            FROM documents WHERE order_id = ?
            """,
            (order_id,),
        ).fetchall()
    record_by_type = {row['document_type']: row for row in rows}
    result = []
    for document_type in DOCUMENT_TYPES:
        record = record_by_type.get(document_type)
        formats = []
        if record:
            if record['file_path_word']:
                formats.append('Word')
            if record['file_path_excel']:
                formats.append('Excel')
            if record['file_path_pdf']:
                formats.append('PDF')
        result.append({
            '单证': document_type,
            '已生成格式': '、'.join(formats) or '未生成',
            'PDF': '已生成' if record and record['file_path_pdf'] else '未生成',
            '更新时间': record['updated_at'] if record else '—',
        })
    return result


def generated_file_rows(order_id: int) -> list[dict]:
    """只读列出输出目录中的文件，供统一下载。"""
    output_dir = get_order_output_dir(order_id)
    if not output_dir.exists():
        return []
    rows = []
    for item in sorted(output_dir.iterdir()):
        if not item.is_file():
            continue
        stat = item.stat()
        rows.append({
            '文件名': item.name,
            '大小(KB)': round(stat.st_size / 1024, 1),
            '修改时间': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
            '_path': str(item),
        })
    return rows


page_header(
    '单证生成与导出',
    caption='每种单证仅生成所选模板对应的文件格式；CI、PL 可分别选用 Excel 模板；'
            '生成文件集中保存在 outputs 子文件夹。',
)

orders = list_orders(owner_id=owner_id)
order_map = {f"{order['order_no']} | {order.get('customer_name_cn', '')} | {order.get('product_name_en', '')}": order['id'] for order in orders}
order_labels = list(order_map.keys()) or ['暂无订单']
previous_order_id = st.session_state.get('workflow_current_order_id')
selected_index = next(
    (
        index for index, label in enumerate(order_labels)
        if order_map.get(label) == previous_order_id
    ),
    0,
)
selected_order_label = st.selectbox(
    '选择订单',
    options=order_labels,
    index=selected_index,
    key='document_selected_order_label',
)
selected_order_id = order_map.get(selected_order_label)

if selected_order_id is None:
    st.warning('请先在“订单录入与计算”页面创建订单。')
    st.stop()
st.session_state['workflow_current_order_id'] = selected_order_id
selected_order = next((order for order in orders if order['id'] == selected_order_id), None)
workflow_labels = {
    'order_confirmed': '订单已确认，待关联信用证/生成单证',
    'credit_confirmed': '信用证已确认，待生成四单',
    'documents_in_progress': '四单生成中',
    'documents_ready_for_review': '四单已生成，待业务员复核',
    'pdf_confirmed': '业务员已确认 PDF 版本',
}
workflow_tones = {
    'order_confirmed': 'neutral',
    'credit_confirmed': 'info',
    'documents_in_progress': 'info',
    'documents_ready_for_review': 'warning',
    'pdf_confirmed': 'success',
}
workflow_status = (selected_order or {}).get('workflow_status')
lc_record = get_lc_by_order(selected_order_id, owner_id)
if lc_record:
    st.session_state['workflow_current_lc_id'] = lc_record['id']
else:
    st.session_state.pop('workflow_current_lc_id', None)
current_risks = get_lc_risks(lc_record['id']) if lc_record else []
high_risk_open = any(
    str(risk.get('risk_level') or '').strip().casefold() in {'高', 'high', 'critical'}
    and risk.get('handling_status') not in {'已确认可接受', '已整改'}
    for risk in current_risks
)
previous_consistency = st.session_state.get(
    f'workflow_consistency_{selected_order_id}'
)

with st.container(border=True):
    st.caption(
        f"当前订单：{selected_order.get('order_no') if selected_order else '—'}"
        f" · {selected_order.get('customer_name_cn') if selected_order else '—'}"
        f" · {selected_order.get('product_name_en') if selected_order else '—'}"
    )
    st.caption('订单工作流状态')
    render_status_badge(
        workflow_labels.get(workflow_status, '处理中'),
        workflow_tones.get(workflow_status, 'neutral'),
    )
    render_workflow_progress(
        build_workflow_statuses(
            selected_order,
            lc_record,
            high_risk_open=high_risk_open,
            consistency=previous_consistency,
        ),
        '当前订单存在未处理高风险信用证条款；请查看下方风险与校验信息。'
        if high_risk_open else None,
    )
    subsection('四单生成状态')
    render_data_table(
        document_status_rows(selected_order_id),
        empty_message='四单均未生成。',
    )
    if previous_consistency and previous_consistency.get('blockers'):
        st.warning('上次一致性校验发现高风险错误；仍可继续查看和处理，PDF门禁保持原有规则。')

if lc_record:
    try:
        parsed_lc = json.loads(lc_record.get('parsed_json') or '{}')
    except json.JSONDecodeError:
        parsed_lc = {}
else:
    parsed_lc = {}
    st.warning('当前订单尚未关联已确认的信用证；关键期限显示待核对。')

section('信用证关键期限')
render_lc_deadline_cards(parsed_lc, selected_order)

template_tab, check_tab, generate_tab, export_tab = st.tabs(
    ['模板设置', '单单一致性校验', '生成单证', '导出 PDF']
)

with template_tab:
    doc_type = st.selectbox('单证类型', DOCUMENT_TYPES)
    supported_upload_types = ['docx', 'xlsx'] if doc_type in {'Commercial Invoice', 'Packing List'} else ['docx']
    uploaded_file = st.file_uploader(
        f"可选：上传{doc_type}模板（{', '.join('.' + suffix for suffix in supported_upload_types)}）",
        type=supported_upload_types,
        key=f'custom_template_upload_{doc_type}',
    )
    uploaded_template_path = save_uploaded_template(uploaded_file)
    template_options, default_template_path = templates_for_document(doc_type)
    if uploaded_template_path and uploaded_template_path not in template_options:
        template_options.append(uploaded_template_path)
    suggested = uploaded_template_path or suggested_template(
        template_options,
        doc_type,
        suggested_word_template(template_options, doc_type, default_template_path),
    )
    template_options_signature = hashlib.sha256(
        '|'.join(str(Path(option).resolve()) for option in template_options).encode('utf-8')
    ).hexdigest()[:10]
    template_path = st.selectbox(
        f'{doc_type}使用的模板（决定输出格式）',
        template_options,
        index=template_options.index(suggested),
        format_func=template_format_label,
        key=f'template_{selected_order_id}_{doc_type}_{template_options_signature}',
    )
    st.caption(f'本次只生成：{Path(template_path).suffix.upper()} 文件')
    if Path(template_path).suffix.lower() == '.xlsx':
        st.caption(f"工作簿工作表：{'、'.join(get_excel_template_sheets(template_path))}")

    subsection('批量生成时四种单证分别使用的模板')
    batch_template_paths = {}
    for batch_doc_type in DOCUMENT_TYPES:
        options, default_batch_path = templates_for_document(batch_doc_type)
        suggested_batch_template = suggested_template(
            options,
            batch_doc_type,
            suggested_word_template(options, batch_doc_type, default_batch_path),
        )
        if uploaded_template_path and batch_doc_type == doc_type:
            suggested_batch_template = uploaded_template_path
        options_signature = hashlib.sha256(
            '|'.join(str(Path(option).resolve()) for option in options).encode('utf-8')
        ).hexdigest()[:10]
        batch_template_paths[batch_doc_type] = st.selectbox(
            f'{batch_doc_type}模板（决定输出格式）',
            options,
            index=options.index(suggested_batch_template),
            format_func=template_format_label,
            key=f'batch_template_{selected_order_id}_{batch_doc_type}_{options_signature}',
        )

    lc_instruction = get_document_lc_instructions(selected_order_id, doc_type)
    if lc_instruction:
        st.info(f'本单证将同步以下信用证要求：\n\n{lc_instruction}')
    else:
        st.caption('此订单暂无映射到该单证的信用证要求；请确认已在信用证页面完成分析和订单关联。')
    st.info('CI 和 PL 可直接使用所选 Excel 工作簿模板；PI 和销售合同使用所选 Word 模板。')
    st.warning(
        '为避免丢失模板原有信息，订单中尚未维护的船名、品牌、柜号/封号、批次等字段会保留模板内容；'
        '正式出单前请核对并更新这些字段。'
    )

with check_tab:
    section(
        '单单一致性校验',
        caption='比较已确认信用证、订单及最新生成的 PI、Commercial Invoice、Packing List、Sales Contract。',
    )
    requirements = get_document_count_requirements(selected_order_id)
    prepared_counts = {}
    if requirements:
        subsection('L/C 单据份数要求')
        st.caption('请确认本次按信用证要求备妥的正本/副本份数；系统生成电子文件不等同于实体签章份数。')
        for requirement in requirements:
            original_col, copy_col = st.columns(2)
            with original_col:
                original_count = st.number_input(
                    f"{requirement['document_type']} · 正本（要求 {requirement['original_count']} 份）",
                    min_value=0,
                    step=1,
                    value=0,
                    key=(
                        f"prepared_originals_{selected_order_id}_"
                        f"{requirement['lc_id']}_{requirement['key']}"
                    ),
                )
            with copy_col:
                copy_count = st.number_input(
                    f"{requirement['document_type']} · 副本（要求 {requirement['copy_count']} 份）",
                    min_value=0,
                    step=1,
                    value=0,
                    key=(
                        f"prepared_copies_{selected_order_id}_"
                        f"{requirement['lc_id']}_{requirement['key']}"
                    ),
                )
            prepared_counts[requirement['key']] = {
                'original_count': int(original_count),
                'copy_count': int(copy_count),
            }
    else:
        st.error('待核对：未识别到信用证单据份数要求，请人工核对信用证原文。')

    consistency = validate_order_consistency(selected_order_id, prepared_counts)
    st.session_state[f'workflow_consistency_{selected_order_id}'] = {
        'blockers': consistency['blockers'],
        'needs_review': consistency['needs_review'],
        'warnings': consistency['warnings'],
    }
    if consistency['blockers']:
        st.error('发现明确的高风险不一致；处理完成前将阻止 PDF 生成。')
        for blocker in consistency['blockers']:
            st.error(f"**{blocker['field']}**：{'；'.join(blocker['reasons'])}")
    if consistency['needs_review']:
        st.warning('请人工核对以下项目。系统无法从当前数据或自定义模板中可靠提取/比较这些字段；此状态本身不会阻止 PDF。')
        for item in consistency['needs_review']:
            st.markdown(f"- **{item['field']}**：{'；'.join(item['reasons'])}")
    if consistency['warnings']:
        with st.expander(f"查看缺失或提示项（{len(consistency['warnings'])}）", expanded=False):
            for item in consistency['warnings']:
                st.caption(f"{item['field']}：{'；'.join(item['reasons'])}")

    status_labels = {
        'passed': '一致',
        'warning': '提示',
        'needs_review': '请人工核对',
        'error': '明确不一致',
        'missing': '缺失',
    }
    consistency_rows = []
    for item in consistency['rows']:
        values = item['values']
        consistency_rows.append({
            '校验字段': item['label'],
            '信用证': values.get('信用证') if values.get('信用证') not in (None, '') else '待核对',
            '订单': values.get('订单') if values.get('订单') not in (None, '') else '待核对',
            'PI': values.get('PI') if values.get('PI') not in (None, '') else '待核对',
            'Commercial Invoice': values.get('Commercial Invoice') if values.get('Commercial Invoice') not in (None, '') else '待核对',
            'Packing List': values.get('Packing List') if values.get('Packing List') not in (None, '') else '待核对',
            'Sales Contract': values.get('Sales Contract') if values.get('Sales Contract') not in (None, '') else '待核对',
            '严重等级': item['severity'],
            '结果': status_labels.get(item['status'], item['status']),
            '说明': '；'.join(item['details']),
        })
    render_data_table(consistency_rows)

with generate_tab:
    section('生成单证')
    if st.button('生成当前单证', type='primary', use_container_width=True):
        try:
            results = generate_document(
                selected_order_id,
                doc_type,
                custom_template_path=template_path,
            )
            invalidate_workflow_consistency(selected_order_id)
            st.success(f'已生成：{doc_type}')
            for key, label in [('word', 'Word'), ('excel', 'Excel')]:
                file_path = results.get(key)
                if file_path and Path(file_path).exists():
                    st.caption(f'{label}：{Path(file_path).name}')
            st.caption('可在「导出 PDF」标签页下载已生成文件。')
        except Exception as exc:
            st.error(f'生成失败：{exc}')

    if st.button('批量生成四单', use_container_width=True):
        try:
            results = generate_all_documents_for_order(
                selected_order_id,
                template_paths=batch_template_paths,
            )
            invalidate_workflow_consistency(selected_order_id)
            st.success('四单已全部生成')
            for doc_type_name, paths in results.items():
                names = [
                    Path(paths[key]).name
                    for key in ('word', 'excel')
                    if paths.get(key)
                ]
                if names:
                    st.caption(f'{doc_type_name}：{"、".join(names)}')
        except Exception as exc:
            st.error(f'四单生成失败：{exc}')

with export_tab:
    section(
        '复核确认后生成 PDF',
        caption='PDF 由已生成的 Word/Excel 文件转换，保留各自模板版式；请确保本机已安装 Microsoft Office。',
    )
    pdf_confirmed = st.checkbox(
        '我已逐份核对当前订单的 Word/Excel 单证内容，确认无误。',
        key=f'confirm_documents_{selected_order_id}',
    )
    if st.button(
        '确认无误，生成全部 PDF',
        disabled=not pdf_confirmed or bool(consistency['blockers']),
        type='primary',
        use_container_width=True,
    ):
        try:
            with st.spinner('正在将四种单证排版为单页 A4 PDF，请稍候…'):
                pdf_results = generate_pdfs_for_order(
                    selected_order_id,
                    prepared_counts=prepared_counts,
                )
            st.success(f'已生成 {len(pdf_results)} 份 PDF；原有 Word/Excel 文件已保留。')
            for document_name, file_path in pdf_results.items():
                st.caption(f'{document_name}：{Path(file_path).name}')
        except Exception as exc:
            st.error(f'PDF 生成失败：{exc}')

    section('当前订单已生成文件')
    file_rows = generated_file_rows(selected_order_id)
    render_data_table(
        [
            {key: value for key, value in row.items() if key != '_path'}
            for row in file_rows
        ],
        empty_message='尚未生成任何单证文件。',
    )
    if file_rows:
        file_labels = {row['文件名']: row['_path'] for row in file_rows}
        file_selection_column, download_column = st.columns([3, 1])
        with file_selection_column:
            selected_file_label = st.selectbox('选择要下载的文件', list(file_labels))
        with download_column:
            with open(file_labels[selected_file_label], 'rb') as file_handle:
                st.download_button(
                    '下载所选文件',
                    data=file_handle.read(),
                    file_name=selected_file_label,
                    use_container_width=True,
                )
