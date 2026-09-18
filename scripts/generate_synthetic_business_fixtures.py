# -*- coding: utf-8 -*-
"""Generate synthetic Business PDF fixtures for Phase 5 testing:
1. tests/fixtures/business/synthetic_business_digital.pdf (selectable digital text layer for pypdf)
2. tests/fixtures/business/synthetic_business_scanned.pdf (pure image rasterized for Qwen Vision OCR)
"""

import os
import sys
import shutil

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from reportlab.lib.pagesizes import A4
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


def build_digital_business_pdf(output_path: str, font_name: str, bold_font_name: str):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=24,
        rightMargin=24,
        topMargin=20,
        bottomMargin=20,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        fontName=bold_font_name,
        fontSize=11,
        leading=14,
        alignment=1,  # Center
        textColor=colors.HexColor("#002B49"),
    )
    subtitle_style = ParagraphStyle(
        "SubTitleStyle",
        fontName=bold_font_name,
        fontSize=9,
        leading=12,
        alignment=1,
        textColor=colors.HexColor("#004080"),
    )
    heading_style = ParagraphStyle(
        "HeadingStyle",
        fontName=bold_font_name,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#002B49"),
        spaceBefore=3,
        spaceAfter=1,
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        fontName=font_name,
        fontSize=7.2,
        leading=9.5,
        textColor=colors.black,
    )
    table_cell_style = ParagraphStyle(
        "TableCellStyle",
        fontName=font_name,
        fontSize=6.8,
        leading=8.5,
        textColor=colors.black,
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        fontName=bold_font_name,
        fontSize=6.8,
        leading=8.5,
        textColor=colors.black,
    )
    table_hdr_style = ParagraphStyle(
        "TableHdrStyle",
        fontName=bold_font_name,
        fontSize=6.8,
        leading=8.5,
        alignment=1,
        textColor=colors.white,
    )

    story = []

    # Title Banner
    story.append(Paragraph("BÁO CÁO NĂNG LỰC DOANH NGHIỆP & HỒ SƠ HOẠT ĐỘNG KINH DOANH", title_style))
    story.append(Paragraph("CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ TRUYỀN THÔNG ĐÔNG NAM Á", subtitle_style))
    story.append(Spacer(1, 8))

    # General Identity
    id_text = """
    <b>Tên công ty:</b> CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ TRUYỀN THÔNG ĐÔNG NAM Á<br/>
    <b>Tên viết tắt:</b> DONG NAM A TELECOM JSC &nbsp;&nbsp;|&nbsp;&nbsp; <b>Mã số thuế:</b> 0108889999<br/>
    <b>Năm thành lập:</b> 2015 &nbsp;&nbsp;|&nbsp;&nbsp; <b>Trụ sở:</b> Tòa nhà Đông Nam Á, Số 18 Duy Tân, Cầu Giấy, Hà Nội
    """
    story.append(Paragraph(id_text, body_style))
    story.append(Spacer(1, 3))

    # 1. Quá trình hình thành & Tăng vốn
    story.append(Paragraph("1. LỊCH SỬ HÌNH THÀNH VÀ CÁC MỐC TĂNG VỐN", heading_style))
    history_text = (
        "Thành lập năm 2015 tiền thân là Trung tâm Công nghệ Viễn thông Đông Nam Á, chính thức chuyển đổi thành "
        "Công ty Cổ phần năm 2018. Doanh nghiệp chuyên cung cấp giải pháp viễn thông, thiết bị IoT và tích hợp hệ thống cho các doanh nghiệp lớn."
    )
    story.append(Paragraph(history_text, body_style))
    story.append(Spacer(1, 4))

    milestones_data = [
        [
            Paragraph("Thời điểm", table_hdr_style),
            Paragraph("Vốn điều lệ (triệu VND)", table_hdr_style),
            Paragraph("Sự kiện ghi nhận", table_hdr_style),
        ],
        [
            Paragraph("2020", table_cell_bold),
            Paragraph("50.000", table_cell_style),
            Paragraph("Tăng vốn điều lệ từ phát hành cổ phần", table_cell_style),
        ],
        [
            Paragraph("15/05/2023", table_cell_bold),
            Paragraph("120.000", table_cell_style),
            Paragraph("Chào bán cho cổ đông chiến lược", table_cell_style),
        ],
    ]
    t_milestones = Table(milestones_data, colWidths=[80, 120, 320])
    t_milestones.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#002B49")),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#B0C4DE")),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(t_milestones)
    story.append(Spacer(1, 3))

    # 2. Chủ sở hữu & Cổ đông
    story.append(Paragraph("2. CHỦ SỞ HỮU VÀ CƠ CẤU CỔ ĐÔNG LỚN", heading_style))
    owner_text = "Doanh nghiệp trực thuộc sở hữu của Tập đoàn Công nghệ Viễn thông Quốc tế Á Châu."
    story.append(Paragraph(owner_text, body_style))
    story.append(Spacer(1, 4))

    shareholders_data = [
        [
            Paragraph("STT", table_hdr_style),
            Paragraph("Tên Cổ đông / Thành viên", table_hdr_style),
            Paragraph("MST / CCCD", table_hdr_style),
            Paragraph("Tỷ lệ sở hữu (%)", table_hdr_style),
            Paragraph("Vốn góp (triệu VND)", table_hdr_style),
        ],
        [
            Paragraph("1", table_cell_style),
            Paragraph("Tập đoàn Công nghệ Viễn thông Quốc tế Á Châu", table_cell_bold),
            Paragraph("0102345678", table_cell_style),
            Paragraph("51.0%", table_cell_style),
            Paragraph("61.200", table_cell_style),
        ],
        [
            Paragraph("2", table_cell_style),
            Paragraph("Nguyễn Văn Toàn", table_cell_bold),
            Paragraph("001080009876", table_cell_style),
            Paragraph("25.5%", table_cell_style),
            Paragraph("30.600", table_cell_style),
        ],
        [
            Paragraph("3", table_cell_style),
            Paragraph("Trần Thị Mai Phương", table_cell_bold),
            Paragraph("001185004321", table_cell_style),
            Paragraph("15.0%", table_cell_style),
            Paragraph("18.000", table_cell_style),
        ],
    ]
    t_sh = Table(shareholders_data, colWidths=[25, 230, 95, 80, 90])
    t_sh.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#002B49")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#B0C4DE")),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(t_sh)
    story.append(Spacer(1, 3))

    # 3. Ban điều hành
    story.append(Paragraph("3. CƠ CẤU BAN ĐIỀU HÀNH VÀ LÃNH ĐẠO CHỦ CHỐT", heading_style))
    mgmt_text = (
        "<b>+ Chủ tịch HĐQT kiêm Tổng Giám đốc:</b> Nguyễn Văn Toàn — Kỹ sư Viễn thông, "
        "hơn 18 năm kinh nghiệm trong ngành viễn thông và công nghệ thông tin.<br/>"
        "<b>+ Giám đốc Kỹ thuật & Vận hành:</b> Lê Quốc Hưng — "
        "2016-2021: Trưởng phòng Giải pháp IoT; 2021-nay: Giám đốc Kỹ thuật."
    )
    story.append(Paragraph(mgmt_text, body_style))
    story.append(Spacer(1, 3))

    # 4. Mô hình hoạt động & Sản phẩm chính
    story.append(Paragraph("4. MÔ HÌNH HOẠT ĐỘNG, SẢN PHẨM VÀ CƠ SỞ VẬT CHẤT", heading_style))
    op_text = (
        "Doanh nghiệp hoạt động theo mô hình sản xuất và phân phối các thiết bị đầu cuối viễn thông và giải pháp IoT. "
        "Công nghệ & Quy trình sản xuất: Dây chuyền SMT tự động hóa kiểm thử tiêu chuẩn quốc tế ISO 9001:2015."
    )
    story.append(Paragraph(op_text, body_style))
    story.append(Spacer(1, 4))

    products_data = [
        [
            Paragraph("STT", table_hdr_style),
            Paragraph("Sản phẩm / Dịch vụ chính", table_hdr_style),
            Paragraph("Quy cách & Thương hiệu", table_hdr_style),
            Paragraph("Tỷ trọng Doanh thu (%)", table_hdr_style),
        ],
        [
            Paragraph("1", table_cell_style),
            Paragraph("Thiết bị định vị & cảm biến IoT thông minh", table_cell_bold),
            Paragraph("Chuẩn công nghiệp IP67", table_cell_style),
            Paragraph("45.0%", table_cell_style),
        ],
        [
            Paragraph("2", table_cell_style),
            Paragraph("Hệ thống tổng đài IP và Router viễn thông", table_cell_bold),
            Paragraph("Nhập khẩu chính hãng", table_cell_style),
            Paragraph("35.0%", table_cell_style),
        ],
        [
            Paragraph("3", table_cell_style),
            Paragraph("Dịch vụ phần mềm quản trị và bảo trì hệ thống", table_cell_bold),
            Paragraph("Bản quyền SaaS", table_cell_style),
            Paragraph("20.0%", table_cell_style),
        ],
    ]
    t_p = Table(products_data, colWidths=[25, 235, 160, 100])
    t_p.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#002B49")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#B0C4DE")),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(t_p)
    story.append(Spacer(1, 4))

    # Kho bãi & MMTB
    wh_text = (
        "<b>Hệ thống kho bãi:</b> Kho hàng trung tâm tại Lô C2 KCN Quang Minh, Mê Linh, Hà Nội, diện tích 3.500 m2, "
        "hình thức Thuê dài hạn KCN 10 năm, công suất lưu trữ Theo đơn hàng thiết bị IoT.<br/>"
        "<b>Máy móc thiết bị chính:</b> Dây chuyền lắp ráp và kiểm thử bo mạch SMT, xuất xứ Nhật Bản - Yamaha, "
        "công suất thiết kế 50.000 sản phẩm/năm, hiệu suất vận hành 92%."
    )
    story.append(Paragraph(wh_text, body_style))
    story.append(Spacer(1, 3))

    # 5. Nhà cung cấp & Khách hàng
    story.append(Paragraph("5. CHUỖI CUNG ỨNG: NHÀ CUNG CẤP & KHÁCH HÀNG ĐẦU RA", heading_style))

    story.append(Paragraph("<b>Bảng Top Nhà cung cấp đầu vào:</b>", body_style))
    suppliers_data = [
        [
            Paragraph("STT", table_hdr_style),
            Paragraph("Tên Nhà cung cấp", table_hdr_style),
            Paragraph("Mặt hàng cung ứng", table_hdr_style),
            Paragraph("Tỷ trọng mua (%)", table_hdr_style),
            Paragraph("Phương thức thanh toán", table_hdr_style),
        ],
        [
            Paragraph("1", table_cell_style),
            Paragraph("Công ty TNHH Linh Kiện Điện Tử Qualcomm Việt Nam", table_cell_bold),
            Paragraph("Chipset 4G/5G và vi xử lý IoT", table_cell_style),
            Paragraph("32.0%", table_cell_style),
            Paragraph("L/C trả ngay", table_cell_style),
        ],
        [
            Paragraph("2", table_cell_style),
            Paragraph("Quectel Wireless Solutions Co., Ltd", table_cell_bold),
            Paragraph("Module truyền thông không dây", table_cell_style),
            Paragraph("28.5%", table_cell_style),
            Paragraph("TTR gối đầu 30 ngày", table_cell_style),
        ],
        [
            Paragraph("3", table_cell_style),
            Paragraph("Công ty Cổ phần Dây và Cáp Điện Thượng Đình", table_cell_bold),
            Paragraph("Cáp quang và phụ kiện truyền dẫn", table_cell_style),
            Paragraph("18.0%", table_cell_style),
            Paragraph("Chuyển khoản theo tiến độ", table_cell_style),
        ],
    ]
    t_sup = Table(suppliers_data, colWidths=[25, 200, 140, 75, 80])
    t_sup.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#002B49")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#B0C4DE")),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(t_sup)
    story.append(Spacer(1, 4))

    dist_text = "<b>Kênh phân phối:</b> Phân phối trực tiếp đến các nhà mạng viễn thông, tập đoàn công nghiệp và mạng lưới đại lý trên toàn quốc."
    story.append(Paragraph(dist_text, body_style))
    story.append(Spacer(1, 4))

    story.append(Paragraph("<b>Bảng Top Khách hàng đầu ra:</b>", body_style))
    customers_data = [
        [
            Paragraph("STT", table_hdr_style),
            Paragraph("Tên Khách hàng", table_hdr_style),
            Paragraph("Sản phẩm cung cấp", table_hdr_style),
            Paragraph("Tỷ trọng Doanh thu (%)", table_hdr_style),
            Paragraph("Chính sách công nợ", table_hdr_style),
        ],
        [
            Paragraph("1", table_cell_style),
            Paragraph("Tổng Công ty Viễn thông Viettel", table_cell_bold),
            Paragraph("Thiết bị cảm biến và Gateway IoT", table_cell_style),
            Paragraph("34.5%", table_cell_style),
            Paragraph("Bảo lãnh thanh toán 45 ngày", table_cell_style),
        ],
        [
            Paragraph("2", table_cell_style),
            Paragraph("Tập đoàn Bưu chính Viễn thông Việt Nam (VNPT)", table_cell_bold),
            Paragraph("Router và thiết bị truyền dẫn", table_cell_style),
            Paragraph("26.0%", table_cell_style),
            Paragraph("Chuyển khoản sau nghiệm thu 30 ngày", table_cell_style),
        ],
        [
            Paragraph("3", table_cell_style),
            Paragraph("Tổng Công ty Viễn thông MobiFone", table_cell_bold),
            Paragraph("Thiết bị định vị và dịch vụ giải pháp", table_cell_style),
            Paragraph("19.5%", table_cell_style),
            Paragraph("Trả chậm 30 ngày", table_cell_style),
        ],
    ]
    t_cust = Table(customers_data, colWidths=[25, 200, 140, 75, 80])
    t_cust.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#002B49")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#B0C4DE")),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(t_cust)
    story.append(Spacer(1, 6))

    # 6. Tuyên bố thị trường & Đối thủ
    story.append(Paragraph("6. VỊ THẾ THỊ TRƯỜNG VÀ TUYÊN BỐ CỦA DOANH NGHIỆP", heading_style))
    market_text = (
        "<b>Tuyên bố thị phần:</b> Chiếm khoảng 22% thị phần phân phối thiết bị IoT chuyên dụng tại Việt Nam.<br/>"
        "<b>Đối thủ cạnh tranh chính:</b> Công ty Cổ phần Viễn thông Á Châu; Công ty TNHH Công nghệ Số Tân Tiến.<br/>"
        "<b>Lợi thế cạnh tranh tự công bố:</b> Lợi thế về dây chuyền công nghệ kiểm thử SMT đạt chuẩn quốc tế và quan hệ hợp tác trực tiếp với Qualcomm."
    )
    story.append(Paragraph(market_text, body_style))

    doc.build(story)
    print(f"[+] Digital Business PDF generated successfully at: {output_path}")


