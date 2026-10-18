from __future__ import annotations

from io import BytesIO
from typing import Any, Dict

import streamlit as st
import pandas as pd

from database.db import get_connection
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
from modules.ui_style import page_header, render_data_table, section


XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

current_user = require_authenticated_user()
owner_id = int(current_user['id'])
is_admin = current_user['role'] == 'admin'


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


def customer_order_count(customer_id: int) -> int:
    """只读统计：用于删除前的影响提示，不做任何写入。"""
    with get_connection() as conn:
        return conn.execute(
            'SELECT COUNT(*) FROM orders WHERE customer_id = ?',
            (customer_id,),
        ).fetchone()[0]


page_header(
    '客户管理',
    caption='每位客户归属一名业务员跟进；订单录入时会自动匹配客户，未匹配时可直接建立客户档案。',
)

if 'customer_edit_id' not in st.session_state:
    st.session_state.customer_edit_id = None
if 'customer_form_open' not in st.session_state:
    st.session_state.customer_form_open = False
if 'customer_pending_delete_id' not in st.session_state:
    st.session_state.customer_pending_delete_id = None

search_column, action_column = st.columns([3, 1])
with search_column:
    search_text = st.text_input(
        '搜索客户（中文名、英文名、联系方式、地址）',
        placeholder='输入关键词进行筛选...',
    )
with action_column:
    if st.button('新建客户', type='primary', use_container_width=True):
        st.session_state.customer_edit_id = None
        st.session_state.customer_form_open = True
        st.session_state.customer_pending_delete_id = None
        st.rerun()

# 管理员可查看全库客户并按归属业务员筛选；业务员仅查看本人名下客户
scope_owner = None if is_admin else owner_id
owner_filter_id = 0
owner_names: Dict[int, str] = {}
if is_admin:
    with get_connection() as conn:
        owner_names = {
            int(row['id']): row['display_name']
            for row in conn.execute('SELECT id, display_name FROM users ORDER BY id')
        }
    owner_filter_id = st.selectbox(
        '归属业务员（管理员筛选）',
        options=[0] + list(owner_names),
        format_func=lambda key: '全部业务员' if key == 0 else f'{owner_names[key]}（#{key}）',
    )
else:
    owner_filter_id = owner_id

customers = list_customers(search_text, owner_filter_id or scope_owner)
# 全部记录：管理员为全库客户，业务员仅本人名下的客户
scoped_customers = list_customers('', scope_owner)

with st.expander('批量导入 / 导出（辅助）', expanded=False):
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
        import_owner_options = {
            f"{user['display_name']}（{user['username']}）": user['id']
            for user in active_users
        }
        selected_owner = st.selectbox('导入客户的跟进业务员', list(import_owner_options))
        import_owner_id = import_owner_options[selected_owner]
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

    st.divider()
    st.markdown('**导出客户资料（.xlsx）**')
    if not scoped_customers:
        st.caption('当前账号暂无可访问的客户记录，导出已停用。')
        st.button('导出全部客户（0 条）', disabled=True, use_container_width=True)
    else:
        st.caption(
            '导出不会修改任何客户资料。导出全部包含所有业务员的客户，并附归属业务员列。'
            if is_admin
            else '导出不会修改任何客户资料，导出范围仅包含本人名下的客户。'
        )
        filtered_column, all_column = st.columns(2)
        with filtered_column:
            if customers:
                filtered_name, filtered_data = export_customers_excel(
                    search_text, owner_filter_id or scope_owner
                )
                st.download_button(
                    f'导出当前筛选结果（{len(customers)} 条）',
                    data=filtered_data,
                    file_name=filtered_name,
                    mime=XLSX_MIME,
                    use_container_width=True,
                )
            else:
                st.button('导出当前筛选结果（0 条）', disabled=True, use_container_width=True)
                st.caption('当前筛选条件下没有客户记录。')
        with all_column:
            all_name, all_data = export_customers_excel('', scope_owner)
            st.download_button(
                f'导出全部客户（{len(scoped_customers)} 条）',
                data=all_data,
                file_name=all_name,
                mime=XLSX_MIME,
                use_container_width=True,
            )

