# -*- coding: utf-8 -*-
"""
Script: test_thep_mien_nam_clean.py
Mô tả: Chạy kiểm thử xuất Phần A chuẩn 100% cho CÔNG TY TNHH MTV THÉP MIỀN NAM - VNSTEEL:
1. Xóa toàn bộ các chú thích thừa trong ngoặc: (RM cung cấp), (Auto chọn), (Lấy data từ Phần E), (Nguồn: BCTC)...
2. Logic tick checkbox dựa trên dữ liệu thực tế (Đánh giá rủi ro MTXH, Giới hạn NHNN, Khách hàng hạn chế).
3. Thêm tùy chọn "Tái cấp tăng" vào mục Đề xuất nhu cầu tín dụng: [ ] Tái cấp   [ ] Tái cấp tăng   [X] Cấp mới.
"""

import os
import sys
import copy
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.table import WD_TABLE_ALIGNMENT

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

parent_dir = r"c:\Users\minhnh33\Documents\Hackathon"
template_path = os.path.join(parent_dir, "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - Tho.docx")
out_dir = r"c:\Users\minhnh33\Documents\Hackathon\msb_eb_copilot\output"
os.makedirs(out_dir, exist_ok=True)
out_docx = os.path.join(out_dir, "TO_TRINH_MB07_PHAN_A_THEP_MIEN_NAM_CLEAN.docx")


