from __future__ import annotations

import json
import hashlib

import streamlit as st
from PIL import UnidentifiedImageError

from modules.auth import require_authenticated_user
from modules.lc_parser import (
    analyze_lc_clauses,
    build_lc_summary,
    extract_lc_text,
    parse_lc_text,
    save_lc_record,
    translate_lc_text,
)
st.set_page_config(layout='wide')
owner_id = int(require_authenticated_user()['id'])

st.title('信用证解析、条款分析与翻译')
st.caption('先上传并确认信用证最终版本，再识别录入订单；信用证在订单确认时关联，并自动生成交单提醒。')
st.info('信用证文本会发送到 .env 配置的 AI 服务；若本机 OCR 不可用，图片也会发送给支持视觉的 AI 服务。分析结果请人工核对后再同步。')

uploaded_file = st.file_uploader('上传信用证文件或图片', type=['pdf', 'png', 'jpg', 'jpeg'])
if 'lc_analysis_preview' not in st.session_state:
    st.session_state['lc_analysis_preview'] = None
if uploaded_file is not None:
    upload_digest = hashlib.sha256(uploaded_file.getvalue()).hexdigest()
    if st.session_state.get('lc_upload_digest') != upload_digest:
        st.session_state['lc_analysis_preview'] = None
        st.session_state['lc_upload_digest'] = upload_digest

if uploaded_file is not None and st.button('识别、分析并翻译', type='primary'):
    try:
        with st.spinner('正在提取信用证内容…'):
            raw_text = extract_lc_text(uploaded_file.name, uploaded_file.getvalue())
        if not raw_text.strip():
            st.error('未能从文件中识别出文字。若这是扫描件，请确认已安装 Tesseract，或配置支持视觉的 AI 服务。')
        else:
            parsed = parse_lc_text(raw_text)
            st.session_state['lc_analysis_preview'] = {
                'filename': uploaded_file.name,
                'raw_text': raw_text,
                'parsed': parsed,
            }
            with st.spinner('正在分析不利条款和单据要求…'):
                analysis = analyze_lc_clauses(raw_text)
            parsed['documents_required'] = analysis['document_requirements']
            parsed['adverse_clauses'] = analysis['adverse_clauses']
            parsed['presentation_period_days'] = analysis['presentation_period_days']
            parsed['dispatch_days_after_shipment'] = analysis['dispatch_days_after_shipment']
            parsed['dispatch_instruction'] = analysis['dispatch_instruction']
            st.session_state['lc_analysis_preview']['parsed'] = parsed
            st.session_state['lc_analysis_preview']['analysis'] = analysis
            with st.spinner('正在翻译信用证全文…'):
                translation = translate_lc_text(raw_text)
            st.session_state['lc_analysis_preview']['translation'] = translation
    except (ValueError, RuntimeError, OSError, UnidentifiedImageError) as exc:
        st.error(f'处理失败：{exc}')

preview = st.session_state.get('lc_analysis_preview')
if preview:
    st.caption(f"当前分析文件：{preview['filename']}")
    st.subheader('识别出的信用证原文')
    st.text_area('原文', preview['raw_text'], height=220, disabled=True, label_visibility='collapsed')

    analysis = preview.get('analysis')
    if analysis:
        parsed = preview['parsed']
        st.subheader('关键信息摘要')
        st.text(build_lc_summary(parsed))
        with st.expander('结构化字段'):
            st.json(parsed)

        st.subheader('不利或需重点关注的条款')
        adverse_clauses = analysis['adverse_clauses']
        if adverse_clauses:
            for index, item in enumerate(adverse_clauses, start=1):
                st.markdown(f"**{index}. [{item['risk_level']}风险] {item['risk_type']}**")
                st.markdown(f"- 信用证原文：{item['original_clause_en']}")
                st.markdown(f"- 风险说明：{item['risk_explanation_cn']}")
                st.markdown(f"- 建议：{item['suggested_action_cn']}")
                if item['affected_documents']:
                    st.markdown(f"- 可能影响单据：{', '.join(item['affected_documents'])}")
        else:
            st.success('未识别到明显不利条款；仍建议人工核对信用证原文。')

        st.subheader('单据要求及正副本份数')
        requirements = analysis['document_requirements']
        if requirements:
            st.dataframe(
                [
                    {
                        '单据类型': item['document_type'],
                        '正本份数': item['original_count'] if item['original_count'] is not None else '原文未明确',
                        '副本份数': item['copy_count'] if item['copy_count'] is not None else '原文未明确',
                        '四单同步目标': '、'.join(item['affected_documents']) or '其他单据/待人工确认',
                        '附加要求': item['special_requirements'] or '无',
                    }
                    for item in requirements
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.warning('未从信用证中识别到明确的单据份数要求，请人工核对原文。')

        st.subheader('确认信用证最终版本')
        st.caption('请核对原文、中文翻译、结构化字段、不利条款及单据份数。确认保存后，此版本不可由系统自动改写。')
        with st.form('approve_lc_form'):
            final_translation = st.text_area(
                '信用证中文翻译（可修改）',
                value=preview.get('translation', ''),
                height=320,
            )
            final_parsed_json = st.text_area(
                '最终结构化信用证信息（JSON，可修改）',
                value=json.dumps(parsed, ensure_ascii=False, indent=2),
                height=320,
            )
            confirmed = st.checkbox('我已逐项核对信用证原文、翻译和条款分析，确认该版本可用于订单执行。')
            save_final = st.form_submit_button('确认最终版本并保存待关联信用证', type='primary')
        if save_final:
            if not confirmed:
                st.error('请先勾选确认。')
            else:
                try:
                    final_parsed = json.loads(final_parsed_json)
                    if not isinstance(final_parsed, dict):
                        raise ValueError('结构化信息必须是 JSON 对象。')
                    if not final_translation.strip():
                        raise ValueError('请确认并保存信用证中文翻译。')
                    requirements = final_parsed.get('documents_required')
                    if requirements is not None and not isinstance(requirements, list):
                        raise ValueError('documents_required 必须为数组。')
                    lc_id = save_lc_record(
                        None,
                        final_parsed,
                        preview['raw_text'],
                        final_parsed.get('adverse_clauses', analysis['adverse_clauses']),
                        translation_text=final_translation,
                        owner_id=owner_id,
                        approved_by=owner_id,
                    )
                    st.session_state.pop('lc_analysis_preview', None)
                    st.session_state.pop('lc_upload_digest', None)
                    st.success(f'信用证最终版本已确认保存（记录 ID：{lc_id}）。下一步请识别录入订单并关联该信用证。')
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    st.error(f'无法保存信用证最终版本：{exc}')
    else:
        st.info('原文已提取。请配置 AI 服务后点击“识别、分析并翻译”以继续分析。')
