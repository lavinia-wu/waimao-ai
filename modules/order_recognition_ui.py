from __future__ import annotations

from datetime import date
import hashlib
import json

import streamlit as st

from database.db import get_connection
from modules.customers import get_or_create_customer, list_customers
from modules.lc_deadlines import parse_date
from modules.lc_parser import (
    attach_lc_to_order,
    get_lc_by_order,
    list_approved_unlinked_lcs,
)
from modules.order_recognition import extract_order_source_text, recognize_order_text
from modules.orders import create_order
from modules.products import create_product, list_products
from modules.reminders import generate_and_store_reminders


def render_order_recognition() -> None:
    user = st.session_state['auth_user']
    owner_id = int(user['id'])

    st.caption('识别结果经业务员核对确认后，会自动保存到下方订单管理列表；缺失信息可在手动录入中补充。')
    st.warning('识别内容可能有误。订单资料会发送到 .env 配置的 AI 服务；请确认信息合规并逐项核对后再提交。')
    if st.session_state.get('last_created_order_no'):
        st.success(f"最近确认入库订单：{st.session_state['last_created_order_no']}。请进入“单证生成”复核四单。")

    uploaded = st.file_uploader(
        '上传订单资料',
        type=['xls', 'xlsx', 'xlsm', 'doc', 'docx', 'pdf', 'png', 'jpg', 'jpeg'],
        help='支持 Excel、Word、PDF 和常见图片；读取旧版 .xls/.doc 需要 Windows 上已安装 Microsoft Office。',
        key='order_source_upload',
    )
    if uploaded is not None:
        upload_digest = hashlib.sha256(uploaded.getvalue()).hexdigest()
        if st.session_state.get('recognized_order_upload_digest') != upload_digest:
            st.session_state.pop('recognized_order', None)
            st.session_state.pop('recognized_order_source_text', None)
            st.session_state['recognized_order_upload_digest'] = upload_digest
    if uploaded and st.button('识别订单信息', type='primary'):
        try:
            with st.spinner('正在读取并识别订单资料…'):
                source_text = extract_order_source_text(uploaded.name, uploaded.getvalue())
                recognized = recognize_order_text(source_text)
            st.session_state['recognized_order'] = recognized
            st.session_state['recognized_order_source_text'] = source_text
            st.session_state['recognized_order_source_name'] = uploaded.name
            st.session_state['recognized_order_upload_digest'] = hashlib.sha256(uploaded.getvalue()).hexdigest()
            st.success('识别完成。请复核并补全必要信息后确认入库。')
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(f'识别失败：{exc}')

    recognized = st.session_state.get('recognized_order')
    if recognized:
        st.markdown('**复核识别结果**')
        customers = list_customers(owner_id=owner_id)
        products = list_products()
        customer_labels = {'新增客户': None}
        for customer in customers:
            customer_labels[
                f"{customer['customer_name_cn']} / {customer['customer_name_en']}"
            ] = customer['id']
        product_labels = {'新增产品': None}
        for product in products:
            product_labels[f"{product['product_name_en']} / {product['product_name_cn']}"] = product['id']
        lc_rows = list_approved_unlinked_lcs(owner_id)
        lc_labels = {'不关联信用证': None}
        for lc in lc_rows:
            lc_labels[f"{lc['lc_no']} · {lc['applicant']} · {lc['currency']} {lc['lc_amount']}"] = lc['id']

        default_customer = next(
            (
                label for label in customer_labels
                if label != '新增客户'
                and any(name and name.lower() in label.lower() for name in (
                    recognized.get('customer_name_en', ''),
                    recognized.get('customer_name_cn', ''),
                ))
            ),
            '新增客户',
        )
        default_product = next(
            (
                label for label in product_labels
                if label != '新增产品'
                and recognized.get('product_name_en')
                and recognized['product_name_en'].lower() in label.lower()
            ),
            '新增产品',
        )

        with st.form('recognized_order_review'):
            st.caption(f"来源文件：{st.session_state.get('recognized_order_source_name', '')}")
            with st.expander('查看系统提取的原始文字'):
                st.text_area(
                    '提取文字',
                    value=st.session_state.get('recognized_order_source_text', ''),
                    height=240,
                    disabled=True,
                    label_visibility='collapsed',
                )
            left, right = st.columns(2)
            with left:
                order_no = st.text_input('订单编号（请确认）', value=recognized.get('order_no', ''))
                customer_choice = st.selectbox(
                    '归属客户',
                    list(customer_labels),
                    index=list(customer_labels).index(default_customer),
                )
                if customer_labels[customer_choice] is None:
                    customer_name_cn = st.text_input('客户中文名', value=recognized.get('customer_name_cn', ''))
                    customer_name_en = st.text_input('客户英文名', value=recognized.get('customer_name_en', ''))
                    customer_address = st.text_area('客户地址', value=recognized.get('customer_address', ''))
                    contact_person = st.text_input('联系人', value=recognized.get('contact_person', ''))
                    customer_email = st.text_input('客户邮箱', value=recognized.get('email', ''))
                    customer_phone = st.text_input('客户电话', value=recognized.get('phone', ''))
                    customer_destination = st.text_input('客户常用目的港', value=recognized.get('destination_port', ''))
                    customer_terms = st.text_input('客户常用付款方式', value=recognized.get('payment_terms', ''))
                    customer_incoterm = st.text_input('客户常用贸易条款', value=recognized.get('incoterm', ''))
                else:
                    customer_name_cn = customer_name_en = customer_address = contact_person = ''
                    customer_email = customer_phone = customer_destination = customer_terms = customer_incoterm = ''

                product_choice = st.selectbox(
                    '归属产品',
                    list(product_labels),
                    index=list(product_labels).index(default_product),
                )
                if product_labels[product_choice] is None:
                    product_name_en = st.text_input('产品英文名', value=recognized.get('product_name_en', ''))
                    product_name_cn = st.text_input('产品中文名', value=recognized.get('product_name_cn', ''))
                    product_hs_code = st.text_input('HS Code', value=recognized.get('hs_code', ''))
                    product_cas_no = st.text_input('CAS No.', value=recognized.get('cas_no', ''))
                    product_specification = st.text_input('产品规格', value=recognized.get('product_specification', ''))
                    packaging_method = st.text_input('包装方式', value=recognized.get('packaging_method', ''))
                    gross_per_unit = st.number_input(
                        '毛重/计量单位（kg）', min_value=0.0,
                        value=float(recognized.get('gross_weight_per_unit') or 0.0),
                    )
                    net_per_unit = st.number_input(
                        '净重/计量单位（kg）', min_value=0.0,
                        value=float(recognized.get('net_weight_per_unit') or 0.0),
                    )
                    volume_per_unit = st.number_input(
                        '体积/计量单位（CBM）', min_value=0.0,
                        value=float(recognized.get('volume_per_unit') or 0.0),
                    )
                else:
                    product_name_en = product_name_cn = product_hs_code = product_cas_no = ''
                    product_specification = packaging_method = ''
                    gross_per_unit = net_per_unit = volume_per_unit = 0.0

            with right:
                quantity = st.number_input(
                    '订单数量',
                    min_value=0.0,
                    value=float(recognized.get('quantity') or 0.0),
                )
                unit = st.text_input('数量单位', value=recognized.get('unit') or 'MT')
                unit_price = st.number_input(
                    '订单单价',
                    min_value=0.0,
                    value=float(recognized.get('unit_price') or 0.0),
                )
                currency = st.text_input('币种', value=recognized.get('currency') or 'USD')
                loading_port = st.text_input('起运港', value=recognized.get('loading_port', ''))
                destination_port = st.text_input('目的港', value=recognized.get('destination_port', ''))
                incoterm = st.text_input('贸易条款', value=recognized.get('incoterm', ''))
                payment_terms = st.text_input('付款方式', value=recognized.get('payment_terms', ''))
                shipment_date_value = recognized.get('shipment_date', '')
                latest_shipment_value = recognized.get('latest_shipment_date', '')
                if shipment_date_value and not parse_date(shipment_date_value):
                    st.warning(f'AI 识别的计划装运日期格式无法确认：{shipment_date_value}')
                if latest_shipment_value and not parse_date(latest_shipment_value):
                    st.warning(f'AI 识别的最迟装运日格式无法确认：{latest_shipment_value}')
                upload_key = st.session_state.get('recognized_order_upload_digest', 'preview')
                shipment_date = st.date_input(
                    '计划装运日期',
                    value=parse_date(shipment_date_value),
                    key=f'recognized_shipment_date_{upload_key}',
                    format='YYYY/MM/DD',
                )
                latest_shipment_date = st.date_input(
                    '最迟装运日',
                    value=parse_date(latest_shipment_value),
                    key=f'recognized_latest_shipment_date_{upload_key}',
                    format='YYYY/MM/DD',
                )
                marks_and_numbers = st.text_area('唛头', value=recognized.get('marks_and_numbers', ''))
                special_requirements = st.text_area('特殊要求', value=recognized.get('special_requirements', ''))
                lc_choice = st.selectbox('关联已确认信用证', list(lc_labels))

            confirm_data = st.checkbox('我已核对识别信息、客户归属、产品和订单条件，确认录入。')
            save_order = st.form_submit_button('确认并创建订单', type='primary')

        if save_order:
            try:
                if not confirm_data:
                    raise ValueError('请先确认已核对识别信息。')
                if not order_no.strip():
                    raise ValueError('请填写订单编号。')
                if quantity <= 0 or unit_price <= 0:
                    raise ValueError('订单数量和单价必须大于 0。')
                for date_label, date_value in (
                    ('计划装运日期', shipment_date),
                    ('最迟装运日', latest_shipment_date),
                ):
                    if date_value is not None and not isinstance(date_value, date):
                        raise ValueError(f'{date_label}必须使用有效日期。')
                customer_id = customer_labels[customer_choice]
                if customer_id is None:
                    if not customer_name_cn.strip() and not customer_name_en.strip():
                        raise ValueError('新客户至少需要中文名或英文名。')
                product_id = product_labels[product_choice]
                if product_id is None:
                    if not product_name_en.strip():
                        raise ValueError('新产品请填写英文名称。')
                    if not currency.strip():
                        raise ValueError('请填写币种。')
                with get_connection() as conn:
                    if conn.execute('SELECT 1 FROM orders WHERE order_no = ?', (order_no.strip(),)).fetchone():
                        raise ValueError('该订单编号已存在，请核对或修改订单编号。')
                if customer_id is None:
                    customer_id, customer_created = get_or_create_customer(
                        {
                            'customer_name_cn': customer_name_cn,
                            'customer_name_en': customer_name_en,
                            'company_address': customer_address,
                            'contact_person': contact_person,
                            'email': customer_email,
                            'phone': customer_phone,
                            'destination_port': customer_destination,
                            'payment_terms': customer_terms,
                            'incoterm': customer_incoterm,
                        },
                        owner_id,
                    )
                    if not customer_created:
                        st.info('客户名称已匹配到现有档案，订单将归属该客户的业务员。')
                if product_id is None:
                    product_id = create_product(
                        {
                            'product_name_en': product_name_en,
                            'product_name_cn': product_name_cn,
                            'hs_code': product_hs_code,
                            'cas_no': product_cas_no,
                            'unit_price': unit_price,
                            'currency': currency,
                            'packaging_method': packaging_method,
                            'gross_weight_per_carton': gross_per_unit,
                            'net_weight_per_carton': net_per_unit,
                            'carton_volume_cbm': volume_per_unit,
                            'specification': product_specification,
                            'product_description_en': recognized.get('product_description_en', ''),
                        }
                    )
                order_id = create_order(
                    {
                        'order_no': order_no,
                        'customer_id': customer_id,
                        'product_id': product_id,
                        'quantity': quantity,
                        'unit': unit,
                        'unit_price': unit_price,
                        'currency': currency,
                        'loading_port': loading_port,
                        'destination_port': destination_port,
                        'incoterm': incoterm,
                        'payment_terms': payment_terms,
                        'shipment_date': shipment_date.isoformat() if shipment_date else '',
                        'latest_shipment_date': latest_shipment_date.isoformat() if latest_shipment_date else '',
                        'presentation_deadline': '',
                        'lc_expiry_date': '',
                        'marks_and_numbers': marks_and_numbers,
                        'special_requirements': special_requirements,
                        'user_id': owner_id,
                        'source_file_name': st.session_state.get('recognized_order_source_name', ''),
                    }
                )
                lc_id = lc_labels[lc_choice]
                if lc_id is not None:
                    attach_lc_to_order(lc_id, order_id, owner_id)
                    lc_record = get_lc_by_order(order_id, owner_id)
                    if lc_record:
                        parsed_lc = json.loads(lc_record.get('parsed_json') or '{}')
                    else:
                        parsed_lc = {}
                else:
                    parsed_lc = {}
                generate_and_store_reminders(order_id, parsed_lc, lc_id)
                st.session_state['last_created_order_no'] = order_no
                st.session_state.pop('recognized_order', None)
                st.success(f'订单 {order_no} 已保存，可前往“单证生成”页面复核四单。')
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(f'订单未能保存：{exc}')
