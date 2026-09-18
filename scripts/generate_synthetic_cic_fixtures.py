# -*- coding: utf-8 -*-
"""Generate synthetic CIC PDF fixtures for Phase 4 testing:
1. tests/fixtures/synthetic_cic_digital.pdf (with selectable text layer for pypdf)
2. tests/fixtures/synthetic_cic_scanned.pdf (pure image rasterized for Qwen Vision OCR)
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import pypdfium2
from PIL import Image


def register_fonts():
    font_path = "C:/Windows/Fonts/arial.ttf"
    bold_font_path = "C:/Windows/Fonts/arialbd.ttf"
    if os.path.exists(font_path) and os.path.exists(bold_font_path):
        pdfmetrics.registerFont(TTFont("Arial", font_path))
        pdfmetrics.registerFont(TTFont("Arial-Bold", bold_font_path))
        return "Arial", "Arial-Bold"
    return "Helvetica", "Helvetica-Bold"


def build_digital_cic_pdf(output_path: str, font_name: str, bold_font_name: str):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(A4),
        leftMargin=30,
        rightMargin=30,
        topMargin=30,
        bottomMargin=30,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        fontName=bold_font_name,
        fontSize=14,
        leading=18,
        alignment=1,  # Center
        textColor=colors.HexColor("#002B49"),
    )
    subtitle_style = ParagraphStyle(
        "SubTitleStyle",
        fontName=font_name,
        fontSize=10,
        leading=14,
        alignment=1,
        textColor=colors.HexColor("#333333"),
    )
    heading_style = ParagraphStyle(
        "HeadingStyle",
        fontName=bold_font_name,
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#002B49"),
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        fontName=font_name,
        fontSize=9,
        leading=13,
        textColor=colors.black,
    )
    bold_body_style = ParagraphStyle(
        "BoldBodyStyle",
        fontName=bold_font_name,
        fontSize=9,
        leading=13,
        textColor=colors.black,
    )
    table_cell_style = ParagraphStyle(
        "TableCellStyle",
        fontName=font_name,
        fontSize=8,
        leading=11,
        textColor=colors.black,
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        fontName=bold_font_name,
        fontSize=8,
        leading=11,
        textColor=colors.black,
    )
    table_hdr_style = ParagraphStyle(
        "TableHdrStyle",
        fontName=bold_font_name,
        fontSize=8,
        leading=11,
        alignment=1,
        textColor=colors.white,
    )

    story = []

    # Header
    story.append(Paragraph("BÁO CÁO THÔNG TIN TÍN DỤNG KHÁCH HÀNG DOANH NGHIỆP", title_style))
    story.append(Paragraph("Mã số tra cứu CIC: 0123456789 - Ngày tra cứu: 28/02/2026", subtitle_style))
    story.append(Spacer(1, 15))

    # Customer info
    story.append(Paragraph("I. THÔNG TIN KHÁCH HÀNG DOANH NGHIỆP", heading_style))
    info_data = [
        [Paragraph("<b>Tên khách hàng:</b>", body_style), Paragraph("CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG", bold_body_style)],
        [Paragraph("<b>Mã số thuế:</b>", body_style), Paragraph("0109876543", bold_body_style)],
        [Paragraph("<b>Địa chỉ trụ sở:</b>", body_style), Paragraph("Tầng 5, Tòa nhà Techno, Phố Duy Tân, Cầu Giấy, Hà Nội", body_style)],
    ]
    t_info = Table(info_data, colWidths=[120, 600])
    t_info.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 12))

    # General credit status
    story.append(Paragraph("II. TỔNG HỢP QUAN HỆ TÍN DỤNG VÀ LỊCH SỬ NỢ", heading_style))
    sum_data = [
        [Paragraph("Tổng số TCTD đang quan hệ tín dụng:", body_style), Paragraph("<b>03 Tổ chức tín dụng</b>", body_style)],
        [Paragraph("Nhóm nợ cao nhất hiện tại:", body_style), Paragraph("<b>Nhóm 1</b> (Nợ đủ tiêu chuẩn)", body_style)],
        [Paragraph("Lịch sử nợ quá hạn 12 tháng gần nhất:", body_style), Paragraph("<b>Trong 12 tháng gần nhất không có nợ quá hạn.</b>", body_style)],
        [Paragraph("Thông tin nghĩa vụ ngoại bảng và phái sinh:", body_style), Paragraph("<b>Không phát sinh giao dịch phái sinh chậm thanh toán.</b>", body_style)],
    ]
    t_sum = Table(sum_data, colWidths=[240, 480])
    t_sum.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(t_sum)
    story.append(Spacer(1, 12))

    # Institution detail table
    story.append(Paragraph("III. CHI TIẾT QUAN HỆ TÍN DỤNG TẠI CÁC TCTD (Đơn vị tính: Triệu đồng)", heading_style))
    headers = [
        Paragraph("STT", table_hdr_style),
        Paragraph("Tổ chức tín dụng", table_hdr_style),
        Paragraph("HMTD ngắn hạn", table_hdr_style),
        Paragraph("Dư nợ ngắn hạn (VND)", table_hdr_style),
        Paragraph("Dư nợ NH quy đổi (USD)", table_hdr_style),
        Paragraph("Dư nợ USD gốc", table_hdr_style),
        Paragraph("Dư nợ trung dài hạn", table_hdr_style),
        Paragraph("Tổng dư nợ", table_hdr_style),
        Paragraph("Nhóm nợ", table_hdr_style),
        Paragraph("Tài sản bảo đảm", table_hdr_style),
    ]

    r1 = [
        Paragraph("1", table_cell_style),
        Paragraph("Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank) - CN Thăng Long", table_cell_bold),
        Paragraph("15.000", table_cell_style),
        Paragraph("8.500", table_cell_style),
        Paragraph("1.500", table_cell_style),
        Paragraph("0", table_cell_style),
        Paragraph("0", table_cell_style),
        Paragraph("10.000", table_cell_bold),
        Paragraph("Nhóm 1", table_cell_style),
        Paragraph("Bất động sản tại Hà Nội", table_cell_style),
    ]

    r2 = [
        Paragraph("2", table_cell_style),
        Paragraph("Ngân hàng TMCP Hàng Hải Việt Nam (MSB) - CN Hà Nội", table_cell_bold),
        Paragraph("10.000", table_cell_style),
        Paragraph("5.200", table_cell_style),
        Paragraph("0", table_cell_style),
        Paragraph("0", table_cell_style),
        Paragraph("2.000", table_cell_style),
        Paragraph("7.200", table_cell_bold),
        Paragraph("Nhóm 1", table_cell_style),
        Paragraph("HĐTG và Hàng tồn kho", table_cell_style),
    ]

    r3 = [
        Paragraph("3", table_cell_style),
        Paragraph("Ngân hàng TNHH MTV Shinhan Việt Nam", table_cell_bold),
        Paragraph("2.500", table_cell_style),
        Paragraph("0", table_cell_style),
        Paragraph("-", table_cell_style),
        Paragraph("50.000 USD", table_cell_bold),
        Paragraph("0", table_cell_style),
        Paragraph("-", table_cell_style),
        Paragraph("Nhóm 1", table_cell_style),
        Paragraph("Tín chấp theo dòng tiền", table_cell_style),
    ]

    t_rel = Table(
        [headers, r1, r2, r3],
        colWidths=[25, 200, 60, 60, 60, 55, 60, 55, 45, 120]
    )
    t_rel.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#002B49")),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor("#FFFBE6")),  # Highlight MSB slightly
    ]))
    story.append(t_rel)
    story.append(Spacer(1, 10))

    # Notes
    note_text = (
        "<b>Ghi chú:</b> Tại Ngân hàng TNHH MTV Shinhan Việt Nam, khoản vay ngoại tệ trị giá 50.000 USD "
        "chưa thực hiện quy đổi ra VND tại thời điểm báo cáo. Khách hàng thực hiện tốt nghĩa vụ trả nợ, "
        "không có lịch sử nợ quá hạn trong 12 tháng qua."
    )
    story.append(Paragraph(note_text, table_cell_style))

    doc.build(story)
    print(f"[+] Digital CIC PDF generated successfully at: {output_path}")


def convert_pdf_to_scanned(input_pdf: str, output_pdf: str):
    """Render PDF pages to raster bitmaps and save as pure image PDF (no text layer)."""
    doc = pypdfium2.PdfDocument(input_pdf)
    images = []
    for page in doc:
        # Render at 200 DPI (scale ~ 2.77)
        bitmap = page.render(scale=2.77)
        pil_image = bitmap.to_pil()
        # Convert to RGB
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")
        images.append(pil_image)

    if not images:
        raise ValueError("No pages found to render for scanned PDF.")

    images[0].save(
        output_pdf,
        save_all=True,
        append_images=images[1:],
        quality=90
    )
    print(f"[+] Scanned (raster image) CIC PDF generated successfully at: {output_pdf}")


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_dir = os.path.join(base_dir, "tests", "fixtures", "cic")
    legacy_target_dir = os.path.join(base_dir, "tests", "fixtures")
    os.makedirs(target_dir, exist_ok=True)

    font_name, bold_font_name = register_fonts()

    digital_pdf = os.path.join(target_dir, "synthetic_cic_digital.pdf")
    scanned_pdf = os.path.join(target_dir, "synthetic_cic_scanned.pdf")

    build_digital_cic_pdf(digital_pdf, font_name, bold_font_name)
    convert_pdf_to_scanned(digital_pdf, scanned_pdf)

    # Also copy to tests/fixtures/ for easy root fixture access
    import shutil
    shutil.copy(digital_pdf, os.path.join(legacy_target_dir, "synthetic_cic_digital.pdf"))
    shutil.copy(scanned_pdf, os.path.join(legacy_target_dir, "synthetic_cic_scanned.pdf"))
    print("[+] Fixtures copied to tests/fixtures/ as well.")


if __name__ == "__main__":
    main()
