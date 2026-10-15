from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Dict

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from services.amount_words import amount_in_english_words
from config.settings import settings


NAVY = colors.HexColor('#17365D')
BLUE = colors.HexColor('#1F4E79')
PALE_BLUE = colors.HexColor('#EAF1F8')
GRID = colors.HexColor('#B7C9D6')
TEXT = colors.HexColor('#243447')


def _register_unicode_font() -> str:
    for font_path in (
        Path('C:/Windows/Fonts/arial.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/Library/Fonts/Arial.ttf'),
    ):
        if font_path.exists():
            font_name = 'TradeUnicode'
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
            return font_name
    return 'Helvetica'


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    text = escape(str(value if value is not None else '')).replace('\n', '<br/>')
    return Paragraph(text or '&nbsp;', style)


def _table(rows, widths, header: bool = False) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
    commands = [
        ('GRID', (0, 0), (-1, -1), 0.45, GRID),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]
    if header:
        commands.extend([
            ('BACKGROUND', (0, 0), (-1, 0), NAVY),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ])
    table.setStyle(TableStyle(commands))
    return table


def _section_heading(text: str, styles: Dict[str, ParagraphStyle]):
    return Paragraph(text.upper(), styles['section'])


def _document_story(document_type: str, values: Dict[str, Any], styles: Dict[str, ParagraphStyle]):
    story = [
        _paragraph(values.get('company_name', ''), styles['company']),
        _paragraph({
            'PI': 'PROFORMA INVOICE',
            'Commercial Invoice': 'COMMERCIAL INVOICE',
            'Packing List': 'PACKING LIST',
            'Sales Contract': 'SALES CONTRACT',
        }.get(document_type, document_type.upper()), styles['title']),
        Spacer(1, 4 * mm),
    ]

    if document_type == 'Sales Contract':
        story.extend([
            _table([
                [_paragraph('CONTRACT NO.', styles['label']), _paragraph(values.get('document_no'), styles['value']),
                 _paragraph('DATE', styles['label']), _paragraph(values.get('date'), styles['value'])],
                [_paragraph('SELLER', styles['label']), _paragraph(f"{values.get('company_name', '')}\n{values.get('company_address', '')}", styles['value']),
                 _paragraph('BUYER', styles['label']), _paragraph(f"{values.get('customer_name_en', '')}\n{values.get('customer_address', '')}", styles['value'])],
            ], [28 * mm, 58 * mm, 24 * mm, 66 * mm]),
            Spacer(1, 5 * mm),
            _paragraph('The Seller and the Buyer agree to the following terms and conditions:', styles['body']),
        ])
        contract_terms = [
            ('1. GOODS AND QUANTITY', f"{values.get('product_name_en', '')} — {values.get('quantity', '')} {values.get('unit', '')}"),
            ('2. PRICE AND CONTRACT VALUE', f"Unit price: {values.get('currency', '')} {values.get('unit_price', '')}    Total: {values.get('currency', '')} {values.get('total_amount', '')}"),
            ('3. DELIVERY', f"Term: {values.get('incoterm', '')}    Loading port: {values.get('loading_port', '')}    Destination: {values.get('destination_port', '')}\nShipment date: {values.get('shipment_date', '')}    Latest shipment: {values.get('latest_shipment_date', '')}"),
            ('4. PAYMENT', values.get('payment_terms', '')),
            ('5. PACKING AND SHIPPING MARKS', f"{values.get('marks_and_numbers', '')}\nGross weight: {values.get('gross_weight', '')} kg    Net weight: {values.get('net_weight', '')} kg    Volume: {values.get('volume', '')} CBM"),
            ('6. SPECIAL TERMS', f"{values.get('remarks', '')}\n{values.get('lc_document_instruction', '')}"),
        ]
        for heading, content in contract_terms:
            story.extend([Spacer(1, 3 * mm), _section_heading(heading, styles), _paragraph(content, styles['body'])])
    else:
        buyer_heading = 'BUYER / APPLICANT' if document_type == 'PI' else 'BUYER / CONSIGNEE'
        seller_heading = 'SELLER / BENEFICIARY' if document_type == 'PI' else 'SELLER / EXPORTER'
        story.extend([
            _table([
                [_paragraph(seller_heading, styles['table_header']), _paragraph(buyer_heading, styles['table_header'])],
                [_paragraph(f"{values.get('company_name', '')}\n{values.get('company_address', '')}\n{values.get('company_email', '')}\n{values.get('company_phone', '')}", styles['value']),
                 _paragraph(f"{values.get('customer_name_en', '')}\n{values.get('customer_address', '')}\nAttn: {values.get('contact_person', '')}\n{values.get('email', '')}", styles['value'])],
            ], [88 * mm, 88 * mm], header=True),
            Spacer(1, 4 * mm),
        ])
        if document_type == 'Packing List':
            metadata = [
                [_paragraph('PACKING LIST NO.', styles['label']), _paragraph(values.get('document_no'), styles['value']),
                 _paragraph('DATE', styles['label']), _paragraph(values.get('date'), styles['value'])],
                [_paragraph('ORDER NO.', styles['label']), _paragraph(values.get('order_no'), styles['value']),
                 _paragraph('CURRENCY', styles['label']), _paragraph(values.get('currency'), styles['value'])],
                [_paragraph('LOADING PORT', styles['label']), _paragraph(values.get('loading_port'), styles['value']),
                 _paragraph('DESTINATION', styles['label']), _paragraph(values.get('destination_port'), styles['value'])],
            ]
        else:
            metadata = [
                [_paragraph('INVOICE NO.', styles['label']), _paragraph(values.get('document_no'), styles['value']),
                 _paragraph('DATE', styles['label']), _paragraph(values.get('date'), styles['value'])],
                [_paragraph('ORDER / CONTRACT NO.', styles['label']), _paragraph(values.get('order_no'), styles['value']),
                 _paragraph('CURRENCY', styles['label']), _paragraph(values.get('currency'), styles['value'])],
                [_paragraph('INCOTERM', styles['label']), _paragraph(values.get('incoterm'), styles['value']),
                 _paragraph('PAYMENT TERMS', styles['label']), _paragraph(values.get('payment_terms'), styles['value'])],
                [_paragraph('LOADING PORT', styles['label']), _paragraph(values.get('loading_port'), styles['value']),
                 _paragraph('DESTINATION', styles['label']), _paragraph(values.get('destination_port'), styles['value'])],
            ]
        story.append(_table(metadata, [34 * mm, 52 * mm, 34 * mm, 56 * mm]))
        story.extend([Spacer(1, 5 * mm), _section_heading(
            'Packing Details' if document_type == 'Packing List' else 'Description of Goods', styles,
        )])

        if document_type == 'Packing List':
            item_rows = [[
                _paragraph('NO.', styles['table_header']),
                _paragraph('DESCRIPTION OF GOODS', styles['table_header']),
                _paragraph('PACKAGES / QTY', styles['table_header']),
                _paragraph('NET WT (KG)', styles['table_header']),
                _paragraph('GROSS WT (KG)', styles['table_header']),
                _paragraph('MEASUREMENT (CBM)', styles['table_header']),
            ], [
                _paragraph('1', styles['value']),
                _paragraph(values.get('product_name_en'), styles['value']),
                _paragraph(f"{values.get('quantity', '')} {values.get('unit', '')}", styles['value']),
                _paragraph(values.get('net_weight'), styles['value']),
                _paragraph(values.get('gross_weight'), styles['value']),
                _paragraph(values.get('volume'), styles['value']),
            ]]
            story.append(_table(item_rows, [10 * mm, 48 * mm, 31 * mm, 25 * mm, 28 * mm, 30 * mm], header=True))
            story.extend([
                Spacer(1, 4 * mm),
                _table([[
                    _paragraph('TOTAL PACKAGES / QTY', styles['label']),
                    _paragraph(f"{values.get('quantity', '')} {values.get('unit', '')}", styles['value']),
                    _paragraph('TOTAL NET WT', styles['label']),
                    _paragraph(f"{values.get('net_weight', '')} kg", styles['value']),
                ], [
                    _paragraph('TOTAL GROSS WT', styles['label']),
                    _paragraph(f"{values.get('gross_weight', '')} kg", styles['value']),
                    _paragraph('TOTAL MEASUREMENT', styles['label']),
                    _paragraph(f"{values.get('volume', '')} CBM", styles['value']),
                ]], [38 * mm, 48 * mm, 38 * mm, 56 * mm]),
            ])
        else:
            item_rows = [[
                _paragraph('NO.', styles['table_header']),
                _paragraph('DESCRIPTION', styles['table_header']),
                _paragraph('QUANTITY', styles['table_header']),
                _paragraph('UNIT PRICE', styles['table_header']),
                _paragraph('AMOUNT', styles['table_header']),
            ], [
                _paragraph('1', styles['value']),
                _paragraph(values.get('product_name_en'), styles['value']),
                _paragraph(f"{values.get('quantity', '')} {values.get('unit', '')}", styles['value']),
                _paragraph(f"{values.get('currency', '')} {values.get('unit_price', '')}", styles['value']),
                _paragraph(f"{values.get('currency', '')} {values.get('total_amount', '')}", styles['value']),
            ]]
            story.extend([
                _table(item_rows, [12 * mm, 69 * mm, 30 * mm, 33 * mm, 36 * mm], header=True),
                Spacer(1, 3 * mm),
                _table([[
                    _paragraph('TOTAL AMOUNT', styles['label']),
                    _paragraph(f"{values.get('currency', '')} {values.get('total_amount', '')}", styles['total']),
                ]], [120 * mm, 60 * mm]),
            ])
            story.extend([
                Spacer(1, 4 * mm),
                _table([[
                    _paragraph('GROSS WEIGHT', styles['label']), _paragraph(f"{values.get('gross_weight', '')} kg", styles['value']),
                    _paragraph('NET WEIGHT', styles['label']), _paragraph(f"{values.get('net_weight', '')} kg", styles['value']),
                    _paragraph('VOLUME', styles['label']), _paragraph(f"{values.get('volume', '')} CBM", styles['value']),
                ]], [28 * mm, 31 * mm, 25 * mm, 29 * mm, 20 * mm, 30 * mm]),
            ])

        story.extend([
            Spacer(1, 4 * mm),
            _paragraph(f"Marks & Numbers: {values.get('marks_and_numbers', '')}", styles['body']),
        ])
        if values.get('remarks'):
            story.append(_paragraph(f"Remarks: {values.get('remarks')}", styles['body']))
        if values.get('lc_document_instruction'):
            story.append(Spacer(1, 3 * mm))
            story.append(_section_heading('Letter of Credit Requirements', styles))
            story.append(_paragraph(values.get('lc_document_instruction'), styles['body']))

    if document_type in {'PI', 'Commercial Invoice'}:
        story.extend([
            Spacer(1, 7 * mm),
            _paragraph(
                f"AMOUNT IN WORDS: {amount_in_english_words(values.get('total_amount'), values.get('currency', 'USD'))}",
                styles['body'],
            ),
        ])
    story.extend([
        Spacer(1, 10 * mm),
        _table([[
            _paragraph('AUTHORIZED SIGNATURE', styles['label']),
            _paragraph('COMPANY STAMP', styles['label']),
        ], [
            _paragraph('\n\n______________________________\nName / Title: __________________\nDate: _________________________', styles['value']),
            _paragraph('\n\n______________________________\n', styles['value']),
        ]], [90 * mm, 90 * mm]),
    ])
    return story


