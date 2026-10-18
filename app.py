from __future__ import annotations

import streamlit as st

from config.settings import settings
from database.init_db import init_db
from modules.auth import authenticate, create_user, get_active_user, user_count
from modules.ui_style import inject_base_css, page_header, render_status_badge

ROLE_LABELS = {
    'admin': '管理员',
    'sales': '业务员',
}


def render_authentication() -> bool:
    page_header('外贸业务工作台', caption='请先登录或使用管理员账号初始化系统')
    if user_count() == 0:
        st.info('首次使用，请创建系统管理员账号。已有客户和订单将归属该管理员。')
        with st.form('initial_admin_form'):
            username = st.text_input('管理员账号')
            display_name = st.text_input('管理员姓名')
            password = st.text_input('设置密码（至少 10 位）', type='password')
            confirm_password = st.text_input('确认密码', type='password')
            submitted = st.form_submit_button('创建管理员并进入系统', type='primary')
        if submitted:
            if password != confirm_password:
                st.error('两次输入的密码不一致。')
            else:
                try:
                    user_id = create_user(username, display_name, password, role='admin')
                    st.session_state['auth_user'] = get_active_user(user_id)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        return False

    current = st.session_state.get('auth_user')
    if current:
        refreshed = get_active_user(int(current['id']))
        if refreshed:
            st.session_state['auth_user'] = refreshed
            return True
        st.session_state.pop('auth_user', None)

    with st.form('login_form'):
        username = st.text_input('账号')
        password = st.text_input('密码', type='password')
        submitted = st.form_submit_button('登录', type='primary')
    if submitted:
        user = authenticate(username, password)
        if user is None:
            st.error('账号或密码错误，或该账号已停用。')
        else:
            st.session_state['auth_user'] = user
            st.rerun()
    return False


def configure_app() -> None:
    st.set_page_config(
        page_title='外贸AI智能单证与信用证风控系统',
        page_icon='📦',
        layout='wide',
        initial_sidebar_state='expanded',
    )


def main() -> None:
    configure_app()
    init_db()
    inject_base_css()

    if not render_authentication():
        return
    current_user = st.session_state['auth_user']
    with st.sidebar:
        st.markdown('**外贸AI单证与信用证风控系统**')
        st.caption('外贸业务工作台')
        st.divider()
        st.markdown(f"**{current_user['display_name']}** · {current_user['username']}")
        render_status_badge(
            ROLE_LABELS.get(str(current_user['role']), str(current_user['role'])),
            'info',
        )
        if st.button('退出登录', use_container_width=True):
            st.session_state.pop('auth_user', None)
            st.rerun()

    pages = [
        st.Page('pages/1_首页.py', title='业务看板', icon='🏠'),
        st.Page('pages/6_信用证解析与风控.py', title='信用证上传与确认', icon='⚠️'),
        st.Page('pages/2_客户管理.py', title='客户管理', icon='👥'),
        st.Page('pages/3_产品库与MSDS解析.py', title='产品库', icon='🧪'),
        st.Page('pages/4_订单录入与计算.py', title='订单管理', icon='🧾'),
        st.Page('pages/5_单证生成与导出.py', title='单证生成', icon='📄'),
        st.Page('pages/9_个人账号.py', title='我的账号', icon='👤'),
    ]
    if current_user['role'] == 'admin':
        pages.append(st.Page('pages/7_用户管理.py', title='业务员账号管理', icon='🔐'))

    navigation = st.navigation(pages)
    navigation.run()


if __name__ == '__main__':
    main()