def convert_pdf_to_scanned(input_pdf: str, output_pdf: str):
    """Render PDF pages to raster bitmaps and save as pure image PDF (no text layer)."""
    doc = pypdfium2.PdfDocument(input_pdf)
    images = []
    for page in doc:
        # Render at 200 DPI (scale ~ 2.77)
        bitmap = page.render(scale=2.77)
        pil_image = bitmap.to_pil()
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
    print(f"[+] Scanned (raster image) Business PDF generated successfully at: {output_pdf}")


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_dir = os.path.join(base_dir, "tests", "fixtures", "business")
    legacy_target_dir = os.path.join(base_dir, "tests", "fixtures")
    os.makedirs(target_dir, exist_ok=True)

    font_name, bold_font_name = register_fonts()

    digital_pdf = os.path.join(target_dir, "synthetic_business_digital.pdf")
    scanned_pdf = os.path.join(target_dir, "synthetic_business_scanned.pdf")

    build_digital_business_pdf(digital_pdf, font_name, bold_font_name)
    convert_pdf_to_scanned(digital_pdf, scanned_pdf)

    # Copy to root fixtures dir for convenience
    shutil.copy(digital_pdf, os.path.join(legacy_target_dir, "synthetic_business_digital.pdf"))
    shutil.copy(scanned_pdf, os.path.join(legacy_target_dir, "synthetic_business_scanned.pdf"))
    print("[+] Fixtures copied to tests/fixtures/ as well.")


if __name__ == "__main__":
    main()
