from __future__ import annotations

import hashlib
from typing import Any, Dict, List

import streamlit as st

from database.db import get_connection
from modules.auth import require_authenticated_user
from modules.products import (
    MATCH_LEVEL_FUZZY,
    MATCH_LEVEL_NAME,
    MATCH_LEVEL_NAME_SPEC,
    MATCH_LEVEL_SKU,
    build_product_payload_from_request,
    compute_stock_status,
    create_product,
    delete_product,
    evaluate_demand_vs_stock,
    export_products_excel,
    extract_product_metadata_from_pdf,
    find_sku_conflicts,
    get_product_by_id,
    list_products,
    match_products_for_request,
    parse_chat_product_requests,
    save_uploaded_pdf,
    single_match_id,
    update_product,
)
from modules.ui_style import (
    STOCK_UNMAINTAINED_TEXT,
    page_header,
    render_card,
    render_data_table,
    render_empty_state,
    section,
    stock_display_value,
    stock_status_color,
)

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

MATCH_LEVEL_LABELS = {
    MATCH_LEVEL_SKU: '明确匹配',
    MATCH_LEVEL_NAME_SPEC: '明确匹配',
    MATCH_LEVEL_NAME: '明确匹配',
    MATCH_LEVEL_FUZZY: '相似匹配',
}

# 识别流程的全部会话状态统一前缀；文本框本身的 key 不带此前缀
CHAT_STATE_PREFIX = 'chatp_'

current_user = require_authenticated_user()
owner_id = int(current_user['id'])


def parse_optional_float(text: str, label: str) -> float | None:
    """页面输入转数值：留空表示未填写（None），非法输入明确报错。"""
    cleaned = str(text or '').strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(f'{label}必须是数字，当前值：{cleaned}') from None


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
        # 库存：数值为 None 时显示为空字符串，避免出现字面量 "None"
        'sku': str(defaults.get('sku') or ''),
        'stock_qty': '' if defaults.get('stock_qty') is None else str(defaults['stock_qty']),
        'unit': str(defaults.get('unit') or ''),
        'safety_stock': '' if defaults.get('safety_stock') is None else str(defaults['safety_stock']),
        'warehouse': str(defaults.get('warehouse') or ''),
    }


def clear_chat_recognition() -> None:
    """清空识别流程的全部会话状态（不影响文本框内容本身）。"""
    for key in [str(existing_key) for existing_key in st.session_state.keys()]:
        if key.startswith(CHAT_STATE_PREFIX):
            st.session_state.pop(key, None)


def run_recognition() -> None:
    """执行一次识别：解析 → 存入会话状态。此过程不写数据库。"""
    parsed_items = parse_chat_product_requests(chat_source)
    clear_chat_recognition()
    for index, parsed_item in enumerate(parsed_items):
        parsed_item['uid'] = f'{source_digest[:10]}_{index}'
    st.session_state[CHAT_STATE_PREFIX + 'items'] = parsed_items
    st.session_state[CHAT_STATE_PREFIX + 'digest'] = source_digest
    if not parsed_items:
        st.warning('未识别到明确的产品信息，请检查原文，或使用下方表单手动录入。')


def candidate_label(candidate: Dict[str, Any]) -> str:
    stock_status = compute_stock_status(
        candidate.get('stock_qty'), candidate.get('safety_stock')
    )
    english = candidate.get('product_name_en') or '（无英文名）'
    chinese = candidate.get('product_name_cn') or ''
    return (
        f"ID {candidate['id']} · {english} {chinese} · "
        f"规格 {candidate.get('specification') or '未维护'} · "
        f"库存 {stock_display_value(candidate.get('stock_qty'))} "
        f"{candidate.get('unit') or ''} · {stock_status}"
    )


