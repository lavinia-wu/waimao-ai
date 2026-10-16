from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from database.db import get_connection
from config.settings import settings
from services.excel_service import (
    export_document_excel,
    get_excel_template_sheets as read_excel_template_sheets,
    list_excel_templates as get_excel_templates,
)
from services.word_service import ensure_default_template, export_document_word, list_word_templates as get_word_templates


DOCUMENT_TYPES = [
    'PI',
    'Commercial Invoice',
    'Packing List',
    'Sales Contract',
]


def _filename_part(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' ._') or '未命名'


def get_order_output_dir(order_id: int) -> Path:
    data = get_order_document_context(order_id)
    sequence = int(data['_system_order_sequence'])
    customer_name = data.get('customer_name_cn') or data.get('customer_name_en') or '客户'
    product_name = data.get('product_name_en') or data.get('product_name_cn') or '产品'
    folder_name = f'{sequence:03d}{_filename_part(str(customer_name).strip())}{_filename_part(str(product_name).strip())}'
    return settings.outputs_dir / folder_name


def ensure_default_templates() -> Dict[str, str]:
    settings.templates_dir.mkdir(parents=True, exist_ok=True)
    generated = {}
    for doc_type in DOCUMENT_TYPES:
        generated[doc_type] = ensure_default_template(doc_type)
    return generated


def get_order_document_context(order_id: int) -> Dict[str, Any]:
    with get_connection() as conn:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if order is None:
            raise ValueError('订单不存在')
        customer = conn.execute('SELECT * FROM customers WHERE id = ?', (order['customer_id'],)).fetchone()
        product = conn.execute('SELECT * FROM products WHERE id = ?', (order['product_id'],)).fetchone()
        lc = conn.execute(
            'SELECT * FROM letters_of_credit WHERE order_id = ? AND is_approved = 1 ORDER BY id DESC LIMIT 1',
            (order_id,),
        ).fetchone()

    order_dict = dict(order) if order else {}
    customer_dict = dict(customer) if customer else {}
    product_dict = dict(product) if product else {}
    lc_dict = dict(lc) if lc else {}
    try:
        lc_parsed = json.loads(lc_dict.get('parsed_json') or '{}')
    except json.JSONDecodeError:
        lc_parsed = {}
    try:
        lc_requirements = json.loads(lc_dict.get('documents_required_json') or '[]')
    except json.JSONDecodeError:
        lc_requirements = []
    lc_no = lc_dict.get('lc_no', '')
    lc_issue_date = lc_dict.get('issue_date', '')

    quantity = float(order_dict.get('quantity') or 0)
    unit_price = float(order_dict.get('unit_price') or product_dict.get('unit_price') or 0)
    gross = float(product_dict.get('gross_weight_per_carton') or 0)
    net = float(product_dict.get('net_weight_per_carton') or 0)
    volume = float(product_dict.get('carton_volume_cbm') or 0)
    total_amount = quantity * unit_price
    gross_total = quantity * gross
    net_total = quantity * net
    volume_total = quantity * volume

    return {
        'company_name': 'Shanghai Export Trade Co., Ltd.',
        'company_address': 'Shanghai, China',
        'company_phone': '+86 21 8888 8888',
        'company_email': 'sales@exporttrade.com',
        'customer_name_en': customer_dict.get('customer_name_en', ''),
        'customer_name_cn': customer_dict.get('customer_name_cn', ''),
        '_system_order_sequence': int(order_dict['id']),
        'customer_address': customer_dict.get('company_address', ''),
        'contact_person': customer_dict.get('contact_person', ''),
        'email': customer_dict.get('email', ''),
        'phone': customer_dict.get('phone', ''),
        'destination_port': order_dict.get('destination_port', customer_dict.get('destination_port', '')),
        'loading_port': order_dict.get('loading_port', ''),
        'incoterm': order_dict.get('incoterm', ''),
        'payment_terms': order_dict.get('payment_terms', ''),
        'product_name_en': product_dict.get('product_name_en', ''),
        'product_name_cn': product_dict.get('product_name_cn', ''),
        'product_code': product_dict.get('hs_code', ''),
        'hs_code': product_dict.get('hs_code', ''),
        'product_specification': product_dict.get('specification', ''),
        'packaging_method': product_dict.get('packaging_method', ''),
        'product_description_en': product_dict.get('product_description_en', ''),
        'quantity': quantity,
        'unit': order_dict.get('unit', 'carton'),
        'unit_price': unit_price,
        'currency': order_dict.get('currency', product_dict.get('currency', 'USD')),
        'total_amount': total_amount,
        'gross_weight': gross_total,
        'net_weight': net_total,
        'volume': volume_total,
        'marks_and_numbers': order_dict.get('marks_and_numbers', ''),
        'remarks': order_dict.get('special_requirements', ''),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'document_no': f"{order_dict.get('order_no', 'ORDER')}-{datetime.now().strftime('%Y%m%d')}",
        'order_no': order_dict.get('order_no', 'ORDER'),
        'shipment_date': order_dict.get('shipment_date', ''),
        'latest_shipment_date': order_dict.get('latest_shipment_date', ''),
        'presentation_deadline': order_dict.get('presentation_deadline', ''),
        'lc_expiry_date': lc_dict.get('expiry_date') or order_dict.get('lc_expiry_date', ''),
        'lc_no': lc_no,
        'lc_issue_date': lc_issue_date,
        '_lc_document_requirements': lc_requirements if isinstance(lc_requirements, list) else [],
        '_lc_adverse_clauses': lc_parsed.get('adverse_clauses', []),
    }


