from __future__ import annotations

from typing import Any, Dict, List


def compare_invoice_vs_lc(invoice: Dict[str, Any], lc: Dict[str, Any]) -> List[Dict[str, Any]]:
    mismatches = []
    field_map = {
        'goods_description': ('goods_description', 'goods_description'),
        'amount': ('total_amount', 'lc_amount'),
        'currency': ('currency', 'currency'),
        'quantity': ('quantity', 'quantity'),
        'incoterm': ('incoterm', 'incoterm'),
        'loading_port': ('loading_port', 'loading_port'),
        'discharge_port': ('destination_port', 'discharge_port'),
    }
    for label, (invoice_key, lc_key) in field_map.items():
        invoice_value = invoice.get(invoice_key)
        lc_value = lc.get(lc_key)
        if str(invoice_value) != str(lc_value):
            mismatches.append({
                'field': label,
                'lc_value': lc_value,
                'document_value': invoice_value,
                'recommendation': '请核对并调整单据内容与信用证一致。',
            })
    return mismatches


def compare_packing_list_vs_invoice(pl: Dict[str, Any], invoice: Dict[str, Any]) -> List[Dict[str, Any]]:
    mismatches = []
    for key in ['product_name_en', 'quantity', 'gross_weight', 'net_weight', 'volume', 'marks_and_numbers']:
        pl_value = pl.get(key)
        inv_value = invoice.get(key)
        if str(pl_value) != str(inv_value):
            mismatches.append({
                'field': key,
                'lc_value': inv_value,
                'document_value': pl_value,
                'recommendation': '请核对箱单与发票一致，避免交单时被拒。',
            })
    return mismatches


def compare_packing_list_vs_lc(pl: Dict[str, Any], lc: Dict[str, Any]) -> List[Dict[str, Any]]:
    mismatches = []
    allowed_tolerance = float(lc.get('tolerance_percentage', 0) or 0)
    gross_weight = float(pl.get('gross_weight', 0) or 0)
    total_lc_weight = float(lc.get('max_gross_weight', 0) or 0)
    if total_lc_weight and gross_weight > total_lc_weight * (1 + allowed_tolerance / 100):
        mismatches.append({
            'field': 'gross_weight',
            'lc_value': total_lc_weight,
            'document_value': gross_weight,
            'recommendation': '重量超出信用证规定范围，请调整装箱或说明。',
        })
    return mismatches


def compare_contract_vs_invoice(contract: Dict[str, Any], invoice: Dict[str, Any]) -> List[Dict[str, Any]]:
    mismatches = []
    for key in ['customer_name_en', 'product_name_en', 'total_amount', 'incoterm', 'payment_terms']:
        if str(contract.get(key)) != str(invoice.get(key)):
            mismatches.append({
                'field': key,
                'lc_value': contract.get(key),
                'document_value': invoice.get(key),
                'recommendation': '合同与发票需保持一致，避免后续账务纠纷。',
            })
    return mismatches


def run_consistency_checks(order_context: Dict[str, Any], lc_context: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    invoice = {
        'goods_description': order_context.get('goods_description') or order_context.get('product_name_en'),
        'total_amount': order_context.get('total_amount'),
        'currency': order_context.get('currency'),
        'quantity': order_context.get('quantity'),
        'incoterm': order_context.get('incoterm'),
        'loading_port': order_context.get('loading_port'),
        'destination_port': order_context.get('destination_port'),
        'product_name_en': order_context.get('product_name_en'),
        'gross_weight': order_context.get('gross_weight'),
        'net_weight': order_context.get('net_weight'),
        'volume': order_context.get('volume'),
        'marks_and_numbers': order_context.get('marks_and_numbers'),
        'customer_name_en': order_context.get('customer_name_en'),
        'payment_terms': order_context.get('payment_terms'),
    }
    packing_list = {
        'product_name_en': order_context.get('product_name_en'),
        'quantity': order_context.get('quantity'),
        'gross_weight': order_context.get('gross_weight'),
        'net_weight': order_context.get('net_weight'),
        'volume': order_context.get('volume'),
        'marks_and_numbers': order_context.get('marks_and_numbers'),
    }
    contract = {
        'customer_name_en': order_context.get('customer_name_en'),
        'product_name_en': order_context.get('product_name_en'),
        'total_amount': order_context.get('total_amount'),
        'incoterm': order_context.get('incoterm'),
        'payment_terms': order_context.get('payment_terms'),
    }

    return {
        'invoice_vs_lc': compare_invoice_vs_lc(invoice, lc_context),
        'packing_vs_invoice': compare_packing_list_vs_invoice(packing_list, invoice),
        'packing_vs_lc': compare_packing_list_vs_lc(packing_list, lc_context),
        'contract_vs_invoice': compare_contract_vs_invoice(contract, invoice),
    }
