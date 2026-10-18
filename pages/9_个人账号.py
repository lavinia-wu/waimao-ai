from __future__ import annotations

import streamlit as st

from modules.auth import change_password, require_authenticated_user
from modules.ui_style import page_header


user = require_authenticated_user()

page_header(
    '我的账号',
    caption=f"账号：{user['username']} · {user['display_name']}；可在此修改登录密码。",
)

with st.form('change_password_form'):
    password = st.text_input('新密码（至少 10 位）', type='password')
    confirmation = st.text_input('再次输入新密码', type='password')
    submitted = st.form_submit_button('更新密码', type='primary')
if submitted:
    if password != confirmation:
        st.error('两次输入的密码不一致。')
    else:
        try:
            change_password(user['id'], password)
            st.success('密码已更新。')
        except ValueError as exc:
            st.error(str(exc))