def generate_clean_section_a_thep_mien_nam():
    doc_tpl = docx.Document(template_path)
    doc_new = docx.Document()

    for s in doc_new.sections:
        s.top_margin = Inches(0.6)
        s.bottom_margin = Inches(0.6)
        s.left_margin = Inches(0.7)
        s.right_margin = Inches(0.7)

    # Tiêu đề Phần A
    p = doc_new.add_paragraph()
    r = p.add_run("PHẦN A. TÓM TẮT THÔNG TIN CHUNG")
    r.bold = True
    r.font.size = Pt(12)
    r.font.name = "Times New Roman"

    # Clone nguyên bản Table 1 từ template MSB
    t1_orig = doc_tpl.tables[1]
    tbl_new = doc_new.add_table(rows=0, cols=0)
    tbl_new._tbl.addprevious(copy.deepcopy(t1_orig._tbl))
    doc_new._body._element.remove(tbl_new._tbl)
    t1 = doc_new.tables[-1]

    # Xử lý Row 2: tháo bỏ thẻ <w:sdt> dropdown của MSB để thành ô w:tc chuẩn (2 ô: Label và Value)
    r2_tr = t1.rows[2]._tr
    sdt_elem = r2_tr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}sdt')
    if sdt_elem is not None:
        tc_inside = sdt_elem.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc')
        if tc_inside is not None:
            r2_tr.replace(sdt_elem, tc_inside)

    # --- ĐIỀN DỮ LIỆU SẠCH 100% (KHÔNG CHÚ THÍCH NGOẶC) ---
    
    # Row 0: Tên KHDN
    t1.rows[0].cells[2].text = "CÔNG TY TRÁCH NHIỆM HỮU HẠN MỘT THÀNH VIÊN THÉP MIỀN NAM - VNSTEEL"

    # Row 1: Viết tắt
    t1.rows[1].cells[2].text = "SSCV"

    # Row 2: Loại hình DN
    t1.rows[2].cells[0].text = "Loại hình doanh nghiệp"
    t1.rows[2].cells[2].text = "Công ty TNHH MTV"

    # Row 3: Tình trạng KH & CIF
    t1.rows[3].cells[2].text = "☑ KH mới       ☐ KH hiện hữu"
    t1.rows[3].cells[4].text = "CIF: 1689234"

    # Row 4: Đối tượng KH
    t1.rows[4].cells[2].text = "☑ LC              ☐ LMC                 ☐ Khác"

    # Row 5: Thuộc nhóm, tập đoàn
    t1.rows[5].cells[2].text = "TỔNG CÔNG TY THÉP VIỆT NAM - CTCP (VNSTEEL)"

    # Row 6: Địa chỉ trụ sở chính
    t1.rows[6].cells[2].text = "Khu công nghiệp Phú Mỹ 1, Phường Phú Mỹ, Thị xã Phú Mỹ, Tỉnh Bà Rịa - Vũng Tàu"

    # Row 7: Số ĐKKD, Ngày cấp, Nơi cấp
    t1.rows[7].cells[2].text = "3502269994"
    t1.rows[7].cells[3].text = "Ngày cấp: 10/12/2014 thay đổi lần thứ 8 ngày 11/07/2025"
    t1.rows[7].cells[6].text = "Nơi cấp: Sở Tài chính Tỉnh Bà Rịa - Vũng Tàu"

    # Row 8: Thời gian bắt đầu hoạt động
    t1.rows[8].cells[2].text = "10/12/2014"

    # Row 9: Người đại diện theo pháp luật
    t1.rows[9].cells[2].text = "Lê Việt"
    t1.rows[9].cells[3].text = "Chức vụ: Tổng giám đốc"

    # Row 10: Người đại diện đề nghị cấp tín dụng
    t1.rows[10].cells[2].text = "Lê Việt"
    t1.rows[10].cells[3].text = "Chức vụ: Tổng giám đốc"

    # Row 11: Đối tượng hạn chế cấp TD (Đánh giá theo data blacklist: Không vi phạm)
    t1.rows[11].cells[2].text = "☐ Có"
    t1.rows[11].cells[3].text = "☑ Không"

    # Row 12: Quản lý rủi ro MTXH (Đánh giá theo phân loại ngành Thép: Không thuộc diện dự án đặc biệt rủi ro MTXH)
    t1.rows[12].cells[2].text = "☐ KH thuộc đối tượng phải đánh giá rủi ro MTXH theo quy định MSB"
    t1.rows[12].cells[3].text = "☑ KH không thuộc đối tượng phải đánh giá rủi ro MTXH theo quy định MSB"

    # Row 13: Doanh thu năm gần nhất
    t1.rows[13].cells[2].text = "7.469.517 triệu đồng (Theo BCTC kiểm toán 2024)"

    # Row 14: Header ngành (giữ nguyên cấu trúc)
    # Row 15: Ngành nghề kinh doanh chính
    t1.rows[15].cells[1].text = "24100"
    t1.rows[15].cells[2].text = "Sản xuất sắt, thép, gang (Luyện cán thép xây dựng cuộn và thanh vằn)"
    t1.rows[15].cells[5].text = "95%"

    # Row 16: Các sản phẩm chính
    t1.rows[16].cells[1].text = "24100"
    t1.rows[16].cells[2].text = "Thép cuộn phi 6, phi 8; Thép thanh vằn D10 - D40 mác CB300, CB400, CB500 mang thương hiệu 'V'"
    t1.rows[16].cells[5].text = "95%"

    # Row 17: Vốn đăng ký
    t1.rows[17].cells[2].text = "Vốn đăng ký: 1.000.000 triệu đồng"

    # Row 18: Vốn thực góp & Tính đến ngày
    t1.rows[18].cells[2].text = "Vốn thực góp: 1.000.000 triệu đồng"
    t1.rows[18].cells[7].text = "31/12/2024"

    # Row 19: XHTD ID
    t1.rows[19].cells[2].text = "Mã ID của hồ sơ (theo hệ thống XHTD): XHTD-2026-SSCV-001"

    # Row 20: XHTD Hạng & Điểm
    t1.rows[20].cells[2].text = "Hạng: AA"
    t1.rows[20].cells[3].text = "Số điểm: 93.5"

    # Row 21: Dư nợ cho vay tại MSB (Dữ liệu từ CIC: Chưa phát sinh nợ tại MSB)
    t1.rows[21].cells[2].text = "0 triệu đồng"
    t1.rows[21].cells[3].text = "So với quy định của Ngân hàng Nhà nước:\n☐ Vượt giới hạn\n☑ Trong giới hạn"

    # Row 22: Tổng dư tín dụng tại MSB
    t1.rows[22].cells[2].text = "0 triệu đồng"
    t1.rows[22].cells[3].text = "So với quy định của Ngân hàng Nhà nước:\n☐ Vượt giới hạn\n☑ Trong giới hạn"

    # Row 23: Header Thẩm quyền
    # Row 24: HMTD đã cấp cho KH & nhóm liên quan
    t1.rows[24].cells[3].text = "0 triệu đồng"
    t1.rows[24].cells[6].text = "0 triệu đồng"

    # Row 25: HMTD đề xuất cấp cho KH lần này
    t1.rows[25].cells[3].text = "1.500.000 triệu đồng"
    t1.rows[25].cells[6].text = "500.000 triệu đồng"

    # Row 26: Tổng cộng
    t1.rows[26].cells[3].text = "1.500.000 triệu đồng"
    t1.rows[26].cells[6].text = "500.000 triệu đồng"

    # Row 27: Thẩm quyền phê duyệt đề xuất lần này
    t1.rows[27].cells[2].text = "Thẩm quyền phê duyệt đề xuất lần này:\n☐ HĐTD&ĐT                              ☐ HĐQT\n☑ HĐTDCC"

    # Row 28: Kỳ phê duyệt gần nhất
    t1.rows[28].cells[2].text = "Chưa phát sinh (Hồ sơ cấp mới năm 2026)"

    # Row 29: Đề xuất nhu cầu tín dụng (Bổ sung đầy đủ 3 options: Tái cấp, Tái cấp tăng, Cấp mới)
    t1.rows[29].cells[2].text = "☐ Tái cấp       ☐ Tái cấp tăng       ☑ Cấp mới"

    # Format Font chuẩn Times New Roman, màu đen
    for row in t1.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                for run in para.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(9.5)
                    run.font.color.rgb = RGBColor(0, 0, 0)

    doc_new.save(out_docx)
    print(f"✅ ĐÃ XUẤT THÀNH CÔNG BẢN WORD SẠCH 100%: {out_docx}")


if __name__ == "__main__":
    generate_clean_section_a_thep_mien_nam()
