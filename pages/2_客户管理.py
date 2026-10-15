from __future__ import annotations

from io import BytesIO
from typing import Any, Dict

import streamlit as st
import pandas as pd

from modules.auth import list_users, require_authenticated_user
from modules.customers import (
    create_customer,
    delete_customer,
    export_customers_excel,
    get_customer_by_id,
    import_customers_excel,
    list_customers,
    update_customer,
)


st.set_page_config(layout='wide')
current_user = require_authenticated_user()
owner_id = int(current_user['id'])


def build_customer_form(defaults: Dict[str, Any] | None = None):
    defaults = defaults or {}
    return {
        'customer_name_cn': st.text_input('客户中文名', value=str(defaults.get('customer_name_cn', ''))),
        'customer_name_en': st.text_input('客户英文名', value=str(defaults.get('customer_name_en', ''))),
        'company_address': st.text_area('公司地址', value=str(defaults.get('company_address', ''))),
        'contact_person': st.text_input('联系人', value=str(defaults.get('contact_person', ''))),
        'email': st.text_input('邮箱', value=str(defaults.get('email', ''))),
        'phone': st.text_input('电话', value=str(defaults.get('phone', ''))),
        'destination_port': st.text_input('目的港', value=str(defaults.get('destination_port', ''))),
        'payment_terms': st.text_input('付款方式', value=str(defaults.get('payment_terms', ''))),
        'incoterm': st.text_input('贸易条款', value=str(defaults.get('incoterm', ''))),
        'remark': st.text_area('备注', value=str(defaults.get('remark', ''))),
    }


st.title('客户管理')
st.caption('每位客户归属一名业务员跟进；订单录入时会自动匹配客户，未匹配时可直接建立客户档案。')

if 'customer_edit_id' not in st.session_state:
    st.session_state.customer_edit_id = None

with st.expander('通过 Excel 批量导入客户'):
    st.caption('客户名称至少填写中文名或英文名。导入时会按客户名称检查重复项。')
    template_frame = pd.DataFrame(columns=[
        '客户中文名', '客户英文名', '公司地址', '联系人', '邮箱', '电话',
        '目的港', '付款方式', '贸易条款', '备注',
    ])
    template_buffer = BytesIO()
    template_frame.to_excel(template_buffer, index=False)
    st.download_button(
        '下载 Excel 导入模板',
        data=template_buffer.getvalue(),
        file_name='客户批量导入模板.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    import_file = st.file_uploader(
        '选择客户 Excel 文件',
        type=['xlsx'],
        key='customer_excel_import',
    )
    import_owner_id = owner_id
    if current_user['role'] == 'admin':
        active_users = [user for user in list_users() if user['is_active']]
        owner_options = {
            f"{user['display_name']}（{user['username']}）": user['id']
            for user in active_users
        }
        selected_owner = st.selectbox('导入客户的跟进业务员', list(owner_options))
        import_owner_id = owner_options[selected_owner]
    if import_file and st.button('导入客户', type='primary'):
        try:
            result = import_customers_excel(import_file.getvalue(), import_owner_id)
            st.success(
                f"导入完成：新增 {result['imported']} 条，重复跳过 {result['duplicates']} 条，"
                f"异常 {len(result['errors'])} 条。"
            )
            for error in result['errors']:
                st.warning(error)
        except ValueError as exc:
            st.error(str(exc))

search_text = st.text_input('搜索客户（中文名、英文名、联系方式、地址）', placeholder='输入关键词进行筛选...')

left, right = st.columns([1, 1])
with left:
    if st.button('新建客户', use_container_width=True):
        st.session_state.customer_edit_id = None
with right:
    if st.button('导出为 Excel', use_container_width=True):
        file_path = 'customer_export.xlsx'
        export_customers_excel(file_path, search_text, owner_id)
        st.success(f'已导出：{file_path}')
        with open(file_path, 'rb') as file:
            st.download_button(
                label='下载 Excel',
                data=file,
                file_name='customer_export.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )

customers = list_customers(search_text, owner_id)

if not customers:
    st.info('暂未找到客户记录，可在下方表单中新增客户。')

selected_customer = (
    get_customer_by_id(st.session_state.customer_edit_id, owner_id)
    if st.session_state.customer_edit_id else None
)
st.subheader(
    f"编辑客户：{selected_customer.get('customer_name_cn') or selected_customer.get('customer_name_en', '')}"
    if selected_customer else '新增客户'
)
customer_defaults = selected_customer or {}
with st.form('customer_form'):
    customer_form = build_customer_form(customer_defaults)
    save_button = st.form_submit_button('保存客户信息')
    cancel_button = st.form_submit_button('取消编辑')

if cancel_button:
    st.session_state.customer_edit_id = None
    st.rerun()

if save_button:
    try:
        if st.session_state.customer_edit_id is None:
            create_customer(customer_form, owner_id)
            st.success('客户新增成功')
        else:
            update_customer(st.session_state.customer_edit_id, customer_form, owner_id)
            st.success('客户更新成功')
        st.session_state.customer_edit_id = None
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

st.subheader('客户列表')
for customer in customers:
    col_name, col_action1, col_action2 = st.columns([4, 1, 1])
    with col_name:
        st.markdown(
            f"**{customer['customer_name_cn']}** / {customer['customer_name_en']}\n"
            f"电话：{customer['phone']} | 联系人：{customer['contact_person']}\n"
            f"目的港：{customer['destination_port']} | 付款方式：{customer['payment_terms']}"
        )
    with col_action1:
        if st.button('编辑', key=f'edit_{customer["id"]}', use_container_width=True):
            st.session_state.customer_edit_id = customer['id']
            st.rerun()
    with col_action2:
        if st.button('删除', key=f'delete_{customer["id"]}', use_container_width=True):
            delete_customer(customer['id'], owner_id)
            st.success('已删除客户')
            st.rerun()

    st.divider()
