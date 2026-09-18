# -*- coding: utf-8 -*-
import docx
import os
import sys
import copy
from docx.shared import Inches, Pt, RGBColor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

parent_dir = r"c:\Users\minhnh33\Documents\Hackathon"
template_path = os.path.join(parent_dir, "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - Tho.docx")

def populate_exact_mb07_table1(template_path, output_path, data):
    """Clone nguyên bản Table 1 từ template gốc và điền chính xác 100% dữ liệu vào từng ô."""
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

    # Clone Table 1 từ file gốc
    t1_orig = doc_tpl.tables[1]
    tbl_new = doc_new.add_table(rows=0, cols=0)
    tbl_new._tbl.addprevious(copy.deepcopy(t1_orig._tbl))
    doc_new._body._element.remove(tbl_new._tbl)
    
    t1 = doc_new.tables[-1]

    # Điền đúng từng dòng
    # Row 0: Tên khách hàng doanh nghiệp
    t1.rows[0].cells[2].text = data["name"]

    # Row 1: Viết tắt
    t1.rows[1].cells[2].text = data["ticker"]

    # Row 2: Loại hình doanh nghiệp
    t1.rows[2].cells[1].text = "Công ty Cổ phần"

    # Row 3: Tình trạng khách hàng & CIF
    kh_check = "☑ KH mới       ☐ KH hiện hữu" if data.get("customer_status") == "KH mới" else "☐ KH mới       ☑ KH hiện hữu"
    t1.rows[3].cells[2].text = kh_check
    t1.rows[3].cells[4].text = f"CIF: {data.get('cif', '1089562')}"

    # Row 4: Đối tượng khách hàng
    seg_check = "☑ LC              ☐ LMC                 ☐ Khác" if data.get("customer_segment") == "LC" else "☐ LC              ☑ LMC                 ☐ Khác"
    t1.rows[4].cells[2].text = seg_check

    # Row 5: Thuộc nhóm, tập đoàn
    t1.rows[5].cells[2].text = data.get("group", "TẬP ĐOÀN DẦU KHÍ QUỐC GIA VIỆT NAM (PVN)")

    # Row 6: Địa chỉ trụ sở chính
    t1.rows[6].cells[2].text = data.get("address", "Lầu 4, Tòa nhà PetroVietnam, số 1-5 Lê Duẩn, P. Bến Nghé, Quận 1, TP.HCM")

    # Row 7: Số ĐKKD, Ngày cấp, Nơi cấp
    t1.rows[7].cells[2].text = data["tax_code"]
    t1.rows[7].cells[3].text = "Ngày cấp: 28/03/2006 thay đổi lần thứ 16 (ngày 15/08/2024)"
    t1.rows[7].cells[6].text = "Nơi cấp: Sở Kế hoạch và Đầu tư TP. Hồ Chí Minh"

    # Row 8: Thời gian bắt đầu hoạt động
    t1.rows[8].cells[2].text = "28/03/2006"

    # Row 9: Người đại diện theo pháp luật
    t1.rows[9].cells[2].text = data.get("legal_rep", "Ông Nguyễn Ngọc Luận")
    t1.rows[9].cells[3].text = "Chức vụ: Tổng Giám đốc"

    # Row 10: Người đại diện đề nghị cấp tín dụng
    t1.rows[10].cells[2].text = data.get("legal_rep", "Ông Nguyễn Ngọc Luận")
    t1.rows[10].cells[3].text = "Chức vụ: Tổng Giám đốc"

    # Row 11: Đối tượng hạn chế
    t1.rows[11].cells[2].text = "☐ Có"
    t1.rows[11].cells[3].text = "☑ Không"

    # Row 12: Quản lý rủi ro MTXH
    t1.rows[12].cells[2].text = "☐ KH thuộc đối tượng phải đánh giá rủi ro MTXH theo quy định MSB"
    t1.rows[12].cells[3].text = "☑ KH không thuộc đối tượng phải đánh giá rủi ro MTXH theo quy định MSB"

    # Row 13: Doanh thu năm gần nhất
    t1.rows[13].cells[2].text = f"{data['revenue_t_minus_1']/1e6:,.0f} triệu đồng (Theo BCTC kiểm toán 2024)"

    # Row 14: Header ngành (giữ nguyên từ template)
    # Row 15: Ngành nghề kinh doanh chính
    t1.rows[15].cells[1].text = "46611"
    t1.rows[15].cells[2].text = "Bán buôn khí dầu mỏ hóa lỏng (LPG) và khí thiên nhiên nén (CNG)"
    t1.rows[15].cells[5].text = "92.5%"

    # Row 16: Các sản phẩm chính
    t1.rows[16].cells[1].text = "46611"
    t1.rows[16].cells[2].text = "Khí LPG bình dân dụng 12kg-45kg, LPG bồn công nghiệp, Khí nén CNG đốt lò"
    t1.rows[16].cells[5].text = "92.5%"

    # Row 17: Vốn điều lệ đăng ký
    t1.rows[17].cells[2].text = f"Vốn đăng ký: {data.get('charter_capital', 500_000_000_000)/1e6:,.0f} triệu đồng"

    # Row 18: Vốn thực góp & Tính đến ngày
    t1.rows[18].cells[2].text = f"Vốn thực góp: {data['equity_vnd']/1e6:,.0f} triệu đồng"
    t1.rows[18].cells[7].text = "31/12/2024"

    # Row 19: XHTD ID
    t1.rows[19].cells[2].text = "Mã ID của hồ sơ (theo hệ thống XHTD): 1589623"

    # Row 20: XHTD Hạng & Điểm
    t1.rows[20].cells[2].text = "Hạng: A+"
    t1.rows[20].cells[3].text = "Số điểm: 88.5"

    # Row 21: Dư nợ cho vay tại MSB (Link từ CIC Phần E)
    t1.rows[21].cells[2].text = "0 triệu đồng (Link từ Phần E - CIC)"
    t1.rows[21].cells[3].text = "So với quy định của Ngân hàng Nhà nước:\n☐ Vượt giới hạn\n☑ Trong giới hạn"

    # Row 22: Tổng dư tín dụng tại MSB (Link từ CIC Phần E)
    t1.rows[22].cells[2].text = "0 triệu đồng (Link từ Phần E - CIC)"
    t1.rows[22].cells[3].text = "So với quy định của Ngân hàng Nhà nước:\n☐ Vượt giới hạn\n☑ Trong giới hạn"

    # Row 23: Header Thẩm quyền (giữ nguyên)
    # Row 24: HMTD đã cấp cho KH & nhóm KH liên quan
    t1.rows[24].cells[3].text = "0 triệu đồng"
    t1.rows[24].cells[6].text = "0 triệu đồng"

    # Row 25: HMTD đề xuất cấp cho KH lần này
    t1.rows[25].cells[3].text = f"{data['total_limit']/1e6:,.0f} triệu đồng"
    t1.rows[25].cells[6].text = f"{data['unsecured_limit']/1e6:,.0f} triệu đồng"

    # Row 26: Tổng cộng
    t1.rows[26].cells[3].text = f"{data['total_limit']/1e6:,.0f} triệu đồng"
    t1.rows[26].cells[6].text = f"{data['unsecured_limit']/1e6:,.0f} triệu đồng"

    # Row 27: Thẩm quyền phê duyệt đề xuất lần này
    t1.rows[27].cells[2].text = "Thẩm quyền phê duyệt đề xuất lần này:\n☐ HĐTD&ĐT                              ☐ HĐQT\n☑ HĐTDCC"

    # Row 28: Kỳ phê duyệt gần nhất
    t1.rows[28].cells[2].text = "Chưa phát sinh (Hồ sơ cấp mới năm 2026)"

    # Row 29: Đề xuất nhu cầu tín dụng
    t1.rows[29].cells[2].text = "☐ Tái cấp\n☑ Cấp mới"

    # Đặt lại font chữ Times New Roman cho toàn bộ các ô
    for r in t1.rows:
        for c in r.cells:
            for p in c.paragraphs:
                for run in p.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(9.5)
                    run.font.color.rgb = RGBColor(0, 0, 0)

    doc_new.save(output_path)
    print(f"✅ ĐÃ XUẤT THÀNH CÔNG BẢNG PHẦN A CHÍNH XÁC 100%: {output_path}")