def _document_lc_instructions(data: Dict[str, Any], document_type: str) -> str:
    instructions = []
    for item in data.get('_lc_document_requirements', []):
        if not isinstance(item, dict):
            continue
        affected = item.get('affected_documents') or []
        if document_type not in affected and _normalize_document_type(item.get('document_type', '')) != document_type:
            continue
        counts = []
        if item.get('original_count') is not None:
            counts.append(f"{item['original_count']}份正本")
        if item.get('copy_count') is not None:
            counts.append(f"{item['copy_count']}份副本")
        line = f"{item.get('document_type', document_type)}：{'、'.join(counts) or '份数按信用证要求'}"
        details = item.get('special_requirements') or item.get('requirements', '')
        if details:
            line += f'；{details}'
        instructions.append(line)

    for item in data.get('_lc_adverse_clauses', []):
        if not isinstance(item, dict) or document_type not in (item.get('affected_documents') or []):
            continue
        clause = item.get('clause_translation_cn') or item.get('risk_explanation_cn', '')
        if clause:
            instructions.append(f"注意信用证条款（{item.get('risk_level', '中')}）：{clause}")
        recommendation = item.get('suggested_action_cn')
        if recommendation:
            instructions.append(f'处理建议：{recommendation}')

    return '\n'.join(instructions)


def get_document_lc_instructions(order_id: int, document_type: str) -> str:
    data = get_order_document_context(order_id)
    return _document_lc_instructions(data, document_type)


def _normalize_document_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {'pi', 'proforma invoice', '形式发票'}:
        return 'PI'
    if normalized in {'commercial invoice', 'invoice', '发票', '商业发票'}:
        return 'Commercial Invoice'
    if normalized in {'packing list', 'packing', '装箱单'}:
        return 'Packing List'
    if normalized in {'sales contract', 'contract', '销售合同'}:
        return 'Sales Contract'
    return value


