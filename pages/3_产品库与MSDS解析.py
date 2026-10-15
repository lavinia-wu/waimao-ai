from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from modules.auth import require_authenticated_user
from modules.products import (
    create_product,
    delete_product,
    extract_product_metadata_from_pdf,
    get_product_by_id,
    list_products,
    parse_chat_order_details,
    save_uploaded_pdf,
    update_product,
)


st.set_page_config(layout='wide')
require_authenticated_user()


def default_product_form(defaults: Dict[str, Any] | None = None) -> Dict[str, Any]:
    defaults = defaults or {}
    return {
        'product_name_en': str(defaults.get('product_name_en', '')),
        'product_name_cn': str(defaults.get('product_name_cn', '')),
        'hs_code': str(defaults.get('hs_code', '')),
        'cas_no': str(defaults.get('cas_no', '')),
        'unit_price': str(defaults.get('unit_price', '')),
        'currency': str(defaults.get('currency', 'USD')),
        'packaging_method': str(defaults.get('packaging_method', '')),
        'gross_weight_per_carton': str(defaults.get('gross_weight_per_carton', '')),
        'net_weight_per_carton': str(defaults.get('net_weight_per_carton', '')),
        'carton_volume_cbm': str(defaults.get('carton_volume_cbm', '')),
        'specification': str(defaults.get('specification', '')),
        'msds_file_path': str(defaults.get('msds_file_path', '')),
        'product_description_en': str(defaults.get('product_description_en', '')),
        'transport_info': str(defaults.get('transport_info', '')),
        'compliance_description': str(defaults.get('compliance_description', '')),
    }


if 'product_edit_id' not in st.session_state:
    st.session_state.product_edit_id = None

st.title('产品库 + MSDS 解析')
st.caption('支持手动录入、PDF解析、AI确认和订单回填')

with st.container():
    uploaded_file = st.file_uploader('上传 MSDS / SDS / 产品规格书 PDF', type=['pdf'])
    if uploaded_file is not None:
        try:
            saved_path = save_uploaded_pdf(uploaded_file)
            parsed = extract_product_metadata_from_pdf(saved_path)
            if parsed:
                st.session_state.ai_preview = parsed
                st.session_state.msds_path = saved_path
                st.success(f'已读取 PDF 并生成 AI 预览：{saved_path}')
            else:
                st.warning('PDF 已上传，但未识别到清晰字段，可手动填写。')
        except Exception as exc:
            st.error(f'解析失败：{exc}')

chat_text = st.text_area('粘贴客户聊天记录 / 邮件内容（用于识别产品信息）', height=150, placeholder='例如：产品：LDPE Resin；数量：500 cartons；单价：1200 USD；目的港：Qingdao；交期：2026-11-30；特殊要求：Need palletized shipment')
if chat_text.strip():
    parsed_chat = parse_chat_order_details(chat_text)
    if parsed_chat:
        st.subheader('聊天记录识别结果')
        st.json(parsed_chat)
        st.session_state.chat_preview = parsed_chat

preview_data = st.session_state.get('ai_preview', {})
current_defaults = {}
if st.session_state.get('chat_preview'):
    current_defaults.update(st.session_state.chat_preview)
if preview_data:
    current_defaults.update(preview_data)
if st.session_state.product_edit_id is not None:
    existing = get_product_by_id(st.session_state.product_edit_id)
    if existing:
        current_defaults = default_product_form(existing)

with st.form('product_management_form'):
    st.subheader('产品信息表单')
    form_data = default_product_form(current_defaults)
    cols = st.columns(2)
    with cols[0]:
        form_data['product_name_en'] = st.text_input('英文品名', value=form_data['product_name_en'])
        form_data['product_name_cn'] = st.text_input('中文品名', value=form_data['product_name_cn'])
        form_data['hs_code'] = st.text_input('HS编码', value=form_data['hs_code'])
        form_data['cas_no'] = st.text_input('CAS号', value=form_data['cas_no'])
        form_data['unit_price'] = st.text_input('单价', value=form_data['unit_price'])
        form_data['currency'] = st.selectbox('币种', ['USD', 'CNY', 'EUR'], index=['USD', 'CNY', 'EUR'].index(form_data['currency']) if form_data['currency'] in ['USD', 'CNY', 'EUR'] else 0)
        form_data['packaging_method'] = st.text_input('包装方式', value=form_data['packaging_method'])
    with cols[1]:
        form_data['gross_weight_per_carton'] = st.text_input('每箱毛重（kg）', value=form_data['gross_weight_per_carton'])
        form_data['net_weight_per_carton'] = st.text_input('每箱净重（kg）', value=form_data['net_weight_per_carton'])
        form_data['carton_volume_cbm'] = st.text_input('每箱体积（CBM）', value=form_data['carton_volume_cbm'])
        form_data['specification'] = st.text_input('规格', value=form_data['specification'])
        form_data['msds_file_path'] = st.text_input('MSDS文件路径', value=form_data['msds_file_path'])
        form_data['transport_info'] = st.text_input('运输信息', value=form_data['transport_info'])
        form_data['compliance_description'] = st.text_area('合规出口描述', value=form_data['compliance_description'])
        form_data['product_description_en'] = st.text_area('产品英文描述', value=form_data['product_description_en'])

    confirm_checkbox = st.checkbox('我已确认 AI 提取内容无误，可保存到产品库', value=False)
    save_button = st.form_submit_button('保存产品')

if save_button:
    try:
        if not confirm_checkbox:
            st.warning('请先确认 AI 提取结果后再保存。')
        elif st.session_state.product_edit_id is None:
            create_product(form_data)
            st.success('产品已保存')
            st.session_state.product_edit_id = None
            st.rerun()
        else:
            update_product(st.session_state.product_edit_id, form_data)
            st.success('产品已更新')
            st.session_state.product_edit_id = None
            st.rerun()
    except ValueError as exc:
        st.error(str(exc))

st.subheader('产品列表')
search_text = st.text_input('搜索产品', placeholder='请输入英文名 / 中文名 / HS编码', key='product_search')
products = list_products(search_text)
if not products:
    st.info('暂无产品记录')
for product in products:
    c1, c2, c3 = st.columns([4, 1, 1])
    with c1:
        st.markdown(f"**{product['product_name_en']}** / {product['product_name_cn']}\nHS: {product['hs_code']} | CAS: {product['cas_no']}\n单价: {product['unit_price']} {product['currency']} | 包装: {product['packaging_method']}")
    with c2:
        if st.button('编辑', key=f'product_edit_{product["id"]}', use_container_width=True):
            st.session_state.product_edit_id = product['id']
            st.rerun()
    with c3:
        if st.button('删除', key=f'product_delete_{product["id"]}', use_container_width=True):
            delete_product(product['id'])
            st.success('已删除产品')
            st.rerun()
    st.divider()