if __name__ == "__main__":
    from src.mock_data import SAMPLE_COMPANIES
    pgs = SAMPLE_COMPANIES["GAS_SOUTH"]
    pgs_data = {
        "name": pgs["name"],
        "ticker": pgs["ticker"],
        "tax_code": pgs["tax_code"],
        "years_in_operation": pgs["years_in_operation"],
        "charter_capital": pgs.get("charter_capital", 500_000_000_000),
        "equity_vnd": pgs["equity_vnd"],
        "revenue_t_minus_1": pgs["revenue_t_minus_1"],
        "total_limit": 1_202_375_000_000,
        "unsecured_limit": pgs["requested_unsecured_limit"],
        "cif": "1089562",
        "customer_status": "KH mới",
        "customer_segment": "LC",
        "group": "Tập đoàn Dầu khí Quốc gia Việt Nam (PVN) / PV GAS",
        "address": pgs.get("address", "Lầu 4, Tòa nhà PetroVietnam, 1-5 Lê Duẩn, Q.1, TP.HCM"),
        "legal_rep": pgs.get("legal_rep", "Ông Nguyễn Ngọc Luận")
    }
    
    out_dir = r"c:\Users\minhnh33\Documents\Hackathon\msb_eb_copilot\output"
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "TEST_EXACT_PHAN_A_MSB_TEMPLATE.docx")
    populate_exact_mb07_table1(template_path, out_file, pgs_data)