def render_matched_product(
    product: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    selected_id: int,
    requested_qty: float | None,
    requested_unit: str,
) -> None:
    """把「客户需求」与「实际库存」分两块展示，避免混淆。"""
    matched = next((row for row in candidates if int(row['id']) == selected_id), None)
    level = str(matched.get('match_level') or '') if matched else ''
    basis = str(matched.get('match_basis') or '') if matched else ''
    st.caption(f"{MATCH_LEVEL_LABELS.get(level, '匹配')}（{basis}）")

    demand_column, stock_column = st.columns(2)
    with demand_column:
        st.markdown('**客户需求**')
        demand_qty = '未提及' if requested_qty is None else str(requested_qty)
        st.write(f'{demand_qty} {requested_unit or "（单位未提及）"}')
        st.caption('客户需求数量不等于库存，也不会写入库存。')
    with stock_column:
        st.markdown('**实际库存（来自产品库）**')
        stock_status = compute_stock_status(
            product.get('stock_qty'), product.get('safety_stock')
        )
        st.badge(f'库存状态：{stock_status}', color=stock_status_color(stock_status))
        st.write(
            f"库存 {stock_display_value(product.get('stock_qty'))} "
            f"{product.get('unit') or ''}"
        )
        st.write(f"安全库存 {stock_display_value(product.get('safety_stock'))}")
        st.write(f"仓库 {product.get('warehouse') or STOCK_UNMAINTAINED_TEXT}")
        st.caption(product.get('stock_updated_at') or '库存从未维护过')

    comparison = evaluate_demand_vs_stock(product, requested_qty, requested_unit)
    if comparison['comparable']:
        if comparison['enough']:
            st.success('库存数量满足本次客户需求数量。')
        else:
            st.warning('库存数量低于本次客户需求数量。')
    else:
        st.caption(f"未做对比：{comparison['reason']}（仅展示原始信息）")


def save_new_product(uid: str, payload: Dict[str, Any]) -> None:
    create_product(payload, owner_id)
    st.session_state.setdefault(CHAT_STATE_PREFIX + 'saved_uids', set()).add(uid)
    st.session_state.pop(f'pending_{uid}', None)
    st.session_state.pop(f'conflicts_{uid}', None)
    st.success('产品资料已新增；库存保持「未维护」，需另行维护。')
    st.rerun()


def handle_new_product(uid: str, edited_item: Dict[str, Any]) -> None:
    payload = build_product_payload_from_request(edited_item)
    conflicts = find_sku_conflicts(payload.get('sku', ''))
    if conflicts:
        st.session_state[f'pending_{uid}'] = payload
        st.session_state[f'conflicts_{uid}'] = conflicts
        return
    save_new_product(uid, payload)


def render_sku_conflicts(uid: str) -> None:
    conflicts = st.session_state.get(f'conflicts_{uid}') or []
    if not conflicts:
        return
    pending = st.session_state.get(f'pending_{uid}') or {}
    st.warning(f"SKU “{pending.get('sku', '')}”已被其他产品使用，新增已暂停。")
    render_data_table(
        [
            {
                '产品ID': item['id'],
                '英文品名': item['product_name_en'],
                '中文品名': item['product_name_cn'],
                '规格/牌号': item['specification'],
                '创建时间': item['created_at'],
            }
            for item in conflicts
        ]
    )
    confirm_column, cancel_column = st.columns(2)
    with confirm_column:
        if st.button(
            '仍要保存（保留重复 SKU）',
            key=f'keep_sku_{uid}',
            type='primary',
            use_container_width=True,
        ):
            save_new_product(uid, st.session_state[f'pending_{uid}'])
    with cancel_column:
        if st.button('取消', key=f'cancel_sku_{uid}', use_container_width=True):
            st.session_state.pop(f'pending_{uid}', None)
            st.session_state.pop(f'conflicts_{uid}', None)
            st.rerun()


def product_order_count(product_id: int) -> int:
    """只读统计：用于删除前的影响提示，不做任何写入。"""
    with get_connection() as conn:
        return conn.execute(
            'SELECT COUNT(*) FROM orders WHERE product_id = ?',
            (product_id,),
        ).fetchone()[0]


if 'product_edit_id' not in st.session_state:
    st.session_state.product_edit_id = None
if 'product_form_open' not in st.session_state:
    st.session_state.product_form_open = False
if 'product_pending_delete_id' not in st.session_state:
    st.session_state.product_pending_delete_id = None

page_header(
    '产品库',
    caption='手动录入、PDF 解析与聊天识别；库存未维护与 0 是两个状态，库存状态由数量与安全库存实时计算。',
)

search_column, action_column = st.columns([3, 1])
with search_column:
    search_text = st.text_input(
        '搜索产品', placeholder='请输入英文名 / 中文名 / HS编码', key='product_search'
    )
with action_column:
    if st.button('新增产品', type='primary', use_container_width=True):
        st.session_state.product_edit_id = None
        st.session_state.product_form_open = True
        st.session_state.pop('sku_conflicts', None)
        st.session_state.pop('pending_product_payload', None)
        st.rerun()

products = list_products(search_text)
all_products = list_products('')

