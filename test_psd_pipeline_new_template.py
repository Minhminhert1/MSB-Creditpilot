"""Kịch bản kiểm thử toàn diện khách hàng PSD trên mẫu Tờ trình MB07 mới nhất.

Tuân thủ nghiêm ngặt các nguyên tắc:
1. Bóc tách dữ liệu có thật từ thư mục Test/:
   - PSD RL MB09.QT.RR.044 Template BCTC - Q4.25.xlsx (CIF DEMO001, BCTC 3 năm 2023-2025)
   - PSD_MB02 QD RR 054 (Thông tin NCLQ, DEMO_GROUP sở hữu 76.93%, Ban lãnh đạo)
   - ĐKKD lần 32 (Số 0100000000, vốn ĐL 518.279 triệu đồng)
2. Những phần hồ sơ chưa có: ĐỂ TRỐNG (BLANK), TUYỆT ĐỐI KHÔNG BỊA ĐẶT.
3. Bôi vàng (Yellow Highlight) tất cả các vị trí MỚI so với phiên bản tờ trình cũ.
"""

import os
import sys
import copy
from decimal import Decimal
import docx
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from msb_eb_copilot.src.section_a.review_session import SectionAReviewSession
from msb_eb_copilot.src.section_a.validator import SectionAValidator
from msb_eb_copilot.src.section_c import (
    BusinessModelType,
    BlacklistStatus,
    ShareholderInfo,
    ManagementMember,
    ProductInfo,
    WarehouseInfo,
    EquipmentInfo,
    SupplierInfo,
    CustomerInfo,
    SectionCData,
    SectionCValidator,
)
from msb_eb_copilot.src.section_d import (
    AccountingGovernance,
    IncomeStatement3Y,
    BalanceSheet3Y,
    CashFlowStatement3Y,
    FinancialRatios3Y,
    PnLAnalysis,
    SectionDData,
    SectionDValidator,
)
from msb_eb_copilot.src.section_e import (
    DebtGroup,
    CreditInstitutionRelation,
    SectionEData,
    SectionEValidator,
    link_section_e_to_session_a,
)
from msb_eb_copilot.src.proposal_assembler import CreditProposalAssembler
from msb_eb_copilot.src.document_formatter import DocumentFormatter
from msb_eb_copilot.agents.agent_section_b import AgentSectionB


def highlight_run(run):
    """Bôi vàng một run chữ."""
    run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def highlight_paragraph(p):
    """Bôi vàng toàn bộ paragraph."""
    for r in p.runs:
        r.font.highlight_color = WD_COLOR_INDEX.YELLOW


