"""信用证工作台：只读聚合"待办与概况"。

本模块只做统计与排序，不复用会改变现有风险算法、期限计算和数据库结构的东西：
- 高风险判定口径与 modules.document_validation._unresolved_high_risk_blockers 一致，
  保证页面统计与 PDF 服务端门禁不会给出相反结论；
- 日期、字段、单据要求的校验仍调用 lc_confirmation / lc_deadlines 的既有函数。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from modules.lc_confirmation import FIELD_GROUPS
from modules.lc_deadlines import parse_date
from modules.lc_parser import RESOLVED_RISK_STATUSES

HIGH_RISK_LEVELS = {'高', 'high', 'critical'}
# 待办排序：数字越小越靠前
PRIORITY_ORDER = {'必须处理': 0, '需确认': 1, '一般提示': 2}

ALL_FIELD_INDEX = [
    (group_title, field, label, kind, required)
    for group_title, fields in FIELD_GROUPS
    for field, label, kind, required, _aliases in fields
]
REQUIRED_FIELD_INDEX = [
    (group_title, field, label)
    for group_title, field, label, _kind, required in ALL_FIELD_INDEX
    if required
]


def lc_parsed_values(record: Dict[str, Any] | None) -> Dict[str, Any]:
    """从已保存的信用证记录中取出结构化字段值（只读，不做任何写入）。"""
    raw = (record or {}).get('parsed_json')
    try:
        parsed = json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() in {'', '待核对'}:
        return True
    return False


def _to_count(value: Any) -> int | None:
    if value is None or value == '':
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _first_sentence(text: Any, limit: int = 60) -> str:
    sentence = str(text or '').strip()
    if not sentence:
        return ''
    for part in sentence.replace('。', '\n').split('\n'):
        if part.strip():
            sentence = part.strip()
            break
    return sentence if len(sentence) <= limit else sentence[:limit] + '…'


def is_unhandled_risk(risk: Dict[str, Any]) -> bool:
    """未处理高风险：高风险且未标记已确认可接受/已整改。

    与 PDF 门禁的判定口径一致，避免页面与服务端给出相反结论。
    """
    level = str(risk.get('risk_level') or '').strip().casefold()
    if level not in HIGH_RISK_LEVELS:
        return False
    return str(risk.get('handling_status') or '未处理') not in RESOLVED_RISK_STATUSES


def unhandled_high_risks(risks: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    return [dict(risk) for risk in risks or [] if is_unhandled_risk(risk)]


def risk_target(risk: Dict[str, Any]) -> str:
    """待办项的定位键：已保存风险用记录 ID，未保存风险用条款内容哈希。

    保证多条待办互不冲突，页面据此展开对应的处理区域。
    """
    identity = risk.get('id')
    if identity is not None:
        return f'risk_{identity}'
    clause = str(risk.get('original_clause_en') or '')
    return f'risk_{hashlib.sha256(clause.encode("utf-8")).hexdigest()[:12]}'


def normalize_document_requirements(rows: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    """统一单据要求行的字段名：编辑器行（中文列名）与信用证结构化行（英文字段名）均可。"""
    normalized = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        normalized.append({
            'document_type': str(row.get('单据类型') or row.get('document_type') or '').strip(),
            'original_count': _to_count(
                row.get('正本份数') if '正本份数' in row else row.get('original_count')
            ),
            'copy_count': _to_count(
                row.get('副本份数') if '副本份数' in row else row.get('copy_count')
            ),
            'requirements': str(
                row.get('特殊要求')
                or row.get('special_requirements')
                or row.get('requirements')
                or ''
            ),
        })
    return normalized


def unresolved_document_requirements(
    requirements: List[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    """待核对单据要求：类型缺失或份数未明确。"""
    pending = []
    for index, item in enumerate(normalize_document_requirements(requirements)):
        document_type = item['document_type']
        original = item['original_count']
        copies = item['copy_count']
        if not document_type:
            reason = '单据类型未识别，需人工核对原文后补充'
        elif original is None and copies is None:
            reason = '正本与副本份数均未明确，需人工核对原文'
        elif original is None or copies is None:
            reason = '正本或副本份数未明确，需人工核对原文'
        else:
            continue
        pending.append({
            'index': index,
            'document_type': document_type or f'第 {index + 1} 行',
            'reason': reason,
        })
    return pending


def pending_fields(
    field_values: Dict[str, Any] | None,
    confirmed_groups: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """缺失或待核对的关键字段。

    已人工确认的分组不再计入；仅打开页面不会让字段变成已确认。
    """
    field_values = field_values or {}
    confirmed_groups = set(confirmed_groups or [])
    pending = []
    for group_title, field, label, kind, required in ALL_FIELD_INDEX:
        if group_title in confirmed_groups:
            continue
        value = field_values.get(field)
        if required and _is_blank(value):
            reason = '必填字段缺失，需人工确认'
        elif kind == 'date' and not _is_blank(value) and parse_date(value) is None:
            reason = f'日期“{value}”无法识别，需人工确认'
        elif kind == 'boolean' and _is_blank(value):
            reason = '原文未明确，需人工核对后确认'
        else:
            continue
        pending.append({
            'group': group_title,
            'field': field,
            'label': label,
            'reason': reason,
        })
    return pending


def blocking_reasons(consistency: Dict[str, Any] | None) -> List[str]:
    """PDF 阻断原因摘要：只取与服务端门禁同口径的阻断项（error + high）。"""
    if not consistency:
        return []
    reasons = []
    for item in consistency.get('blockers') or []:
        if item.get('status') != 'error' or item.get('severity') != 'high':
            continue
        reasons.append(
            f"{item.get('field') or '一致性阻断'}："
            + '；'.join(item.get('reasons') or [])
        )
    return reasons


def build_pending_summary(
    *,
    risks: List[Dict[str, Any]] | None = None,
    field_values: Dict[str, Any] | None = None,
    confirmed_groups: List[str] | None = None,
    document_requirements: List[Dict[str, Any]] | None = None,
    consistency: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """处理概况：全部数字来自真实状态，不含"已查看即已处理"。"""
    open_high_risks = unhandled_high_risks(risks)
    fields = pending_fields(field_values, confirmed_groups)
    documents = unresolved_document_requirements(document_requirements)
    blockers = blocking_reasons(consistency)
    return {
        'open_high_risk_count': len(open_high_risks),
        'pending_field_count': len(fields),
        'pending_document_count': len(documents),
        'blocking_count': len(blockers),
        'blocking_reasons': blockers,
        'has_consistency': consistency is not None,
        'total': len(open_high_risks) + len(fields) + len(documents) + len(blockers),
    }


def build_pending_items(
    *,
    risks: List[Dict[str, Any]] | None = None,
    field_values: Dict[str, Any] | None = None,
    confirmed_groups: List[str] | None = None,
    document_requirements: List[Dict[str, Any]] | None = None,
    consistency: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """按业务优先级排序的待办清单。每条只带标题、优先级、一句话、状态与依据。"""
    items: List[Dict[str, Any]] = []

    for risk in unhandled_high_risks(risks):
        items.append({
            'kind': 'high_risk',
            'target': risk_target(risk),
            'priority': '必须处理',
            'title': f"高风险条款 · {risk.get('risk_type') or '信用证条款风险'}",
            'summary': _first_sentence(risk.get('risk_explanation_cn'))
            or '该条款可能影响交单，需核对原文后处理。',
            'status': str(risk.get('handling_status') or '未处理'),
            'evidence': {
                '英文原文': risk.get('original_clause_en') or '—',
                '中文翻译': risk.get('clause_translation_cn') or '—',
                '风险解释': risk.get('risk_explanation_cn') or '—',
                '整改建议': risk.get('suggested_action_cn') or '—',
                '受影响单据': ', '.join(
                    risk.get('affected_documents') or []
                ) if isinstance(risk.get('affected_documents'), list) else '待确认',
            },
        })

    for field in pending_fields(field_values, confirmed_groups):
        items.append({
            'kind': 'field',
            'target': f"field_{field['field']}",
            'priority': '需确认',
            'title': f"关键字段 · {field['label']}",
            'summary': field['reason'],
            'status': '待人工确认',
            'evidence': {'所属分组': field['group'], '字段来源': '信用证原文及 AI 识别结果'},
        })

    for document in unresolved_document_requirements(document_requirements):
        items.append({
            'kind': 'document',
            'target': 'documents',
            'priority': '需确认',
            'title': f"单据要求 · {document['document_type']}",
            'summary': document['reason'],
            'status': '待人工核对',
            'evidence': {'字段来源': '信用证原文及 AI 条款分析'},
        })

    for reason in blocking_reasons(consistency):
        items.append({
            'kind': 'consistency',
            'target': 'consistency',
            'priority': '必须处理',
            'title': '一致性校验阻断',
            'summary': reason,
            'status': '阻止 PDF 生成',
            'evidence': {'字段来源': '最新一次一致性校验结果'},
        })

    items.sort(key=lambda item: PRIORITY_ORDER.get(item['priority'], 1))
    return items
