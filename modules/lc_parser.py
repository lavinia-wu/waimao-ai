from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any, Dict, List

import fitz
import pytesseract
from PIL import Image

from database.db import get_connection
from modules.orders import get_order_by_id, update_order

RISK_HANDLING_LEVELS = ('必须处理', '需确认', '一般提示')
RISK_HANDLING_STATUSES = (
    '未处理',
    '已确认可接受',
    '已整改',
    '待客户确认',
    '待修改信用证',
)
RESOLVED_RISK_STATUSES = {'已确认可接受', '已整改'}


def _risk_handling_level(risk_level: Any, requested: Any = None) -> str:
    if requested in RISK_HANDLING_LEVELS:
        return str(requested)
    level = str(risk_level or '').strip().casefold()
    if level in {'高', 'high', 'critical'}:
        return '必须处理'
    if level in {'低', 'low', 'minor'}:
        return '一般提示'
    return '需确认'


def _risk_items(value: List[Dict[str, Any]] | str | None) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict) and item.get('original_clause_en')]


def _insert_lc_risks(conn, lc_id: int, risks: list[dict[str, Any]]) -> None:
    for item in risks:
        risk_level = str(item.get('risk_level') or '中')
        handling_status = item.get('handling_status')
        if handling_status not in RISK_HANDLING_STATUSES:
            handling_status = '未处理'
        note = str(item.get('handling_note') or '').strip()
        conn.execute(
            """
            INSERT INTO lc_risks (
                lc_id, risk_level, risk_type, original_clause_en,
                clause_translation_cn, risk_explanation_cn, suggested_action_cn,
                handling_level, handling_status, handling_note, handled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lc_id,
                risk_level,
                str(item.get('risk_type') or '信用证条款风险'),
                str(item.get('original_clause_en') or ''),
                str(item.get('clause_translation_cn') or item.get('translation_cn') or ''),
                str(item.get('risk_explanation_cn') or ''),
                str(item.get('suggested_action_cn') or ''),
                _risk_handling_level(risk_level, item.get('handling_level')),
                handling_status,
                note,
                None,
            ),
        )
        if handling_status != '未处理' or note:
            conn.execute(
                'UPDATE lc_risks SET handled_at = CURRENT_TIMESTAMP WHERE id = last_insert_rowid()'
            )


def get_lc_risks(lc_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            'SELECT * FROM lc_risks WHERE lc_id = ? ORDER BY id',
            (lc_id,),
        ).fetchall()
        lc_row = conn.execute(
            'SELECT parsed_json, risk_report_json FROM letters_of_credit WHERE id = ?',
            (lc_id,),
        ).fetchone()
        if lc_row is None:
            return []
        record = dict(lc_row)
        parsed = _safe_json_object(record.get('parsed_json'))
        if not rows:
            legacy_risks = _risk_items(parsed.get('adverse_clauses'))
            if not legacy_risks:
                legacy_risks = _risk_items(record.get('risk_report_json'))
            if legacy_risks:
                _insert_lc_risks(conn, lc_id, legacy_risks)
                conn.commit()
        if not rows:
            rows = conn.execute(
                'SELECT * FROM lc_risks WHERE lc_id = ? ORDER BY id',
                (lc_id,),
            ).fetchall()
        source_risks = _risk_items(parsed.get('adverse_clauses'))
        if not source_risks:
            source_risks = _risk_items(record.get('risk_report_json'))
        by_clause = {
            str(item.get('original_clause_en') or ''): item
            for item in source_risks
        }
        result = []
        for row in rows:
            risk = dict(row)
            source = by_clause.get(str(risk.get('original_clause_en') or ''), {})
            risk['affected_documents'] = source.get('affected_documents') or []
            result.append(risk)
        return result


def _safe_json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if value else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def list_approved_lcs(owner_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, lc_no, applicant, order_id, expiry_date
            FROM letters_of_credit
            WHERE user_id = ? AND is_approved = 1
            ORDER BY approved_at DESC, id DESC
            """,
            (owner_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_lc_risk_handling(
    risk_id: int,
    status: str,
    note: str,
    owner_id: int,
) -> None:
    if status not in RISK_HANDLING_STATUSES:
        raise ValueError('无效的信用证风险处理状态。')
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE lc_risks
            SET handling_status = ?, handling_note = ?,
                handled_at = CASE
                    WHEN ? = '未处理' AND ? = '' THEN NULL
                    ELSE CURRENT_TIMESTAMP
                END
            WHERE id = ? AND EXISTS (
                SELECT 1 FROM letters_of_credit
                WHERE letters_of_credit.id = lc_risks.lc_id
                  AND letters_of_credit.user_id = ?
                  AND letters_of_credit.is_approved = 1
            )
            """,
            (status, note.strip(), status, note.strip(), risk_id, owner_id),
        )
        if cursor.rowcount != 1:
            raise ValueError('风险条款不存在或不属于当前业务员的已确认信用证。')
        conn.commit()


def _llm_settings() -> tuple[str, str, str, str]:
    provider = os.getenv('LLM_PROVIDER', 'openai').strip().lower()
    if provider == 'deepseek':
        api_key = os.getenv('DEEPSEEK_API_KEY', '').strip()
        default_base_url = 'https://api.deepseek.com/v1'
        default_model = 'deepseek-chat'
    else:
        api_key = os.getenv('OPENAI_API_KEY', '').strip()
        default_base_url = 'https://api.openai.com/v1'
        default_model = 'gpt-4o-mini'
    return (
        provider,
        api_key,
        os.getenv('BASE_URL', '').strip().rstrip('/') or default_base_url,
        os.getenv('LLM_MODEL', os.getenv('MODEL_NAME', default_model)).strip(),
    )


def _call_chat_completion(messages: List[Dict[str, Any]], temperature: float = 0.1) -> str:
    provider, api_key, base_url, model = _llm_settings()
    if not api_key:
        raise ValueError(f'尚未配置 {provider.upper()} API 密钥。请在 .env 中配置对应的 API_KEY。')

    request_body = json.dumps({
        'model': model,
        'temperature': temperature,
        'messages': messages,
    }).encode('utf-8')
    request = urllib.request.Request(
        f'{base_url}/chat/completions',
        data=request_body,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode('utf-8'))
    except json.JSONDecodeError as exc:
        raise RuntimeError('AI 服务返回了无效的 JSON 响应。') from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'AI 服务请求失败（HTTP {exc.code}）：{detail}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'无法连接 AI 服务：{exc.reason}') from exc

    try:
        content = result['choices'][0]['message']['content'].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise RuntimeError('AI 服务返回了无法识别的结果。') from exc
    if not content:
        raise RuntimeError('AI 服务返回内容为空。')
    return content


def _extract_text_with_vision(images: List[bytes]) -> str:
    provider, _, _, _ = _llm_settings()
    if provider == 'deepseek':
        raise RuntimeError('当前 DeepSeek 配置不支持信用证图片 OCR；请安装 Tesseract，或切换到支持图片的视觉模型。')

    content: List[Dict[str, Any]] = [{
        'type': 'text',
        'text': '请逐字识别这些信用证页面中的全部文字，保留原有段落、编号、金额、日期和 MT700 字段代码。只输出识别出的原文，不翻译、不总结。',
    }]
    content.extend(
        {
            'type': 'image_url',
            'image_url': {'url': f'data:image/png;base64,{base64.b64encode(image).decode("ascii")}'},
        }
        for image in images
    )
    return _call_chat_completion([{'role': 'user', 'content': content}])


def extract_lc_text(filename: str, file_bytes: bytes) -> str:
    suffix = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
    if suffix == 'pdf':
        try:
            with fitz.open(stream=file_bytes, filetype='pdf') as document:
                page_texts = []
                pages_needing_ocr = []
                for page in document:
                    text = page.get_text().strip()
                    if text:
                        page_texts.append(text)
                    else:
                        image_bytes = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes('png')
                        pages_needing_ocr.append(image_bytes)
                if pages_needing_ocr:
                    try:
                        page_texts.append('\n'.join(
                            pytesseract.image_to_string(Image.open(io.BytesIO(image)), lang='eng+chi_sim').strip()
                            for image in pages_needing_ocr
                        ))
                    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError):
                        page_texts.append(_extract_text_with_vision(pages_needing_ocr))
                return '\n'.join(text for text in page_texts if text)
        except fitz.FileDataError as exc:
            raise ValueError('无法读取该 PDF，请确认文件未损坏且格式正确。') from exc

    if suffix in {'png', 'jpg', 'jpeg'}:
        try:
            return pytesseract.image_to_string(Image.open(io.BytesIO(file_bytes)), lang='eng+chi_sim').strip()
        except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError):
            return _extract_text_with_vision([file_bytes])

    raise ValueError('仅支持 PDF、PNG、JPG 或 JPEG 文件。')


def translate_lc_text(raw_text: str) -> str:
    if not raw_text.strip():
        raise ValueError('没有可翻译的信用证文本。')

    return _call_chat_completion([
        {
            'role': 'system',
            'content': (
                '你是专业的国际贸易跟单和信用证翻译人员。将用户提供的信用证原文完整、准确地翻译成简体中文，'
                '保留原有编号、字段代码、金额、日期、公司名和专有名词；不得省略条款或自行补充内容。'
            ),
        },
        {'role': 'user', 'content': raw_text},
    ])


def analyze_lc_clauses(raw_text: str) -> Dict[str, Any]:
    if not raw_text.strip():
        raise ValueError('没有可分析的信用证文本。')

    response = _call_chat_completion([
        {
            'role': 'system',
            'content': (
                '你是信用证审单和出口单证专家。只依据原文分析，不要推测或补充信用证未写明的要求。'
                '完整找出对受益人不利或执行困难的条款，以及所有单据要求（单据名称、正本份数、'
                '副本份数、内容/签章/认证要求、适用的四单类型）。四单类型只使用 PI、Commercial Invoice、'
                'Packing List、Sales Contract。其他单据也要列出，但 affected_documents 留空。'
                '提取交单期限天数、明确写出的装运后邮寄/寄出天数和寄单说明；原文没有明确写的数值必须返回 null。'
                '必须只返回一个合法 JSON 对象，不要 Markdown。格式：'
                '{"adverse_clauses":[{"risk_level":"高|中|低","clause":"原文条款","translation":"中文翻译",'
                '"issue":"中文风险解释","recommendation":"中文处理建议","affected_documents":["Commercial Invoice"]}],'
                '"document_requirements":[{"document_type":"Commercial Invoice","original_count":2,'
                '"copy_count":2,"requirements":"单据内容、签字、认证等要求","affected_documents":["Commercial Invoice"]}],'
                '"presentation_period_days":21,"dispatch_days_after_shipment":5,"dispatch_instruction":"原文寄单要求"}。'
                '数量必须是非负整数或 null；无要求的列表用空数组，文本用空字符串，未明确的天数用 null。'
            ),
        },
        {'role': 'user', 'content': raw_text},
    ])
    json_match = re.search(r'\{.*\}', response, flags=re.DOTALL)
    if not json_match:
        raise RuntimeError('信用证条款分析结果不是有效 JSON。')
    try:
        result = json.loads(json_match.group(0))
    except json.JSONDecodeError as exc:
        raise RuntimeError('信用证条款分析结果无法解析。') from exc
    if not isinstance(result, dict):
        raise RuntimeError('信用证条款分析结果格式不正确。')

    adverse_clauses = result.get('adverse_clauses', [])
    document_requirements = result.get('document_requirements', [])
    if not isinstance(adverse_clauses, list) or not isinstance(document_requirements, list):
        raise RuntimeError('信用证条款或单据要求结果格式不正确。')

    cleaned_risks = []
    for item in adverse_clauses:
        if not isinstance(item, dict) or not item.get('clause'):
            continue
        level = str(item.get('risk_level', '中'))
        cleaned_risks.append({
            'risk_level': level if level in {'高', '中', '低'} else '中',
            'risk_type': str(item.get('issue', '信用证条款风险')),
            'original_clause_en': str(item.get('clause', '')),
            'clause_translation_cn': str(item.get('translation') or item.get('issue', '')),
            'risk_explanation_cn': str(item.get('issue', '')),
            'suggested_action_cn': str(item.get('recommendation', '')),
            'affected_documents': _clean_affected_documents(item.get('affected_documents')),
        })

    cleaned_requirements = []
    for item in document_requirements:
        if not isinstance(item, dict) or not item.get('document_type'):
            continue
        cleaned_requirements.append({
            'document_type': str(item.get('document_type', '')).strip(),
            'original_count': _non_negative_int(item.get('original_count')),
            'copy_count': _non_negative_int(item.get('copy_count')),
            'special_requirements': str(item.get('requirements', '')).strip(),
            'affected_documents': _clean_affected_documents(item.get('affected_documents')),
        })

    return {
        'adverse_clauses': cleaned_risks,
        'document_requirements': cleaned_requirements,
        'presentation_period_days': _non_negative_int(result.get('presentation_period_days')),
        'dispatch_days_after_shipment': _non_negative_int(result.get('dispatch_days_after_shipment')),
        'dispatch_instruction': str(result.get('dispatch_instruction', '')).strip(),
    }


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _clean_affected_documents(value: Any) -> List[str]:
    allowed = {'PI', 'Commercial Invoice', 'Packing List', 'Sales Contract'}
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item) in allowed]


def parse_lc_text(raw_text: str) -> Dict[str, Any]:
    text = (raw_text or '').strip()
    if not text:
        return {}

    def extract(pattern: str, default: str = '') -> str:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return default
        value = match.group(1).strip()
        return value.strip('"\'\n\r')

    result = {
        'lc_no': extract(r'(?:L/C\s*No\.|LC\s*NO|信用证号|letter\s*of\s*credit\s*no\.?|lc\s*no\.?)[\s:：]*([A-Za-z0-9\-/]+)', 'N/A'),
        'issue_date': extract(r'(?:Issue\s*Date|开证日期|开证日|date\s*of\s*issue)[\s:：]*([0-9]{4}-?[0-9]{1,2}-?[0-9]{1,2})', ''),
        'expiry_date': extract(r'(?:Expiry\s*Date|有效期|expiry)[\s:：]*([0-9]{4}-?[0-9]{1,2}-?[0-9]{1,2})', ''),
        'latest_shipment_date': extract(r'(?:Latest\s*Shipment\s*Date|最迟装运日|latest\s*shipment)[\s:：]*([0-9]{4}-?[0-9]{1,2}-?[0-9]{1,2})', ''),
        'presentation_period': extract(r'(?:Presentation\s*Period|交单期限|presentation\s*period)[\s:：]*([^\n]+)', 'Within 21 days after shipment'),
        'issuing_bank': extract(r'(?:Issuing\s*Bank|开证行|issuing\s*bank)[\s:：]*([^\n]+)', 'N/A'),
        'applicant': extract(r'(?:Applicant|申请人|applicant)[\s:：]*([^\n]+)', 'N/A'),
        'beneficiary': extract(r'(?:Beneficiary|受益人|beneficiary)[\s:：]*([^\n]+)', 'N/A'),
        'lc_amount': extract(r'(?:Amount|金额|LC\s*Amount)[\s:：]*([0-9,]+(?:\.\d+)?)', '0'),
        'currency': extract(r'(?:Currency|币别|currency)[\s:：]*([A-Z]{3})', 'USD'),
        'tolerance_percentage': extract(r'(?:Tolerance|溢短装|tolerance)[\s:：]*([0-9]+(?:\.\d+)?)', '0'),
        'loading_port': extract(r'(?:Loading\s*Port|起运港|loading\s*port)[\s:：]*([^\n]+)', ''),
        'discharge_port': extract(r'(?:Discharge\s*Port|目的港|port\s*of\s*discharge|discharge\s*port)[\s:：]*([^\n]+)', ''),
        'transshipment_allowed': 'Yes' if re.search(r'(?:transshipment\s*allowed|允许转运|转运)', text, flags=re.IGNORECASE) else 'No',
        'partial_shipment_allowed': 'Yes' if re.search(r'(?:partial\s*shipment\s*allowed|允许分批装运|分批装运)', text, flags=re.IGNORECASE) else 'No',
        'goods_description': extract(r'(?:Goods\s*Description|货物描述|description\s*of\s*goods)[\s:：]*([^\n]+(?:\n[^\n]+){0,5})', 'N/A'),
        'incoterm': extract(r'(?:Incoterms|贸易条款|incoterm)[\s:：]*([A-Z]+\s*[0-9]*)', 'FOB'),
        'documents_required': [],
    }

    result['lc_amount'] = result['lc_amount'].replace(',', '')
    try:
        result['lc_amount'] = float(result['lc_amount'])
    except ValueError:
        result['lc_amount'] = 0.0
    try:
        result['tolerance_percentage'] = float(result['tolerance_percentage'])
    except ValueError:
        result['tolerance_percentage'] = 0.0

    if 'documents_required' in result:
        result['documents_required_json'] = json.dumps(result['documents_required'], ensure_ascii=False)

    return result


def build_lc_summary(parsed: Dict[str, Any]) -> str:
    if not parsed:
        return '无可用信用证内容。'
    lines = [
        '信用证中文精简摘要',
        f"信用证号：{parsed.get('lc_no', 'N/A')}",
        f"开证日期：{parsed.get('issue_date', 'N/A')}",
        f"有效期：{parsed.get('expiry_date', 'N/A')}",
        f"最迟装运日：{parsed.get('latest_shipment_date', 'N/A')}",
        f"交单期限：{parsed.get('presentation_period', 'N/A')}",
        f"金额：{parsed.get('lc_amount', '0')} {parsed.get('currency', 'USD')}",
        f"溢短装：{parsed.get('tolerance_percentage', 0)}%",
        f"起运港：{parsed.get('loading_port', 'N/A')}",
        f"目的港：{parsed.get('discharge_port', 'N/A')}",
        f"货物描述：{parsed.get('goods_description', 'N/A')}",
        f"贸易条款：{parsed.get('incoterm', 'N/A')}",
    ]
    requirements = parsed.get('documents_required') or []
    if requirements:
        lines.append('单据份数要求：')
        for item in requirements:
            counts = []
            if item.get('original_count') is not None:
                counts.append(f"{item['original_count']}份正本")
            if item.get('copy_count') is not None:
                counts.append(f"{item['copy_count']}份副本")
            line = f"- {item.get('document_type', '单据')}：{'、'.join(counts) or '原文未明确'}"
            details = item.get('special_requirements') or item.get('requirements', '')
            if details:
                line += f'；{details}'
            lines.append(line)
    else:
        lines.append('单据份数要求：请核对信用证全文，当前未识别到明确要求。')
    return '\n'.join(lines)


def get_lc_by_order(order_id: int, owner_id: int | None = None) -> Dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM letters_of_credit
            WHERE order_id = ? AND is_approved = 1
              AND (? IS NULL OR user_id = ?)
            ORDER BY id DESC LIMIT 1
            """,
            (order_id, owner_id, owner_id),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


def list_approved_unlinked_lcs(owner_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, lc_no, applicant, currency, lc_amount, expiry_date, approved_at
            FROM letters_of_credit
            WHERE user_id = ? AND is_approved = 1 AND order_id IS NULL
            ORDER BY approved_at DESC, id DESC
            """,
            (owner_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_lc_record(
    order_id: int | None,
    parsed: Dict[str, Any],
    raw_text: str,
    risk_report_json: List[Dict[str, Any]] | str | None = None,
    *,
    translation_text: str = '',
    owner_id: int | None = None,
    approved_by: int | None = None,
) -> int:
    documents_required = parsed.get('documents_required') or []
    risks = _risk_items(
        risk_report_json
        if risk_report_json is not None
        else parsed.get('adverse_clauses')
    )
    payload = {
        'order_id': order_id,
        'lc_no': parsed.get('lc_no', 'N/A'),
        'issuing_bank': parsed.get('issuing_bank', 'N/A'),
        'applicant': parsed.get('applicant', 'N/A'),
        'beneficiary': parsed.get('beneficiary', 'N/A'),
        'lc_amount': float(str(parsed.get('lc_amount', 0) or 0).replace(',', '')),
        'currency': parsed.get('currency', 'USD'),
        'tolerance_percentage': float(str(parsed.get('tolerance_percentage', 0) or 0).replace(',', '')),
        'issue_date': parsed.get('issue_date', ''),
        'expiry_date': parsed.get('expiry_date', ''),
        'latest_shipment_date': parsed.get('latest_shipment_date', ''),
        'presentation_period': parsed.get('presentation_period', ''),
        'loading_port': parsed.get('loading_port', ''),
        'discharge_port': parsed.get('discharge_port', ''),
        'transshipment_allowed': 1 if str(parsed.get('transshipment_allowed', 'No')).lower() in ('yes', 'true', '1') else 0,
        'partial_shipment_allowed': 1 if str(parsed.get('partial_shipment_allowed', 'No')).lower() in ('yes', 'true', '1') else 0,
        'goods_description': parsed.get('goods_description', ''),
        'documents_required_json': json.dumps(documents_required, ensure_ascii=False),
        'raw_text': raw_text,
        'parsed_json': json.dumps(parsed, ensure_ascii=False),
        'risk_report_json': json.dumps(risk_report_json, ensure_ascii=False) if risk_report_json is not None else '[]',
    }
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO letters_of_credit (
                order_id, lc_no, issuing_bank, applicant, beneficiary, lc_amount, currency,
                tolerance_percentage, issue_date, expiry_date, latest_shipment_date, presentation_period,
                loading_port, discharge_port, transshipment_allowed, partial_shipment_allowed,
                goods_description, documents_required_json, raw_text, parsed_json, risk_report_json,
                user_id, translation_text, is_approved, approved_at, approved_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1,
                      CURRENT_TIMESTAMP, ?)
            """,
            (
                payload['order_id'],
                payload['lc_no'],
                payload['issuing_bank'],
                payload['applicant'],
                payload['beneficiary'],
                payload['lc_amount'],
                payload['currency'],
                payload['tolerance_percentage'],
                payload['issue_date'],
                payload['expiry_date'],
                payload['latest_shipment_date'],
                payload['presentation_period'],
                payload['loading_port'],
                payload['discharge_port'],
                payload['transshipment_allowed'],
                payload['partial_shipment_allowed'],
                payload['goods_description'],
                payload['documents_required_json'],
                payload['raw_text'],
                payload['parsed_json'],
                payload['risk_report_json'],
                owner_id,
                translation_text,
                approved_by,
            ),
        )
        _insert_lc_risks(conn, int(cursor.lastrowid), risks)
        conn.commit()
        return int(cursor.lastrowid)


def bind_lc_to_order(order_id: int, lc_record: Dict[str, Any], owner_id: int | None = None) -> Dict[str, Any]:
    order = get_order_by_id(order_id, owner_id)
    if not order:
        raise ValueError('订单不存在或不属于当前业务员。')

    presentation_deadline = _parse_iso_date(lc_record.get('presentation_deadline'))
    if not presentation_deadline:
        shipment_date = _parse_iso_date(order.get('shipment_date'))
        presentation_days = lc_record.get('presentation_period_days')
        try:
            presentation_days = int(presentation_days)
        except (TypeError, ValueError):
            presentation_days = _extract_period_days(
                presentation_days or lc_record.get('presentation_period', '')
            )
        if shipment_date and presentation_days is not None and presentation_days >= 0:
            deadline = shipment_date + timedelta(days=presentation_days)
            expiry_date = _parse_iso_date(lc_record.get('expiry_date') or order.get('lc_expiry_date'))
            if expiry_date and expiry_date < deadline:
                deadline = expiry_date
            presentation_deadline = deadline.isoformat()

    updated = {
        'order_no': order['order_no'],
        'customer_id': order['customer_id'],
        'product_id': order['product_id'],
        'quantity': order['quantity'],
        'unit': order['unit'],
        'unit_price': order['unit_price'],
        'currency': order['currency'],
        'loading_port': lc_record.get('loading_port') or order['loading_port'],
        'destination_port': lc_record.get('discharge_port') or order['destination_port'],
        'incoterm': lc_record.get('incoterm') or order['incoterm'],
        'payment_terms': order['payment_terms'],
        'shipment_date': order['shipment_date'],
        'latest_shipment_date': lc_record.get('latest_shipment_date') or order['latest_shipment_date'],
        'presentation_deadline': presentation_deadline or order['presentation_deadline'],
        'lc_expiry_date': lc_record.get('expiry_date') or order['lc_expiry_date'],
        'marks_and_numbers': order['marks_and_numbers'],
        'special_requirements': order['special_requirements'],
        'status': order['status'],
    }
    if lc_record.get('lc_amount') and not order['total_amount']:
        updated['total_amount'] = float(lc_record['lc_amount'])
    update_order(order_id, updated)
    return updated


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _extract_period_days(value: Any) -> int | None:
    match = re.search(r'(\d+)\s*(?:days?|天)', str(value or ''), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def attach_lc_to_order(lc_id: int, order_id: int, owner_id: int) -> None:
    with get_connection() as conn:
        lc = conn.execute(
            'SELECT * FROM letters_of_credit WHERE id = ? AND user_id = ? AND is_approved = 1 AND order_id IS NULL',
            (lc_id, owner_id),
        ).fetchone()
        if lc is None:
            raise ValueError('信用证不存在、未确认或已关联其他订单。')
        order = conn.execute(
            'SELECT id FROM orders WHERE id = ? AND user_id = ?',
            (order_id, owner_id),
        ).fetchone()
        if order is None:
            raise ValueError('订单不存在或不属于当前业务员。')
        conn.execute(
            'UPDATE letters_of_credit SET order_id = ? WHERE id = ? AND user_id = ? AND order_id IS NULL',
            (order_id, lc_id, owner_id),
        )
        conn.execute(
            "UPDATE orders SET workflow_status = 'credit_confirmed' WHERE id = ? AND user_id = ?",
            (order_id, owner_id),
        )
        conn.commit()
    record = dict(lc)
    parsed = json.loads(record['parsed_json'] or '{}')
    record.update(parsed)
    bind_lc_to_order(order_id, record, owner_id)
