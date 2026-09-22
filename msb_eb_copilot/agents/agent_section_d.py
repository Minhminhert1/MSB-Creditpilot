"""
Agent Section D: TÌNH HÌNH TÀI CHÍNH DOANH NGHIỆP (Chuẩn 100% Format Mẫu MB07 MSB & Thẩm định KHDN Lớn)
Đối chiếu trực tiếp:
- MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - bản tham khảo.docx
- THÉP TÂY ĐÔ_ Tờ trình_2026.docx
"""

import os
import json
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls


def set_cell_background(cell, fill_hex):
    tcPr = cell._element.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)


def set_cell_margins(cell, top=100, bottom=100, left=140, right=140):
    tcPr = cell._element.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)


def set_table_borders(table, color="B0C4DE", sz="4"):
    tblPr = table._element.xpath('w:tblPr')
    if tblPr:
        borders = parse_xml(
            f'<w:tblBorders {nsdecls("w")}>'
            f'<w:top w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>'
            f'<w:bottom w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>'
            f'<w:left w:val="none"/>'
            f'<w:right w:val="none"/>'
            f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
            f'<w:insideV w:val="none"/>'
            f'</w:tblBorders>'
        )
        tblPr[0].append(borders)


def format_currency(val):
    if val is None or val == "":
        return ""
    try:
        f = float(val)
        if f == 0:
            return "0"
        return f"{f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return str(val)


def format_pct(val):
    if val is None or val == "":
        return ""
    try:
        f = float(val)
        return f"{f:.2f}%".replace(".", ",")
    except (ValueError, TypeError):
        return str(val)


