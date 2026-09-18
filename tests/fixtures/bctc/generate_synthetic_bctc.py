# -*- coding: utf-8 -*-
"""Generate synthetic Vietnamese Financial Statement (BCTC) PDF fixtures.

Creates:
1. tests/fixtures/bctc/bctc_synthetic_digital.pdf (Selectable text via matplotlib/pypdf)
2. tests/fixtures/bctc/bctc_synthetic_scanned.pdf (Pure raster images via PIL, no text layer)

Contains 2 years of P&L and Balance Sheet with standard Vietnamese accounting codes (TT 200).
Company: CÔNG TY CỔ PHẦN PHÁT TRIỂN CÔNG NGHỆ VẠN XUÂN (MST: 0109988776) - 100% FICTITIOUS.
"""

import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image, ImageDraw, ImageFont
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pypdfium2

OUTPUT_DIR = os.path.join(os.path.dirname(__file__))
os.makedirs(OUTPUT_DIR, exist_ok=True)

DIGITAL_PDF_PATH = os.path.join(OUTPUT_DIR, "bctc_synthetic_digital.pdf")
SCANNED_PDF_PATH = os.path.join(OUTPUT_DIR, "bctc_synthetic_scanned.pdf")

# Page 1: P&L
PAGE_1_LINES = [
    "CÔNG TY CỔ PHẦN PHÁT TRIỂN CÔNG NGHỆ VẠN XUÂN",
    "Mã số thuế: 0109988776",
    "Địa chỉ: Số 88 Phố Cầu Giấy, Phường Dịch Vọng, Cầu Giấy, Hà Nội",
    "-----------------------------------------------------------------------------------------",
    "BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH",
    "Cho năm tài chính kết thúc ngày 31/12/2025",
    "Đơn vị tính: VND",
    "",
    "CHỈ TIÊU | MÃ SỐ | THUYẾT MINH | NĂM 2025 | NĂM 2024",
    "1. Doanh thu bán hàng và cung cấp dịch vụ | 01 | VI.01 | 120.000.000.000 | 100.000.000.000",
    "2. Các khoản giảm trừ doanh thu | 02 | VI.02 | 0 | 0",
    "3. Doanh thu thuần về bán hàng và cung cấp dịch vụ | 10 | VI.03 | 120.000.000.000 | 100.000.000.000",
    "4. Giá vốn hàng bán | 11 | VI.04 | 96.000.000.000 | 82.000.000.000",
    "5. Lợi nhuận gộp về bán hàng và cung cấp dịch vụ | 20 | VI.05 | 24.000.000.000 | 18.000.000.000",
    "6. Doanh thu hoạt động tài chính | 21 | VI.06 | 2.500.000.000 | 1.800.000.000",
    "7. Chi phí tài chính | 22 | VI.07 | 3.200.000.000 | 2.500.000.000",
    "    Trong đó: Chi phí lãi vay | 23 | VI.08 | 2.800.000.000 | 2.200.000.000",
    "8. Chi phí bán hàng | 25 | VI.09 | 6.000.000.000 | 4.800.000.000",
    "9. Chi phí quản lý doanh nghiệp | 26 | VI.10 | 4.500.000.000 | 3.600.000.000",
    "10. Lợi nhuận thuần từ hoạt động kinh doanh | 30 | | 12.800.000.000 | 8.900.000.000",
    "11. Tổng lợi nhuận kế toán trước thuế | 50 | | 12.800.000.000 | 8.900.000.000",
    "12. Chi phí thuế TNDN hiện hành | 51 | | 2.560.000.000 | 1.780.000.000",
    "13. Lợi nhuận sau thuế thu nhập doanh nghiệp | 60 | | 10.240.000.000 | 7.120.000.000",
]