section('产品列表')
render_data_table(
    [
        {
            '英文品名': product['product_name_en'],
            '中文品名': product['product_name_cn'],
            '规格/牌号': product.get('specification') or '未维护',
            'SKU': product.get('sku') or '未维护',
            '库存': f"{stock_display_value(product.get('stock_qty'))} {product.get('unit') or ''}".strip(),
            '安全库存': stock_display_value(product.get('safety_stock')),
            '库存状态': compute_stock_status(
                product.get('stock_qty'), product.get('safety_stock')
            ),
            '仓库': product.get('warehouse') or '未维护',
            '库存更新时间': product.get('stock_updated_at') or '从未维护',
        }
        for product in products
    ],
    empty_message='暂无产品记录，可使用上方「新增产品」或从聊天记录识别建档。',
)

if products:
    product_labels = {
        f"{product['product_name_en']} / {product['product_name_cn']}（#{product['id']}）": product['id']
        for product in products
    }
    product_selection_column, edit_column, delete_column = st.columns([3, 1, 1])
    with product_selection_column:
        selected_product_label = st.selectbox('选择产品进行操作', list(product_labels))
    target_product_id = product_labels[selected_product_label]
    with edit_column:
        if st.button('编辑所选产品', use_container_width=True):
            st.session_state.product_edit_id = target_product_id
            st.session_state.product_form_open = True
            st.session_state.pop('sku_conflicts', None)
            st.session_state.pop('pending_product_payload', None)
            st.rerun()
    with delete_column:
        if st.button('删除所选产品', use_container_width=True):
            st.session_state.product_pending_delete_id = target_product_id
            st.rerun()

pending_delete_id = st.session_state.product_pending_delete_id
if pending_delete_id:
    target = next(
        (product for product in products if product['id'] == pending_delete_id), None
    )
    if target is None:
        st.session_state.product_pending_delete_id = None
    else:
        target_name = target['product_name_en'] or target['product_name_cn'] or f"#{pending_delete_id}"
        affected = product_order_count(pending_delete_id)
        st.warning(
            f"确认删除产品「{target_name}」？"
            + (
                f"该产品被 {affected} 个订单引用。删除产品不会删除这些订单，"
                '但订单会失去产品关联。'
                if affected
                else '该产品暂未被订单引用。'
            )
        )
        confirm_column, cancel_column = st.columns([1, 1])
        with confirm_column:
            if st.button('确认删除产品', type='primary', use_container_width=True):
                delete_product(pending_delete_id)
                if st.session_state.product_edit_id == pending_delete_id:
                    st.session_state.product_edit_id = None
                    st.session_state.product_form_open = False
                st.session_state.product_pending_delete_id = None
                st.success('已删除产品')
                st.rerun()
        with cancel_column:
            if st.button('取消删除产品', use_container_width=True):
                st.session_state.product_pending_delete_id = None
                st.rerun()

with st.expander('导出产品资料（辅助）', expanded=False):
    st.caption('导出不会修改任何产品资料；附件只记录有无，不导出文件路径。')
    if not all_products:
        st.caption('产品库暂无记录，导出已停用。')
        st.button('导出全部产品（0 条）', disabled=True, use_container_width=True)
    else:
        filtered_column, all_column = st.columns(2)
        with filtered_column:
            if products:
                filtered_name, filtered_data = export_products_excel(search_text)
                st.download_button(
                    f'导出当前筛选结果（{len(products)} 条）',
                    data=filtered_data,
                    file_name=filtered_name,
                    mime=XLSX_MIME,
                    use_container_width=True,
                )
            else:
                st.button('导出当前筛选结果（0 条）', disabled=True, use_container_width=True)
                st.caption('当前筛选条件下没有产品记录。')
        with all_column:
            all_name, all_data = export_products_excel('')
            st.download_button(
                f'导出全部产品（{len(all_products)} 条）',
                data=all_data,
                file_name=all_name,
                mime=XLSX_MIME,
                use_container_width=True,
            )

with st.expander('PDF / MSDS 解析（辅助建档）', expanded=False):
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

