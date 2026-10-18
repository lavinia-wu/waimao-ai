from __future__ import annotations

import streamlit as st

from modules.auth import (
    assign_customer_owner,
    change_password,
    create_user,
    list_users,
    require_authenticated_user,
    set_user_active,
)
from modules.customers import list_customers
from modules.ui_style import page_header, render_data_table, section


current_user = require_authenticated_user()
if current_user['role'] != 'admin':
    st.error('仅管理员可以管理业务员账号。')
    st.stop()

page_header(
    '业务员账号管理',
    caption='账号停用后无法登录；客户及订单仍归原业务员所有，不会自动转给其他人。',
)

with st.expander('新增业务员', expanded=False):
    with st.form('create_salesperson_form'):
        username = st.text_input('登录账号')
        display_name = st.text_input('业务员姓名')
        password = st.text_input('初始密码（至少 10 位）', type='password')
        confirm_password = st.text_input('确认初始密码', type='password')
        create_button = st.form_submit_button('创建账号', type='primary')

if create_button:
    if password != confirm_password:
        st.error('两次输入的密码不一致。')
    else:
        try:
            create_user(username, display_name, password)
            st.success('业务员账号已创建。')
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

section('现有账号')
users = list_users()
role_labels = {'admin': '管理员', 'sales': '业务员'}
render_data_table(
    [
        {
            '姓名': user['display_name'],
            '登录账号': user['username'],
            '角色': role_labels.get(str(user['role']), str(user['role'])),
            '状态': '启用' if user['is_active'] else '已停用',
        }
        for user in users
    ],
    empty_message='暂无账号记录。',
)

other_users = [user for user in users if user['id'] != current_user['id']]
if other_users:
    user_labels = {
        f"{user['display_name']}（{user['username']}）": user['id']
        for user in other_users
    }
    user_selection_column, user_action_column = st.columns([3, 1])
    with user_selection_column:
        selected_user_label = st.selectbox('选择账号进行操作', list(user_labels))
    target_user_id = user_labels[selected_user_label]
    target_user = next(user for user in other_users if user['id'] == target_user_id)
    with user_action_column:
        if st.button(
            '停用账号' if target_user['is_active'] else '重新启用',
            use_container_width=True,
        ):
            try:
                set_user_active(
                    target_user_id,
                    not bool(target_user['is_active']),
                    current_user['id'],
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

section('客户归属分配')
all_users = list_users()
active_users = [item for item in all_users if item['is_active']]
owner_options = {
    f"{item['display_name']}（{item['username']}）": item['id']
    for item in active_users
}
owner_labels_by_id = {item['id']: item['display_name'] for item in all_users}
customers = list_customers()
render_data_table(
    [
        {
            '客户': customer.get('customer_name_cn') or customer.get('customer_name_en') or f"#{customer['id']}",
            '当前归属': owner_labels_by_id.get(customer.get('user_id'), '未分配'),
        }
        for customer in customers
    ],
    empty_message='暂无客户记录。',
)

if customers and active_users:
    customer_labels = {
        f"{customer.get('customer_name_cn') or customer.get('customer_name_en') or '客户'}（#{customer['id']}）": customer['id']
        for customer in customers
    }
    customer_column, owner_column, assign_column = st.columns([2, 2, 1])
    with customer_column:
        selected_customer_label = st.selectbox('选择客户', list(customer_labels))
    target_customer_id = customer_labels[selected_customer_label]
    target_customer = next(
        customer for customer in customers if customer['id'] == target_customer_id
    )
    current_owner_label = next(
        (
            label for label, user_id in owner_options.items()
            if user_id == target_customer.get('user_id')
        ),
        next(iter(owner_options)),
    )
    with owner_column:
        selected_owner = st.selectbox(
            '转交给业务员',
            list(owner_options),
            index=list(owner_options).index(current_owner_label),
            key='reassign_owner',
        )
    with assign_column:
        if st.button('保存客户归属', use_container_width=True):
            try:
                assign_customer_owner(target_customer_id, owner_options[selected_owner])
                st.success('客户及其订单、已关联信用证已转交。')
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

with st.expander('修改当前管理员密码', expanded=False):
    with st.form('change_own_password_form'):
        new_password = st.text_input('新密码（至少 10 位）', type='password')
        repeat_password = st.text_input('重复新密码', type='password')
        save_password = st.form_submit_button('修改密码')
    if save_password:
        if new_password != repeat_password:
            st.error('两次输入的密码不一致。')
        else:
            try:
                change_password(current_user['id'], new_password)
                st.success('密码已更新，请使用新密码登录。')
            except ValueError as exc:
                st.error(str(exc))