# Page 2: Balance Sheet
PAGE_2_LINES = [
    "CÔNG TY CỔ PHẦN PHÁT TRIỂN CÔNG NGHỆ VẠN XUÂN",
    "Mã số thuế: 0109988776",
    "-----------------------------------------------------------------------------------------",
    "BẢNG CÂN ĐỐI KẾ TOÁN",
    "Tại ngày 31 tháng 12 năm 2025",
    "Đơn vị tính: VND",
    "",
    "TÀI SẢN | MÃ SỐ | THUYẾT MINH | SỐ CUỐI NĂM (2025) | SỐ ĐẦU NĂM (2024)",
    "A. TÀI SẢN NGẮN HẠN | 100 | | 65.000.000.000 | 52.000.000.000",
    "I. Tiền và các khoản tương đương tiền | 110 | V.01 | 8.500.000.000 | 6.200.000.000",
    "II. Đầu tư tài chính ngắn hạn | 120 | V.02 | 0 | 0",
    "III. Các khoản phải thu ngắn hạn | 130 | V.03 | 26.500.000.000 | 21.800.000.000",
    "IV. Hàng tồn kho | 140 | V.04 | 28.000.000.000 | 22.500.000.000",
    "V. Tài sản ngắn hạn khác | 150 | | 2.000.000.000 | 1.500.000.000",
    "B. TÀI SẢN DÀI HẠN | 200 | | 25.000.000.000 | 23.000.000.000",
    "TỔNG CỘNG TÀI SẢN | 270 | | 90.000.000.000 | 75.000.000.000",
    "",
    "NGUỒN VỐN | MÃ SỐ | THUYẾT MINH | SỐ CUỐI NĂM (2025) | SỐ ĐẦU NĂM (2024)",
    "C. NỢ PHẢI TRẢ | 300 | | 45.000.000.000 | 38.000.000.000",
    "I. Nợ ngắn hạn | 310 | | 35.000.000.000 | 30.000.000.000",
    "    Vay và nợ thuê tài chính ngắn hạn | 320 | V.15 | 20.000.000.000 | 16.000.000.000",
    "II. Nợ dài hạn | 330 | | 10.000.000.000 | 8.000.000.000",
    "D. VỐN CHỦ SỞ HỮU | 400 | V.22 | 45.000.000.000 | 37.000.000.000",
    "I. Vốn chủ sở hữu | 410 | | 45.000.000.000 | 37.000.000.000",
    "    1. Vốn góp của chủ sở hữu | 411 | | 30.000.000.000 | 30.000.000.000",
    "TỔNG CỘNG NGUỒN VỐN | 440 | | 90.000.000.000 | 75.000.000.000",
]


def generate_digital_pdf(output_path: str):
    """Generate clean digital text PDF with matplotlib."""
    with PdfPages(output_path) as pdf:
        for page_num, lines in enumerate([PAGE_1_LINES, PAGE_2_LINES], start=1):
            fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4 size in inches
            ax.axis("off")
            
            y_pos = 0.95
            line_height = 0.033
            for line in lines:
                weight = "bold" if any(h in line for h in ["CÔNG TY", "BÁO CÁO", "BẢNG CÂN ĐỐI", "CHỈ TIÊU", "TÀI SẢN", "NGUỒN VỐN", "TỔNG CỘNG"]) else "normal"
                size = 11 if ("CÔNG TY" in line or "BÁO CÁO" in line or "BẢNG CÂN ĐỐI" in line) else 8.5
                ax.text(0.06, y_pos, line, fontsize=size, fontweight=weight, family="sans-serif", verticalalignment="top")
                y_pos -= line_height
            
            # Page number
            ax.text(0.5, 0.03, f"Trang {page_num}/2", fontsize=9, horizontalalignment="center")
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
    print(f"[OK] Generated digital BCTC PDF: {output_path}")


def generate_scanned_pdf(digital_pdf_path: str, output_path: str):
    """Rasterize digital PDF pages to pure images using pypdfium2, creating a true scanned PDF."""
    pdf = pypdfium2.PdfDocument(digital_pdf_path)
    images = []
    for i in range(len(pdf)):
        page = pdf[i]
        # Render at 150 DPI
        pil_img = page.render(scale=150 / 72.0).to_pil()
        # Convert to RGB
        pil_img = pil_img.convert("RGB")
        images.append(pil_img)
    
    if images:
        images[0].save(output_path, save_all=True, append_images=images[1:], resolution=150.0)
    print(f"[OK] Generated scanned BCTC PDF (image-only): {output_path}")


if __name__ == "__main__":
    generate_digital_pdf(DIGITAL_PDF_PATH)
    generate_scanned_pdf(DIGITAL_PDF_PATH, SCANNED_PDF_PATH)
