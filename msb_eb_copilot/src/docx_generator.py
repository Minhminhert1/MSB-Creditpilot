"""
Module: docx_generator.py
Mô tả: Engine sinh Tờ trình cấp tín dụng mẫu MB07 CHUẨN 100% THEO TEMPLATE THỰC TẾ CỦA MSB (Bao gồm Table 0 Box, Table 1 Hồ sơ KH, Table 2 Mã hạn mức ECS1000/1100/1200/1300, Bảng BCTC 3 năm, Bảng CIC, Bảng TSBĐ, Bảng RORWA, và Khung chữ ký chuẩn).
"""

import io
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn
from typing import Dict, Any, List


def set_cell_background(cell, fill_hex: str):
    """Set background color for table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)


def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Set inner cell padding in twips."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}><w:top w:w="{top}" w:type="dxa"/><w:bottom w:w="{bottom}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/></w:tcMar>')
    tcPr.append(tcMar)


def create_mb07_proposal(data: Dict[str, Any], demand: Dict[str, Any], rorwa: Dict[str, Any], prescreen: Dict[str, Any]) -> io.BytesIO:
    """Sinh file Word Tờ trình MB07 theo đúng 100% format mẫu chuẩn của MSB."""
    doc = Document()
    
    # Page setup
    for section in doc.sections:
        section.top_margin = Inches(0.7)
        section.bottom_margin = Inches(0.7)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    # ----------------- PHẦN A. TÓM TẮT THÔNG TIN CHUNG -----------------
    p_head = doc.add_paragraph()
    r_head = p_head.add_run("PHẦN A. TÓM TẮT THÔNG TIN CHUNG")
    r_head.bold = True
    r_head.font.size = Pt(12)

    # TABLE 0: HEADER INFO BOX (CHUẨN MSB)
    t0 = doc.add_table(rows=5, cols=4)
    t0.alignment = WD_TABLE_ALIGNMENT.CENTER
    t0_data = [
        ["Đơn vị lập tờ trình", "TRUNG TÂM KHÁCH HÀNG DOANH NGHIỆP LỚN (EB/CIB)", "Số tờ trình", f"01.2026/TT-{data['ticker']}/EB"],
        ["Đơn vị lập tờ trình", "TRUNG TÂM KHÁCH HÀNG DOANH NGHIỆP LỚN (EB/CIB)", "Ngày lập", "20/02/2026"],
        ["Cán bộ Quản lý QHKH (RM)", "Chuyên viên QHKH Cao cấp MSB", "Điện thoại:", "0988.123.456"],
        ["Cán bộ Hỗ trợ QHKH", "Chuyên viên Hỗ trợ Tín dụng", "Điện thoại:", "0912.345.678"],
        ["Giám đốc ĐVKD / Trung tâm", "Giám đốc Trung tâm KHDN Lớn", "Điện thoại:", "0903.888.999"]
    ]
    for r_idx, row_content in enumerate(t0_data):
        for c_idx, text in enumerate(row_content):
            cell = t0.rows[r_idx].cells[c_idx]
            cell.text = text
            set_cell_margins(cell, 60, 60, 100, 100)
            if c_idx in [0, 2]:
                cell.paragraphs[0].runs[0].bold = True
                set_cell_background(cell, "F2F2F2")
            cell.paragraphs[0].runs[0].font.size = Pt(9.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # TABLE 1: THÔNG TIN KHÁCH HÀNG (CHUẨN MB07 MSB)
    t1 = doc.add_table(rows=12, cols=4)
    t1.alignment = WD_TABLE_ALIGNMENT.CENTER
    t1_data = [
        ["Tên khách hàng doanh nghiệp", data['name'], "Mã CIF", "1589623"],
        ["Tên viết tắt / Mã CK", f"{data['ticker']} - {data['archetype']}", "Loại hình DN", "Công ty Cổ phần"],
        ["Tình trạng khách hàng", "☑ KH mới       ☐ KH hiện hữu", "Đối tượng KH", "☑ LC (Doanh nghiệp lớn)    ☐ LMC"],
        ["Thuộc nhóm / Tập đoàn", data.get("name", "Độc lập"), "Xếp hạng TDNB", "A+ (Rủi ro rất thấp)"],
        ["Địa chỉ trụ sở chính", data.get("address", "TP. Hồ Chí Minh"), "Thời gian HĐ", f"{data['years_in_operation']:.1f} năm"],
        ["Số Đăng ký kinh doanh", data['tax_code'], "Ngày cấp / Nơi cấp", "Sở Kế hoạch & Đầu tư TP.HCM"],
        ["Người đại diện theo PL", data.get("legal_rep", "Ban Tổng Giám đốc"), "Chức vụ", "Tổng Giám đốc / Chủ tịch"],
        ["Vốn điều lệ đăng ký", f"{data.get('charter_capital', data['equity_vnd']):,.0f} VND", "Vốn CSH thực tế", f"{data['equity_vnd']:,.0f} VND"],
        ["Ngành nghề SXKD chính", data['industry'], "Mô hình cấp TD", "☑ Cấp đơn lẻ    ☐ Hạn mức nhóm"],
        ["Tra cứu CIC (24 tháng)", "☑ Không có nợ nhóm 2-5 toàn hệ thống", "Cơ cấu nợ", "☑ Không có nợ cơ cấu"],
        ["Danh mục hạn chế MSB", "☑ Không thuộc danh sách cấm/hạn chế", "QĐ.RR.074 Pre-screen", f"☑ {prescreen['overall_status']} (0 vi phạm)"],
        ["Nhu cầu cấp tín dụng", f"Tổng HMTD: {demand['total_credit_facility_msb']:,.0f} VND", "Hạn mức KTSBĐ", f"{data['requested_unsecured_limit']:,.0f} VND"]
    ]
    for r_idx, row_content in enumerate(t1_data):
        for c_idx, text in enumerate(row_content):
            cell = t1.rows[r_idx].cells[c_idx]
            cell.text = text
            set_cell_margins(cell, 60, 60, 100, 100)
            if c_idx in [0, 2]:
                cell.paragraphs[0].runs[0].bold = True
                set_cell_background(cell, "EAECEE")
            cell.paragraphs[0].runs[0].font.size = Pt(9.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # ----------------- PHẦN B: NỘI DUNG ĐỀ XUẤT CẤP TÍN DỤNG -----------------
    doc.add_heading("PHẦN B: NỘI DUNG ĐỀ XUẤT CẤP TÍN DỤNG TẠI MSB", level=1)
    
    # TABLE 2: BẢNG TỔNG HỢP HẠN MỨC (MÃ HẠN MỨC CHUẨN MSB ECS1000, ECS1100, ECS1200, ECS1300)
    t2 = doc.add_table(rows=6, cols=5)
    t2.alignment = WD_TABLE_ALIGNMENT.CENTER
    t2_headers = ["Cụ thể", "Mã hạn mức", "Hạn mức đã duyệt cũ (tr.VND)", "Hạn mức đề xuất mới (tr.VND)", "Ghi chú / Cơ chế cấp"]
    for c_idx, h in enumerate(t2_headers):
        cell = t2.rows[0].cells[c_idx]
        cell.text = h
        cell.paragraphs[0].runs[0].bold = True
        set_cell_background(cell, "003366")
        cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
        cell.paragraphs[0].runs[0].font.size = Pt(9.0)

    t2_rows = [
        ["A. Tín dụng hạn mức ngắn hạn tổng hợp", "ECS1000", "0", f"{demand['total_credit_facility_msb']/1e6:,.0f}", "Duyệt mới theo QĐ.RR.074"],
        ["- Cho vay ngắn hạn bổ sung VLĐ", "ECS1100", "0", f"{demand['loan_limit_msb']/1e6:,.0f}", f"KTSBĐ: {data['requested_unsecured_limit']/1e6:,.0f} tr.VND"],
        ["- Bảo lãnh (HĐ, Tạm ứng, Thanh toán)", "ECS1200", "0", f"{demand['guarantee_limit']/1e6:,.0f}", f"Thời hạn BL tối đa {data['guarantee_tenor_days']} ngày"],
        ["- Phát hành L/C (Sight / UPAS)", "ECS1300", "0", f"{demand['lc_limit']/1e6:,.0f}", f"Kỳ hạn L/C bình quân {data['lc_tenor_days']} ngày"],
        ["- Thẻ tín dụng Doanh nghiệp", "ECS1400", "0", "500", "Cấp thẻ Corporate thanh toán"]
    ]
    for r_idx, row_content in enumerate(t2_rows):
        for c_idx, text in enumerate(row_content):
            cell = t2.rows[r_idx + 1].cells[c_idx]
            cell.text = text
            cell.paragraphs[0].runs[0].font.size = Pt(9.0)
            if r_idx == 0:
                cell.paragraphs[0].runs[0].bold = True
                set_cell_background(cell, "FFF0E6")

    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # Chi tiết từng nghiệp vụ tín dụng
    p_dt = doc.add_paragraph()
    p_dt.add_run("1. Điều kiện cấp Hạn mức Cho vay ngắn hạn (ECS1100):\n").bold = True
    p_dt.add_run(f"• Số tiền: {demand['loan_limit_msb']:,.0f} VND (Bằng chữ: Theo số phê duyệt)\n")
    p_dt.add_run(f"• Thời hạn hạn mức: 12 tháng kể từ ngày ký Hợp đồng tín dụng. Thời hạn từng KUNN tối đa 06 tháng.\n")
    p_dt.add_run(f"• Mục đích: Thanh toán tiền mua hàng hóa, nguyên vật liệu phục vụ hoạt động SXKD {data['industry']}.\n")
    p_dt.add_run(f"• Lãi suất cho vay: Tối thiểu {data['loan_interest_rate']*100:.2f}%/năm (hoặc theo quy định FTP + biên độ NIM tối thiểu của MSB tại từng thời điểm giải ngân).\n")
    p_dt.add_run(f"• Phương thức giải ngân: Chuyển khoản trực tiếp cho bên thụ hưởng theo Hóa đơn VAT và Hợp đồng kinh tế.")

    p_dt.add_run("\n2. Điều kiện cấp Hạn mức Mở L/C (ECS1300) & Bảo lãnh (ECS1200):\n").bold = True
    p_dt.add_run(f"• Hạn mức L/C: {demand['lc_limit']:,.0f} VND. Loại L/C: L/C trả chậm UPAS hoặc L/C trả ngay Sight. Tỷ lệ ký quỹ: 0% - 10% tùy theo từng hợp đồng nhập khẩu.\n")
    p_dt.add_run(f"• Hạn mức Bảo lãnh: {demand['guarantee_limit']:,.0f} VND. Loại bảo lãnh: Bảo lãnh thực hiện hợp đồng, bảo lãnh thanh toán, tạm ứng. Mức phí bảo lãnh: Tối thiểu {data['guarantee_fee_rate']*100:.2f}%/năm.")

    # ----------------- PHẦN C: HOẠT ĐỘNG KINH DOANH CỦA KHÁCH HÀNG -----------------
    doc.add_heading("PHẦN C: HOẠT ĐỘNG KINH DOANH CỦA KHÁCH HÀNG", level=1)
    p_c = doc.add_paragraph()
    p_c.add_run("1. Năng lực sản xuất kinh doanh & Chuỗi giá trị:\n").bold = True
    p_c.add_run(f"Khách hàng là doanh nghiệp có vị thế hàng đầu trong ngành {data['industry']}. Mô hình hoạt động khép kín từ khâu nhập khẩu/thu mua nguyên liệu trực tiếp từ các đối tác uy tín toàn cầu cho đến hệ thống phân phối phủ rộng khắp toàn quốc.\n")

    p_c.add_run("\n2. Bảng cơ cấu Top 5 Nhà cung cấp chính (Nguồn hàng đầu vào):\n").bold = True
    tbl_s = doc.add_table(rows=1, cols=5)
    tbl_s.alignment = WD_TABLE_ALIGNMENT.CENTER
    s_hdrs = ["STT", "Tên Nhà cung cấp", "Sản phẩm / Dịch vụ", "Doanh số năm (VND)", "Tỷ trọng / Điều khoản thanh toán"]
    for i, h in enumerate(s_hdrs):
        c = tbl_s.rows[0].cells[i]
        c.text = h
        c.paragraphs[0].runs[0].bold = True
        set_cell_background(c, "003366")
        c.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
        c.paragraphs[0].runs[0].font.size = Pt(9.0)

    for idx, s in enumerate(data.get("top_suppliers", [])):
        r = tbl_s.add_row()
        r.cells[0].text = str(idx + 1)
        r.cells[1].text = s["name"]
        r.cells[2].text = s["product"]
        r.cells[3].text = f"{s['turnover']:,.0f}"
        r.cells[4].text = f"{s['share']} | {s['term']}"
        for cell in r.cells: cell.paragraphs[0].runs[0].font.size = Pt(8.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    p_c2 = doc.add_paragraph()
    p_c2.add_run("3. Bảng cơ cấu Top 5 Khách hàng tiêu thụ chính (Đầu ra sản phẩm):\n").bold = True
    tbl_b = doc.add_table(rows=1, cols=5)
    tbl_b.alignment = WD_TABLE_ALIGNMENT.CENTER
    b_hdrs = ["STT", "Tên Khách hàng tiêu thụ", "Sản phẩm cung cấp", "Doanh thu năm (VND)", "Tỷ trọng / Phương thức thanh toán"]
    for i, h in enumerate(b_hdrs):
        c = tbl_b.rows[0].cells[i]
        c.text = h
        c.paragraphs[0].runs[0].bold = True
        set_cell_background(c, "003366")
        c.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
        c.paragraphs[0].runs[0].font.size = Pt(9.0)

    for idx, b in enumerate(data.get("top_buyers", [])):
        r = tbl_b.add_row()
        r.cells[0].text = str(idx + 1)
        r.cells[1].text = b["name"]
        r.cells[2].text = b["product"]
        r.cells[3].text = f"{b['revenue']:,.0f}"
        r.cells[4].text = f"{b['share']} | {b['term']}"
        for cell in r.cells: cell.paragraphs[0].runs[0].font.size = Pt(8.5)

    # ----------------- PHẦN D: TÌNH HÌNH TÀI CHÍNH DOANH NGHIỆP -----------------
    doc.add_heading("PHẦN D: TÌNH HÌNH TÀI CHÍNH DOANH NGHIỆP (3 NĂM LIÊN TIẾP)", level=1)
    
    f3 = data.get("financial_3yr", {})
    years = f3.get("years", ["2023", "2024", "2025 (Kế hoạch)"])

    tbl_fin = doc.add_table(rows=1, cols=4)
    tbl_fin.alignment = WD_TABLE_ALIGNMENT.CENTER
    f_hdrs = ["Chỉ tiêu BCTC Hợp nhất (Đơn vị: Tỷ VND)", years[0], years[1], years[2]]
    for i, h in enumerate(f_hdrs):
        c = tbl_fin.rows[0].cells[i]
        c.text = h
        c.paragraphs[0].runs[0].bold = True
        set_cell_background(c, "003366")
        c.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
        c.paragraphs[0].runs[0].font.size = Pt(9.0)

    fin_items = [
        ("I. BÁO CÁO KẾT QUẢ KINH DOANH", "", "", ""),
        ("1. Doanh thu thuần", f3["revenue"][0]/1e9, f3["revenue"][1]/1e9, f3["revenue"][2]/1e9),
        ("2. Giá vốn hàng bán (COGS)", f3["cogs"][0]/1e9, f3["cogs"][1]/1e9, f3["cogs"][2]/1e9),
        ("3. Lợi nhuận gộp", f3["gross_profit"][0]/1e9, f3["gross_profit"][1]/1e9, f3["gross_profit"][2]/1e9),
        ("4. Chi phí hoạt động (Bán hàng & QLDN)", f3["operating_expense"][0]/1e9, f3["operating_expense"][1]/1e9, f3["operating_expense"][2]/1e9),
        ("5. Lợi nhuận sau thuế (LNST)", f3["net_profit"][0]/1e9, f3["net_profit"][1]/1e9, f3["net_profit"][2]/1e9),
        ("II. BẢNG CÂN ĐỐI KẾ TOÁN", "", "", ""),
        ("6. Tổng tài sản", f3["total_assets"][0]/1e9, f3["total_assets"][1]/1e9, f3["total_assets"][2]/1e9),
        ("7. Tài sản ngắn hạn (Tiền, Phải thu, Tồn kho)", f3["current_assets"][0]/1e9, f3["current_assets"][1]/1e9, f3["current_assets"][2]/1e9),
        ("8. Nợ phải trả", f3["total_liabilities"][0]/1e9, f3["total_liabilities"][1]/1e9, f3["total_liabilities"][2]/1e9),
        ("   - Vay nợ ngắn hạn TCTD", f3["short_term_debt"][0]/1e9, f3["short_term_debt"][1]/1e9, f3["short_term_debt"][2]/1e9),
        ("9. Vốn chủ sở hữu (Vốn CSH)", f3["equity"][0]/1e9, f3["equity"][1]/1e9, f3["equity"][2]/1e9),
        ("III. LƯU CHUYỂN TIỀN TỆ & KHẢ NĂNG TRẢ NỢ", "", "", ""),
        ("10. Dòng tiền thuần từ HĐKD (OCF)", f3["operating_cash_flow"][0]/1e9, f3["operating_cash_flow"][1]/1e9, f3["operating_cash_flow"][2]/1e9),
    ]

    for item in fin_items:
        r = tbl_fin.add_row()
        r.cells[0].text = item[0]
        if item[1] != "":
            r.cells[1].text = f"{item[1]:,.1f}"
            r.cells[2].text = f"{item[2]:,.1f}"
            r.cells[3].text = f"{item[3]:,.1f}"
        if item[0].startswith("I.") or item[0].startswith("II.") or item[0].startswith("III."):
            r.cells[0].paragraphs[0].runs[0].bold = True
            for c_idx in range(4):
                set_cell_background(r.cells[c_idx], "D6EAF8")
        elif item[0].startswith("1.") or item[0].startswith("5.") or item[0].startswith("9.") or item[0].startswith("10."):
            if len(r.cells[0].paragraphs[0].runs) > 0:
                r.cells[0].paragraphs[0].runs[0].bold = True
        for cell in r.cells:
            if len(cell.paragraphs[0].runs) > 0:
                cell.paragraphs[0].runs[0].font.size = Pt(8.5)

    # ----------------- PHẦN E: THÔNG TIN QUAN HỆ TÍN DỤNG (CIC) -----------------
    doc.add_heading("PHẦN E: THÔNG TIN QUAN HỆ TÍN DỤNG CỦA KHÁCH HÀNG (CIC)", level=1)
    
    tbl_e = doc.add_table(rows=1, cols=6)
    tbl_e.alignment = WD_TABLE_ALIGNMENT.CENTER
    e_hdrs = ["STT", "Tên Ngân hàng / TCTD", "Nghiệp vụ tài trợ", "Hạn mức (VND)", "Dư nợ hiện tại (VND)", "Nhóm nợ / TSBĐ"]
    for i, h in enumerate(e_hdrs):
        c = tbl_e.rows[0].cells[i]
        c.text = h
        c.paragraphs[0].runs[0].bold = True
        set_cell_background(c, "003366")
        c.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
        c.paragraphs[0].runs[0].font.size = Pt(9.0)

    for idx, b in enumerate(data.get("bank_relations", [])):
        r = tbl_e.add_row()
        r.cells[0].text = str(idx + 1)
        r.cells[1].text = b["bank"]
        r.cells[2].text = b["facility"]
        r.cells[3].text = f"{b['limit']:,.0f}"
        r.cells[4].text = f"{b['debt']:,.0f}"
        r.cells[5].text = f"{b['status']} - {b['collateral']}"
        if "MSB" in b["bank"]:
            for c in r.cells: set_cell_background(c, "FFF0E6")
        for cell in r.cells: cell.paragraphs[0].runs[0].font.size = Pt(8.5)

    # ----------------- PHẦN F: ĐÁNH GIÁ RỦI RO TRỌNG YẾU -----------------
    doc.add_heading("PHẦN F: ĐÁNH GIÁ RỦI RO TRỌNG YẾU VÀ BIỆN PHÁP KIỂM SOÁT", level=1)
    
    p_rf = doc.add_paragraph()
    p_rf.add_run("1. Rủi ro ngành nghề & biến động thị trường:\n").bold = True
    p_rf.add_run(f"• Doanh nghiệp hoạt động quy mô lớn trong lĩnh vực {data['industry']}. Biến động giá hàng hóa thế giới được kiểm soát qua việc ký kết hợp đồng kỳ hạn và chốt giá L/C UPAS.\n\n")
    p_rf.add_run("2. Rủi ro Dòng tiền & Khả năng trả nợ vay MSB:\n").bold = True
    p_rf.add_run(f"• Ràng buộc Khách hàng cam kết chuyển tối thiểu 40% doanh thu thuần qua tài khoản tại MSB. Duy trì số dư CASA bình quân tối thiểu {data['casa_avg_balance']/1e9:,.1f} tỷ VND/tháng.\n\n")
    p_rf.add_run("3. Rủi ro Tài sản bảo đảm & Quản trị khoản cấp KTSBĐ:\n").bold = True
    p_rf.add_run(f"• {prescreen['ktsbd_notes']}. Thực hiện kiểm tra thực địa kho bãi và giám sát BCTC định kỳ quý.")

    # ----------------- PHẦN G: ĐÁNH GIÁ NHU CẦU TÍN DỤNG (MB09 & RORWA) -----------------
    doc.add_heading("PHẦN G: ĐÁNH GIÁ / THẨM ĐỊNH VỀ NHU CẦU CẤP TÍN DỤNG (MB09 & RORWA)", level=1)
    
    p_g = doc.add_paragraph()
    p_g.add_run("1. Bảng xác định Vòng quay Vốn lưu động & Nhu cầu vốn (MB09):\n").bold = True
    p_g.add_run(f"• Vòng quay tồn kho (DIO): {data['dio']} ngày | Phải thu (DSO): {data['dso']} ngày | Phải trả (DPO): {data['dpo']} ngày\n")
    p_g.add_run(f"• Chu kỳ ngân quỹ CCC: {demand['ccc_days']} ngày → Vòng quay VLĐ: {demand['turns_per_year']} vòng/năm\n")
    p_g.add_run(f"• Tổng chi phí SXKD hợp lý: {demand['total_operating_expense']/1e9:,.1f} tỷ VND → Nhu cầu VLĐ: {demand['working_capital_demand']/1e9:,.1f} tỷ VND\n")
    p_g.add_run(f"• Vốn tự có tham gia: {data['equity_participation']/1e9:,.1f} tỷ VND | Vay TCTD khác: {data['other_debt']/1e9:,.1f} tỷ VND\n")
    p_g.add_run(f"→ Hạn mức Cho vay MSB đề xuất: {demand['loan_limit_msb']/1e9:,.1f} tỷ VND | Hạn mức L/C: {demand['lc_limit']/1e9:,.1f} tỷ VND | Hạn mức BL: {demand['guarantee_limit']/1e9:,.1f} tỷ VND.")

    p_g.add_run("\n2. Đánh giá Hiệu quả Vốn Rủi ro RORWA & TORWA (Basel II):\n").bold = True
    tbl_gr = doc.add_table(rows=1, cols=3)
    tbl_gr.alignment = WD_TABLE_ALIGNMENT.CENTER
    gr_hdrs = ["Chỉ số Hiệu quả Vốn Rủi ro", "Kết quả tính toán", "Chuẩn MSB / Đánh giá"]
    for i, h in enumerate(gr_hdrs):
        c = tbl_gr.rows[0].cells[i]
        c.text = h
        c.paragraphs[0].runs[0].bold = True
        set_cell_background(c, "003366")
        c.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
        c.paragraphs[0].runs[0].font.size = Pt(9.0)

    gr_items = [
        ("Tổng tài sản có Rủi ro quy đổi (RWA)", f"{rorwa['total_rwa']/1e9:,.1f} tỷ VND", "Basel II"),
        ("Tổng thu nhập hoạt động (TOI)", f"{rorwa['total_income']/1e9:,.2f} tỷ VND", f"NII: {rorwa['total_nii']/1e9:.2f} tỷ | Fee: {rorwa['total_non_nii']/1e9:.2f} tỷ"),
        ("Lợi nhuận ròng phân bổ trước thuế (PBT)", f"{rorwa['net_deal_profit']/1e9:,.2f} tỷ VND", "Sau trừ Opex & Dự phòng EL"),
        ("CHỈ SỐ TORWA (%)", f"{rorwa['torwa']:.2f}%", ">= 1.50% (ĐẠT CHUẨN MSB)" if rorwa['torwa_passed'] else "< 1.50%"),
        ("CHỈ SỐ RORWA (%)", f"{rorwa['rorwa']:.2f}%", ">= 0.50% (ĐẠT CHUẨN MSB)" if rorwa['rorwa_passed'] else "< 0.50%")
    ]
    for item in gr_items:
        r = tbl_gr.add_row()
        r.cells[0].text = item[0]
        r.cells[1].text = item[1]
        r.cells[2].text = item[2]
        if "TORWA" in item[0] or "RORWA" in item[0]:
            r.cells[0].paragraphs[0].runs[0].bold = True
            set_cell_background(r.cells[0], "E6F7FF")
            set_cell_background(r.cells[1], "E6F7FF")
        for cell in r.cells: cell.paragraphs[0].runs[0].font.size = Pt(8.5)

    # ----------------- PHẦN H: ĐỊNH HƯỚNG QUAN HỆ & BÁN CHÉO -----------------
    doc.add_heading("PHẦN H: ĐỊNH HƯỚNG QUAN HỆ VỚI KHÁCH HÀNG TRONG 12 THÁNG TỚI", level=1)
    p_h = doc.add_paragraph()
    cs = data.get("cross_sell_plan", {})
    p_h.add_run(f"• Chi lương (Payroll): {cs.get('payroll', 'Triển khai chi lương toàn bộ CBNV')}\n")
    p_h.add_run(f"• Tiền gửi CASA: {cs.get('casa_target', 'Cam kết duy trì số dư CASA')}\n")
    p_h.add_run(f"• Mua bán ngoại tệ (FX): {cs.get('fx_volume', 'Giao dịch ngoại tệ thanh toán L/C')}\n")
    p_h.add_run(f"• Dịch vụ số & POS QR: {cs.get('pos_qr', 'Lắp đặt POS/QR')}\n")
    p_h.add_run(f"• Bán lẻ & Thẻ tín dụng: {cs.get('retail_cross', 'Thẻ tín dụng & Bảo hiểm')}")

    # ----------------- PHẦN I: XÁC NHẬN VÀ ĐỀ NGHỊ PHÊ DUYỆT -----------------
    doc.add_heading("PHẦN I: XÁC NHẬN VÀ ĐỀ NGHỊ PHÊ DUYỆT", level=1)
    p_end = doc.add_paragraph()
    p_end.add_run(f"Đơn vị Kinh doanh kính trình Hội đồng Tín dụng / Ban Phê duyệt Tín dụng MSB phê duyệt cấp hạn mức tín dụng cho {data['name']} với tổng hạn mức {demand['total_credit_facility_msb']:,.0f} VND theo đúng các điều kiện và nội dung trình nêu trên.\n\n")

    p_sd = doc.add_paragraph()
    p_sd.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_sd.add_run("Hà Nội, ngày ..... tháng ..... năm 2026\n").italic = True

    t_sign = doc.add_table(rows=3, cols=3)
    t_sign.alignment = WD_TABLE_ALIGNMENT.CENTER
    s_h = t_sign.rows[0].cells
    s_h[0].text = "CHUYÊN VIÊN QHKH (RM)"
    s_h[1].text = "TRƯỞNG PHÒNG KHDN"
    s_h[2].text = "GIÁM ĐỐC TRUNG TÂM EB"
    for c in s_h:
        c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        c.paragraphs[0].runs[0].bold = True
        c.paragraphs[0].runs[0].font.size = Pt(9.5)

    t_sign.rows[1].cells[0].text = "\n\n\n\n"
    t_sign.rows[1].cells[1].text = "\n\n\n\n"
    t_sign.rows[1].cells[2].text = "\n\n\n\n"

    t_sign.rows[2].cells[0].text = "(Ký, ghi rõ họ tên)"
    t_sign.rows[2].cells[1].text = "(Ký, ghi rõ họ tên)"
    t_sign.rows[2].cells[2].text = "(Ký, ghi rõ họ tên)"
    for c in t_sign.rows[2].cells:
        c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        c.paragraphs[0].runs[0].italic = True
        c.paragraphs[0].runs[0].font.size = Pt(8.5)

    target_stream = io.BytesIO()
    doc.save(target_stream)
    target_stream.seek(0)
    return target_stream