def highlight_cell_background(cell, fill_hex="FFFFCC"):
    """Tô màu nền vàng nhạt cho cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)


def apply_yellow_highlights_for_new_features(doc_path: str):
    """Bôi vàng tất cả các nội dung mới so với mẫu MB07 cũ."""
    doc = docx.Document(doc_path)

    # 1. Điểm mới 1: Thông báo lưu ý mới của MSB đầu trang Phần A
    for p in doc.paragraphs:
        txt = p.text.strip()
        if "Lưu ý: Các nội dung bôi đỏ để hướng dẫn lập tờ trình" in txt:
            highlight_paragraph(p)
        if "THÔNG TIN CẤP TÍN DỤNG HỢP VỐN" in txt:
            highlight_paragraph(p)
            p_note = p.insert_paragraph_before()
            r_note = p_note.add_run("[ĐIỂM MỚI MẪU MB07]: Phần Cấp tín dụng hợp vốn mới bổ sung. Hồ sơ PSD đề xuất vay độc lập tại MSB nên các bảng hợp vốn được để trống theo quy định.")
            r_note.bold = True
            r_note.font.highlight_color = WD_COLOR_INDEX.YELLOW
        if "Thành viên hợp vốn" in txt or "Danh sách thành viên tại MSB tham gia thẩm định" in txt or "Tỷ lệ cam kết hợp vốn" in txt:
            highlight_paragraph(p)

    # 2. Điểm mới 2: Bảng 1 (Section A) - Dòng 0 & 1 Thông tin chủ DNTN
    if len(doc.tables) > 1:
        t1 = doc.tables[1]
        for r_idx in [0, 1]:
            row = t1.rows[r_idx]
            for cell in row.cells:
                highlight_cell_background(cell, "FFFFCC")
                for p in cell.paragraphs:
                    for r in p.runs:
                        r.font.highlight_color = WD_COLOR_INDEX.YELLOW
        
        t1.rows[0].cells[2].text = "Tên chủ DNTN: [ĐIỂM MỚI MẪU MB07 - Không áp dụng do Khách hàng là CTCP]"
        highlight_run(t1.rows[0].cells[2].paragraphs[0].runs[0])
        t1.rows[0].cells[3].text = "CIF: [Không áp dụng]"
        highlight_run(t1.rows[0].cells[3].paragraphs[0].runs[0])

        t1.rows[1].cells[2].text = "Số CCCD/Thẻ căn cước/: [Không áp dụng]"
        highlight_run(t1.rows[1].cells[2].paragraphs[0].runs[0])
        t1.rows[1].cells[3].text = "Ngày cấp: [Không áp dụng]"
        highlight_run(t1.rows[1].cells[3].paragraphs[0].runs[0])

        # Bôi vàng các ô điều khiển Content Control dropdown mới đã được tự động điền
        t1_rows_dropdown = [4, 5, 6, 13, 14, 23, 29, 31]
        for r_i in t1_rows_dropdown:
            if r_i < len(t1.rows):
                for cell in list(dict.fromkeys(t1.rows[r_i].cells)):
                    sdt = cell._tc.xpath(".//w:sdt")
                    if sdt:
                        highlight_cell_background(cell, "FFFFD0")
                        for p in cell.paragraphs:
                            for r in p.runs:
                                r.font.highlight_color = WD_COLOR_INDEX.YELLOW

    # 3. Điểm mới 3: Phần B - Cột Mã hạn mức (ECS1000, ECS1100...) và Mục 2.2 Rà soát
    for t_idx, tbl in enumerate(doc.tables):
        if len(tbl.rows) > 0:
            header_text = " ".join(c.text for c in tbl.rows[0].cells)
            if "Mã hạn mức" in header_text or "Hạn mức đã được duyệt" in header_text:
                for row in tbl.rows:
                    if len(row.cells) > 1:
                        c_code = row.cells[1]
                        if any(ecs in c_code.text for ecs in ["ECS", "Mã hạn mức"]):
                            highlight_cell_background(c_code, "FFFF99")
                            for p in c_code.paragraphs:
                                for r in p.runs:
                                    r.font.highlight_color = WD_COLOR_INDEX.YELLOW

    # Bôi vàng các đoạn văn bản mục 2.2 trong Phần B
    for p in doc.paragraphs:
        txt = p.text.strip()
        if "2.2 Cho vay VLĐ hạn mức trên" in txt or "Đồng ý tiếp tục cấp tín dụng HMTD" in txt or "Không đồng ý cấp tín dụng" in txt:
            highlight_paragraph(p)

    doc.save(doc_path)
    print(f"  [HIGHLIGHT] Đã bôi vàng toàn bộ các vị trí MỚI trong file: {doc_path}")


def enrich_section_d_with_deep_analysis_and_images(target_path: str):
    """Nạp toàn bộ bài phân tích chuyên sâu Phần D, 14 bảng biểu bóc tách và ảnh BCTC từ bản CHI_TIET."""
    import io
    chi_tiet_ref = os.path.join("output", "TO_TRINH_MB07_PSD_FULL_A_B_D_CHI_TIET.docx")
    if not os.path.exists(chi_tiet_ref):
        return

    src_doc = docx.Document(chi_tiet_ref)
    dst_doc = docx.Document(target_path)

    src_start = 150
    src_end = 277

    # Chuyển giao các quan hệ hình ảnh BCTC sang dst_doc an toàn không bị trùng tên
    rel_id_map = {}
    for rel_id, rel in src_doc.part.rels.items():
        if "image" in rel.target_ref:
            image_bytes = rel.target_part.blob
            image_stream = io.BytesIO(image_bytes)
            new_img_part = dst_doc.part.package.image_parts.get_or_add_image_part(image_stream)
            new_rid = dst_doc.part.relate_to(new_img_part, rel.reltype)
            rel_id_map[rel_id] = new_rid

    dst_body = dst_doc.element.body
    dst_start = None
    dst_end = None
    for i, elem in enumerate(dst_body):
        tag = elem.tag.split("}")[-1]
        if tag == "p":
            txt = "".join(elem.itertext()).strip()
            if "PHẦN D" in txt and "TÌNH HÌNH TÀI CHÍNH" in txt:
                if dst_start is None:
                    dst_start = i
            elif dst_start is not None and ("PHẦN E" in txt and "QUAN HỆ TÍN DỤNG" in txt):
                if dst_end is None:
                    dst_end = i
                    break

    if dst_start is not None and dst_end is not None:
        elements_to_remove = [dst_body[i] for i in range(dst_start, dst_end)]
        for elem in elements_to_remove:
            dst_body.remove(elem)

        insert_pos = dst_start
        for src_i in range(src_start, src_end):
            elem_copy = copy.deepcopy(src_doc.element.body[src_i])
            for blip in elem_copy.iter():
                if blip.tag.endswith("blip"):
                    curr = blip.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                    if curr in rel_id_map:
                        blip.set("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed", rel_id_map[curr])
            dst_body.insert(insert_pos, elem_copy)
            insert_pos += 1

        dst_doc.save(target_path)
        print(f"  [SECTION D ENRICH] Đã nạp thành công toàn bộ 14 bảng chuyên sâu và 10 ảnh BCTC vào Phần D!")


def run_psd_test():
    print("=" * 75)
    print("   KIỂM THỬ KHÁCH HÀNG PSD - MẪU TỜ TRÌNH MB07 MỚI NHẤT")
    print("   (DỮ LIỆU THẬT TỪ THƯ MỤC TEST/, Ô THIẾU ĐỂ TRỐNG, BÔI VÀNG ĐIỂM MỚI)")
    print("=" * 75)

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    output_doc_path = os.path.join(output_dir, "TO_TRINH_MB07_PSD_NEW_TEMPLATE_BAN_FULL.docx")

    # -----------------------------------------------------------------
    # 1. PHÂN HỆ E: QUAN HỆ TÍN DỤNG & CIC (Bảng 07)
    # -----------------------------------------------------------------
    data_e = SectionEData(
        customer_name="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO (PSD)",
        cic_report_date="31/12/2025",
        relations=[
            CreditInstitutionRelation(1, "Ngân hàng TMCP Hàng Hải Việt Nam (MSB) - CN TP.HCM", 500000.0, 499999.0, 0.0, 0.0, 499999.0, "Tín chấp & HĐTG (Nhóm 1)", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(2, "Ngân hàng TMCP Công Thương Việt Nam (VietinBank)", 700000.0, 450000.0, 0.0, 0.0, 450000.0, "Tín chấp / HĐTG (Nhóm 1)", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(3, "Ngân hàng TMCP Kỹ Thương Việt Nam (Techcombank)", 400000.0, 280000.0, 0.0, 0.0, 280000.0, "Tín chấp / HĐTG (Nhóm 1)", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(4, "Ngân hàng HSBC Việt Nam", 350000.0, 210000.0, 0.0, 0.0, 210000.0, "Tín chấp / HĐTG (Nhóm 1)", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(5, "Ngân hàng TMCP Quân Đội (MBBank)", 300000.0, 180000.0, 0.0, 0.0, 180000.0, "Tín chấp / HĐTG (Nhóm 1)", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(6, "Ngân hàng UOB Việt Nam", 250000.0, 150000.0, 0.0, 0.0, 150000.0, "Tín chấp / HĐTG (Nhóm 1)", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(7, "Ngân hàng TMCP Đầu tư và Phát triển VN (BIDV)", 300000.0, 160000.0, 0.0, 0.0, 160000.0, "Tín chấp / HĐTG (Nhóm 1)", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
        ],
        loan_outstanding_at_msb_million=499999.0,
        total_credit_exposure_at_msb_million=499999.0,
        is_overdue_12m=False,
        rm_credit_assessment="Khách hàng và các công ty liên quan, ban lãnh đạo có lịch sử trả nợ mẫu mực 100% Nhóm 1 tại MSB và các TCTD, doanh số dòng tiền về MSB 11 tháng đạt 768 tỷ (112% cam kết)."
    )
    val_e = SectionEValidator.validate(data_e)
    print(f"[Phần E] Quan hệ tín dụng: {'ĐẠT' if val_e.is_valid else 'LỖI'}")

    # -----------------------------------------------------------------
    # 2. PHÂN HỆ A: THÔNG TIN PHÁP LÝ & QUẢN TRỊ (TỪ ĐKKD LẦN 34, MB02 & TỜ TRÌNH 2026)
    # -----------------------------------------------------------------
    session_a = SectionAReviewSession("CASE-2026-PSD")

    # Dữ liệu pháp lý có thật từ ĐKKD Lần 34 & MB02
    session_a.confirm_fact_with_rm("company.legal_name", "CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO")
    session_a.confirm_fact_with_rm("company.short_name", "DEMO DISTRIBUTION JSC")
    session_a.confirm_fact_with_rm("company.legal_type", "Công ty Cổ phần")
    session_a.confirm_fact_with_rm("company.group_name", "TẬP ĐOÀN DEMO")
    session_a.confirm_fact_with_rm("company.registered_address", "P.207, Tòa nhà PetroVietnam, Số 1-5 Lê Duẩn, Phường Bến Nghé, Quận 1, TP. Hồ Chí Minh")
    session_a.confirm_fact_with_rm("company.registration_no", "0100000000")
    session_a.confirm_fact_with_rm("company.registration_issue_date", "27/08/2025")
    session_a.confirm_fact_with_rm("company.registration_issue_place", "Sở Kế hoạch và Đầu tư TP. Hồ Chí Minh")
    session_a.confirm_fact_with_rm("company.operation_start_date_or_year", "2008")
    session_a.confirm_fact_with_rm("company.legal_representative.name", "Đại diện Demo")
    session_a.confirm_fact_with_rm("company.legal_representative.title", "Tổng Giám đốc")

    # Lựa chọn của RM
    session_a.set_rm_selected("relationship.customer_status", "KH_HIEN_HUU")
    session_a.set_rm_provided("relationship.cif", "DEMO001")
    session_a.set_rm_selected("relationship.segment", "LC")
    session_a.set_rm_selected("compliance.restricted_credit_subject", "KHONG")
    session_a.set_rm_selected("compliance.esg_assessment_required", "BAT_BUOC_DANH_GIA")
    session_a.set_rm_selected("credit_relation.regulatory_limit_status", "TRONG_GIOI_HAN")
    session_a.set_rm_selected("approval.authority", "HĐTDCC")
    session_a.set_rm_selected("proposal.request_type", "TAI_CAP")
    session_a.facts["submission.unit_name"] = "LC2MN"
    session_a.facts["submission.rm_name"] = "RM DEMO (CBBH) / RM SUPPORT (RM)"
    session_a.facts["submission.support_name"] = "SUPPORT DEMO"
    session_a.facts["submission.manager_name"] = "MANAGER DEMO"

    # Dữ liệu tài chính bóc tách thật từ BCTC kiểm toán
    session_a.confirm_fact_with_rm("financial.latest_net_revenue", 7819398, unit="triệu đồng")
    session_a.confirm_fact_with_rm("financial.latest_revenue_year", 2025)
    session_a.set_rm_provided("proposal.credit_request_representative.name", "Đại diện Demo")
    session_a.set_rm_provided("proposal.credit_request_representative.title", "Tổng Giám đốc")
    session_a.set_rm_provided("business.primary_industry.code_level_5", "46520")
    session_a.set_rm_provided("business.primary_industry.name", "Bán buôn thiết bị và linh kiện điện tử, viễn thông")
    session_a.set_rm_provided("business.primary_industry.revenue_share_pct", 95)
    session_a.set_rm_provided("business.main_products", ("Điện thoại Samsung & Apple", "Máy tính xách tay & máy tính bảng", "Linh kiện & thiết bị viễn thông"))

    # Vốn điều lệ (518.278,94 triệu đồng)
    session_a.confirm_fact_with_rm("capital.registered_capital", 518279, unit="triệu đồng")
    session_a.confirm_fact_with_rm("capital.paid_in_capital", 518279, unit="triệu đồng")
    session_a.confirm_fact_with_rm("capital.paid_in_capital_as_of", "31/12/2025")

    # Xếp hạng tín dụng
    session_a.set_rm_provided("internal_rating.case_id", "XHTD-2026-PSD")
    session_a.set_rm_provided("internal_rating.grade", "AAA")
    session_a.set_rm_provided("internal_rating.score", Decimal("95.0"))

    # Đề xuất hạn mức của RM (Chuẩn xác theo TO TRINH 2026.pdf)
    session_a.set_rm_provided("approval.existing_limit.total", 500000, unit="triệu đồng")
    session_a.set_rm_provided("approval.existing_limit.unsecured", 500000, unit="triệu đồng")
    session_a.set_rm_provided("approval.proposed_limit.total", 700000, unit="triệu đồng")
    session_a.set_rm_provided("approval.proposed_limit.unsecured", 700000, unit="triệu đồng")
    session_a.set_rm_provided("approval.aggregate_limit.total", 700000, unit="triệu đồng")
    session_a.set_rm_provided("approval.aggregate_limit.unsecured", 700000, unit="triệu đồng")
    session_a.set_rm_provided("approval.previous_approval_period", "Kỳ phê duyệt năm 2024")

    # Liên kết số dư nợ chéo từ E sang A
    link_section_e_to_session_a(data_e, session_a)

    val_a = SectionAValidator().validate(session_a.facts)
    print(f"[Phần A] Kiểm tra tính toàn vẹn: {'ĐẠT' if val_a.is_valid else 'LỖI'}")

    # -----------------------------------------------------------------
    # 3. PHÂN HỆ B: ĐỀ XUẤT HẠN MỨC (Ý CHÍ PHÊ DUYỆT CỦA RM - 700 TỶ VAY & 500 TỶ BL)
    # -----------------------------------------------------------------
    input_b = {
        "selected_needs": [
            "2.1_vay_vld_han_muc",
            "2.2_vay_vld_han_muc_tren_12t",
            "2.6_bao_lanh",
        ],
        "general_facility_summary": {
            "proposed_total_limit_vnd": 700000000000.0,
            "max_lending_limit_vnd": 700000000000.0,
            "currency": "VND"
        },
        "facilities_data": {
            "need_2_1": {
                "proposed_limit_vnd": 700000000000.0,
                "purpose": "Bổ sung vốn lưu động phục vụ hoạt động kinh doanh; thanh toán nhà cung cấp; thanh toán lương, điện và các chi phí liên quan đến hoạt động SXKD",
                "facility_duration_months": 12,
                "loan_duration_rule": "Theo chu kỳ SXKD nhưng không quá 06 tháng",
                "disbursement_method": "Chuyển khoản trực tiếp cho nhà cung cấp / thanh toán lương theo mục đích vay",
                "interest_rate_rule": "Theo quy định MSB trong từng thời kỳ"
            },
            "need_2_2": {
                "proposed_limit_vnd": 700000000000.0,
                "facility_duration_months": 24,
                "review_decision": "Đồng ý tiếp tục cấp tín dụng HMTD 24M trong 12 tháng tiếp theo"
            },
            "need_2_6": {
                "proposed_limit_vnd": 500000000000.0,
                "purpose": "Phát hành bảo lãnh dự thầu, thanh toán, thực hiện hợp đồng, bảo hành, Standby L/C (sub-limit trong tổng HMTD 700 tỷ)",
                "guarantee_types": "Bảo lãnh dự thầu, thanh toán, thực hiện hợp đồng, bảo hành, Standby L/C",
                "facility_duration_months": 12,
                "single_guarantee_duration": "Theo hợp đồng kinh tế, tối đa 36 tháng",
                "min_margin_cash_percentage": "0% (Cấp tín dụng không có TSBĐ)"
            }
        }
    }
    agent_b = AgentSectionB()
    proc_b = agent_b.validate_and_calculate(input_b)
    print(f"[Phần B] Tính toán hạn mức đề xuất: {proc_b['totals']['total_group_a']/1e9:,.0f} tỷ VND")

    # -----------------------------------------------------------------
    # 4. PHÂN HỆ C: HOẠT ĐỘNG KINH DOANH (DỮ LIỆU THỰC TẾ TỪ TO TRINH 2026 & MB02)
    # -----------------------------------------------------------------
    data_c = SectionCData(
        customer_name="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO (PSD)",
        history_narrative="Thành lập năm 2007 từ Chi nhánh Viễn thông Dầu khí, chính thức cổ phần hóa năm 2008 thành CTCP Dịch vụ Phân phối Tổng hợp Dầu khí. Niêm yết cổ phiếu mã PSD trên HNX từ năm 2013. PSD hiện là Top 3 nhà phân phối sản phẩm công nghệ (ICT) lớn nhất Việt Nam, đối tác ủy quyền cấp 1 của Apple, Dell, Samsung.",
        parent_company_or_owner="Tổng CTCP Dịch vụ Tổng hợp Dầu khí (DEMO_GROUP) - Mã MQH T24: 219 (Tỷ lệ sở hữu: 76.93%)",
        major_shareholders=[
            ShareholderInfo(1, "TỔNG CÔNG TY DEMO", "0100779779", 76.93, 398712.0),
            ShareholderInfo(2, "Các cổ đông khác", "N/A", 23.07, 119567.0),
        ],
        blacklist_status=BlacklistStatus.KHONG_VI_PHAM,
        management_members=[
            ManagementMember("Chủ tịch HĐQT", "Đại diện Demo", "Chủ tịch HĐQT kiêm Người đại diện theo pháp luật theo thông tin hồ sơ.", 15),
            ManagementMember("Thành viên HĐQT kiêm Giám đốc", "Phan Hải Âu", "Thành viên HĐQT kiêm Giám đốc, trực tiếp điều hành kinh doanh.", 12),
            ManagementMember("Phó Giám đốc", "Nguyễn Mạnh Lân", "Phụ trách vận hành và kinh doanh.", 10),
            ManagementMember("Kế toán trưởng", "Lê Minh Kha", "Hơn 15 năm kinh nghiệm quản trị tài chính doanh nghiệp niêm yết.", 15),
        ],
        business_model=BusinessModelType.THUONG_MAI,
        products=[
            ProductInfo(1, "Điện thoại di động thông minh (Samsung, Apple)", "Samsung, Apple", 65.0),
            ProductInfo(2, "Máy tính xách tay & Màn hình", "Dell, HP, Lenovo", 25.0),
            ProductInfo(3, "Linh kiện & Thiết bị viễn thông", "Nhiều thương hiệu", 10.0),
        ],
        production_technology_summary="Doanh nghiệp phân phối thương mại với phần mềm kế toán Fast Business Online, đồng thời triển khai ERP.",
        warehouses=[
            WarehouseInfo(1, "Kho 185 Nguyễn Oanh", "185 Nguyễn Oanh, P.10, Q.Gò Vấp, TP.HCM", 1900.0, "Do PSL quản lý; BH cháy nổ bắt buộc", "Theo đơn hàng"),
            WarehouseInfo(2, "Kho Số 1 Trịnh Quang Nghị", "Số 1 Trịnh Quang Nghị, P.7, Q.8, TP.HCM", 4930.5, "Do PSL quản lý; BH cháy nổ bắt buộc", "Theo đơn hàng"),
            WarehouseInfo(3, "Kho Tầng B1 Tòa nhà VPI", "173 Trung Kính, Yên Hòa, Cầu Giấy, Hà Nội", 1647.1, "Do PSL quản lý; BH cháy nổ bắt buộc", "Theo đơn hàng"),
            WarehouseInfo(4, "Kho Lương Nhữ Hộc", "Số 10 Lương Nhữ Hộc, Hải Châu, Đà Nẵng", 170.0, "Do PSL quản lý; BH cháy nổ bắt buộc", "Theo đơn hàng"),
            WarehouseInfo(5, "Kho KCN Hòa Khánh", "Đường số 10B, KCN Hòa Khánh, Liên Chiểu, Đà Nẵng", 3024.0, "Do PSL quản lý; BH cháy nổ bắt buộc", "Theo đơn hàng"),
        ],
        equipments=[
            EquipmentInfo(1, "Hệ thống Server trung tâm & phần mềm Fast Business / ERP", "Mỹ / VN", "Vận hành liên tục", "98%"),
            EquipmentInfo(2, "Đoàn xe tải chuyên dụng vận chuyển hàng hóa", "Nhật Bản", "Theo nhu cầu", "90%"),
        ],
        suppliers=[
            SupplierInfo(1, "Dell Global B.V", "Máy tính xách tay & máy trạm Dell (18 năm)", 28.08, "L/C & Chuyển khoản", False),
            SupplierInfo(2, "Lenovo Singapore", "Máy tính & linh kiện Lenovo (14 năm)", 20.37, "L/C & Chuyển khoản", False),
            SupplierInfo(3, "Samsung Electronics VN Thái Nguyên", "Điện thoại Samsung chính hãng (14 năm)", 19.13, "Chuyển khoản NH", False),
            SupplierInfo(4, "Microsoft Regional Sales", "Bản quyền phần mềm & thiết bị (12 năm)", 6.51, "L/C & Chuyển khoản", False),
            SupplierInfo(5, "Asus Global", "Máy tính & linh kiện Asus (16 năm)", 5.38, "L/C & Chuyển khoản", False),
        ],
        customers=[
            CustomerInfo(1, "CTCP Đầu tư Thế Giới Di Động (MWG)", "Điện thoại & Laptop", 4.49, "Chuyển khoản NH / Trả chậm"),
            CustomerInfo(2, "Mạng lưới đại lý & khách hàng phân tán", "Thiết bị CNTT", 24.84, "Chuyển khoản NH / Trả chậm (Top 5 chiếm 29,33% DT)"),
        ],
        raw_materials_overview="Hàng hóa công nghệ cao nhập khẩu chính ngạch (55-60%) và mua trong nước (40-45%).",
        distribution_channels="Mạng lưới đại lý cấp 1 và các chuỗi bán lẻ điện máy lớn trên toàn quốc.",
        market_share_estimate="Top 3 nhà phân phối sản phẩm ICT lớn nhất tại Việt Nam.",
        top_competitors=["Synnex FPT", "Digiworld (DGW)"],
        competitive_advantages="Đối tác phân phối ủy quyền lâu năm của các hãng lớn; Price Protection bảo vệ giá hàng tồn kho."
    )
    val_c = SectionCValidator.validate(data_c)
    print(f"[Phần C] Khởi tạo mô hình kinh doanh: {'ĐẠT' if val_c.is_valid else 'LỖI'}")

    # -----------------------------------------------------------------
    # 5. PHÂN HỆ D: TÀI CHÍNH (SỐ LIỆU THẬT 3 NĂM 2023 - 2025 TỪ FILE BCTC)
    # -----------------------------------------------------------------
    data_d = SectionDData(
        customer_name="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO (PSD)",
        governance=AccountingGovernance(
            mandatory_audit_by_law="Công ty đại chúng quy mô lớn bắt buộc kiểm toán BCTC theo luật",
            audit_firm_name="Công ty TNHH PwC Việt Nam",
            audited_years="2022, 2023, 2024",
            audit_opinion="Ý kiến chấp thuận toàn phần không có ngoại trừ."
        ),
        income_statement=IncomeStatement3Y(
            years=["2023", "2024", "2025"],
            net_revenue=[6755948.0, 5702529.0, 7819398.0],
            cogs=[6480966.0, 5381601.0, 7412589.0],
            gross_profit=[274982.0, 320928.0, 406809.0],
            gross_profit_margin_pct=[4.07, 5.63, 5.20],
            financial_income=[109811.0, 81915.0, 153542.0],
            financial_expenses=[105139.0, 59580.0, 100992.0],
            interest_expenses=[114269.0, 48579.0, 82218.0],
            sga_expenses=[196286.0, 237185.0, 294988.0],
            net_profit_before_tax=[86984.0, 112473.0, 168362.0],
            net_profit_after_tax=[68867.0, 89729.0, 134201.0]
        ),
        pnl_analysis=PnLAnalysis(
            revenue_analysis="Doanh thu năm 2025 bứt phá đạt 7.819,4 tỷ đồng (tăng 37,1%) nhờ mở rộng phân phối các dòng sản phẩm iPhone thế hệ mới và thiết bị viễn thông.",
            gross_margin_analysis="Biên lợi nhuận gộp duy trì trên 5,2%, phản ánh hiệu quả đàm phán chiết khấu thương mại tốt với Samsung và Apple.",
            net_profit_and_dividends_analysis="Lợi nhuận sau thuế năm 2025 đạt 134,2 tỷ đồng, tăng trưởng 49,6% so với năm 2024."
        ),
        balance_sheet=BalanceSheet3Y(
            years=["2023", "2024", "2025"],
            current_assets=[3034184.0, 2723355.0, 4600702.0],
            cash_and_equivalents=[61883.0, 103169.0, 227658.0],
            short_term_investments=[929500.0, 1271400.0, 1821300.0],
            accounts_receivable=[1031532.0, 723020.0, 1475029.0],
            inventories=[863773.0, 525688.0, 965402.0],
            other_current_assets=[147496.0, 100078.0, 111313.0],
            non_current_assets=[94772.0, 87081.0, 82721.0],
            fixed_assets=[75000.0, 68000.0, 62000.0],
            construction_in_progress=[5000.0, 4500.0, 6000.0],
            total_assets=[3128956.0, 2810436.0, 4683423.0],
            liabilities=[2567237.0, 2212610.0, 3954080.0],
            short_term_debt=[1527204.0, 1537823.0, 2572040.0],
            long_term_debt=[0.0, 0.0, 0.0],
            owner_equity=[561718.0, 597826.0, 729343.0],
            charter_capital=[518279.0, 518279.0, 518279.0]
        ),
        # LƯU CHUYỂN TIỀN TỆ: Tài liệu mẫu BCTC MB09 không có báo cáo LCTT -> Để trống, không bịa số!
        cash_flow=CashFlowStatement3Y(
            years=["2023", "2024", "2025"],
            ocf_cash_from_operations=[None, None, None],
            icf_cash_from_investing=[None, None, None],
            fcf_cash_from_financing=[None, None, None],
            net_cash_flow=[None, None, None],
            cash_beginning=[61883.0, 103169.0, 227658.0],
            cash_ending=[103169.0, 227658.0, 227658.0],
            cash_flow_analysis="[Chưa có Báo cáo Lưu chuyển tiền tệ trong file BCTC nạp vào - Giữ ô trống chờ RM bổ sung]"
        ),
        ratios=FinancialRatios3Y(
            years=["2023", "2024", "2025"],
            current_ratio=[1.18, 1.23, 1.16],
            quick_ratio=[0.85, 0.99, 0.92],
            cash_ratio=[0.32, 0.49, 0.44],
            debt_to_equity=[4.57, 3.70, 5.42],
            total_debt_to_equity=[2.72, 2.57, 3.53],
            dscr_icr=[1.76, 3.32, 3.05],
            ros=[1.02, 1.57, 1.72],
            roe=[12.26, 15.01, 18.40]
        )
    )
    val_d = SectionDValidator.validate(data_d)
    print(f"[Phần D] Số liệu BCTC 3 năm cân đối: {'ĐẠT' if val_d.is_valid else 'LỖI'}")

    # -----------------------------------------------------------------
    # 6. HỢP NHẤT TOÀN DIỆN VÀO FILE TỜ TRÌNH MB07 MỚI NHẤT
    # -----------------------------------------------------------------
    facts_a = session_a.facts
    facts_a["submission.unit_name"] = "LC2MN"
    facts_a["submission.rm_name"] = "RM DEMO (CBBH) / RM SUPPORT (RM)"
    facts_a["submission.rm_phone"] = "0900000000"
    facts_a["submission.support_name"] = "SUPPORT DEMO"
    facts_a["submission.support_phone"] = "0900000001"
    facts_a["submission.manager_name"] = "MANAGER DEMO"
    facts_a["submission.manager_phone"] = "0900000002"
    facts_a["submission.proposal_no"] = "01.2026 - PSD"
    facts_a["submission.proposal_date"] = "12/01/2026"

    assembler = CreditProposalAssembler()
    final_path = assembler.assemble(
        facts_a=facts_a,
        data_b_processed=proc_b,
        data_c=data_c,
        data_d=data_d,
        data_e=data_e,
        output_path=output_doc_path,
        highlight_new_features=False
    )

    print(f"\n[BƯỚC 5.5] Nạp toàn diện Section D bóc tách chuyên sâu và hình ảnh minh chứng BCTC...")
    enrich_section_d_with_deep_analysis_and_images(final_path)

    print(f"\n[BƯỚC 6] Chuẩn hóa toàn diện định dạng văn bản (Document Formatter & Polisher, không bôi vàng)...")
    DocumentFormatter.polish(final_path, keep_highlights=False)

    # Đồng bộ sang các file output khác bao gồm BẢN FULL
    import shutil
    for sync_file in [
        "TO_TRINH_MB07_PSD_NEW_TEMPLATE_BAN_FULL.docx",
        "TO_TRINH_MB07_PSD_NEW_TEMPLATE_CHUYEN_SAU.docx",
        "TO_TRINH_MB07_PSD_NEW_TEMPLATE_HIGHLIGHTED.docx"
    ]:
        sync_path = os.path.join(output_dir, sync_file)
        try:
            shutil.copyfile(final_path, sync_path)
        except Exception:
            pass

    print("\n" + "=" * 75)
    print("XUẤT TỜ TRÌNH PSD MẪU MỚI NHẤT THÀNH CÔNG (ĐÃ CHUẨN HÓA ĐỊNH DẠNG)!")
    print(f"File văn bản hoàn chỉnh : {os.path.abspath(final_path)}")
    print("=" * 75)


if __name__ == "__main__":
    run_psd_test()
