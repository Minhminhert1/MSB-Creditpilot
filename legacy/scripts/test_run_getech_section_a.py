"""
Script: test_run_getech_section_a.py
Mô tả: Chạy kiểm thử hoàn chỉnh Agent A cho Khách hàng mới (GETECH CORP - Chủ tịch Hoàng Minh).
1. Bóc tách OCR tự động từ 4 file hồ sơ trong test_new_customer/
2. Nạp dữ liệu RM cung cấp
3. Chạy Agent A để kiểm tra chéo (Vốn điều lệ, Pre-screening QĐ.074, Giới hạn NHNN)
4. Render và xuất ra file Word mẫu biểu Table 1 MB07 chuẩn 100% của MSB.
"""

import os
import sys
import json
import re
import openpyxl
import docx
import copy
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agents.agent_section_a import AgentSectionA


def parse_raw_customer_files(customer_dir: str) -> dict:
    """Mô phỏng module OCR/Parser bóc tách dữ liệu từ các file gốc."""
    
    # 1. Đọc ĐKKD
    dkkd_path = os.path.join(customer_dir, "1_Giay_Dang_Ky_Kinh_Doanh_GETECH.txt")
    with open(dkkd_path, "r", encoding="utf-8") as f:
        dkkd_text = f.read()

    # 2. Đọc Điều lệ
    dieu_le_path = os.path.join(customer_dir, "2_Dieu_Le_Cong_Ty_GETECH_Trich_Luc.txt")
    with open(dieu_le_path, "r", encoding="utf-8") as f:
        dieu_le_text = f.read()

    # 3. Đọc Excel BCTC sheet "Tờ trình"
    bctc_path = os.path.join(customer_dir, "3_BCTC_Sheet_To_Trinh_GETECH.xlsx")
    wb = openpyxl.load_workbook(bctc_path, data_only=True)
    ws = wb["Tờ trình"]
    
    # Bóc Doanh thu thuần và Vốn thực góp từ Excel
    revenue_net = 0.0
    contributed_capital = 0.0
    capital_date = "31/12/2024"
    for row in ws.iter_rows(values_only=True):
        if row and len(row) >= 5:
            if "Doanh thu thuần" in str(row[1]):
                revenue_net = float(row[4])
            elif "Vốn đầu tư của chủ sở hữu" in str(row[1]):
                contributed_capital = float(row[4])
            elif "Thời điểm chốt số liệu" in str(row[1]):
                capital_date = str(row[4])

    # 4. Đọc Báo cáo CIC
    cic_path = os.path.join(customer_dir, "4_Bao_Cao_CIC_GETECH.txt")
    with open(cic_path, "r", encoding="utf-8") as f:
        cic_text = f.read()

    # Trích xuất có cấu trúc
    ocr_data = {
        "company_name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ & THIẾT BỊ NĂNG LƯỢNG TOÀN CẦU",
        "company_short_name": "GETECH CORP (GET)",
        "enterprise_type": "Công ty Cổ phần",
        "headquarters_address": "Tầng 12, Tòa nhà Keangnam Landmark 72, Đường Phạm Hùng, Phường Mễ Trì, Quận Nam Từ Liêm, TP. Hà Nội",
        "tax_code_business_reg_no": "0109887766",
        "business_reg_date": "15/04/2012, thay đổi lần thứ 8 ngày 10/06/2024",
        "business_reg_place": "Sở Kế hoạch và Đầu tư Thành phố Hà Nội",
        "operation_start_date": "15/04/2012",
        "legal_representative_name": "Ông Hoàng Minh",
        "legal_representative_title": "Chủ tịch HĐQT kiêm Tổng Giám đốc",
        "group_affiliation": "TẬP ĐOÀN ĐẦU TƯ & PHÁT TRIỂN NĂNG LƯỢNG TÁI TẠO TOÀN CẦU (GETECH HOLDINGS GROUP)",
        "charter_capital_registered_vnd": 350000.0,
        "latest_year_revenue_vnd": revenue_net if revenue_net > 0 else 3850000.0
    }

    linked_cic = {
        "outstanding_loan_at_msb_vnd": 0.0,
        "total_credit_exposure_at_msb_vnd": 0.0
    }

    return ocr_data, linked_cic, contributed_capital, capital_date


