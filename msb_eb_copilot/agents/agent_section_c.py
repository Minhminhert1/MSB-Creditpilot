# -*- coding: utf-8 -*-
"""
Module: agent_section_c.py
Mô tả: Specialist Agent C - Phân tích Hoạt động Kinh doanh, Cơ cấu Sở hữu, Ban Lãnh đạo & Chuỗi Cung ứng (Phần C).
Nhiệm vụ:
1. Xử lý dữ liệu định danh pháp lý từ Điều lệ & ĐKKD.
2. Rà soát cơ cấu cổ đông, người liên quan và đối tượng hạn chế (Điều 126 Luật TCTD).
3. Đánh giá chuỗi cung ứng Đầu vào (Top NCC) và Đầu ra (Top Khách hàng, Thị phần & Đối thủ).
4. Xuất bản Word chuẩn MB07 cho Phần C.
"""

import os
import sys
import json
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from typing import Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class AgentSectionC:
    """Agent C - Chuyên viên Thẩm định Hoạt động Kinh doanh & Năng lực Doanh nghiệp."""

    def __init__(self, spec_dir: str = None):
        if spec_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            spec_dir = os.path.join(base_dir, "sections_spec", "03_section_C_business")
        self.spec_dir = spec_dir

    def validate_and_process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Kiểm tra tính hợp lệ và chuẩn hóa dữ liệu Phần C."""
        warnings = []
        
        # 1. Kiểm tra tập trung khách hàng đầu ra (> 30% doanh thu)
        top_custs = input_data.get("outbound_distribution", {}).get("top_customers", [])
        for c in top_custs:
            share_str = c.get("revenue_share_percentage", "0%").replace("%", "").strip()
            try:
                if float(share_str) >= 30.0:
                    warnings.append(f"Khách hàng '{c.get('customer_name')}' chiếm {share_str}% doanh thu (>=30%). Đề xuất RM kiểm tra biện pháp bảo lãnh thanh toán.")
            except ValueError:
                pass

        # 2. Kiểm tra tập trung nhà cung cấp (> 40% chi phí mua)
        top_sups = input_data.get("inbound_supply_chain", {}).get("top_suppliers", [])
        for s in top_sups:
            share_str = s.get("purchase_share_percentage", "0%").replace("%", "").strip()
            try:
                if float(share_str) >= 40.0:
                    warnings.append(f"Nhà cung cấp '{s.get('supplier_name')}' chiếm {share_str}% nguyên liệu (>=40%). Cần đánh giá rủi ro phụ thuộc nguồn cung.")
            except ValueError:
                pass

        return {
            "processed_data": input_data,
            "warnings": warnings,
            "status": "PASS"
        }

    def generate_docx(self, input_data: Dict[str, Any], output_path: str) -> str:
        """Tạo file Word Phần C chuẩn format MSB MB07."""
        doc = docx.Document()

        for s in doc.sections:
            s.top_margin = Inches(0.6)
            s.bottom_margin = Inches(0.6)
            s.left_margin = Inches(0.7)
            s.right_margin = Inches(0.7)

        # Tiêu đề PHẦN C
        p_main = doc.add_paragraph()
        r_main = p_main.add_run("PHẦN C: HOẠT ĐỘNG KINH DOANH CỦA KHÁCH HÀNG")
        r_main.bold = True
        r_main.font.size = Pt(12)
        r_main.font.name = "Times New Roman"

        def add_heading_2(text):
            p = doc.add_paragraph()
            r = p.add_run(text)
            r.bold = True
            r.font.size = Pt(11)
            r.font.name = "Times New Roman"
            return p

        def add_body_p(text, bold_prefix=None):
            p = doc.add_paragraph()
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_after = Pt(4)
            if bold_prefix:
                r_b = p.add_run(bold_prefix)
                r_b.bold = True
                r_b.font.size = Pt(10)
                r_b.font.name = "Times New Roman"
            r_t = p.add_run(text)
            r_t.font.size = Pt(10)
            r_t.font.name = "Times New Roman"
            return p

        hist = input_data.get("company_history", {})
        own = input_data.get("ownership_and_governance", {})
        mgmt = input_data.get("management_team", {})
        biz = input_data.get("business_model_and_products", {})
        inbound = input_data.get("inbound_supply_chain", {})
        outbound = input_data.get("outbound_distribution", {})

        # 1. Thời gian hoạt động của doanh nghiệp
        add_heading_2("1. Thời gian hoạt động của doanh nghiệp")
        add_body_p(hist.get("history_narrative", ""), bold_prefix="Tóm tắt quá trình hình thành, phát triển: ")

        # Bảng tăng vốn
        milestones = hist.get("capital_increase_milestones", [])
        if milestones:
            p_tbl = doc.add_paragraph()
            r_tbl = p_tbl.add_run("Quá trình tăng vốn điều lệ:")
            r_tbl.bold = True
            r_tbl.font.size = Pt(10)
            r_tbl.font.name = "Times New Roman"

            t_mile = doc.add_table(rows=1 + len(milestones), cols=3)
            t_mile.alignment = WD_TABLE_ALIGNMENT.CENTER
            headers = ["Thời điểm", "Vốn điều lệ (triệu VND)", "Sự kiện ghi nhận"]
            for col_idx, h in enumerate(headers):
                cell = t_mile.rows[0].cells[col_idx]
                cell.text = h
                cell.paragraphs[0].runs[0].bold = True

            for row_idx, m in enumerate(milestones):
                r = t_mile.rows[1 + row_idx]
                r.cells[0].text = m.get("effective_date", "")
                r.cells[1].text = f"{m.get('charter_capital_vnd', 0):,.0f}".replace(",", ".")
                r.cells[2].text = m.get("event_description", "")

        # 2. Chủ sở hữu và Người liên quan
        add_heading_2("\n2. Chủ sở hữu và Người liên quan")
        add_body_p(f"Doanh nghiệp thuộc sở hữu 100% của {own.get('parent_company_name', '')}.", bold_prefix="Thông tin Chủ sở hữu: ")

        # Bảng Cổ đông lớn
        shareholders = own.get("major_shareholders", [])
        if shareholders:
            t_sh = doc.add_table(rows=1 + len(shareholders), cols=5)
            t_sh.alignment = WD_TABLE_ALIGNMENT.CENTER
            headers = ["STT", "Tên Cổ đông / Thành viên", "Mã số thuế", "Tỷ lệ sở hữu", "Vốn góp (triệu VND)"]
            for col_idx, h in enumerate(headers):
                cell = t_sh.rows[0].cells[col_idx]
                cell.text = h
                cell.paragraphs[0].runs[0].bold = True

            for row_idx, sh in enumerate(shareholders):
                r = t_sh.rows[1 + row_idx]
                r.cells[0].text = str(row_idx + 1)
                r.cells[1].text = sh.get("shareholder_name", "")
                r.cells[2].text = sh.get("id_tax_code", "")
                r.cells[3].text = sh.get("ownership_percentage", "")
                r.cells[4].text = f"{sh.get('contributed_capital_vnd', 0):,.0f}".replace(",", ".")

        add_body_p(own.get("blacklist_and_restricted_status", "Không thuộc danh sách Blacklist, không vi phạm Điều 126 Luật TCTD."), bold_prefix="Xác nhận tình trạng pháp lý: ")

        # 3. Cơ cấu tổ chức và Ban lãnh đạo
        add_heading_2("\n3. Cơ cấu tổ chức và Thành viên Ban lãnh đạo")
        exec_board = mgmt.get("executive_board", {})
        add_body_p(f"{exec_board.get('general_director_name', '')} - {exec_board.get('general_director_profile', '')}", bold_prefix="Tổng Giám đốc: ")
        add_body_p(f"{exec_board.get('chief_accountant_name', '')} - {exec_board.get('chief_accountant_profile', '')}", bold_prefix="Kế toán trưởng: ")
        add_body_p(mgmt.get("headcount_and_departments", {}).get("organizational_structure_summary", ""), bold_prefix="Quy mô bộ máy: ")

        # 4. Ngành nghề kinh doanh và Công nghệ
        add_heading_2("\n4. Ngành nghề kinh doanh, Sản phẩm và Công nghệ sản xuất")
        add_body_p(biz.get("core_business_model", ""), bold_prefix="Mô hình hoạt động: ")
        
        prod_list = biz.get("main_products_portfolio", [])
        if prod_list:
            t_prod = doc.add_table(rows=1 + len(prod_list), cols=4)
            t_prod.alignment = WD_TABLE_ALIGNMENT.CENTER
            headers = ["STT", "Sản phẩm chính", "Thương hiệu", "Tỷ trọng DT (%)"]
            for col_idx, h in enumerate(headers):
                cell = t_prod.rows[0].cells[col_idx]
                cell.text = h
                cell.paragraphs[0].runs[0].bold = True

            for row_idx, p in enumerate(prod_list):
                r = t_prod.rows[1 + row_idx]
                r.cells[0].text = str(row_idx + 1)
                r.cells[1].text = p.get("product_name", "")
                r.cells[2].text = p.get("brand_name", "")
                r.cells[3].text = p.get("revenue_contribution_percentage", "")

        cap_info = biz.get("production_technology_and_capacity", {})
        add_body_p(f"{cap_info.get('technology_description', '')} Công suất thiết kế: {cap_info.get('designed_capacity_annual', '')}. Hiệu suất vận hành thực tế: {cap_info.get('actual_utilization_rate', '')}.", bold_prefix="Công nghệ & Công suất: ")

        # 5. Thị trường Đầu vào và Nhà cung cấp
        add_heading_2("\n5. Thị trường Đầu vào và Nhà cung cấp chính")
        add_body_p(inbound.get("raw_materials_overview", ""), bold_prefix="Nguyên vật liệu chính: ")
        add_body_p(inbound.get("pricing_mechanism", ""), bold_prefix="Cơ chế định giá mua: ")

        sups = inbound.get("top_suppliers", [])
        if sups:
            t_sup = doc.add_table(rows=1 + len(sups), cols=5)
            t_sup.alignment = WD_TABLE_ALIGNMENT.CENTER
            headers = ["STT", "Nhà cung cấp", "Mặt hàng", "Tỷ trọng (%)", "Phương thức thanh toán"]
            for col_idx, h in enumerate(headers):
                cell = t_sup.rows[0].cells[col_idx]
                cell.text = h
                cell.paragraphs[0].runs[0].bold = True

            for row_idx, s in enumerate(sups):
                r = t_sup.rows[1 + row_idx]
                r.cells[0].text = str(row_idx + 1)
                r.cells[1].text = s.get("supplier_name", "")
                r.cells[2].text = s.get("supplied_goods", "")
                r.cells[3].text = s.get("purchase_share_percentage", "")
                r.cells[4].text = s.get("payment_terms", "")

        # 6. Thị trường Đầu ra và Khách hàng
        add_heading_2("\n6. Thị trường Đầu ra, Khách hàng và Đối thủ cạnh tranh")
        add_body_p(outbound.get("distribution_channels", ""), bold_prefix="Kênh phân phối: ")
        
        comp = outbound.get("market_share_and_competitors", {})
        add_body_p(f"Thị phần: {comp.get('market_share_estimate', '')}. Đối thủ chính: {', '.join(comp.get('top_competitors', []))}. Lợi thế cạnh tranh: {comp.get('competitive_advantages', '')}", bold_prefix="Thị phần & Đối thủ: ")

        custs = outbound.get("top_customers", [])
        if custs:
            t_cust = doc.add_table(rows=1 + len(custs), cols=5)
            t_cust.alignment = WD_TABLE_ALIGNMENT.CENTER
            headers = ["STT", "Khách hàng chính", "Sản phẩm", "Tỷ trọng DT (%)", "Chính sách công nợ"]
            for col_idx, h in enumerate(headers):
                cell = t_cust.rows[0].cells[col_idx]
                cell.text = h
                cell.paragraphs[0].runs[0].bold = True

            for row_idx, c in enumerate(custs):
                r = t_cust.rows[1 + row_idx]
                r.cells[0].text = str(row_idx + 1)
                r.cells[1].text = c.get("customer_name", "")
                r.cells[2].text = c.get("product_purchased", "")
                r.cells[3].text = c.get("revenue_share_percentage", "")
                r.cells[4].text = c.get("credit_terms", "")

        add_body_p(outbound.get("receivables_and_credit_policy", ""), bold_prefix="Chính sách kiểm soát công nợ: ")

        # Format Font chuẩn Times New Roman cho toàn bộ bảng
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        for run in para.runs:
                            run.font.name = "Times New Roman"
                            run.font.size = Pt(9.5)
                            run.font.color.rgb = RGBColor(0, 0, 0)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        doc.save(output_path)
        return output_path


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample_file = os.path.join(base_dir, "sections_spec", "03_section_C_business", "4_sample_input.json")
    out_file = os.path.join(base_dir, "output", "TO_TRINH_MB07_PHAN_C_THEP_MIEN_NAM.docx")

    with open(sample_file, "r", encoding="utf-8") as f:
        sample_data = json.load(f)

    agent = AgentSectionC()
    processed = agent.validate_and_process(sample_data)
    print("=== AGENT C PROCESSED ===")
    print(f"Status: {processed['status']}")
    print(f"Warnings: {processed['warnings']}")

    res_path = agent.generate_docx(sample_data, out_file)
    print(f"✅ ĐÃ XUẤT THÀNH CÔNG BẢN WORD PHẦN C: {res_path}")
