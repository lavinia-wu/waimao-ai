from __future__ import annotations

import json
from typing import Any, Dict

import streamlit as st

from modules.auth import require_authenticated_user
from modules.customers import get_or_create_customer, list_customers
from modules.orders import (
    calculate_totals,
    create_order,
    delete_order,
    duplicate_order,
    get_order_by_id,
    list_orders,
    update_order,
)
from modules.products import get_product_by_id, list_products
from modules.lc_parser import (
    attach_lc_to_order,
    get_lc_by_order,
    get_lc_risks,
    list_approved_unlinked_lcs,
)
from modules.reminders import generate_and_store_reminders
from modules.workflow_navigation import (
    build_workflow_statuses,
    render_page_next_step,
    render_workflow_progress,
)


st.set_page_config(layout='wide')
owner_id = int(require_authenticated_user()['id'])
all_orders = list_orders(owner_id=owner_id)
current_order_id = st.session_state.get('order_edit_id') or st.session_state.get(
    'workflow_current_order_id'
)
current_order = next(
    (order for order in all_orders if order.get('id') == current_order_id),
    None,
)
if current_order is None and all_orders:
    current_order = all_orders[0]
    current_order_id = current_order['id']
    st.session_state['workflow_current_order_id'] = current_order_id
current_lc = (
    get_lc_by_order(current_order_id, owner_id)
    if current_order_id is not None else None
)
current_risks = get_lc_risks(current_lc['id']) if current_lc else []
high_risk_open = any(
    str(risk.get('risk_level') or '').strip().casefold() in {'高', 'high', 'critical'}
    and risk.get('handling_status') not in {'已确认可接受', '已整改'}
    for risk in current_risks
)
consistency_summary = (
    st.session_state.get(f'workflow_consistency_{current_order_id}')
    if current_order_id is not None else None
)


def default_order_form(defaults: Dict[str, Any] | None = None) -> Dict[str, Any]:
    defaults = defaults or {}
    return {
        'order_no': str(defaults.get('order_no', '')),
        'customer_id': defaults.get('customer_id', ''),
        'product_id': defaults.get('product_id', ''),
        'quantity': str(defaults.get('quantity', '')),
        'unit': str(defaults.get('unit', 'carton')),
        'unit_price': str(defaults.get('unit_price', '')),
        'currency': str(defaults.get('currency', 'USD')),
        'loading_port': str(defaults.get('loading_port', '')),
        'destination_port': str(defaults.get('destination_port', '')),
        'incoterm': str(defaults.get('incoterm', '')),
        'payment_terms': str(defaults.get('payment_terms', '')),
        'shipment_date': str(defaults.get('shipment_date', '')),
        'latest_shipment_date': str(defaults.get('latest_shipment_date', '')),
        'presentation_deadline': str(defaults.get('presentation_deadline', '')),
        'lc_expiry_date': str(defaults.get('lc_expiry_date', '')),
        'marks_and_numbers': str(defaults.get('marks_and_numbers', '')),
        'special_requirements': str(defaults.get('special_requirements', '')),
        'status': str(defaults.get('status', 'draft')),
    }


if 'order_edit_id' not in st.session_state:
    st.session_state.order_edit_id = None

st.title('订单管理')
st.caption('新订单可选择识别资料或手动录入；确认保存后统一进入下方订单列表。')
render_workflow_progress(
    build_workflow_statuses(
        current_order,
        current_lc,
        high_risk_open=high_risk_open,
        consistency=consistency_summary,
        lc_preview=bool(st.session_state.get('lc_analysis_preview')),
    ),
    '当前订单关联的信用证存在未处理高风险条款；可继续前往单证页查看，PDF生成仍沿用现有门禁。'
    if high_risk_open else None,
)
render_page_next_step('下一步：前往单证生成', 'pages/5_单证生成与导出.py')
st.divider()

customers = list_customers(owner_id=owner_id)
products = list_products()
customer_options = {f"{c['id']} - {c['customer_name_cn']} / {c['customer_name_en']}": c['id'] for c in customers}
product_options = {f"{p['id']} - {p['product_name_en']} / {p['product_name_cn']}": p['id'] for p in products}

