"""
Script: test_section_a_generator.py
Mô tả: Công cụ kiểm thử độc lập cho Agent A:
1. Đọc dữ liệu JSON mẫu của Phần A (4 nguồn dữ liệu).
2. Chạy logic đối soát và validation của Agent A.
3. Xuất file Word chuyên biệt chứa đúng Bảng Phần A để đối chiếu trực tiếp với 2 ảnh mẫu của MSB.
"""

import os
import sys
import json
import io
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agents.agent_section_a import AgentSectionA


def set_cell_background(cell, fill_hex: str):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)


def set_cell_margins(cell, top=60, bottom=60, left=100, right=100):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}><w:top w:w="{top}" w:type="dxa"/><w:bottom w:w="{bottom}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/></w:tcMar>')
    tcPr.append(tcMar)


def export_section_a_docx(data: dict, out_path: str):
    """Xuất file Word chuyên biệt cho Phần A đúng chuẩn 100% 2 ảnh MSB."""
    doc = docx.Document()
    for s in doc.sections:
        s.top_margin = Inches(0.6)
        s.bottom_margin = Inches(0.6)
        s.left_margin = Inches(0.7)
        s.right_margin = Inches(0.7)

    # Tiêu đề Phần A
    p_title = doc.add_paragraph()
    r = p_title.add_run("PHẦN A. TÓM TẮT THÔNG TIN CHUNG")
    r.bold = True
    r.font.size = Pt(12)
    r.font.color.rgb = RGBColor(0, 51, 102)

    # BẢNG 1: THÔNG TIN PHÁP LÝ & ĐỊNH DANH (KHỚP ẢNH 1 & ẢNH 2)
    tbl = doc.add_table(rows=0, cols=4)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER

    def add_row_2col(label, val, bold_label=True, bg_label="EAECEE"):
        row = tbl.add_row()
        # Merge cell 1, 2, 3 thành 1 ô lớn
        cell_lbl = row.cells[0]
        cell_lbl.text = label
        set_cell_margins(cell_lbl)
        if bold_label: cell_lbl.paragraphs[0].runs[0].bold = True
        set_cell_background(cell_lbl, bg_label)
        cell_lbl.paragraphs[0].runs[0].font.size = Pt(9.5)

        # Merge 3 ô còn lại
        c1 = row.cells[1]
        c2 = row.cells[2]
        c3 = row.cells[3]
        c1.merge(c2).merge(c3)
        c1.text = str(val)
        set_cell_margins(c1)
        c1.paragraphs[0].runs[0].font.size = Pt(9.5)

    def add_row_4col(l1, v1, l2, v2, bg="EAECEE"):
        row = tbl.add_row()
        for idx, (lbl, val) in enumerate([(l1, v1), (l2, v2)]):
            c_lbl = row.cells[idx*2]
            c_val = row.cells[idx*2 + 1]
            c_lbl.text = lbl
            c_val.text = str(val)
            set_cell_margins(c_lbl)
            set_cell_margins(c_val)
            c_lbl.paragraphs[0].runs[0].bold = True
            set_cell_background(c_lbl, bg)
            c_lbl.paragraphs[0].runs[0].font.size = Pt(9.5)
            c_val.paragraphs[0].runs[0].font.size = Pt(9.5)

    # Đổ dữ liệu
    add_row_2col("Tên khách hàng doanh nghiệp", data['company_name'])
    add_row_2col("Viết tắt", data['company_short_name'])
    add_row_2col("Loại hình doanh nghiệp", data['enterprise_type'])
    
    # Tình trạng KH & CIF
    kh_status = "☑ KH mới       ☐ KH hiện hữu" if data['customer_status'] == "KH mới" else "☐ KH mới       ☑ KH hiện hữu"
    add_row_4col("Tình trạng khách hàng", kh_status, "Mã CIF", data['cif_number'])
    
    # Đối tượng KH
    seg_status = "☑ LC          ☐ LMC          ☐ Khác" if data['customer_segment'] == "LC" else "☐ LC          ☑ LMC          ☐ Khác"
    add_row_2col("Đối tượng khách hàng", seg_status)
    
    add_row_2col("Thuộc nhóm, tập đoàn", data['group_affiliation'])
    add_row_2col("Địa chỉ trụ sở chính", data['headquarters_address'])
    
    # ĐKKD
    add_row_4col("Số đăng ký kinh doanh", data['tax_code_business_reg_no'], "Ngày cấp & Nơi cấp", f"{data['business_reg_date']} tại {data['business_reg_place']}")
    add_row_2col("Thời gian bắt đầu hoạt động²", data['operation_start_date'])
    add_row_4col("Người đại diện theo pháp luật", f"{data['legal_representative_name']} ({data['legal_representative_title']})", "Người ĐD đề nghị cấp TD", data['credit_applicant_representative'])
    
    # Cờ Auto
    add_row_2col("Khách hàng thuộc đối tượng hạn chế cấp tín dụng hay không?", "☐ Có              ☑ Không (Auto chọn)")
    add_row_2col("Quản lý rủi ro MTXH³", "☐ Thuộc đối tượng đánh giá       ☑ Không thuộc đối tượng phải đánh giá rủi ro MTXH theo QĐ MSB")
    add_row_2col("Doanh thu năm gần nhất", f"{data['latest_year_revenue_vnd']:,.0f} triệu đồng (Nguồn: Excel BCTC, sheet 'Tờ trình')")

    # Ngành nghề cấp 5
    add_row_4col("Mã ngành cấp 5⁴", data['industry_level_5_code'], "Tên ngành & Tỷ trọng", f"{data['industry_level_5_name']} ({data['industry_revenue_share']})")
    add_row_2col("Ngành nghề KD chính⁵", data['main_business_activity'])
    add_row_2col("Các sản phẩm chính⁶", data['main_products'])

    # Vốn điều lệ
    add_row_4col("Vốn đăng ký (Điều lệ)", f"{data['charter_capital_registered_vnd']:,.0f} triệu đồng", "Vốn thực góp (BCTC/RM)", f"{data['actual_contributed_capital_vnd']:,.0f} triệu đồng (Tính đến {data['contributed_capital_as_of_date']})")
    
    # XHTD nội bộ
    add_row_4col("Xếp hạng tín dụng nội bộ⁷", f"Mã ID: {data['internal_rating_dvkd']['profile_id']}", "Hạng & Số điểm", f"Hạng {data['internal_rating_dvkd']['rating_grade']} (Điểm: {data['internal_rating_dvkd']['rating_score']})")

    # Dư nợ MSB link từ CIC
    add_row_4col("Dư nợ cho vay tại MSB⁸", f"{data['outstanding_loan_at_msb_vnd']:,.0f} triệu đồng (Link từ Phần E)", "Quy định của NHNN⁹", "☑ Trong giới hạn       ☐ Vượt giới hạn")
    add_row_2col("Tổng dư tín dụng tại MSB¹⁰", f"{data['total_credit_exposure_at_msb_vnd']:,.0f} triệu đồng (Vay + L/C + Bảo lãnh - Link từ Phần E)")

    # Ma trận Thẩm quyền
    m = data['approval_authority_matrix']
    add_row_4col("HMTD đã cấp nhóm liên quan", f"Tổng: {m['existing_approved_limit_total_vnd']:,.0f} trđ | KTSBĐ: {m['existing_approved_limit_unsecured_vnd']:,.0f} trđ", "HMTD đề xuất lần này", f"Tổng: {m['proposed_limit_total_vnd']:,.0f} trđ | KTSBĐ: {m['proposed_limit_unsecured_vnd']:,.0f} trđ")
    add_row_4col("TỔNG CỘNG HMTD ĐỀ XUẤT", f"{m['grand_total_limit_vnd']:,.0f} triệu đồng", "Thẩm quyền phê duyệt", f"☑ {m['target_approval_level']}       ☐ HĐTD&ĐT       ☐ HĐQT")
    add_row_4col("Kỳ phê duyệt gần nhất", data['latest_approval_session'], "Đề xuất nhu cầu tín dụng", f"☑ {data['credit_proposal_type']}       ☐ Tái cấp")

    doc.save(out_path)
    print(f"ĐÃ XUẤT FILE TEST WORD: {out_path}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    sample_file = os.path.join(base_dir, "sections_spec", "01_section_A_profile", "4_sample_input.json")
    out_docx = os.path.join(base_dir, "output", "TEST_PHAN_A_GAS_SOUTH_CHUAN_MSB.docx")

    with open(sample_file, "r", encoding="utf-8") as f:
        input_data = json.load(f)

    agent = AgentSectionA()
    processed_data = agent.validate_and_process(input_data)
    
    os.makedirs(os.path.dirname(out_docx), exist_ok=True)
    export_section_a_docx(processed_data, out_docx)