section('客户列表')
table_rows = []
for customer in customers:
    row = {
        '客户中文名': customer['customer_name_cn'],
        '客户英文名': customer['customer_name_en'],
    }
    if is_admin:
        row['归属业务员'] = owner_names.get(int(customer['user_id'] or 0), '未分配')
    row.update({
        '联系人': customer['contact_person'],
        '电话': customer['phone'],
        '邮箱': customer['email'],
        '目的港': customer['destination_port'],
        '付款方式': customer['payment_terms'],
    })
    table_rows.append(row)
render_data_table(
    table_rows,
    empty_message='暂未找到客户记录，可使用上方「新建客户」建立档案。',
)

if customers:
    customer_labels = {
        (
            f"{owner_names.get(int(customer['user_id'] or 0), '未分配')} · "
            if is_admin
            else ''
        )
        + f"{customer['customer_name_cn']} / {customer['customer_name_en']}（#{customer['id']}）": customer['id']
        for customer in customers
    }
    selection_column, edit_column, delete_column = st.columns([3, 1, 1])
    with selection_column:
        selected_label = st.selectbox('选择客户进行操作', list(customer_labels))
    target_customer_id = customer_labels[selected_label]
    with edit_column:
        if st.button('编辑所选客户', use_container_width=True):
            st.session_state.customer_edit_id = target_customer_id
            st.session_state.customer_form_open = True
            st.session_state.customer_pending_delete_id = None
            st.rerun()
    with delete_column:
        if st.button('删除所选客户', use_container_width=True):
            st.session_state.customer_pending_delete_id = target_customer_id
            st.rerun()

pending_delete_id = st.session_state.customer_pending_delete_id
if pending_delete_id:
    target = next(
        (customer for customer in customers if customer['id'] == pending_delete_id),
        None,
    )
    if target is None:
        st.session_state.customer_pending_delete_id = None
    else:
        target_name = target['customer_name_cn'] or target['customer_name_en'] or f"#{pending_delete_id}"
        owner_text = (
            f"（归属：{owner_names.get(int(target['user_id'] or 0), '未分配')}）"
            if is_admin else ''
        )
        affected = customer_order_count(pending_delete_id)
        st.warning(
            f"确认删除客户「{target_name}」{owner_text}？"
            + (
                f"该客户名下有 {affected} 个订单。删除客户不会删除这些订单，"
                '但订单会失去客户关联。'
                if affected
                else '该客户名下暂无订单。'
            )
        )
        confirm_column, cancel_column = st.columns([1, 1])
        with confirm_column:
            if st.button('确认删除', type='primary', use_container_width=True):
                try:
                    delete_customer(pending_delete_id, scope_owner)
                    st.session_state.customer_pending_delete_id = None
                    if st.session_state.customer_edit_id == pending_delete_id:
                        st.session_state.customer_edit_id = None
                        st.session_state.customer_form_open = False
                    st.success('已删除客户')
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with cancel_column:
            if st.button('取消删除', use_container_width=True):
                st.session_state.customer_pending_delete_id = None
                st.rerun()

selected_customer = (
    get_customer_by_id(st.session_state.customer_edit_id, scope_owner)
    if st.session_state.customer_edit_id else None
)
form_title = (
    f"编辑客户：{selected_customer.get('customer_name_cn') or selected_customer.get('customer_name_en', '')}"
    if selected_customer else '新增客户'
)
with st.expander(form_title, expanded=st.session_state.customer_form_open):
    customer_defaults = selected_customer or {}
    with st.form('customer_form'):
        customer_form = build_customer_form(customer_defaults)
        save_button = st.form_submit_button('保存客户信息', type='primary')
        cancel_button = st.form_submit_button('取消编辑')

if cancel_button:
    st.session_state.customer_edit_id = None
    st.session_state.customer_form_open = False
    st.rerun()

if save_button:
    try:
        if st.session_state.customer_edit_id is None:
            create_customer(customer_form, owner_id)
            st.success('客户新增成功')
        else:
            update_customer(st.session_state.customer_edit_id, customer_form, scope_owner)
            st.success('客户更新成功')
        st.session_state.customer_edit_id = None
        st.session_state.customer_form_open = False
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))