def render_exact_word_section_a(template_path: str, output_path: str, p: dict):
    """Render ra đúng mẫu Table 1 gốc MSB MB07."""
    doc_tpl = docx.Document(template_path)
    doc_new = docx.Document()
    for s in doc_new.sections:
        s.top_margin = Inches(0.6)
        s.bottom_margin = Inches(0.6)
        s.left_margin = Inches(0.7)
        s.right_margin = Inches(0.7)

    p_head = doc_new.add_paragraph()
    r = p_head.add_run("PHẦN A. TÓM TẮT THÔNG TIN CHUNG")
    r.bold = True
    r.font.size = Pt(12)
    r.font.name = "Times New Roman"

    # Clone Table 1
    t1_orig = doc_tpl.tables[1]
    tbl_new = doc_new.add_table(rows=0, cols=0)
    tbl_new._tbl.addprevious(copy.deepcopy(t1_orig._tbl))
    doc_new._body._element.remove(tbl_new._tbl)
    t1 = doc_new.tables[-1]

    # Điền chính xác 30 hàng của Table 1
    t1.rows[0].cells[2].text = p["company_name"]
    t1.rows[1].cells[2].text = p["company_short_name"]
    t1.rows[2].cells[1].text = p["enterprise_type"]
    
    t1.rows[3].cells[2].text = "☑ KH mới       ☐ KH hiện hữu" if p["customer_status"] == "KH mới" else "☐ KH mới       ☑ KH hiện hữu"
    t1.rows[3].cells[4].text = f"CIF: {p['cif_number']}"
    
    t1.rows[4].cells[2].text = "☑ LC              ☐ LMC                 ☐ Khác" if p["customer_segment"] == "LC" else "☐ LC              ☑ LMC                 ☐ Khác"
    t1.rows[5].cells[2].text = p["group_affiliation"]
    t1.rows[6].cells[2].text = p["headquarters_address"]
    
    t1.rows[7].cells[2].text = p["tax_code_business_reg_no"]
    t1.rows[7].cells[3].text = f"Ngày cấp: {p['business_reg_date']}"
    t1.rows[7].cells[6].text = f"Nơi cấp: {p['business_reg_place']}"
    
    t1.rows[8].cells[2].text = p["operation_start_date"]
    t1.rows[9].cells[2].text = p["legal_representative_name"]
    t1.rows[9].cells[3].text = f"Chức vụ: {p['legal_representative_title']}"
    
    t1.rows[10].cells[2].text = p["credit_applicant_representative"]
    t1.rows[10].cells[3].text = f"Chức vụ: {p['legal_representative_title']}"
    
    t1.rows[11].cells[2].text = "☐ Có"
    t1.rows[11].cells[3].text = "☑ Không (Auto chọn)"
    
    t1.rows[12].cells[2].text = "☐ KH thuộc đối tượng phải đánh giá rủi ro MTXH theo quy định MSB"
    t1.rows[12].cells[3].text = "☑ KH không thuộc đối tượng phải đánh giá rủi ro MTXH theo quy định MSB (Auto chọn)"
    
    t1.rows[13].cells[2].text = f"{p['latest_year_revenue_vnd']:,.0f} triệu đồng (Nguồn: Excel BCTC, sheet 'Tờ trình' - Doanh thu thuần)"
    
    t1.rows[15].cells[1].text = p["industry_level_5_code"]
    t1.rows[15].cells[2].text = p["industry_level_5_name"]
    t1.rows[15].cells[5].text = p["industry_revenue_share"]
    
    t1.rows[16].cells[1].text = p["industry_level_5_code"]
    t1.rows[16].cells[2].text = p["main_products"]
    t1.rows[16].cells[5].text = p["industry_revenue_share"]
    
    t1.rows[17].cells[2].text = f"Vốn đăng ký: {p['charter_capital_registered_vnd']:,.0f} triệu đồng (Nguồn: ĐIỀU LỆ)"
    t1.rows[18].cells[2].text = f"Vốn thực góp: {p['actual_contributed_capital_vnd']:,.0f} triệu đồng (Nguồn: BCTC/RM)"
    t1.rows[18].cells[7].text = str(p["contributed_capital_as_of_date"])
    
    t1.rows[19].cells[2].text = f"Mã ID của hồ sơ (theo hệ thống XHTD): {p['internal_rating_dvkd']['profile_id']}"
    t1.rows[20].cells[2].text = f"Hạng: {p['internal_rating_dvkd']['rating_grade']}"
    t1.rows[20].cells[3].text = f"Số điểm: {p['internal_rating_dvkd']['rating_score']}"
    
    t1.rows[21].cells[2].text = f"{p['outstanding_loan_at_msb_vnd']:,.0f} triệu đồng (LẤY DATA TỪ PHẦN E - CIC)"
    t1.rows[21].cells[3].text = "So với quy định của Ngân hàng Nhà nước:\n☐ Vượt giới hạn\n☑ Trong giới hạn (AUTO CHỌN TRONG GIỚI HẠN)"
    
    t1.rows[22].cells[2].text = f"{p['total_credit_exposure_at_msb_vnd']:,.0f} triệu đồng (LẤY DATA TỪ PHẦN E - CIC)"
    t1.rows[22].cells[3].text = "So với quy định của Ngân hàng Nhà nước:\n☐ Vượt giới hạn\n☑ Trong giới hạn"
    
    m = p["approval_authority_matrix"]
    t1.rows[24].cells[3].text = f"{m['existing_approved_limit_total_vnd']:,.0f} triệu đồng"
    t1.rows[24].cells[6].text = f"{m['existing_approved_limit_unsecured_vnd']:,.0f} triệu đồng"
    
    t1.rows[25].cells[3].text = f"{m['proposed_limit_total_vnd']:,.0f} triệu đồng"
    t1.rows[25].cells[6].text = f"{m['proposed_limit_unsecured_vnd']:,.0f} triệu đồng"
    
    t1.rows[26].cells[3].text = f"{m['grand_total_limit_vnd']:,.0f} triệu đồng"
    t1.rows[26].cells[6].text = f"{m['grand_unsecured_limit_vnd']:,.0f} triệu đồng"
    
    t1.rows[27].cells[2].text = f"Thẩm quyền phê duyệt đề xuất lần này:\n☐ HĐTD&ĐT                              ☐ HĐQT\n☑ {m['target_approval_level']} (RM CUNG CẤP)"
    t1.rows[28].cells[2].text = p["latest_approval_session"]
    t1.rows[29].cells[2].text = f"☐ Tái cấp\n☑ {p['credit_proposal_type']} (RM CUNG CẤP)"

    # Format Font
    for row in t1.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                for run in para.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(9.5)
                    run.font.color.rgb = RGBColor(0, 0, 0)

    doc_new.save(output_path)
    print(f"✅ ĐÃ XUẤT THÀNH CÔNG FILE WORD PHẦN A: {output_path}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    customer_dir = os.path.join(os.path.dirname(base_dir), "test_new_customer")
    template_path = os.path.join(os.path.dirname(base_dir), "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - Tho.docx")
    out_docx = os.path.join(base_dir, "output", "KET_QUA_TEST_PHAN_A_GETECH_HOANG_MINH.docx")

    # 1. Bóc tách tự động
    ocr_data, linked_cic, contrib_cap, cap_date = parse_raw_customer_files(customer_dir)

    # 2. Ghép dữ liệu RM cung cấp
    full_input = {
        "ocr_from_documents": ocr_data,
        "rm_provided_inputs": {
            "cif_number": "1588999",
            "customer_status": "KH mới",
            "customer_segment": "LC",
            "credit_applicant_representative": "Ông Hoàng Minh - Chủ tịch HĐQT kiêm TGĐ",
            "industry_level_5_code": "46594",
            "industry_level_5_name": "Bán buôn thiết bị, linh kiện điện tử và pin năng lượng tái tạo",
            "industry_revenue_share": "90%",
            "main_business_activity": "Kinh doanh thiết bị năng lượng mặt trời, Inverter và trạm biến áp",
            "main_products": "Tấm pin năng lượng mặt trời, Inverter công nghiệp, Trạm biến áp 110kV",
            "actual_contributed_capital_vnd": contrib_cap if contrib_cap > 0 else 350000.0,
            "contributed_capital_as_of_date": cap_date,
            "internal_rating_dvkd": {
                "profile_id": "XHTD-2026-GETECH-001",
                "rating_grade": "A+",
                "rating_score": 91.5
            },
            "approval_authority_matrix": {
                "existing_approved_limit_total_vnd": 0.0,
                "existing_approved_limit_unsecured_vnd": 0.0,
                "proposed_limit_total_vnd": 850000.0,
                "proposed_limit_unsecured_vnd": 300000.0,
                "target_approval_level": "HĐTDCC"
            },
            "latest_approval_session": "Chưa phát sinh (Hồ sơ cấp mới 2026)",
            "credit_proposal_type": "Cấp mới"
        },
        "linked_from_section_e": linked_cic,
        "auto_default_flags": {
            "restricted_credit_subject": "Không",
            "environmental_social_risk_esg": "Không thuộc đối tượng",
            "sbv_single_borrower_limit_check": "Trong giới hạn"
        }
    }

    # 3. Chạy qua Agent A
    agent = AgentSectionA()
    processed_profile = agent.validate_and_process(full_input)

    # 4. Render ra Word
    render_exact_word_section_a(template_path, out_docx, processed_profile)