with st.expander('聊天 / 邮件产品识别（辅助建档）', expanded=False):
    st.caption(
        '粘贴客户聊天记录或邮件内容，点击“识别产品”后逐条核对。'
        '识别、查询和选择都不写入数据库；新增产品资料需要再次确认。'
    )
    chat_source = st.text_area(
        '粘贴客户聊天记录 / 邮件内容',
        height=150,
        key='chat_source_text',
        placeholder='例如：我们需要 PP 550J，25 吨\n另外 HDPE 6098H 有库存吗？',
    )
    source_digest = (
        hashlib.sha1(chat_source.strip().encode('utf-8')).hexdigest()
        if chat_source.strip()
        else ''
    )
    if st.button('识别产品', type='primary'):
        run_recognition()

    recognized_items = st.session_state.get(CHAT_STATE_PREFIX + 'items') or []
    recognized_digest = st.session_state.get(CHAT_STATE_PREFIX + 'digest', '')
    saved_uids = st.session_state.setdefault(CHAT_STATE_PREFIX + 'saved_uids', set())

    if recognized_items and source_digest and recognized_digest != source_digest:
        st.info('原文已变更，当前展示的是上一次识别结果。')
        rerun_column, drop_column = st.columns([1, 1])
        with rerun_column:
            if st.button('重新识别', key='chat_re_recognize'):
                run_recognition()
                st.rerun()
        with drop_column:
            if st.button('放弃识别结果', key='chat_drop_recognition'):
                clear_chat_recognition()
                st.rerun()

    for item_index, item in enumerate(recognized_items):
        item_uid = item.get('uid') or f'{recognized_digest[:10]}_{item_index}'
        snippet = str(item.get('raw_snippet') or '').strip()
        with render_card(f'需求 {item_index + 1}', caption=f'原文片段：{snippet}' if snippet else None):
            # 先给足默认值：解析抛错时下方「录入新产品」仍要能拿到可回填的内容
            item_name = str(item.get('product_name_en') or '')
            item_spec = str(item.get('specification') or '')
            item_sku = str(item.get('sku_hint') or '')
            item_unit = str(item.get('requested_unit') or '')
            item_qty_text = '' if item.get('requested_qty') is None else str(item['requested_qty'])
            candidates: List[Dict[str, Any]] = []
            try:
                request_columns = st.columns(2)
                with request_columns[0]:
                    item_name = st.text_input(
                        '产品 / 牌号',
                        value=str(item.get('product_name_en') or ''),
                        key=f'req_name_{item_uid}',
                    )
                with request_columns[1]:
                    item_spec = st.text_input(
                        '规格 / 型号',
                        value=str(item.get('specification') or ''),
                        key=f'req_spec_{item_uid}',
                    )
                quantity_columns = st.columns(3)
                with quantity_columns[0]:
                    item_sku = st.text_input(
                        'SKU / 编号',
                        value=str(item.get('sku_hint') or ''),
                        key=f'req_sku_{item_uid}',
                    )
                with quantity_columns[1]:
                    default_qty = (
                        '' if item.get('requested_qty') is None else str(item['requested_qty'])
                    )
                    item_qty_text = st.text_input(
                        '需求数量', value=default_qty, key=f'req_qty_{item_uid}'
                    )
                with quantity_columns[2]:
                    item_unit = st.text_input(
                        '需求单位',
                        value=str(item.get('requested_unit') or ''),
                        key=f'req_unit_{item_uid}',
                    )
                st.caption('需求数量与需求单位属于客户需求，仅用于查询库存，不会写入库存。')

                requested_qty = parse_optional_float(item_qty_text, '需求数量')
                edited_item = {
                    'product_name_en': item_name,
                    'product_name_cn': str(item.get('product_name_cn') or ''),
                    'sku_hint': item_sku,
                    'specification': item_spec,
                    'requested_qty': requested_qty,
                    'requested_unit': item_unit,
                }
                candidates = match_products_for_request(edited_item)

                if not candidates:
                    render_empty_state(
                        '未匹配到已有产品',
                        hint='可修正上方字段后重新匹配，或确认录入为新产品资料（库存默认未维护）。',
                    )
                else:
                    labels = {candidate_label(row): int(row['id']) for row in candidates}
                    auto_id = single_match_id(candidates)
                    options = list(labels)
                    default_index = options.index(next(
                        label for label, product_id in labels.items() if product_id == auto_id
                    )) if auto_id is not None else None
                    choice = st.selectbox(
                        '候选产品',
                        options,
                        index=default_index,
                        placeholder='请选择候选产品（多条候选不会自动绑定）',
                        key=f'req_candidate_{item_uid}',
                    )
                    selected_id = labels.get(choice) if choice else None
                    if selected_id:
                        product = get_product_by_id(selected_id)
                        if product:
                            render_matched_product(
                                product,
                                candidates,
                                selected_id,
                                requested_qty,
                                item_unit,
                            )
            except ValueError as exc:
                st.error(str(exc))

        with st.expander('录入为新产品资料', expanded=not candidates):
            new_name = st.text_input(
                '英文品名（必填）', value=item_name, key=f'new_name_{item_uid}'
            )
            new_cn = st.text_input(
                '中文品名',
                value=str(item.get('product_name_cn') or ''),
                key=f'new_cn_{item_uid}',
            )
            new_spec = st.text_input('规格 / 牌号', value=item_spec, key=f'new_spec_{item_uid}')
            new_sku = st.text_input('SKU / 编号', value=item_sku, key=f'new_sku_{item_uid}')
            st.caption('新增产品资料不等于库存入库：新增后库存显示为「未维护」。')
            if item_uid in saved_uids:
                st.success('该产品资料已入库，无需重复提交。')
            else:
                if st.button('确认新增产品资料', key=f'new_submit_{item_uid}', type='primary'):
                    try:
                        handle_new_product(
                            item_uid,
                            {
                                'product_name_en': new_name,
                                'product_name_cn': new_cn,
                                'specification': new_spec,
                                'sku_hint': new_sku,
                            },
                        )
                    except ValueError as exc:
                        st.error(str(exc))
            render_sku_conflicts(item_uid)

