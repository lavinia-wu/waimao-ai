from __future__ import annotations

import re
from typing import Any, Dict, List


RISK_RULES = [
    {
        'risk_type': '客户检验证条款',
        'risk_level': '高',
        'keywords': ['certificate of inspection', 'customer inspection', 'inspection certificate', '检验证书'],
        'suggested_action_cn': '要求申请人明确检验机构和检验标准，避免被要求由客户指定机构检验；必要时要求更改为独立第三方检验。'
    },
    {
        'risk_type': '客户签字确认条款',
        'risk_level': '高',
        'keywords': ['customer signature', 'customer confirmation', '签字确认', 'signed by buyer'],
        'suggested_action_cn': '要求删除客户签字确认、客户审批等非UCP600惯例要求，明确凭单据审单即可结算。'
    },
    {
        'risk_type': '境外有效期或交单期',
        'risk_level': '高',
        'keywords': ['outside china', 'overseas', 'in london', 'in new york', '境外', '海外'],
        'suggested_action_cn': '尽量要求在我国境内有效，避免因时差和地理因素导致交单失败，必须提前安排航运与交单。'
    },
    {
        'risk_type': '限制议付条款',
        'risk_level': '高',
        'keywords': ['restricted negotiation', 'negotiation restricted', '议付受限制', 'not negotiable'],
        'suggested_action_cn': '要求取消限制议付，确保银行可按正常UCP600审单议付。'
    },
    {
        'risk_type': '模糊货描或可随意拒付条款',
        'risk_level': '高',
        'keywords': ['goods description vague', 'as per buyer', 'subject to buyer approval', '可随意拒付', '模糊货描'],
        'suggested_action_cn': '明确商品名称、规格、HS编码及数量，尽量使用准确、可验证的货物描述。'
    },
    {
        'risk_type': '不合理溢短装',
        'risk_level': '中',
        'keywords': ['tolerance', '溢短装', 'more or less'],
        'suggested_action_cn': '核实溢短装比例是否合理，必要时要求开证行确认或调整装运方案。'
    },
    {
        'risk_type': '苛刻交单条件',
        'risk_level': '中',
        'keywords': ['documents presented within', 'presentation period', '交单条件', 'strict'],
        'suggested_action_cn': '提前判断航运和交单窗口，确保单据提前准备并留出合规审单时间。'
    },
    {
        'risk_type': '提单收货人、通知人、背书要求异常',
        'risk_level': '高',
        'keywords': ['shipper', 'notify party', 'endorsement', '背书', '通知人', '收货人'],
        'suggested_action_cn': '提前核对提单抬头、通知人和背书要求，避免提单不符合开证要求。'
    },
    {
        'risk_type': '特定机构认证',
        'risk_level': '高',
        'keywords': ['certified by', 'specific institution', '特定机构认证', 'must be certified'],
        'suggested_action_cn': '尽量避免指定检测机构或认证机构，要求银行可接受常规单据。'
    },
    {
        'risk_type': '指定检验机构',
        'risk_level': '高',
        'keywords': ['inspection by applicant', 'applicant designated inspection', '指定检验机构', '申请人指定'],
        'suggested_action_cn': '确认检验机构是否可接受并尽量转为独立第三方检测，避免因机构限定导致交单失败。'
    },
    {
        'risk_type': '信用证修改、转让、撤销风险',
        'risk_level': '高',
        'keywords': ['transfer', 'amendment', 'revocation', '转让', '修改', '撤销'],
        'suggested_action_cn': '要求确认信用证是否可能转让或修改，必要时与开证行和申请人同步沟通。'
    },
    {
        'risk_type': '不符合UCP600惯例',
        'risk_level': '高',
        'keywords': ['non-ucp600', 'not in compliance with ucp', '不符合UCP600', '不符合惯例'],
        'suggested_action_cn': '对照UCP600进行审查，删除非惯例条款并尽快获取开证行确认。'
    },
]


def analyze_lc_risks(raw_text: str) -> List[Dict[str, Any]]:
    text = raw_text or ''
    findings: List[Dict[str, Any]] = []
    lower_text = text.lower()
    for rule in RISK_RULES:
        matched = False
        for keyword in rule['keywords']:
            if keyword.lower() in lower_text:
                matched = True
                break
        if matched:
            findings.append({
                'risk_level': rule['risk_level'],
                'risk_type': rule['risk_type'],
                'original_clause_en': ', '.join(rule['keywords'][:3]),
                'clause_translation_cn': rule['risk_type'],
                'risk_explanation_cn': f'文本中存在 {rule["risk_type"]} 特征，可能造成审单、交单或收汇风险。',
                'suggested_action_cn': rule['suggested_action_cn'],
            })
    return findings
