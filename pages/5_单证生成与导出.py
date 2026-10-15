from __future__ import annotations

import hashlib
from pathlib import Path
import re

import streamlit as st

from config.settings import settings
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
from modules.orders import list_orders
from services.word_service import ensure_default_template


st.set_page_config(layout='wide')
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


st.title('单证生成与导出')
st.caption('每种单证仅生成所选模板对应的文件格式；CI、PL 可分别选用 Excel 模板。')
st.caption('系统内置 Word 模板与客户模板分开存放；生成文件集中保存在“outputs/订单序号+客户+产品”子文件夹。')

orders = list_orders(owner_id=owner_id)
order_map = {f"{order['order_no']} | {order.get('customer_name_cn', '')} | {order.get('product_name_en', '')}": order['id'] for order in orders}
selected_order_label = st.selectbox('选择订单', options=list(order_map.keys()) or ['暂无订单'])
selected_order_id = order_map.get(selected_order_label)

if selected_order_id is None:
    st.warning('请先在“订单录入与计算”页面创建订单。')
    st.stop()
selected_order = next((order for order in orders if order['id'] == selected_order_id), None)
workflow_labels = {
    'order_confirmed': '订单已确认，待关联信用证/生成单证',
    'credit_confirmed': '信用证已确认，待生成四单',
    'documents_in_progress': '四单生成中',
    'documents_ready_for_review': '四单已生成，待业务员复核',
    'pdf_confirmed': '业务员已确认 PDF 版本',
}
st.info(f"当前订单状态：{workflow_labels.get((selected_order or {}).get('workflow_status'), '处理中')}")

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

with st.expander('批量生成时为四种单证分别选择模板'):
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

if st.button('生成当前单证', use_container_width=True):
    try:
        results = generate_document(
            selected_order_id,
            doc_type,
            custom_template_path=template_path,
        )
        st.success(f'已生成：{doc_type}')
        st.json(results)
        for key, label in [('word', 'Word'), ('excel', 'Excel')]:
            file_path = results.get(key)
            if file_path and Path(file_path).exists():
                with open(file_path, 'rb') as fh:
                    st.download_button(label=f'下载 {label}', data=fh.read(), file_name=Path(file_path).name, use_container_width=True)
    except Exception as exc:
        st.error(f'生成失败：{exc}')

if st.button('批量生成四单', use_container_width=True):
    try:
        results = generate_all_documents_for_order(
            selected_order_id,
            template_paths=batch_template_paths,
        )
        st.success('四单已全部生成')
        for doc_type_name, paths in results.items():
            st.markdown(f'### {doc_type_name}')
            for key, label in [('word', 'Word'), ('excel', 'Excel')]:
                file_path = paths.get(key)
                if file_path and Path(file_path).exists():
                    with open(file_path, 'rb') as fh:
                        st.download_button(label=f'下载 {label}', data=fh.read(), file_name=Path(file_path).name, use_container_width=True)
    except Exception as exc:
        st.error(f'四单生成失败：{exc}')

st.subheader('复核确认后生成 PDF')
st.caption('PDF 由已生成的 Word/Excel 文件转换，保留各自模板版式；请确保本机已安装 Microsoft Office。')
pdf_confirmed = st.checkbox(
    '我已逐份核对当前订单的 Word/Excel 单证内容，确认无误。',
    key=f'confirm_documents_{selected_order_id}',
)
if st.button('确认无误，生成全部 PDF', disabled=not pdf_confirmed, use_container_width=True):
    try:
        pdf_results = generate_pdfs_for_order(selected_order_id)
        st.success('四份 PDF 已生成；原有 Word/Excel 文件已保留。')
        for document_name, file_path in pdf_results.items():
            with open(file_path, 'rb') as fh:
                st.download_button(
                    label=f'下载 {document_name} PDF',
                    data=fh.read(),
                    file_name=Path(file_path).name,
                    mime='application/pdf',
                    key=f'download_pdf_{selected_order_id}_{document_name}',
                    use_container_width=True,
                )
    except Exception as exc:
        st.error(f'PDF 生成失败：{exc}')

st.subheader('当前订单已生成文件')
if selected_order:
    output_dir = get_order_output_dir(selected_order_id)
    if output_dir.exists():
        files = sorted(output_dir.iterdir())
        if files:
            for item in files:
                if item.is_file():
                    with open(item, 'rb') as fh:
                        st.download_button(label=f'下载 {item.name}', data=fh.read(), file_name=item.name, use_container_width=True)
        else:
            st.info('尚未生成任何单证文件。')
    else:
        st.info('尚未生成任何单证文件。')
else:
    st.info('请选择有效订单。')