entry_tabs = st.tabs(['手动录入', '识别订单资料'])
with entry_tabs[0]:
    selected_order = get_order_by_id(st.session_state.order_edit_id, owner_id) if st.session_state.order_edit_id else None
    form_defaults = default_order_form(selected_order)

    with st.form('order_entry_form'):
        st.subheader('订单基本信息')
        c1, c2, c3 = st.columns(3)
        with c1:
            form_defaults['order_no'] = st.text_input('订单编号', value=form_defaults['order_no'])
            customer_labels = ['按名称匹配或新增客户', *customer_options.keys()]
            default_customer_value = next(
                (label for label, value in customer_options.items() if value == form_defaults['customer_id']),
                customer_labels[0],
            )
            selected_customer_label = st.selectbox(
                '客户',
                options=customer_labels,
                index=customer_labels.index(default_customer_value),
            )
            if selected_customer_label == customer_labels[0]:
                customer_name_cn = st.text_input('客户中文名', value='')
                customer_name_en = st.text_input('客户英文名', value='')
                customer_address = st.text_input('公司地址（可选）', value='')
                customer_contact = st.text_input('联系人（可选）', value='')
                customer_email = st.text_input('邮箱（可选）', value='')
                customer_phone = st.text_input('电话（可选）', value='')
                customer_id = None
            else:
                customer_id = customer_options[selected_customer_label]
                customer_name_cn = customer_name_en = customer_address = ''
                customer_contact = customer_email = customer_phone = ''
        with c2:
            if product_options:
                product_labels = list(product_options.keys())
                default_product_value = next((label for label, value in product_options.items() if value == form_defaults['product_id']), product_labels[0])
                selected_product_label = st.selectbox('产品', options=product_labels, index=product_labels.index(default_product_value))
                form_defaults['product_id'] = product_options[selected_product_label]
            else:
                st.warning('请先新增产品记录。')
                form_defaults['product_id'] = ''
            form_defaults['quantity'] = st.number_input('数量', min_value=0.0, value=float(form_defaults['quantity']) if form_defaults['quantity'] not in ('', None) else 0.0)
            form_defaults['unit'] = st.text_input('计量单位', value=form_defaults['unit'])
        with c3:
            form_defaults['unit_price'] = st.number_input('单价', min_value=0.0, value=float(form_defaults['unit_price']) if form_defaults['unit_price'] not in ('', None) else 0.0)
            form_defaults['currency'] = st.selectbox('币种', ['USD', 'CNY', 'EUR'], index=['USD', 'CNY', 'EUR'].index(form_defaults['currency']) if form_defaults['currency'] in ['USD', 'CNY', 'EUR'] else 0)
            form_defaults['loading_port'] = st.text_input('起运港', value=form_defaults['loading_port'])
            form_defaults['destination_port'] = st.text_input('目的港', value=form_defaults['destination_port'])
            form_defaults['incoterm'] = st.text_input('贸易条款', value=form_defaults['incoterm'])
            form_defaults['payment_terms'] = st.text_input('付款方式', value=form_defaults['payment_terms'])

        c4, c5 = st.columns(2)
        with c4:
            form_defaults['shipment_date'] = st.date_input('装运日期', value=None if not form_defaults['shipment_date'] else st.to_datetime(form_defaults['shipment_date']))
            form_defaults['latest_shipment_date'] = st.date_input('最迟装运日', value=None if not form_defaults['latest_shipment_date'] else st.to_datetime(form_defaults['latest_shipment_date']))
            form_defaults['presentation_deadline'] = st.date_input('交单截止日', value=None if not form_defaults['presentation_deadline'] else st.to_datetime(form_defaults['presentation_deadline']))
        with c5:
            form_defaults['lc_expiry_date'] = st.date_input('信用证有效期', value=None if not form_defaults['lc_expiry_date'] else st.to_datetime(form_defaults['lc_expiry_date']))
            form_defaults['marks_and_numbers'] = st.text_area('唛头', value=form_defaults['marks_and_numbers'], height=80)
            form_defaults['special_requirements'] = st.text_area('特殊要求', value=form_defaults['special_requirements'], height=80)
            st.caption('订单特殊要求会写入生成的单证；如不需要“Keep dry”，请从此处删除后保存订单。')

        save_button = st.form_submit_button('保存订单')

    if form_defaults.get('product_id'):
        product = get_product_by_id(int(form_defaults['product_id']))
        if product:
            qty = float(form_defaults.get('quantity', 0) or 0)
            totals = calculate_totals(qty, form_defaults.get('unit_price') or product['unit_price'], product.get('gross_weight_per_carton'), product.get('net_weight_per_carton'), product.get('carton_volume_cbm'))
            st.subheader('自动计算结果')
            a1, a2, a3, a4 = st.columns(4)
            a1.metric('总金额', f"{totals['total_amount']:.2f}")
            a2.metric('总毛重', f"{totals['total_gross_weight']:.2f} kg")
            a3.metric('总净重', f"{totals['total_net_weight']:.2f} kg")
            a4.metric('总体积', f"{totals['total_volume']:.2f} CBM")

    if save_button:
        try:
            form_defaults['quantity'] = float(form_defaults['quantity']) if str(form_defaults['quantity']).strip() else 0
            form_defaults['unit_price'] = float(form_defaults['unit_price']) if str(form_defaults['unit_price']).strip() else 0
            if st.session_state.order_edit_id is None:
                if customer_id is None:
                    customer_id, created = get_or_create_customer(
                        {
                            'customer_name_cn': customer_name_cn,
                            'customer_name_en': customer_name_en,
                            'company_address': customer_address,
                            'contact_person': customer_contact,
                            'email': customer_email,
                            'phone': customer_phone,
                        },
                        owner_id,
                    )
                    st.info('已新建客户档案，归属当前业务员。' if created else '已匹配到现有客户，沿用其业务员归属。')
                form_defaults['customer_id'] = customer_id
                form_defaults['user_id'] = owner_id
                order_id = create_order(form_defaults)
                st.session_state['workflow_current_order_id'] = order_id
                st.success('订单保存成功')
            else:
                form_defaults['user_id'] = owner_id
                update_order(st.session_state.order_edit_id, form_defaults)
                order_id = st.session_state.order_edit_id
                st.session_state['workflow_current_order_id'] = order_id
                st.success('订单更新成功')
            lc_record = get_lc_by_order(order_id, owner_id)
            lc_data = json.loads(lc_record.get('parsed_json') or '{}') if lc_record else {}
            generate_and_store_reminders(
                order_id,
                lc_data,
                lc_record['id'] if lc_record else None,
            )
            st.session_state.order_edit_id = None
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