preview_data = st.session_state.get('ai_preview', {})
current_defaults = {}
if preview_data:
    current_defaults.update(preview_data)
if st.session_state.product_edit_id is not None:
    existing = get_product_by_id(st.session_state.product_edit_id)
    if existing:
        current_defaults = default_product_form(existing)

with st.expander('产品信息表单', expanded=st.session_state.product_form_open):
    form_data = default_product_form(current_defaults)
    with st.form('product_management_form'):
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

        with st.container(border=True):
            st.markdown('**库存**')
            stock_cols = st.columns(3)
            with stock_cols[0]:
                form_data['sku'] = st.text_input('产品编号 / SKU', value=form_data['sku'])
            with stock_cols[1]:
                form_data['stock_qty'] = st.text_input('库存数量', value=form_data['stock_qty'])
            with stock_cols[2]:
                form_data['unit'] = st.text_input('库存单位', value=form_data['unit'], placeholder='如 kg / carton')
            storage_cols = st.columns(2)
            with storage_cols[0]:
                form_data['safety_stock'] = st.text_input('安全库存', value=form_data['safety_stock'])
            with storage_cols[1]:
                form_data['warehouse'] = st.text_input('仓库', value=form_data['warehouse'])
            st.caption('留空表示未维护（不是 0）；库存状态由库存数量与安全库存实时计算，不单独保存。')

        confirm_checkbox = st.checkbox('我已确认 AI 提取内容无误，可保存到产品库', value=False)
        save_button = st.form_submit_button('保存产品')


def persist_product(payload: Dict[str, Any]) -> None:
    """保存产品；库存字段变更时由 create/update 记录操作人与时间。"""
    if st.session_state.product_edit_id is None:
        create_product(payload, owner_id)
        st.success('产品已保存')
    else:
        update_product(st.session_state.product_edit_id, payload, owner_id)
        st.success('产品已更新')
    st.session_state.product_edit_id = None
    st.session_state.product_form_open = False
    st.session_state.pop('pending_product_payload', None)
    st.session_state.pop('sku_conflicts', None)
    st.rerun()


if save_button:
    try:
        if not confirm_checkbox:
            st.warning('请先确认 AI 提取结果后再保存。')
        else:
            conflicts = find_sku_conflicts(
                form_data['sku'],
                exclude_product_id=st.session_state.product_edit_id,
            )
            if conflicts:
                st.session_state['pending_product_payload'] = form_data
                st.session_state['sku_conflicts'] = conflicts
            else:
                persist_product(form_data)
    except ValueError as exc:
        st.error(str(exc))

# SKU 冲突确认区位于表单外：只有明确点击“仍要保存”才会落库
sku_conflicts = st.session_state.get('sku_conflicts') or []
if sku_conflicts:
    st.warning(
        f'SKU “{st.session_state.get("pending_product_payload", {}).get("sku", "")}”'
        '已被其他产品使用，保存已暂停。'
    )
    render_data_table(
        [
            {
                '产品ID': item['id'],
                '英文品名': item['product_name_en'],
                '中文品名': item['product_name_cn'],
                '规格/牌号': item['specification'],
                '创建时间': item['created_at'],
            }
            for item in sku_conflicts
        ]
    )
    confirm_column, cancel_column = st.columns([1, 1])
    with confirm_column:
        if st.button(
            '仍要保存（保留重复 SKU）',
            key='product_form_keep_sku',
            type='primary',
            use_container_width=True,
        ):
            persist_product(st.session_state['pending_product_payload'])
    with cancel_column:
        if st.button('取消并修改', key='product_form_cancel_sku', use_container_width=True):
            st.session_state.pop('pending_product_payload', None)
            st.session_state.pop('sku_conflicts', None)
            st.rerun()