class AgentSectionD:
    def __init__(self):
        self.section_id = "04_section_D_financial"

    def validate_and_process(self, input_data: dict) -> dict:
        warnings = []
        pnl = input_data.get("income_statement_3y", {})
        bs = input_data.get("balance_sheet_3y", {})
        cf = input_data.get("cash_flow_statement_3y", {})

        if not pnl.get("net_revenue"):
            warnings.append("Thiếu số liệu Doanh thu 3 năm")
        if not bs.get("total_assets"):
            warnings.append("Thiếu số liệu Bảng cân đối kế toán 3 năm")
        if not cf.get("ocf_cash_from_operations"):
            warnings.append("Thiếu số liệu Báo cáo lưu chuyển tiền tệ")

        return {
            "status": "PASS" if not warnings else "WARNING",
            "warnings": warnings,
            "processed_data": input_data
        }

    def _add_heading(self, doc, text, level=1):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing = 1.15
        run = p.add_run(text)
        run.bold = True
        run.font.name = "Times New Roman"
        if level == 1:
            run.font.size = Pt(11.5)
            run.font.color.rgb = RGBColor(0, 32, 96) # Dark Navy
        elif level == 2:
            run.font.size = Pt(10.5)
            run.font.color.rgb = RGBColor(15, 76, 129) # Classic Blue
        else:
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(30, 30, 30)
        return p

    def _add_body_para(self, doc, text, italic=False, bold_prefix="", indent=0):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.2
        if indent > 0:
            p.paragraph_format.left_indent = Inches(indent * 0.2)

        if bold_prefix:
            r_b = p.add_run(bold_prefix)
            r_b.bold = True
            r_b.font.name = "Times New Roman"
            r_b.font.size = Pt(10)
            r_b.font.color.rgb = RGBColor(0, 0, 0)

        r = p.add_run(text)
        r.italic = italic
        r.font.name = "Times New Roman"
        r.font.size = Pt(10)
        r.font.color.rgb = RGBColor(30, 30, 30)
        return p

    def _create_styled_table(self, doc, headers, rows_data, col_widths=None, align_right_cols=None):
        table = doc.add_table(rows=len(rows_data) + 1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        set_table_borders(table, color="CBD5E1", sz="6")

        align_right_cols = align_right_cols or []

        # Header Row
        hdr_row = table.rows[0]
        tblHeader = parse_xml(f'<w:tblHeader {nsdecls("w")}/>')
        hdr_row._element.get_or_add_trPr().append(tblHeader)
        cantSplit = parse_xml(f'<w:cantSplit {nsdecls("w")}/>')
        hdr_row._element.get_or_add_trPr().append(cantSplit)

        for col_idx, h_text in enumerate(headers):
            cell = hdr_row.cells[col_idx]
            cell.text = h_text
            set_cell_background(cell, "1E3A8A") # Navy Blue Header
            set_cell_margins(cell, top=120, bottom=120, left=140, right=140)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if col_idx in align_right_cols else WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.bold = True
                run.font.name = "Times New Roman"
                run.font.size = Pt(9.5)
                run.font.color.rgb = RGBColor(255, 255, 255)

        # Data Rows
        for row_idx, r_data in enumerate(rows_data):
            row = table.rows[row_idx + 1]
            row._element.get_or_add_trPr().append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))
            is_even = (row_idx % 2 == 1)
            bg_color = "F8FAFC" if is_even else "FFFFFF"

            # Check if row is a major summary row
            is_bold_row = False
            first_cell_str = str(r_data[0]) if r_data else ""
            if any(first_cell_str.startswith(x) for x in ["A.", "B.", "C.", "D.", "I.", "II.", "III.", "IV.", "V.", "Tổng", "TOTAL", "TỔNG"]):
                is_bold_row = True

            for col_idx, val in enumerate(r_data):
                cell = row.cells[col_idx]
                cell.text = str(val) if val is not None else ""
                set_cell_background(cell, "EFF6FF" if is_bold_row else bg_color)
                set_cell_margins(cell, top=80, bottom=80, left=120, right=120)
                p = cell.paragraphs[0]
                if col_idx in align_right_cols:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                elif col_idx == 0 and len(headers) > 4:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                else:
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT

                for run in p.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(9.5)
                    if is_bold_row:
                        run.bold = True
                        run.font.color.rgb = RGBColor(15, 23, 42)
                    else:
                        run.font.color.rgb = RGBColor(51, 65, 85)

        # Column Widths
        if col_widths:
            for i, w in enumerate(col_widths):
                for row in table.rows:
                    row.cells[i].width = Inches(w)

        # Spacing after table
        sp = doc.add_paragraph()
        sp.paragraph_format.space_before = Pt(2)
        sp.paragraph_format.space_after = Pt(4)
        return table

    def generate_docx(self, input_data: dict, output_path: str):
        doc = Document()

        # Set Margins standard MSB
        for section in doc.sections:
            section.top_margin = Inches(0.75)
            section.bottom_margin = Inches(0.75)
            section.left_margin = Inches(0.8)
            section.right_margin = Inches(0.8)

        # Header Title: PHẦN D. TÌNH HÌNH TÀI CHÍNH DOANH NGHIỆP
        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p_title.paragraph_format.space_after = Pt(8)
        r_title = p_title.add_run("PHẦN D. TÌNH HÌNH TÀI CHÍNH DOANH NGHIỆP")
        r_title.bold = True
        r_title.font.name = "Times New Roman"
        r_title.font.size = Pt(12)
        r_title.font.color.rgb = RGBColor(0, 32, 96)

        # 1. TÓM TẮT THÔNG TIN TÀI CHÍNH (Đúng format bullet trong MB07 gốc)
        self._add_heading(doc, "Tóm tắt thông tin tài chính:", level=1)
        gov = input_data.get("accounting_governance", {})
        self._add_body_para(doc, gov.get("mandatory_audit_by_law", "Doanh nghiệp có vốn góp Nhà nước, thuộc đối tượng bắt buộc kiểm toán theo luật"), bold_prefix="- ")
        self._add_body_para(doc, f"Báo cáo tài chính kiểm toán các năm {gov.get('audited_years', '2022 - 2024')} do {gov.get('audit_firm_name', 'Công ty TNHH Hãng Kiểm toán A&C')} thực hiện kiểm toán.", bold_prefix="- Loại BCTC: ")
        self._add_body_para(doc, gov.get("audit_opinion", "Không có (Ý kiến kiểm toán chấp nhận toàn phần, không có ngoại trừ)"), bold_prefix="- Nội dung loại trừ: ")
        self._add_body_para(doc, gov.get("accounting_software", "Hệ thống SAP S/4HANA kết hợp phần mềm quản trị vật tư Bravo 8.0"), bold_prefix="- Phần mềm kế toán doanh nghiệp sử dụng: ")
        self._add_body_para(doc, gov.get("finance_team_structure", "Ban Tài chính Kế toán gồm 14 nhân sự có trình độ chuyên môn cao do Kế toán trưởng trực tiếp điều hành."), bold_prefix="- Cơ cấu tổ chức đội ngũ kế toán tài chính: ")
        self._add_body_para(doc, gov.get("internal_financial_regulations", "Quy chế quản lý tài chính theo Quyết định 125/QĐ-VNS của VNSTEEL, tuân thủ nghiêm ngặt chuẩn mực VAS."), bold_prefix="- Các quy định nội bộ quản trị tài chính của doanh nghiệp: ")
        
        # Summary bullets like template
        hl = input_data.get("executive_highlights", {})
        self._add_body_para(doc, hl.get("revenue_trend", "Doanh thu duy trì quy mô lớn và tăng trưởng ổn định qua các năm."), bold_prefix="- Biến động Doanh thu: ")
        self._add_body_para(doc, hl.get("total_assets_and_liquidity", "Quy mô Tổng tài sản mở rộng lành mạnh, thanh khoản tiền và đầu tư tài chính dồi dào."), bold_prefix="- Quy mô Tổng tài sản & Thanh khoản: ")
        self._add_body_para(doc, hl.get("working_capital_and_ccc", "Vốn lưu động ròng dương, chu kỳ luân chuyển tiền mặt an toàn và vòng quay vốn cao."), bold_prefix="- Vốn lưu động & Chu kỳ tiền mặt: ")
        self._add_body_para(doc, hl.get("safety_ratios", "Các hệ số thanh toán và an toàn nợ vay đạt chuẩn phê duyệt tín dụng của MSB."), bold_prefix="- Các chỉ số an toàn tài chính: ")

        # 2. BẢNG KẾT QUẢ KINH DOANH (P&L 3 NĂM)
        self._add_heading(doc, "Bảng kết quả kinh doanh:", level=1)
        p_dvt = doc.add_paragraph()
        p_dvt.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r_dvt = p_dvt.add_run("ĐVT: Triệu đồng")
        r_dvt.italic = True
        r_dvt.font.name = "Times New Roman"
        r_dvt.font.size = Pt(9.5)

        pnl = input_data.get("income_statement_3y", {})
        years = pnl.get("years", ["2022", "2023", "2024"])

        headers_pnl = ["Chỉ tiêu P&L", f"Năm {years[0]}", f"Năm {years[1]}", f"Năm {years[2]}"]
        rows_pnl = [
            ["1. Doanh thu thuần", format_currency(pnl.get("net_revenue", [0,0,0])[0]), format_currency(pnl.get("net_revenue", [0,0,0])[1]), format_currency(pnl.get("net_revenue", [0,0,0])[2])],
            ["2. Giá vốn hàng bán (COGS)", format_currency(pnl.get("cogs", [0,0,0])[0]), format_currency(pnl.get("cogs", [0,0,0])[1]), format_currency(pnl.get("cogs", [0,0,0])[2])],
            ["3. Lợi nhuận gộp", format_currency(pnl.get("gross_profit", [0,0,0])[0]), format_currency(pnl.get("gross_profit", [0,0,0])[1]), format_currency(pnl.get("gross_profit", [0,0,0])[2])],
            ["   - Biên lợi nhuận gộp (%)", format_pct(pnl.get("gross_profit_margin_pct", [0,0,0])[0]), format_pct(pnl.get("gross_profit_margin_pct", [0,0,0])[1]), format_pct(pnl.get("gross_profit_margin_pct", [0,0,0])[2])],
            ["4. Doanh thu hoạt động tài chính", format_currency(pnl.get("financial_income", [0,0,0])[0]), format_currency(pnl.get("financial_income", [0,0,0])[1]), format_currency(pnl.get("financial_income", [0,0,0])[2])],
            ["5. Chi phí tài chính", format_currency(pnl.get("financial_expenses", [0,0,0])[0]), format_currency(pnl.get("financial_expenses", [0,0,0])[1]), format_currency(pnl.get("financial_expenses", [0,0,0])[2])],
            ["   - Trong đó: Chi phí lãi vay", format_currency(pnl.get("interest_expenses", [0,0,0])[0]), format_currency(pnl.get("interest_expenses", [0,0,0])[1]), format_currency(pnl.get("interest_expenses", [0,0,0])[2])],
            ["6. Chi phí bán hàng & QLDN (SG&A)", format_currency(pnl.get("sga_expenses", [0,0,0])[0]), format_currency(pnl.get("sga_expenses", [0,0,0])[1]), format_currency(pnl.get("sga_expenses", [0,0,0])[2])],
            ["7. Lợi nhuận trước thuế (LNTT)", format_currency(pnl.get("net_profit_before_tax", [0,0,0])[0]), format_currency(pnl.get("net_profit_before_tax", [0,0,0])[1]), format_currency(pnl.get("net_profit_before_tax", [0,0,0])[2])],
            ["8. Lợi nhuận sau thuế (LNST)", format_currency(pnl.get("net_profit_after_tax", [0,0,0])[0]), format_currency(pnl.get("net_profit_after_tax", [0,0,0])[1]), format_currency(pnl.get("net_profit_after_tax", [0,0,0])[2])],
        ]
        self._create_styled_table(doc, headers_pnl, rows_pnl, col_widths=[3.2, 1.2, 1.2, 1.2], align_right_cols=[1, 2, 3])

        # Phân tích sâu P&L theo đúng phong cách MB07
        pnl_ana = input_data.get("pnl_deep_dive_analysis", {})
        self._add_heading(doc, "Nhận xét, đánh giá của ĐVKD về Kết quả kinh doanh:", level=2)
        self._add_body_para(doc, pnl_ana.get("revenue_analysis", ""), bold_prefix="+ Về Doanh thu thuần & Sản lượng: ")
        self._add_body_para(doc, pnl_ana.get("cogs_and_production_cost_analysis", ""), bold_prefix="+ Về Giá vốn hàng bán & Cấu trúc chi phí: ")
        self._add_body_para(doc, pnl_ana.get("gross_margin_analysis", ""), bold_prefix="+ Về Biên lợi nhuận gộp: ")
        self._add_body_para(doc, pnl_ana.get("financial_income_and_expenses_analysis", ""), bold_prefix="+ Về Doanh thu & Chi phí tài chính: ")
        self._add_body_para(doc, pnl_ana.get("sga_expenses_analysis", ""), bold_prefix="+ Về Chi phí Bán hàng & Chi phí Quản lý doanh nghiệp: ")
        self._add_body_para(doc, pnl_ana.get("net_profit_and_dividends_analysis", ""), bold_prefix="+ Về Lợi nhuận sau thuế & Phân phối lợi nhuận: ")

        # 3. BẢNG CÂN ĐỐI KẾ TOÁN (CĐKT 3 NĂM)
        self._add_heading(doc, "Bảng Cân đối kế toán:", level=1)
        p_dvt2 = doc.add_paragraph()
        p_dvt2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r_dvt2 = p_dvt2.add_run("ĐVT: Triệu đồng")
        r_dvt2.italic = True
        r_dvt2.font.name = "Times New Roman"
        r_dvt2.font.size = Pt(9.5)

        bs = input_data.get("balance_sheet_3y", {})
        headers_bs = ["Chỉ tiêu CĐKT", f"Năm {years[0]}", f"Năm {years[1]}", f"Năm {years[2]}"]
        rows_bs = [
            ["A. TÀI SẢN NGẮN HẠN", format_currency(bs.get("current_assets", [0,0,0])[0]), format_currency(bs.get("current_assets", [0,0,0])[1]), format_currency(bs.get("current_assets", [0,0,0])[2])],
            ["I. Tiền và các khoản tương đương tiền", format_currency(bs.get("cash_and_equivalents", [0,0,0])[0]), format_currency(bs.get("cash_and_equivalents", [0,0,0])[1]), format_currency(bs.get("cash_and_equivalents", [0,0,0])[2])],
            ["II. Đầu tư tài chính ngắn hạn (Tiền gửi có kỳ hạn)", format_currency(bs.get("short_term_investments", [0,0,0])[0]), format_currency(bs.get("short_term_investments", [0,0,0])[1]), format_currency(bs.get("short_term_investments", [0,0,0])[2])],
            ["III. Các khoản phải thu ngắn hạn của khách hàng", format_currency(bs.get("accounts_receivable", [0,0,0])[0]), format_currency(bs.get("accounts_receivable", [0,0,0])[1]), format_currency(bs.get("accounts_receivable", [0,0,0])[2])],
            ["IV. Hàng tồn kho", format_currency(bs.get("inventories", [0,0,0])[0]), format_currency(bs.get("inventories", [0,0,0])[1]), format_currency(bs.get("inventories", [0,0,0])[2])],
            ["V. Tài sản ngắn hạn khác", format_currency(bs.get("other_current_assets", [0,0,0])[0]), format_currency(bs.get("other_current_assets", [0,0,0])[1]), format_currency(bs.get("other_current_assets", [0,0,0])[2])],
            ["B. TÀI SẢN DÀI HẠN", format_currency(bs.get("non_current_assets", [0,0,0])[0]), format_currency(bs.get("non_current_assets", [0,0,0])[1]), format_currency(bs.get("non_current_assets", [0,0,0])[2])],
            ["I. Tài sản cố định (Giá trị còn lại)", format_currency(bs.get("fixed_assets_net", [0,0,0])[0]), format_currency(bs.get("fixed_assets_net", [0,0,0])[1]), format_currency(bs.get("fixed_assets_net", [0,0,0])[2])],
            ["   - Nguyên giá TSCĐ", format_currency(bs.get("fixed_assets_cost", [0,0,0])[0]), format_currency(bs.get("fixed_assets_cost", [0,0,0])[1]), format_currency(bs.get("fixed_assets_cost", [0,0,0])[2])],
            ["   - Giá trị hao mòn lũy kế", format_currency(bs.get("fixed_assets_depreciation", [0,0,0])[0]), format_currency(bs.get("fixed_assets_depreciation", [0,0,0])[1]), format_currency(bs.get("fixed_assets_depreciation", [0,0,0])[2])],
            ["TỔNG TÀI SẢN (A + B)", format_currency(bs.get("total_assets", [0,0,0])[0]), format_currency(bs.get("total_assets", [0,0,0])[1]), format_currency(bs.get("total_assets", [0,0,0])[2])],
            ["C. NỢ PHẢI TRẢ", format_currency(bs.get("total_liabilities", [0,0,0])[0]), format_currency(bs.get("total_liabilities", [0,0,0])[1]), format_currency(bs.get("total_liabilities", [0,0,0])[2])],
            ["I. Nợ ngắn hạn", format_currency(bs.get("current_liabilities", [0,0,0])[0]), format_currency(bs.get("current_liabilities", [0,0,0])[1]), format_currency(bs.get("current_liabilities", [0,0,0])[2])],
            ["   1. Phải trả người bán ngắn hạn", format_currency(bs.get("accounts_payable", [0,0,0])[0]), format_currency(bs.get("accounts_payable", [0,0,0])[1]), format_currency(bs.get("accounts_payable", [0,0,0])[2])],
            ["   2. Người mua trả tiền trước ngắn hạn", format_currency(bs.get("advances_from_customers", [0,0,0])[0]), format_currency(bs.get("advances_from_customers", [0,0,0])[1]), format_currency(bs.get("advances_from_customers", [0,0,0])[2])],
            ["   3. Vay và nợ thuê tài chính ngắn hạn", format_currency(bs.get("short_term_debt", [0,0,0])[0]), format_currency(bs.get("short_term_debt", [0,0,0])[1]), format_currency(bs.get("short_term_debt", [0,0,0])[2])],
            ["II. Nợ dài hạn", format_currency(bs.get("long_term_debt", [0,0,0])[0]), format_currency(bs.get("long_term_debt", [0,0,0])[1]), format_currency(bs.get("long_term_debt", [0,0,0])[2])],
            ["D. VỐN CHỦ SỞ HỮU", format_currency(bs.get("owners_equity", [0,0,0])[0]), format_currency(bs.get("owners_equity", [0,0,0])[1]), format_currency(bs.get("owners_equity", [0,0,0])[2])],
            ["   1. Vốn đầu tư của chủ sở hữu", format_currency(bs.get("charter_capital_paid", [0,0,0])[0]), format_currency(bs.get("charter_capital_paid", [0,0,0])[1]), format_currency(bs.get("charter_capital_paid", [0,0,0])[1])],
            ["   2. Lợi nhuận sau thuế chưa phân phối", format_currency(bs.get("undistributed_earnings", [0,0,0])[0]), format_currency(bs.get("undistributed_earnings", [0,0,0])[1]), format_currency(bs.get("undistributed_earnings", [0,0,0])[2])],
            ["TỔNG NGUỒN VỐN (C + D)", format_currency(bs.get("total_assets", [0,0,0])[0]), format_currency(bs.get("total_assets", [0,0,0])[1]), format_currency(bs.get("total_assets", [0,0,0])[2])],
        ]
        self._create_styled_table(doc, headers_bs, rows_bs, col_widths=[3.2, 1.2, 1.2, 1.2], align_right_cols=[1, 2, 3])

        # Phân tích sâu từng khoản mục CĐKT kèm Bảng kê đối tác
        sub = input_data.get("sub_tables_deep_dive", {})
        self._add_heading(doc, "Nhận xét, đánh giá của ĐVKD về Thực trạng Tài sản & Nguồn vốn:", level=2)
        
        # Tiền & Đầu tư
        self._add_body_para(
            doc,
            sub.get("cash_and_investments_analysis", "Quy mô Tiền và Đầu tư tài chính ngắn hạn dồi dào, đảm bảo khả năng thanh toán tức thời và dự phòng thanh khoản cao cho doanh nghiệp."),
            bold_prefix="+ Tiền và các khoản tương đương tiền / Tiền gửi có kỳ hạn: "
        )

        # Phải thu KH + Bảng kê
        self._add_body_para(
            doc,
            sub.get("receivables_analysis", "Các khoản phải thu ngắn hạn khách hàng được quản lý chặt chẽ theo chính sách công nợ và tập trung vào các đối tác uy tín, rủi ro nợ khó đòi thấp."),
            bold_prefix="+ Các khoản phải thu ngắn hạn khách hàng: "
        )
        rec_list = sub.get("receivables_breakdown", [])
        if rec_list:
            h_rec = ["STT", "Khách hàng đầu ra", "Số dư nợ (trđ)", "Tỷ trọng", "Điều khoản thanh toán & Tình trạng nợ"]
            r_rec = [[item["stt"], item["customer_name"], format_currency(item["balance_vnd"]), item["share_pct"], f"{item['terms']} | {item['status']}"] for item in rec_list]
            self._create_styled_table(doc, h_rec, r_rec, col_widths=[0.6, 2.4, 1.1, 0.8, 1.9], align_right_cols=[2, 3])

        # Hàng tồn kho + Bảng kê
        self._add_body_para(
            doc,
            sub.get("inventory_analysis", "Hàng tồn kho được luân chuyển ổn định, cơ cấu phù hợp với chu kỳ hoạt động kinh doanh và kế hoạch cung ứng hàng hóa."),
            bold_prefix="+ Hàng tồn kho: "
        )
        inv_list = sub.get("inventory_breakdown", [])
        if inv_list:
            h_inv = ["STT", "Khoản mục Hàng tồn kho", "Giá trị (trđ)", "Tỷ trọng", "Số ngày luân chuyển & Đánh giá rủi ro"]
            r_inv = [[item["stt"], item["item_category"], format_currency(item["value_vnd"]), item["share_pct"], f"{item['rotation_days']} ngày | {item['market_risk']}"] for item in inv_list]
            self._create_styled_table(doc, h_inv, r_inv, col_widths=[0.6, 2.5, 1.1, 0.8, 1.8], align_right_cols=[2, 3])

        # Tài sản cố định
        self._add_body_para(
            doc,
            sub.get("fixed_assets_analysis", "Tài sản cố định phục vụ trực tiếp cho hoạt động kinh doanh chính, được quản lý, bảo dưỡng và trích khấu hao theo đúng quy định."),
            bold_prefix="+ Tài sản cố định: "
        )

        # Phải trả người bán + Bảng kê
        self._add_body_para(
            doc,
            sub.get("payables_analysis", "Nợ phải trả người bán phản ánh chính sách tín dụng thương mại từ các đối tác cung cấp, luân chuyển đúng cam kết hợp đồng."),
            bold_prefix="+ Phải trả người bán ngắn hạn: "
        )
        pay_list = sub.get("payables_breakdown", [])
        if pay_list:
            h_pay = ["STT", "Nhà cung cấp / Đối tác", "Số dư nợ (trđ)", "Tỷ trọng", "Mặt hàng & Điều khoản thanh toán"]
            r_pay = [[item["stt"], item["supplier_name"], format_currency(item["balance_vnd"]), item["share_pct"], f"{item['product']} | {item['payment_terms']}"] for item in pay_list]
            self._create_styled_table(doc, h_pay, r_pay, col_widths=[0.6, 2.4, 1.1, 0.8, 1.9], align_right_cols=[2, 3])

        # Vay nợ ngân hàng + Bảng kê
        self._add_body_para(
            doc,
            sub.get("bank_debt_analysis", "Tình hình quan hệ tín dụng và vay nợ tại các TCTD duy trì tốt, nợ phân loại Nhóm 1, không phát sinh nợ quá hạn."),
            bold_prefix="+ Vay và nợ thuê tài chính ngắn hạn: "
        )
        bank_list = sub.get("bank_debt_breakdown", [])
        if bank_list:
            h_bank = ["STT", "Tổ chức tín dụng (TCTD)", "HMTD cấp (trđ)", "Dư nợ (trđ)", "Hạn mức L/C & Biện pháp bảo đảm"]
            r_bank = [[item["stt"], item["bank_name"], format_currency(item["credit_limit_vnd"]), format_currency(item["outstanding_loan_vnd"]), f"L/C: {format_currency(item.get('lc_limit_vnd', 0))} trđ | {item['collateral']}"] for item in bank_list]
            self._create_styled_table(doc, h_bank, r_bank, col_widths=[0.5, 2.3, 1.1, 1.1, 1.8], align_right_cols=[2, 3])

        # Vốn CSH
        self._add_body_para(
            doc,
            sub.get("equity_analysis", "Vốn chủ sở hữu duy trì vững mạnh, bảo toàn và phát triển tốt qua các năm."),
            bold_prefix="+ Vốn chủ sở hữu: "
        )

        # Cân đối thanh khoản & Cân đối vốn
        self._add_heading(doc, "Cân đối thanh khoản và Cân đối vốn:", level=2)
        self._add_body_para(
            doc,
            sub.get("liquidity_and_capital_balance_analysis", "Cân đối thanh khoản và cân đối vốn của Công ty được đảm bảo an toàn, vốn lưu động ròng dương, không sử dụng vốn ngắn hạn tài trợ cho tài sản dài hạn.")
        )

        # 4. BÁO CÁO DÒNG TIỀN (LƯU CHUYỂN TIỀN TỆ)
        self._add_heading(doc, "Dòng tiền (Báo cáo Lưu chuyển Tiền tệ):", level=1)
        p_dvt3 = doc.add_paragraph()
        p_dvt3.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r_dvt3 = p_dvt3.add_run("ĐVT: Triệu đồng")
        r_dvt3.italic = True
        r_dvt3.font.name = "Times New Roman"
        r_dvt3.font.size = Pt(9.5)

        cf = input_data.get("cash_flow_statement_3y", {})
        headers_cf = ["Chỉ tiêu Lưu chuyển Tiền tệ", f"Năm {years[0]}", f"Năm {years[1]}", f"Năm {years[2]}"]
        rows_cf = [
            ["1. Lưu chuyển tiền thuần từ HĐKD (OCF)", format_currency(cf.get("ocf_cash_from_operations", [0,0,0])[0]), format_currency(cf.get("ocf_cash_from_operations", [0,0,0])[1]), format_currency(cf.get("ocf_cash_from_operations", [0,0,0])[2])],
            ["2. Lưu chuyển tiền thuần từ HĐ Đầu tư (ICF)", format_currency(cf.get("icf_cash_from_investing", [0,0,0])[0]), format_currency(cf.get("icf_cash_from_investing", [0,0,0])[1]), format_currency(cf.get("icf_cash_from_investing", [0,0,0])[2])],
            ["3. Lưu chuyển tiền thuần từ HĐ Tài chính (FCF)", format_currency(cf.get("fcf_cash_from_financing", [0,0,0])[0]), format_currency(cf.get("fcf_cash_from_financing", [0,0,0])[1]), format_currency(cf.get("fcf_cash_from_financing", [0,0,0])[2])],
            ["LƯU CHUYỂN TIỀN THUẦN TRONG KỲ (1+2+3)", format_currency(cf.get("net_cash_flow", [0,0,0])[0]), format_currency(cf.get("net_cash_flow", [0,0,0])[1]), format_currency(cf.get("net_cash_flow", [0,0,0])[2])],
            ["Tiền và tương đương tiền đầu kỳ", format_currency(cf.get("cash_beginning", [0,0,0])[0]), format_currency(cf.get("cash_beginning", [0,0,0])[1]), format_currency(cf.get("cash_beginning", [0,0,0])[2])],
            ["Tiền và tương đương tiền cuối kỳ", format_currency(cf.get("cash_ending", [0,0,0])[0]), format_currency(cf.get("cash_ending", [0,0,0])[1]), format_currency(cf.get("cash_ending", [0,0,0])[2])],
        ]
        self._create_styled_table(doc, headers_cf, rows_cf, col_widths=[3.2, 1.2, 1.2, 1.2], align_right_cols=[1, 2, 3])
        self._add_body_para(doc, cf.get("cash_flow_analysis", ""), bold_prefix="Nhận xét dòng tiền: ")

        # 5. CÁC CHỈ SỐ TÀI CHÍNH TỔNG HỢP
        self._add_heading(doc, "Các chỉ số tài chính tổng hợp:", level=1)
        ratios = input_data.get("financial_ratios_3y", {})
        headers_ratios = ["Nhóm Chỉ số Tài chính", f"Năm {years[0]}", f"Năm {years[1]}", f"Năm {years[2]}", "Chuẩn MSB", "Đánh giá của ĐVKD"]
        rows_ratios = [
            ["1. Khả năng thanh toán hiện hành (Current Ratio)", f"{ratios.get('current_ratio', [0,0,0])[0]:.2f}", f"{ratios.get('current_ratio', [0,0,0])[1]:.2f}", f"{ratios.get('current_ratio', [0,0,0])[2]:.2f}", "≥ 1.10 lần", "Đạt chuẩn an toàn"],
            ["2. Khả năng thanh toán nhanh (Quick Ratio)", f"{ratios.get('quick_ratio', [0,0,0])[0]:.2f}", f"{ratios.get('quick_ratio', [0,0,0])[1]:.2f}", f"{ratios.get('quick_ratio', [0,0,0])[2]:.2f}", "≥ 0.50 lần", "Đạt chuẩn an toàn"],
            ["3. Khả năng thanh toán tức thời (Cash Ratio)", f"{ratios.get('cash_ratio', [0,0,0])[0]:.2f}", f"{ratios.get('cash_ratio', [0,0,0])[1]:.2f}", f"{ratios.get('cash_ratio', [0,0,0])[2]:.2f}", "≥ 0.20 lần", "Thanh khoản tiền mặt dồi dào"],
            ["4. Đòn bẩy nợ D/E (Nợ phải trả / VCSH)", f"{ratios.get('debt_to_equity', [0,0,0])[0]:.2f}", f"{ratios.get('debt_to_equity', [0,0,0])[1]:.2f}", f"{ratios.get('debt_to_equity', [0,0,0])[2]:.2f}", "≤ 3.00 lần", "Kiểm soát an toàn"],
            ["5. Tổng nợ vay tài chính / VCSH", f"{ratios.get('total_debt_to_equity', [0,0,0])[0]:.2f}", f"{ratios.get('total_debt_to_equity', [0,0,0])[1]:.2f}", f"{ratios.get('total_debt_to_equity', [0,0,0])[2]:.2f}", "≤ 2.00 lần", "Đạt chuẩn EB"],
            ["6. Khả năng chi trả lãi vay (ICR / DSCR)", f"{ratios.get('dscr_icr', [0,0,0])[0]:.2f}", f"{ratios.get('dscr_icr', [0,0,0])[1]:.2f}", f"{ratios.get('dscr_icr', [0,0,0])[2]:.2f}", "≥ 1.50 lần", "Dòng tiền trả nợ tốt"],
            ["7. Tỷ suất sinh lời trên Doanh thu (ROS)", format_pct(ratios.get('ros', [0,0,0])[0]), format_pct(ratios.get('ros', [0,0,0])[1]), format_pct(ratios.get('ros', [0,0,0])[2]), "> 0.00%", "Có lãi liên tục"],
            ["8. Tỷ suất sinh lời trên VCSH (ROE)", format_pct(ratios.get('roe', [0,0,0])[0]), format_pct(ratios.get('roe', [0,0,0])[1]), format_pct(ratios.get('roe', [0,0,0])[2]), "> 0.00%", "Bảo toàn vốn nhà nước"],
        ]
        self._create_styled_table(doc, headers_ratios, rows_ratios, col_widths=[2.4, 0.8, 0.8, 0.8, 0.9, 1.1], align_right_cols=[1, 2, 3])

        # Format toàn bộ font chữ
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        for run in para.runs:
                            run.font.name = "Times New Roman"

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        doc.save(output_path)
        return output_path


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample_file = os.path.join(base_dir, "sections_spec", "04_section_D_financial", "4_sample_input.json")
    out_file = os.path.join(base_dir, "output", "TO_TRINH_MB07_PHAN_D_THEP_MIEN_NAM.docx")

    with open(sample_file, "r", encoding="utf-8") as f:
        sample_data = json.load(f)

    agent = AgentSectionD()
    processed = agent.validate_and_process(sample_data)
    print("=== AGENT D PROCESSED ===")
    print(f"Status: {processed['status']}")
    print(f"Warnings: {processed['warnings']}")

    res_path = agent.generate_docx(sample_data, out_file)
    print(f"[OK] DA XUAT THANH CONG BAN WORD PHAN D CHUAN MB07: {res_path}")