with entry_tabs[1]:
    from modules.order_recognition_ui import render_order_recognition

    render_order_recognition()

st.subheader('订单列表')
search_text = st.text_input('搜索订单', placeholder='订单号 / 客户 / 产品', key='order_search')
orders = list_orders(search_text, owner_id)
if not orders:
    st.info('暂无订单记录')
else:
    st.dataframe(
        [
            {
                '订单编号': order['order_no'],
                '客户': order.get('customer_name_cn') or order.get('customer_name_en') or '',
                '产品': order.get('product_name_en') or order.get('product_name_cn') or '',
                '数量': f"{order['quantity']} {order['unit']}",
                '金额': f"{order['total_amount']:.2f} {order['currency']}",
                '状态': order['status'],
            }
            for order in orders
        ],
        hide_index=True,
        width='stretch',
    )
for order in orders:
    c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
    with c1:
        st.markdown(f"**{order['order_no']}** | {order.get('customer_name_cn', '')} | {order.get('product_name_en', '')}\n数量: {order['quantity']} {order['unit']} | 金额: {order['total_amount']} {order['currency']} | 状态: {order['status']}")
    with c2:
        if st.button('编辑', key=f'order_edit_{order["id"]}', use_container_width=True):
            st.session_state.order_edit_id = order['id']
            st.session_state['workflow_current_order_id'] = order['id']
            st.rerun()
    with c3:
        if st.button('复制', key=f'order_copy_{order["id"]}', use_container_width=True):
            duplicate_order(order['id'], owner_id)
            st.success('已复制订单')
            st.rerun()
    with c4:
        if st.button('删除', key=f'order_delete_{order["id"]}', use_container_width=True):
            delete_order(order['id'], owner_id)
            if st.session_state.get('workflow_current_order_id') == order['id']:
                st.session_state.pop('workflow_current_order_id', None)
            st.success('已删除订单')
            st.rerun()
    st.divider()

unlinked_lcs = list_approved_unlinked_lcs(owner_id)
if unlinked_lcs and orders:
    st.subheader('将已确认信用证关联到订单')
    lc_options = {
        f"{lc['lc_no']} · {lc['applicant']} · {lc['currency']} {lc['lc_amount']}": lc['id']
        for lc in unlinked_lcs
    }
    order_options = {
        f"{order['order_no']} | {order.get('customer_name_cn', '')} | {order.get('product_name_en', '')}": order['id']
        for order in orders
    }
    lc_choice = st.selectbox('待关联信用证', list(lc_options), key='order_attach_lc')
    order_choice = st.selectbox('关联订单', list(order_options), key='order_attach_order')
    if st.button('关联信用证并生成跟单提醒', type='primary'):
        try:
            lc_id = lc_options[lc_choice]
            target_order_id = order_options[order_choice]
            attach_lc_to_order(lc_id, target_order_id, owner_id)
            st.session_state['workflow_current_order_id'] = target_order_id
            st.session_state['workflow_current_lc_id'] = lc_id
            lc_record = get_lc_by_order(target_order_id, owner_id)
            if lc_record:
                import json

                parsed_lc = json.loads(lc_record.get('parsed_json') or '{}')
                reminders = generate_and_store_reminders(
                    target_order_id,
                    parsed_lc,
                    lc_id,
                )
                st.success(f'信用证已关联，已建立 {len(reminders)} 个订单提醒。')
                st.rerun()
        except (ValueError, RuntimeError) as exc:
            st.error(f'关联信用证失败：{exc}')