def export_document_pdf(document_type: str, values: Dict[str, Any], output_path: str | None = None) -> str:
    target = Path(output_path) if output_path else settings.outputs_dir / values.get('order_no', 'document') / f'{document_type}_export.pdf'
    target.parent.mkdir(parents=True, exist_ok=True)

    font_name = _register_unicode_font()
    base_styles = getSampleStyleSheet()
    styles = {
        'company': ParagraphStyle('Company', parent=base_styles['Normal'], fontName=font_name, fontSize=10, leading=13, textColor=BLUE, alignment=TA_CENTER),
        'title': ParagraphStyle('TradeTitle', parent=base_styles['Title'], fontName=font_name, fontSize=17, leading=21, textColor=NAVY, alignment=TA_CENTER, spaceAfter=2),
        'section': ParagraphStyle('Section', parent=base_styles['Heading2'], fontName=font_name, fontSize=9, leading=12, textColor=BLUE, spaceBefore=4, spaceAfter=4),
        'label': ParagraphStyle('Label', parent=base_styles['Normal'], fontName=font_name, fontSize=7.5, leading=10, textColor=BLUE),
        'value': ParagraphStyle('Value', parent=base_styles['Normal'], fontName=font_name, fontSize=8.5, leading=11, textColor=TEXT),
        'body': ParagraphStyle('Body', parent=base_styles['BodyText'], fontName=font_name, fontSize=8.5, leading=12, textColor=TEXT),
        'table_header': ParagraphStyle('TableHeader', parent=base_styles['Normal'], fontName=font_name, fontSize=7.5, leading=9, textColor=colors.white, alignment=TA_LEFT),
        'total': ParagraphStyle('Total', parent=base_styles['Normal'], fontName=font_name, fontSize=11, leading=14, textColor=NAVY, alignment=TA_RIGHT),
    }
    document = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f'{document_type} {values.get("document_no", "")}',
        author=str(values.get('company_name', '')),
    )
    document.build(_document_story(document_type, values, styles))
    return str(target)