def _save_document_record(
    order_id: int,
    document_type: str,
    data: Dict[str, Any],
    word_path: str | None,
    pdf_path: str | None,
    excel_path: str | None,
    output_dir: Path,
) -> None:
    stale_paths = []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, file_path_word, file_path_pdf, file_path_excel
            FROM documents
            WHERE order_id = ? AND document_type = ?
            ORDER BY id DESC
            """,
            (order_id, document_type),
        ).fetchall()
        keep_id = rows[0]['id'] if rows else None
        for row in rows:
            stale_paths.extend(
                path for path in (row['file_path_word'], row['file_path_pdf'], row['file_path_excel'])
                if path
            )
        if keep_id is None:
            conn.execute(
                """
                INSERT INTO documents (
                    order_id, document_type, document_no, issue_date,
                    file_path_word, file_path_pdf, file_path_excel, content_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    document_type,
                    data['document_no'],
                    data['date'],
                    word_path,
                    pdf_path,
                    excel_path,
                    json.dumps(data, ensure_ascii=False, default=str),
                ),
            )
        else:
            conn.execute(
                """
                UPDATE documents
                SET document_no = ?, issue_date = ?, file_path_word = ?,
                    file_path_pdf = ?, file_path_excel = ?, content_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    data['document_no'],
                    data['date'],
                    word_path,
                    pdf_path,
                    excel_path,
                    json.dumps(data, ensure_ascii=False, default=str),
                    keep_id,
                ),
            )
            conn.executemany(
                'DELETE FROM documents WHERE id = ?',
                [(row['id'],) for row in rows[1:]],
            )
        conn.execute(
            "UPDATE orders SET workflow_status = 'documents_in_progress' WHERE id = ?",
            (order_id,),
        )
        conn.commit()

    output_root = output_dir.resolve()
    current_paths = {Path(path).resolve() for path in (word_path, pdf_path, excel_path) if path}
    for old_path in stale_paths:
        path = Path(old_path).resolve()
        if path in current_paths:
            continue
        if path.suffix.lower() not in {'.docx', '.pdf', '.xlsx'}:
            continue
        try:
            path.relative_to(output_root.parent)
        except ValueError:
            continue
        if path.is_file():
            path.unlink()
            parent = path.parent
            while parent != output_root.parent and parent != output_root and parent.is_dir():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent


def generate_document(
    order_id: int,
    document_type: str,
    custom_template_path: str | None = None,
    custom_excel_template_path: str | None = None,
) -> Dict[str, str]:
    if document_type not in DOCUMENT_TYPES:
        raise ValueError(f'不支持的单证类型：{document_type}')

    data = get_order_document_context(order_id)
    data['document_type'] = document_type
    data['lc_document_instruction'] = _document_lc_instructions(data, document_type)
    data.pop('_lc_document_requirements', None)
    data.pop('_lc_adverse_clauses', None)
    output_dir = get_order_output_dir(order_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_template = custom_template_path or custom_excel_template_path
    if selected_template:
        suffix = Path(selected_template).suffix.lower()
    else:
        suffix = '.docx'
        selected_template = ensure_default_template(document_type)

    customer_name = str(data.get('customer_name_cn') or data.get('customer_name_en') or '客户').strip()
    product_name = str(data.get('product_name_en') or data.get('product_name_cn') or '产品').strip()

    filename_stem = (
        f"{int(data['_system_order_sequence']):03d}"
        f"{_filename_part(customer_name)}"
        f"{_filename_part(product_name)}"
        f"_{document_type.replace(' ', '_')}"
    )
    word_path = pdf_path = excel_path = None
    if suffix == '.docx':
        word_path = export_document_word(
            document_type,
            data,
            template_path=selected_template,
            output_path=str(output_dir / f'{filename_stem}.docx'),
        )
    elif suffix == '.xlsx':
        if document_type not in {'Commercial Invoice', 'Packing List'}:
            raise ValueError('Excel 模板目前只支持商业发票（CI）和装箱单（PL）。')
        excel_path = export_document_excel(
            document_type,
            data,
            output_path=str(output_dir / f'{filename_stem}.xlsx'),
            template_path=selected_template,
        )
    else:
        raise ValueError(f'不支持的模板格式：{suffix or "无扩展名"}。请选择 .docx 或 .xlsx 模板。')

    _save_document_record(
        order_id,
        document_type,
        data,
        word_path,
        pdf_path,
        excel_path,
        output_dir,
    )

    result = {'document_no': data['document_no']}
    if word_path:
        result['word'] = word_path
    if excel_path:
        result['excel'] = excel_path
    return result


def generate_all_documents_for_order(
    order_id: int,
    custom_template_path: str | None = None,
    template_paths: Dict[str, str] | None = None,
    custom_excel_template_path: str | None = None,
) -> Dict[str, Dict[str, str]]:
    results = {}
    for doc_type in DOCUMENT_TYPES:
        selected_template = (template_paths or {}).get(doc_type)
        if selected_template is None and custom_excel_template_path and doc_type in {
            'Commercial Invoice',
            'Packing List',
        }:
            selected_template = custom_excel_template_path
        selected_template = selected_template or custom_template_path
        results[doc_type] = generate_document(
            order_id,
            doc_type,
            custom_template_path=selected_template,
        )
    with get_connection() as conn:
        conn.execute(
            "UPDATE orders SET workflow_status = 'documents_ready_for_review' WHERE id = ?",
            (order_id,),
        )
        conn.commit()
    return results


def generate_pdfs_for_order(
    order_id: int,
    prepared_counts: Dict[str, Dict[str, int]] | None = None,
) -> Dict[str, str]:
    from modules.document_validation import assert_pdf_consistency

    assert_pdf_consistency(order_id, prepared_counts)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, document_type, file_path_word, file_path_excel
            FROM documents
            WHERE order_id = ?
            ORDER BY id DESC
            """,
            (order_id,),
        ).fetchall()

    latest_documents = {}
    for row in rows:
        latest_documents.setdefault(row['document_type'], dict(row))

    missing_documents = [doc_type for doc_type in DOCUMENT_TYPES if doc_type not in latest_documents]
    if missing_documents:
        raise ValueError(
            '请先完成四种单证的 Word/Excel 生成，再确认生成 PDF：'
            + '、'.join(missing_documents)
        )

    sources = {}
    for doc_type in DOCUMENT_TYPES:
        record = latest_documents[doc_type]
        source_path = record['file_path_word'] or record['file_path_excel']
        if not source_path or not Path(source_path).is_file():
            raise FileNotFoundError(
                f'{doc_type} 的原始 Word/Excel 文件不存在，请先重新生成该单证。'
            )
        suffix = Path(source_path).suffix.lower()
        if suffix not in {'.docx', '.xlsx'}:
            raise ValueError(f'{doc_type} 的文件格式不支持转 PDF：{suffix}')
        sources[doc_type] = (record, Path(source_path))

    generated = {}
    for doc_type, (record, source_path) in sources.items():
        pdf_path = source_path.with_suffix('.pdf')
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise RuntimeError(
                'PDF 导出需要 Windows Microsoft Office 和 pywin32，请确认 Word、Excel 已安装。'
            ) from exc

        pythoncom.CoInitialize()
        application = None
        document = None
        workbook = None
        try:
            if source_path.suffix.lower() == '.docx':
                application = win32com.client.DispatchEx('Word.Application')
                application.Visible = False
                application.DisplayAlerts = 0
                document = application.Documents.Open(
                    str(source_path.resolve()),
                    ReadOnly=True,
                    ConfirmConversions=False,
                    AddToRecentFiles=False,
                    NoEncodingDialog=True,
                )
                document.PageSetup.PaperSize = 7
                document.PageSetup.Orientation = 0
                document.ExportAsFixedFormat(str(pdf_path.resolve()), 17)
            else:
                application = win32com.client.DispatchEx('Excel.Application')
                application.Visible = False
                application.DisplayAlerts = False
                application.AskToUpdateLinks = False
                workbook = application.Workbooks.Open(
                    str(source_path.resolve()),
                    UpdateLinks=0,
                    ReadOnly=False,
                    AddToMru=False,
                )
                expected_sheet = (
                    'COMMERCIAL INVOICE'
                    if doc_type == 'Commercial Invoice'
                    else 'PACKING LIST'
                )
                worksheet = next(
                    (
                        workbook.Worksheets(index)
                        for index in range(1, workbook.Worksheets.Count + 1)
                        if expected_sheet in str(workbook.Worksheets(index).Name).upper()
                    ),
                    None,
                )
                if worksheet is None:
                    raise ValueError(
                        f'未找到用于导出的 {doc_type} 工作表，请检查所选 Excel 模板。'
                    )
                worksheet.PageSetup.PaperSize = 9
                worksheet.PageSetup.Orientation = 1
                worksheet.PageSetup.Zoom = False
                worksheet.PageSetup.FitToPagesWide = 1
                worksheet.PageSetup.FitToPagesTall = 1
                worksheet.PageSetup.PrintArea = worksheet.UsedRange.Address
                worksheet.ExportAsFixedFormat(0, str(pdf_path.resolve()))
        except Exception as exc:
            raise RuntimeError(
                f'{doc_type} PDF 转换失败（{source_path.name}）：{exc}'
            ) from exc
        finally:
            try:
                if document is not None:
                    document.Close(False)
                if workbook is not None:
                    workbook.Close(False)
            finally:
                try:
                    if application is not None:
                        application.Quit()
                finally:
                    pythoncom.CoUninitialize()

        if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
            raise RuntimeError(f'{doc_type} PDF 导出失败：未生成有效文件。')
        try:
            import fitz

            with fitz.open(pdf_path) as pdf:
                if len(pdf) != 1:
                    raise RuntimeError(
                        f'{doc_type} PDF 共 {len(pdf)} 页，未能排版为单页 A4。'
                    )
                page = pdf[0]
                if abs(page.rect.width - 595.28) > 2 or abs(page.rect.height - 841.89) > 2:
                    raise RuntimeError(
                        f'{doc_type} PDF 页面尺寸不是 A4 纵向：'
                        f'{page.rect.width:.1f} × {page.rect.height:.1f} pt。'
                    )
        except ImportError as exc:
            raise RuntimeError('PDF 页面验证需要 PyMuPDF，请安装项目依赖后重试。') from exc
        generated[doc_type] = str(pdf_path)

    with get_connection() as conn:
        conn.executemany(
            'UPDATE documents SET file_path_pdf = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            [
                (generated[doc_type], sources[doc_type][0]['id'])
                for doc_type in DOCUMENT_TYPES
            ],
        )
        conn.execute(
            "UPDATE orders SET workflow_status = 'pdf_confirmed' WHERE id = ?",
            (order_id,),
        )
        conn.commit()
    return generated


def list_templates() -> List[str]:
    settings.templates_dir.mkdir(parents=True, exist_ok=True)
    return [str(path.name) for path in settings.templates_dir.iterdir() if path.is_file() and path.suffix.lower() in {'.docx', '.pdf', '.xlsx'}]


def list_word_templates() -> List[str]:
    return [str(path) for path in get_word_templates()]


def list_excel_templates() -> List[str]:
    return [str(path) for path in get_excel_templates()]


def get_excel_template_sheets(template_path: str) -> List[str]:
    return read_excel_template_sheets(template_path)
