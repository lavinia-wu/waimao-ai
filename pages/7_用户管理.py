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


current_user = require_authenticated_user()
if current_user['role'] != 'admin':
    st.error('仅管理员可以管理业务员账号。')
    st.stop()

st.title('业务员账号管理')
st.caption('账号停用后无法登录；客户及订单仍归原业务员所有，不会自动转给其他人。')

with st.form('create_salesperson_form'):
    st.subheader('新增业务员')
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

st.subheader('现有账号')
for user in list_users():
    left, right = st.columns([4, 1])
    with left:
        state = '启用' if user['is_active'] else '已停用'
        role = '管理员' if user['role'] == 'admin' else '业务员'
        st.markdown(f"**{user['display_name']}**（{user['username']}） · {role} · {state}")
    if user['id'] != current_user['id']:
        with right:
            label = '停用账号' if user['is_active'] else '重新启用'
            if st.button(label, key=f"user_active_{user['id']}"):
                try:
                    set_user_active(user['id'], not bool(user['is_active']), current_user['id'])
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

st.subheader('客户归属分配')
all_users = list_users()
active_users = [item for item in all_users if item['is_active']]
owner_options = {
    f"{item['display_name']}（{item['username']}）": item['id']
    for item in active_users
}
owner_labels_by_id = {item['id']: item['display_name'] for item in all_users}
for customer in list_customers():
    owner_label = owner_labels_by_id.get(customer.get('user_id'), '未分配')
    st.markdown(
        f"**{customer.get('customer_name_cn') or customer.get('customer_name_en')}** · "
        f"当前归属：{owner_label}"
    )
    current_label = next(
        (label for label, user_id in owner_options.items() if user_id == customer.get('user_id')),
        next(iter(owner_options)),
    )
    with st.form(f"assign_customer_{customer['id']}"):
        selected_owner = st.selectbox(
            '转交给业务员',
            list(owner_options),
            index=list(owner_options).index(current_label),
            key=f"owner_{customer['id']}",
        )
        assign = st.form_submit_button('保存客户归属')
    if assign:
        try:
            assign_customer_owner(customer['id'], owner_options[selected_owner])
            st.success('客户及其订单、已关联信用证已转交。')
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

with st.expander('修改当前管理员密码'):
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
