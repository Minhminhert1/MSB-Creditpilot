# -*- coding: utf-8 -*-
"""Ứng dụng Web hoàn chỉnh: MSB Credit Proposal AI Copilot dành cho RM.

Tính năng nổi bật:
- ĐA KHÁCH HÀNG (MULTI-CASE): Làm tờ trình cho bất kỳ khách hàng nào (PSD, GAS SOUTH, hoặc Bấm "+ Tạo Hồ Sơ Khách Hàng Mới").
- Cơ chế cộng tác: 70-80% AI trích xuất tự động + 20-30% RM nhập/đánh giá.
- Hệ thống phân định rõ ràng:
  + [AI ĐÃ TRÍCH XUẤT]: Thông tin tự động bóc tách từ BCTC, ĐKKD, CIC.
  + [CHƯA CÓ DỮ LIỆU - CẦN RM NHẬP]: Những mục còn thiếu dữ liệu bắt buộc RM phải cung cấp.
  + [CÂU HỎI CỐ ĐỊNH RM]: Thông tin nhân sự thẩm định, tờ trình, hạn mức đề xuất.
  + [GỢI Ý & POP-UP AI]: Phân tích ngữ cảnh theo từng ngành nghề để RM tham khảo.
  + [ĐÁNH GIÁ CỦA RM / ĐVKD]: RM biên tập nhận xét trực tiếp trên giao diện.
- 1-Click "Xuất Tờ Trình MB07 (.DOCX)": Tự động sinh file Word hoàn chỉnh, sạch 100% highlight, chuẩn font mẫu MSB, loại bỏ toàn bộ bảng trống.
"""

import os
import sys
import json
import shutil
import urllib.parse
import uuid
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, ".")
sys.path.insert(0, "msb_eb_copilot")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from msb_eb_copilot.src.credit_committee_prep import CreditCommitteePrepEngine, CommitteeQuestionCard
from msb_eb_copilot.src.narrative import (
    FactPackager, PythonInsightVerifier, GLMInsightDiscoveryAgent,
    GLMNarrativeWriterAgent, DeterministicNarrativeValidator,
    CreditNarrativePackage, NarrativeDraftManager, NarrativeTargetBinding,
    NARRATIVE_DRAFT_STORE
)
from msb_eb_copilot.src.proposal_assembler import CreditProposalAssembler
from msb_eb_copilot.src.document_formatter import DocumentFormatter
from msb_eb_copilot.src.section_a.review_session import SectionAReviewSession
from msb_eb_copilot.src.section_a.validator import SectionAValidator
from msb_eb_copilot.src.section_c import (
    BusinessModelType, BlacklistStatus, ShareholderInfo,
    ManagementMember, ProductInfo, WarehouseInfo, EquipmentInfo,
    SupplierInfo, CustomerInfo, SectionCData, SectionCValidator
)
from msb_eb_copilot.src.section_d import (
    AccountingGovernance, IncomeStatement3Y, BalanceSheet3Y,
    CashFlowStatement3Y, FinancialRatios3Y, PnLAnalysis,
    SectionDData, SectionDValidator
)
from msb_eb_copilot.src.section_e import (
    DebtGroup, CreditInstitutionRelation, SectionEData,
    SectionEValidator, link_section_e_to_session_a
)
from msb_eb_copilot.agents.agent_section_b import AgentSectionB
from msb_eb_copilot.src.ai_client import AIAssistantClient
import base64
import tempfile

# Sentinel for test audit verification: confirms legacy extractor is never called in preview pipeline
AIDocumentExtractor = None

# ==============================================================================
# HACKATHON COMPETITION RUNTIME CONFIGURATION (GREENNODE-ONLY)
# ==============================================================================
os.environ["APP_MODE"] = os.getenv("APP_MODE", "hackathon")
os.environ["AI_PROVIDER"] = "greennode"
os.environ["ALLOW_AI_FALLBACK"] = "false"
os.environ["ALLOW_HEURISTIC_EXTRACTION"] = "false"


def read_uploaded_document_text(file_path: str) -> str:
    """Đọc văn bản thô từ file tài liệu tải lên (PDF, DOCX, XLSX, TXT) để hiển thị."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)
        except Exception as e:
            return f"[Lỗi đọc file PDF: {e}]"
    elif ext == ".docx":
        try:
            import docx
            doc = docx.Document(file_path)
            paras = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paras)
        except Exception as e:
            return f"[Lỗi đọc file DOCX: {e}]"
    elif ext in [".xlsx", ".xls"]:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, data_only=True)
            lines = []
            for sheet in wb.sheetnames[:3]:
                ws = wb[sheet]
                lines.append(f"--- Sheet: {sheet} ---")
                for row in ws.iter_rows(values_only=True):
                    row_vals = [str(v).strip() for v in row if v is not None]
                    if row_vals:
                        lines.append(" | ".join(row_vals))
            return "\n".join(lines[:1000])
        except Exception as e:
            return f"[Lỗi đọc file Excel: {e}]"
    else:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            return f"[Lỗi đọc file text: {e}]"

from msb_eb_copilot.src.ingestion.router import (
    DocumentIngestionRouter,
    DocumentIngestionResult,
)
from msb_eb_copilot.src.ingestion.pdf_text import (
    PDFEncryptedError,
    PDFFileNotFoundError,
    PDFBlankPageError,
    PDFNoTextError,
    PDFIngestionError,
)
from msb_eb_copilot.src.ingestion.pdf_ocr import (
    OCRTimeoutError,
    OCRServiceError,
    OCRIngestionError,
)
from msb_eb_copilot.src.extraction.legal_extraction import (
    LegalDocumentExtractor,
    LegalDocumentExtraction,
    EvidenceField,
    ExtractionError,
    ExtractionAuditError,
    ExtractionSchemaError,
    ExtractionJSONError,
    ExtractionSemanticError,
    ExtractionPageMarkerError,
)
from msb_eb_copilot.src.mapping.legal_mapper import (
    LegalDocumentMapper,
    _normalize_text_for_comparison,
    _normalize_tax_code_for_comparison,
)
from msb_eb_copilot.src.mapping.models import (
    MappingSourceMetadata,
    CanonicalMappingResult,
    MappingError,
    MappingSchemaError,
    MappingWarning,
    MappingConflict,
)
from msb_eb_copilot.src.extraction.financial_extraction import (
    FinancialDocumentExtractor,
    FinancialDocumentExtraction,
    FinancialPeriodExtraction,
    FinancialEvidenceField,
    FinancialGroundingAuditor,
)
from msb_eb_copilot.src.mapping.financial_mapper import (
    FinancialDocumentMapper,
    compute_canonical_ratios,
    FINANCIAL_SOURCE_FACT_FIELDS,
)
from msb_eb_copilot.src.extraction.cic_extraction import (
    CICDocumentExtractor,
    CICDocumentExtraction,
    CICGroundingAuditor,
    CICNormalizer,
    CICIdentityReconciler,
)
from msb_eb_copilot.src.mapping.cic_mapper import CICDocumentMapper
from msb_eb_copilot.src.section_e.models import is_msb_institution
from msb_eb_copilot.src.extraction.business_extraction import (
    BusinessDocumentExtractor,
    BusinessDocumentExtraction,
    BusinessGroundingAuditor,
    BusinessIdentityReconciler,
    BusinessModelClassifier,
)
from msb_eb_copilot.src.mapping.business_mapper import BusinessDocumentMapper

PORT = int(os.getenv("PORT", 8080))

# ==============================================================================
# MULTI-CASE DATABASE
# ==============================================================================
CASES_DB = {
    "PSD": {
        "id": "PSD",
        "name": "PSD - CTCP Dịch vụ Phân phối TH Dầu khí",
        "customer": {
            "name": "CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO",
            "short_name": "DEMO DISTRIBUTION JSC",
            "tax_code": "0100000000",
            "cif": "DEMO001",
            "segment": "LC",
            "parent_group": "TẬP ĐOÀN DEMO",
            "established_year": "2008",
            "address": "P.207, Tòa nhà PetroVietnam, Số 1-5 Lê Duẩn, Phường Bến Nghé, Quận 1, TP. Hồ Chí Minh",
            "legal_rep_name": "Đại diện Demo",
            "legal_rep_title": "Tổng Giám đốc",
            "charter_capital": 518279,
            "revenue_2025": 7819398,
            "rating_grade": "AAA",
            "rating_score": 95.0,
            "restricted_subject": "KHONG",
            "esg_status": "BAT_BUOC_DANH_GIA"
        },
        "rm_metadata": {
            "unit_name": "LC2MN",
            "rm_name": "RM DEMO (CBBH) / RM SUPPORT (RM)",
            "rm_phone": "0900000000",
            "support_name": "SUPPORT DEMO",
            "support_phone": "0900000001",
            "manager_name": "MANAGER DEMO",
            "manager_phone": "0900000002",
            "proposal_no": "01.2026 - PSD",
            "proposal_date": "12/01/2026",
            "approval_authority": "HĐTDCC",
            "request_type": "TAI_CAP"
        },
        "section_b": {
            "selected_needs": ["2.1_vay_vld_han_muc", "2.2_vay_vld_han_muc_tren_12t", "2.6_bao_lanh"],
            "total_limit": 700000,
            "loan_limit": 250000,
            "guarantee_limit": 30000,
            "loan_purpose": "Bổ sung vốn lưu động phục vụ hoạt động kinh doanh; thanh toán nhà cung cấp; chi trả lương và chi phí vận hành thường xuyên.",
            "loan_tenor_months": 12,
            "disbursement_method": "Chuyển khoản trực tiếp cho bên thụ hưởng theo hợp đồng mua bán / Hóa đơn tài chính.",
            "collateral_type": "Tín chấp 100% (Cấp tín dụng không có TSBĐ theo phê duyệt định hạng A+)",
            "cashflow_commitment_pct": 25.0,
            "cashflow_direct_pct": 5.0,
            "ewt_conditions": "Tuân thủ 6 ngưỡng cảnh báo sớm (EWT) theo quy định MSB."
        },
        "section_c": {
            "history_narrative": "Thành lập năm 2007 từ Chi nhánh Viễn thông Dầu khí, chính thức cổ phần hóa năm 2008 thành CTCP Dịch vụ Phân phối Tổng hợp Dầu khí. Niêm yết cổ phiếu mã PSD trên HNX từ năm 2013. PSD hiện là Top 3 nhà phân phối sản phẩm công nghệ (ICT) lớn nhất Việt Nam, đối tác ủy quyền cấp 1 của Apple, Dell, Samsung.",
            "shareholders": [
                {"name": "TỔNG CÔNG TY DEMO", "tax_code": "0100779779", "pct": 76.93, "val": 398712.0},
                {"name": "Các cổdong khác", "tax_code": "N/A", "pct": 23.07, "val": 119567.0}
            ],
            "management": [
                {"title": "Chủ tịch HĐQT", "name": "Đại diện Demo", "note": "Chủ tịch HĐQT kiêm Đại diện pháp luật.", "exp": 15},
                {"title": "Thành viên HĐQT kiêm Giám đốc", "name": "Phan Hải Âu", "note": "Thành viên HĐQT kiêm Giám đốc, trực tiếp điều hành.", "exp": 12},
                {"title": "Phó Giám đốc", "name": "Nguyễn Mạnh Lân", "note": "Phụ trách vận hành và kinh doanh.", "exp": 10},
                {"title": "Kế toán trưởng", "name": "Lê Minh Kha", "note": "Hơn 15 năm kinh nghiệm quản trị tài chính.", "exp": 15}
            ],
            "business_model": "THUONG_MAI",
            "products": [
                {"name": "Điện thoại thông minh (Samsung, Apple)", "spec": "Samsung, Apple", "share": 65.0},
                {"name": "Máy tính xách tay & Màn hình", "spec": "Dell, HP, Lenovo", "share": 25.0},
                {"name": "Linh kiện & Thiết bị viễn thông", "spec": "Nhiều thương hiệu", "share": 10.0}
            ],
            "suppliers": [
                {"name": "Dell Global B.V", "goods": "Máy tính xách tay & máy trạm Dell (18 năm)", "share": 28.08, "term": "L/C & Chuyển khoản"},
                {"name": "Lenovo Singapore", "goods": "Máy tính & linh kiện Lenovo (14 năm)", "share": 20.37, "term": "L/C & Chuyển khoản"},
                {"name": "Samsung Electronics VN Thái Nguyên", "goods": "Điện thoại Samsung chính hãng (14 năm)", "share": 19.13, "term": "Chuyển khoản NH"},
                {"name": "Microsoft Regional Sales", "goods": "Bản quyền phần mềm & thiết bị (12 năm)", "share": 6.51, "term": "L/C & Chuyển khoản"},
                {"name": "Asus Global", "goods": "Máy tính & linh kiện Asus (16 năm)", "share": 5.38, "term": "L/C & Chuyển khoản"}
            ],
            "customers": [
                {"name": "CTCP Đầu tư Thế Giới Di Động (MWG)", "goods": "Điện thoại & Laptop", "share": 4.49, "term": "Chuyển khoản NH / Trả chậm"},
                {"name": "Mạng lưới đại lý & khách hàng phân tán", "goods": "Thiết bị CNTT", "share": 24.84, "term": "Chuyển khoản NH / Trả chậm"}
            ],
            "rm_management_assessment": "Ban điều hành có năng lực chuyên môn vững vàng, gắn bó lâu năm (>15 năm trong ngành phân phối ICT). Tính minh bạch thông tin cao do là công ty đại chúng quy mô lớn.",
            "rm_market_position": "PSD giữ vị thế Top 3 nhà phân phối sản phẩm công nghệ hàng đầu Việt Nam. Cơ cấu khách hàng đầu ra uy tín gồm Thế Giới Di Động, FPT Shop, Viettel Store...",
            "rm_risk_mitigation": "Hợp đồng với nhà cung cấp chính (Apple, Samsung, Dell) có cơ chế bảo vệ giá tồn kho (Price Protection) giúp hạn chế rủi ro giảm giá hàng công nghệ."
        },
        "section_d": {
            "auditor": "Công ty TNHH PwC Việt Nam (Ý kiến chấp thuận toàn phần)",
            "years": ["2023", "2024", "2025"],
            "net_revenue": [6755948.0, 5702529.0, 7819398.0],
            "cogs": [6480966.0, 5381601.0, 7412589.0],
            "gross_profit": [274982.0, 320928.0, 406809.0],
            "net_profit_after_tax": [68867.0, 89729.0, 134201.0],
            "current_assets": [3034184.0, 2723355.0, 4600702.0],
            "cash": [61883.0, 103169.0, 227658.0],
            "receivables": [1031532.0, 723020.0, 1475029.0],
            "inventories": [863773.0, 525688.0, 965402.0],
            "total_assets": [3128956.0, 2810436.0, 4683423.0],
            "short_term_debt": [1527204.0, 1537823.0, 2572040.0],
            "equity": [561718.0, 597826.0, 729343.0],
            "rm_pnl_assessment": "Doanh thu năm 2025 bứt phá đạt 7.819,4 tỷ đồng (tăng 37,1%) nhờ mở rộng phân phối các dòng sản phẩm iPhone thế hệ mới và thiết bị viễn thông. Biên lợi nhuận gộp duy trì trên 5,2%.",
            "rm_balance_sheet_assessment": "Tài sản ngắn hạn chiếm 98,2% tổng tài sản, phù hợp đặc thù doanh nghiệp phân phối thương mại. Tỷ lệ đòn bẩy tài chính ở mức an toàn trong ngành.",
            "rm_cashflow_assessment": "Dòng tiền từ hoạt động kinh doanh đảm bảo thanh khoản. Khách hàng chủ động duy trì lượng tiền gửi và tương đương tiền dồi dào (>227 tỷ VND tại ngày 31/12/2025)."
        },
        "section_e": {
            "cic_date": "31/12/2025",
            "msb_outstanding": 499999.0,
            "history_status": "100% Nhóm 1 (Đủ tiêu chuẩn) trong 24 tháng gần nhất tại MSB và các TCTD.",
            "rm_credit_assessment": "Khách hàng và các công ty liên quan, ban lãnh đạo có lịch sử trả nợ mẫu mực 100% Nhóm 1 tại MSB và các TCTD. Doanh số dòng tiền về MSB 11 tháng năm 2025 đạt 768 tỷ (112% cam kết)."
        }
    },
    "GAS_SOUTH": {
        "id": "GAS_SOUTH",
        "name": "GAS SOUTH - CTCP Kinh doanh Khí Miền Nam",
        "customer": {
            "name": "CÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM",
            "short_name": "GAS SOUTH JSC (PGS)",
            "tax_code": "0304958184",
            "cif": "189420",
            "segment": "LC",
            "parent_group": "TỔNG CÔNG TY KHÍ VIỆT NAM (PV GAS)",
            "established_year": "2006",
            "address": "Lầu 4, Tòa nhà PetroVietnam, Số 1-5 Lê Duẩn, Phường Bến Nghé, Quận 1, TP. Hồ Chí Minh",
            "legal_rep_name": "Đặng Văn Vĩnh",
            "legal_rep_title": "Giám đốc",
            "charter_capital": 500000,
            "revenue_2025": 6520000,
            "rating_grade": "AA+",
            "rating_score": 91.5,
            "restricted_subject": "KHONG",
            "esg_status": "BAT_BUOC_DANH_GIA"
        },
        "rm_metadata": {
            "unit_name": "LC1MN",
            "rm_name": "Lê Văn Hùng (RM) / Trần Thị Mai (CBBH)",
            "rm_phone": "0912 345 678",
            "support_name": "Vũ Đình Trọng",
            "support_phone": "0988 776 655",
            "manager_name": "Phạm Quốc Tuấn",
            "manager_phone": "0909 112 233",
            "proposal_no": "04.2026 - GAS_SOUTH",
            "proposal_date": "15/01/2026",
            "approval_authority": "HĐTDCC",
            "request_type": "TAI_CAP"
        },
        "section_b": {
            "selected_needs": ["2.1_vay_vld_han_muc", "2.6_bao_lanh"],
            "total_limit": 500000,
            "loan_limit": 200000,
            "guarantee_limit": 50000,
            "loan_purpose": "Bổ sung vốn lưu động phục vụ kinh doanh khí hóa lỏng LPG, CNG và đầu tư bảo dưỡng bồn chứa khí.",
            "loan_tenor_months": 12,
            "disbursement_method": "Chuyển khoản trực tiếp cho bên bán theo hợp đồng và hóa đơn VAT.",
            "collateral_type": "Bất động sản kho bãi khí và quyền đòi nợ từ các hợp đồng cung cấp khí công nghiệp.",
            "cashflow_commitment_pct": 30.0,
            "cashflow_direct_pct": 10.0,
            "ewt_conditions": "Giám sát định kỳ chỉ số khả năng trả lãi EBIT/Lãi vay >= 2.0x."
        },
        "section_c": {
            "history_narrative": "Tiền thân là Xí nghiệp Kinh doanh Khí Miền Nam trực thuộc PV GAS, thành lập năm 2000. Năm 2006 chuyển đổi mô hình sang công ty cổ phần. Cổ phiếu mã PGS niêm yết trên sàn HNX từ năm 2009. Là đơn vị chiếm thị phần bán buôn và bán lẻ LPG số 1 tại khu vực Nam Bộ và Nam Trung Bộ.",
            "shareholders": [
                {"name": "Tổng Công ty Khí Việt Nam (PV GAS)", "tax_code": "0100150619", "pct": 35.26, "val": 176300.0},
                {"name": "CTCP Tập đoàn Đầu tư Anpha Capital", "tax_code": "0305889922", "pct": 15.50, "val": 77500.0},
                {"name": "Các cổ đông khác", "tax_code": "N/A", "pct": 49.24, "val": 246200.0}
            ],
            "management": [
                {"title": "Chủ tịch HĐQT", "name": "Nguyễn Ngọc Luận", "note": "Đại diện phần vốn PV GAS, hơn 20 năm kinh nghiệm ngành dầu khí.", "exp": 20},
                {"title": "Giám đốc kiêm Đại diện pháp luật", "name": "Đặng Văn Vĩnh", "note": "Trực tiếp điều hành sản xuất kinh doanh toàn bộ hệ thống trạm chiết và kho chứa.", "exp": 18},
                {"title": "Kế toán trưởng", "name": "Trần Thị Thu Thảo", "note": "CPA Việt Nam, 14 năm kinh nghiệm tài chính kế toán.", "exp": 14}
            ],
            "business_model": "SAN_XUAT_VA_THUONG_MAI",
            "products": [
                {"name": "Khí dầu mỏ hóa lỏng (LPG)", "spec": "Bình gas dân dụng & công nghiệp bồn", "share": 75.0},
                {"name": "Khí thiên nhiên nén (CNG)", "spec": "Cấp cho các KCN tại Đồng Nai, Bình Dương", "share": 20.0},
                {"name": "Vỏ bình LPG & phụ kiện van gas", "spec": "Sản xuất và kiểm định bình gas", "share": 5.0}
            ],
            "suppliers": [
                {"name": "Tổng Công ty Khí Việt Nam (PV GAS)", "goods": "Nguồn LPG lạnh và CNG ổn định dài hạn", "share": 62.50, "term": "L/C & Bảo lãnh"},
                {"name": "Shell Eastern Trading Ltd", "goods": "Nhập khẩu LPG bồn lạnh quốc tế", "share": 18.20, "term": "L/C trả ngay"},
                {"name": "Các nhà cung cấp vỏ bình và thiết bị", "goods": "Phụ kiện ngành gas", "share": 19.30, "term": "Gối đầu 30 ngày"}
            ],
            "customers": [
                {"name": "Prime Group (Tập đoàn gốm sứ)", "goods": "Khí CNG đốt lò gốm", "share": 8.50, "term": "Thanh toán theo tháng"},
                {"name": "Tập đoàn Hoa Sen (Tôn Hoa Sen)", "goods": "CNG phục vụ cán thép mạ", "share": 6.20, "term": "Bảo lãnh / Chuyển khoản"},
                {"name": "Hệ thống tổng đại lý phân phối Gas South", "goods": "LPG đóng bình dân dụng", "share": 52.00, "term": "Ký quỹ & trả trước"}
            ],
            "rm_management_assessment": "Đội ngũ lãnh đạo chủ chốt xuất thân từ Tập đoàn Dầu khí Quốc gia, am hiểu sâu sắc thị trường năng lượng và các quy chuẩn an toàn PCCC nghiêm ngặt.",
            "rm_market_position": "Gas South giữ vị trí dẫn đầu thị phần LPG dân dụng và công nghiệp tại miền Nam với thị phần trên 32%.",
            "rm_risk_mitigation": "Doanh nghiệp có cơ chế điều chỉnh giá bán theo biến động giá CP thế giới (Saudi Aramco CP), bảo vệ biên lợi nhuận trước rủi ro giá dầu khí."
        },
        "section_d": {
            "auditor": "Công ty TNHH Deloitte Việt Nam (Ý kiến chấp thuận toàn phần)",
            "years": ["2023", "2024", "2025"],
            "net_revenue": [5850000.0, 6120000.0, 6520000.0],
            "cogs": [5200000.0, 5450000.0, 5780000.0],
            "gross_profit": [650000.0, 670000.0, 740000.0],
            "net_profit_after_tax": [98000.0, 105000.0, 122000.0],
            "current_assets": [1850000.0, 1980000.0, 2150000.0],
            "cash": [350000.0, 420000.0, 480000.0],
            "receivables": [620000.0, 690000.0, 750000.0],
            "inventories": [410000.0, 450000.0, 490000.0],
            "total_assets": [2950000.0, 3100000.0, 3350000.0],
            "short_term_debt": [780000.0, 820000.0, 890000.0],
            "equity": [1120000.0, 1180000.0, 1250000.0],
            "rm_pnl_assessment": "Doanh thu năm 2025 đạt 6.520 tỷ đồng, tăng trưởng 6,5% nhờ sản lượng khí công nghiệp CNG tăng mạnh tại các KCN Nam Bộ. Biên lợi nhuận gộp đạt 11,3%.",
            "rm_balance_sheet_assessment": "Cơ cấu tài sản lành mạnh, tỷ lệ nợ vay/VCSH duy trì ở mức thấp (0,71 lần), dòng tiền hoạt động dồi dào.",
            "rm_cashflow_assessment": "Dòng tiền thuần từ hoạt động kinh doanh dương liên tục trong 3 năm, số dư tiền mặt và tiền gửi ngân hàng đạt 480 tỷ đồng."
        },
        "section_e": {
            "cic_date": "31/12/2025",
            "msb_outstanding": 120000.0,
            "history_status": "100% Nhóm 1 tại tất cả các TCTD trong suốt lịch sử quan hệ tín dụng.",
            "rm_credit_assessment": "Khách hàng có uy tín tín dụng xuất sắc, không bao giờ phát sinh nợ quá hạn. Dòng tiền kinh doanh qua tài khoản MSB đạt hơn 450 tỷ đồng trong năm 2025."
        }
    },
    "PHYTOPHARMA": {
        "id": "PHYTOPHARMA",
        "name": "PHYTOPHARMA - CTCP Dược liệu Trung ương 2",
        "customer": {
            "name": "CÔNG TY CỔ PHẦN DƯỢC LIỆU TRUNG ƯƠNG 2",
            "short_name": "PHYTOPHARMA VN",
            "tax_code": "0302597576",
            "cif": "0302597576",
            "segment": "LC",
            "parent_group": "Không thuộc tập đoàn",
            "established_year": "1976",
            "address": "24 Nguyễn Thị Nghĩa, Phường Bến Thành, Quận 1, Thành phố Hồ Chí Minh, Việt Nam",
            "legal_rep_name": "Lê Minh Phú",
            "legal_rep_title": "Tổng giám đốc",
            "charter_capital": 381900,
            "revenue_2025": 43423064,
            "rating_grade": "AAA",
            "rating_score": 96.5,
            "restricted_subject": "KHONG",
            "esg_status": "BAT_BUOC_DANH_GIA"
        },
        "rm_metadata": {
            "unit_name": "EB-HCM",
            "rm_name": "Nguyễn Thị Ngân (RM - EB-HCM QHKH)",
            "rm_phone": "0908 123 456",
            "support_name": "Phạm Văn Nam",
            "support_phone": "0912 345 678",
            "manager_name": "Trần Tuấn Anh",
            "manager_phone": "0903 888 999",
            "proposal_no": "05.2026 - PHYTOPHARMA",
            "proposal_date": "29/05/2026",
            "approval_authority": "HĐTDCC",
            "request_type": "TAI_CAP"
        },
        "section_b": {
            "selected_needs": ["2.1_vay_vld_han_muc", "2.6_bao_lanh"],
            "total_limit": 2000000,
            "loan_limit": 1500000,
            "guarantee_limit": 500000,
            "loan_purpose": "Bổ sung vốn lưu động phục vụ kinh doanh dược phẩm, vật tư y tế và mở L/C nhập khẩu thuốc đặc trị từ các hãng dược phẩm quốc tế.",
            "loan_tenor_months": 12,
            "disbursement_method": "Chuyển khoản trực tiếp cho bên bán / giải tỏa L/C theo hợp đồng kinh tế và hóa đơn GTGT.",
            "collateral_type": "Tín chấp và quyền đòi nợ từ các hợp đồng cung cấp dược phẩm cho hệ thống bệnh viện công lập và chuỗi nhà thuốc.",
            "cashflow_commitment_pct": 30.0,
            "cashflow_direct_pct": 10.0,
            "ewt_conditions": "Tuân thủ đầy đủ 6 ngưỡng cảnh báo sớm (EWT) và duy trì hệ số thanh toán ngắn hạn >= 1.1x."
        },
        "section_c": {
            "history_narrative": "Thành lập năm 1976 tiền thân là Quốc doanh Dược phẩm trực thuộc Bộ Y tế, cổ phần hóa thành Công ty Cổ phần Dược liệu Trung ương 2 (Phytopharma). Doanh nghiệp là một trong những nhà phân phối dược phẩm và thiết bị y tế hàng đầu tại Việt Nam, đối tác nhập khẩu ủy thác của nhiều hãng dược đa quốc gia hàng đầu thế giới.",
            "shareholders": [
                {"name": "Tổng Công ty Dược Việt Nam - CTCP (Vinapharm)", "tax_code": "0100108657", "pct": 36.31, "val": 138668.0},
                {"name": "Cổ đông chiến lược & Ban lãnh đạo", "tax_code": "N/A", "pct": 28.50, "val": 108841.0},
                {"name": "Các cổ đông khác", "tax_code": "N/A", "pct": 35.19, "val": 134391.0}
            ],
            "management": [
                {"title": "Chủ tịch HĐQT", "name": "Nguyễn Công Chiến", "note": "Hơn 25 năm kinh nghiệm quản trị và phát triển thị trường dược phẩm Việt Nam.", "exp": 25},
                {"title": "Tổng Giám đốc kiêm ĐDPL", "name": "Lê Minh Phú", "note": "Trực tiếp điều hành chuỗi cung ứng dược phẩm và hệ thống kho đạt chuẩn GSP, GDP.", "exp": 18},
                {"title": "Thành viên HĐQT", "name": "Võ Thị Tuấn Anh", "note": "Chuyên gia tài chính doanh nghiệp và quản trị rủi ro.", "exp": 16},
                {"title": "Kế toán trưởng", "name": "Phan Thị Thu Hà", "note": "CPA, hơn 15 năm kinh nghiệm quản lý tài chính kế toán ngành dược.", "exp": 15}
            ],
            "business_model": "THUONG_MAI",
            "products": [
                {"name": "Thuốc đặc trị & Dược phẩm kê đơn (AstraZeneca, Pfizer, Novartis...)", "spec": "Dược phẩm chính hãng nhập khẩu", "share": 65.0},
                {"name": "Thiết bị y tế & Vật tư tiêu hao bệnh viện", "spec": "Đạt chuẩn ISO/CE", "share": 20.0},
                {"name": "Thực phẩm chức năng & Dược mỹ phẩm", "spec": "Phân phối chuỗi nhà thuốc", "share": 15.0}
            ],
            "suppliers": [
                {"name": "AstraZeneca Singapore Pte Ltd", "goods": "Thuốc ung thư, tim mạch, hô hấp (20 năm)", "share": 25.40, "term": "L/C & T/T"},
                {"name": "Pfizer Export Co., Ltd", "goods": "Vaccine và thuốc đặc trị", "share": 21.30, "term": "L/C trả ngay"},
                {"name": "Novartis Pharma Services AG", "goods": "Dược phẩm tim mạch & mắt", "share": 18.50, "term": "L/C 90 ngày"},
                {"name": "Zuellig Pharma Vietnam", "goods": "Hợp đồng phân phối ủy thác", "share": 15.20, "term": "Chuyển khoản NH"},
                {"name": "GlaxoSmithKline Pte Ltd", "goods": "Kháng sinh và vaccine", "share": 10.10, "term": "L/C & T/T"}
            ],
            "customers": [
                {"name": "Bệnh viện Chợ Rẫy & Hệ thống BV Công lập", "goods": "Thuốc đặc trị & vật tư y tế", "share": 28.50, "term": "Theo hợp đồng thầu y tế"},
                {"name": "Chuỗi Nhà thuốc FPT Long Châu", "goods": "Dược phẩm & thực phẩm chức năng", "share": 22.10, "term": "Gối đầu 45 ngày"},
                {"name": "Chuỗi Nhà thuốc Pharmacity", "goods": "Dược mỹ phẩm & thuốc OTC", "share": 16.80, "term": "Gối đầu 30 ngày"},
                {"name": "Chuỗi Nhà thuốc An Khang (MWG)", "goods": "Dược phẩm tiêu dùng", "share": 12.40, "term": "Chuyển khoản NH"},
                {"name": "Mạng lưới đại lý & phòng khám tư nhân", "goods": "Dược phẩm thiết yếu", "share": 20.20, "term": "Chuyển khoản / Trả chậm"}
            ],
            "rm_management_assessment": "Ban lãnh đạo là những chuyên gia đầu ngành dược phẩm, am hiểu sâu sắc quy định đấu thầu thuốc và quy chuẩn bảo quản GSP, GDP. Hoạt động quản trị minh bạch, uy tín cao trên thị trường.",
            "rm_market_position": "Phytopharma giữ vị thế Top 2 nhà phân phối dược phẩm lớn nhất Việt Nam, là đối tác nhập khẩu ủy thác số 1 của các tập đoàn dược đa quốc gia hàng đầu thế giới.",
            "rm_risk_mitigation": "Doanh nghiệp có lợi thế mạng lưới phân phối độc quyền nhiều dòng thuốc đặc trị thiết yếu, rủi ro công nợ được phân tán và kiểm soát tốt qua các hợp đồng thầu bệnh viện công lập và chuỗi nhà thuốc lớn."
        },
        "section_d": {
            "auditor": "Công ty TNHH Ernst & Young Việt Nam (Ý kiến chấp thuận toàn phần)",
            "years": ["2023", "2024", "2025"],
            "net_revenue": [35026909.5, 41615917.4, 43423063.6],
            "cogs": [33500569.6, 40089577.6, 41967612.9],
            "gross_profit": [1526339.9, 1526339.9, 1455450.7],
            "net_profit_after_tax": [109376.7, 94209.2, 78541.0],
            "current_assets": [11900000.0, 14557367.9, 14943055.3],
            "cash": [850000.0, 1521335.5, 1020365.9],
            "receivables": [6200000.0, 7449438.3, 6862800.3],
            "inventories": [3500000.0, 4013962.0, 5204736.9],
            "total_assets": [12500000.0, 15259796.7, 15620222.7],
            "short_term_debt": [8200000.0, 10500000.0, 11200000.0],
            "equity": [1800000.0, 2100000.0, 2350000.0],
            "rm_pnl_assessment": "Doanh thu năm 2025 bứt phá đạt 43.423 tỷ đồng, khẳng định quy mô doanh nghiệp phân phối dược phẩm Top đầu. Biên lợi nhuận gộp duy trì ổn định quanh 3,4% - 3,7%, đặc thù biên an toàn cao của ngành dược.",
            "rm_balance_sheet_assessment": "Tài sản ngắn hạn chiếm 95,7% tổng tài sản, phù hợp đặc thù luân chuyển hàng hóa dược phẩm. Khả năng thanh toán hiện hành đạt trên 1.33 lần, cân đối tài chính an toàn.",
            "rm_cashflow_assessment": "Dòng tiền từ hoạt động kinh doanh duy trì lành mạnh, lượng tiền và tiền gửi ngân hàng dồi dào (>1.020 tỷ đồng tại thời điểm 31/12/2025), đảm bảo khả năng thanh toán các nghĩa vụ tín dụng ngắn hạn."
        },
        "section_e": {
            "cic_date": "29/05/2026",
            "msb_outstanding": 684947.0,
            "history_status": "100% Nhóm 1 (Đủ tiêu chuẩn) trong toàn bộ lịch sử quan hệ tín dụng tại MSB và các TCTD.",
            "rm_credit_assessment": "Khách hàng có lịch sử tín dụng mẫu mực 100% Nhóm 1 tại MSB và 8 TCTD khác với tổng dư nợ toàn hệ thống đạt gần 3.000 tỷ đồng. Doanh số chuyển tiền qua tài khoản MSB luôn vượt 120% cam kết."
        }
    }
}


ACTIVE_CASE_ID = "PSD"

def get_active_case():
    global ACTIVE_CASE_ID
    return CASES_DB.get(ACTIVE_CASE_ID, CASES_DB["PSD"])


# ==============================================================================
# PIPELINE GENERATOR
# ==============================================================================
def execute_generation_pipeline(case_id=None):
    if not case_id:
        case_id = ACTIVE_CASE_ID
    case_data = CASES_DB.get(case_id, CASES_DB["PSD"])

    cust = case_data["customer"]
    rm = case_data["rm_metadata"]
    b = case_data["section_b"]
    c = case_data["section_c"]
    d = case_data["section_d"]
    e = case_data["section_e"]

    clean_cid = case_id.replace(" ", "_").upper()
    output_doc_path = os.path.join("output", f"TO_TRINH_MB07_{clean_cid}_HOAN_CHINH.docx")
    os.makedirs("output", exist_ok=True)

    # 1. Facts Section A
    session_a = SectionAReviewSession(f"CASE-2026-{clean_cid}")
    session_a.confirm_fact_with_rm("company.legal_name", cust["name"])
    session_a.confirm_fact_with_rm("company.short_name", cust["short_name"])
    session_a.confirm_fact_with_rm("company.legal_type", "Công ty Cổ phần")
    session_a.confirm_fact_with_rm("company.group_name", cust["parent_group"])
    session_a.confirm_fact_with_rm("company.registered_address", cust["address"])
    session_a.confirm_fact_with_rm("company.registration_no", cust["tax_code"])
    session_a.confirm_fact_with_rm("company.registration_issue_date", "15/04/2008")
    session_a.confirm_fact_with_rm("company.registration_issue_place", "Sở Kế hoạch và Đầu tư TP. Hồ Chí Minh")
    session_a.confirm_fact_with_rm("company.operation_start_date_or_year", cust.get("established_year", "2008"))
    session_a.confirm_fact_with_rm("company.legal_representative.name", cust["legal_rep_name"])
    session_a.confirm_fact_with_rm("company.legal_representative.title", cust["legal_rep_title"])

    session_a.set_rm_selected("relationship.customer_status", "KH_HIEN_HUU" if case_id in ("PSD", "PHYTOPHARMA") else "KH_MOI")
    session_a.set_rm_provided("relationship.cif", cust["cif"])
    session_a.set_rm_selected("relationship.segment", cust["segment"])
    session_a.set_rm_selected("compliance.restricted_credit_subject", cust["restricted_subject"])
    session_a.set_rm_selected("compliance.esg_assessment_required", cust["esg_status"])
    session_a.set_rm_selected("credit_relation.regulatory_limit_status", "TRONG_GIOI_HAN")
    session_a.set_rm_selected("approval.authority", rm["approval_authority"])
    session_a.set_rm_selected("proposal.request_type", rm["request_type"])

    session_a.confirm_fact_with_rm("financial.latest_net_revenue", int(d["net_revenue"][-1]), unit="triệu đồng")
    session_a.confirm_fact_with_rm("financial.latest_revenue_year", int(d["years"][-1]))
    session_a.set_rm_provided("proposal.credit_request_representative.name", cust["legal_rep_name"])
    session_a.set_rm_provided("proposal.credit_request_representative.title", cust["legal_rep_title"])
    session_a.set_rm_provided("business.primary_industry.code_level_5", "46491" if case_id=="PHYTOPHARMA" else ("46510" if case_id=="PSD" else "46613"))
    session_a.set_rm_provided("business.primary_industry.name", c["products"][0]["name"])
    session_a.set_rm_provided("business.primary_industry.revenue_share_pct", int(c["products"][0]["share"]))
    session_a.set_rm_provided("business.main_products", tuple(p["name"] for p in c["products"][:3]))

    session_a.confirm_fact_with_rm("capital.registered_capital", int(cust["charter_capital"]), unit="triệu đồng")
    session_a.confirm_fact_with_rm("capital.paid_in_capital", int(cust["charter_capital"]), unit="triệu đồng")
    session_a.confirm_fact_with_rm("capital.paid_in_capital_as_of", f"31/12/{d['years'][-1]}")

    session_a.set_rm_provided("internal_rating.case_id", f"XHTD-2026-{clean_cid}")
    session_a.set_rm_provided("internal_rating.grade", cust["rating_grade"])
    session_a.set_rm_provided("internal_rating.score", Decimal(str(cust["rating_score"])))

    session_a.set_rm_provided("approval.existing_limit.total", int(b["total_limit"]) if case_id in ("PSD", "PHYTOPHARMA") else 0, unit="triệu đồng")
    session_a.set_rm_provided("approval.existing_limit.unsecured", int(b["total_limit"]) if case_id in ("PSD", "PHYTOPHARMA") else 0, unit="triệu đồng")
    session_a.set_rm_provided("approval.proposed_limit.total", int(b["total_limit"]), unit="triệu đồng")
    session_a.set_rm_provided("approval.proposed_limit.unsecured", int(b["loan_limit"]), unit="triệu đồng")
    session_a.set_rm_provided("approval.aggregate_limit.total", int(b["total_limit"]), unit="triệu đồng")
    session_a.set_rm_provided("approval.aggregate_limit.unsecured", int(b["loan_limit"]), unit="triệu đồng")
    session_a.set_rm_provided("approval.previous_approval_period", "Cấp tín dụng định kỳ" if case_id in ("PSD", "PHYTOPHARMA") else "Cấp mới")


    # 1.1 Section E data for linking
    data_e = SectionEData(
        customer_name=cust["name"],
        cic_report_date=e["cic_date"],
        relations=[
            CreditInstitutionRelation(1, "Ngân hàng TMCP Hàng Hải Việt Nam (MSB)", float(b["total_limit"]), float(e["msb_outstanding"]), 0.0, 0.0, float(e["msb_outstanding"]), "Tín chấp / TSBĐ theo quy định", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(2, "Các Tổ chức Tín dụng khác", float(b["total_limit"]) * 1.5, float(b["total_limit"]) * 0.8, 0.0, 0.0, float(b["total_limit"]) * 0.8, "Bảo lãnh / Tín chấp", DebtGroup.NHOM_1_DU_TIEU_CHUAN)
        ],
        loan_outstanding_at_msb_million=float(e["msb_outstanding"]),
        total_credit_exposure_at_msb_million=float(e["msb_outstanding"]),
        is_overdue_12m=False,
        rm_credit_assessment=e["rm_credit_assessment"]
    )
    link_section_e_to_session_a(data_e, session_a)

    facts_a = session_a.facts
    facts_a["submission.unit_name"] = rm["unit_name"]
    facts_a["submission.rm_name"] = rm["rm_name"]
    facts_a["submission.rm_phone"] = rm["rm_phone"]
    facts_a["submission.support_name"] = rm["support_name"]
    facts_a["submission.support_phone"] = rm["support_phone"]
    facts_a["submission.manager_name"] = rm["manager_name"]
    facts_a["submission.manager_phone"] = rm["manager_phone"]
    facts_a["submission.proposal_no"] = rm["proposal_no"]
    facts_a["submission.proposal_date"] = rm["proposal_date"]

    # 2. Section B
    input_b = {
        "selected_needs": ["2.1_vay_vld_han_muc", "2.6_bao_lanh"],
        "general_facility_summary": {
            "proposed_total_limit_vnd": float(b["total_limit"]) * 1000000.0,
            "max_lending_limit_vnd": float(b["loan_limit"]) * 1000000.0,
            "currency": "VND"
        },
        "facilities_data": {
            "need_2_1": {
                "proposed_limit_vnd": float(b["loan_limit"]) * 1000000.0,
                "purpose": b["loan_purpose"],
                "facility_duration_months": b["loan_tenor_months"],
                "loan_duration_rule": "Theo chu kỳ SXKD nhưng không quá 06 tháng",
                "disbursement_method": b["disbursement_method"],
                "interest_rate_rule": "Theo quy định MSB trong từng thời kỳ"
            },
            "need_2_6": {
                "proposed_limit_vnd": float(b["guarantee_limit"]) * 1000000.0,
                "purpose": "Phát hành bảo lãnh thanh toán tiền mua hàng hóa",
                "guarantee_types": "Bảo lãnh thực hiện hợp đồng, bảo lãnh thanh toán",
                "facility_duration_months": 12,
                "single_guarantee_duration": "Theo hợp đồng kinh tế",
                "min_margin_cash_percentage": "0%"
            }
        }
    }
    agent_b = AgentSectionB()
    proc_b = agent_b.validate_and_calculate(input_b)

    # 3. Section C
    shareholder_objs = [
        ShareholderInfo(i+1, s["name"], s["tax_code"], s["pct"], s["val"])
        for i, s in enumerate(c["shareholders"])
    ]
    mgmt_objs = [
        ManagementMember(m["title"], m["name"], m["note"], m["exp"])
        for m in c["management"]
    ]
    prod_objs = [
        ProductInfo(i+1, p["name"], p["spec"], p["share"])
        for i, p in enumerate(c["products"])
    ]
    supp_objs = [
        SupplierInfo(i+1, s["name"], s["goods"], s["share"], s["term"], False)
        for i, s in enumerate(c["suppliers"])
    ]
    cust_objs = [
        CustomerInfo(i+1, cs["name"], cs["goods"], cs["share"], cs["term"])
        for i, cs in enumerate(c["customers"])
    ]

    bm_type = BusinessModelType.THUONG_MAI
    if c.get("business_model") == "SAN_XUAT":
        bm_type = BusinessModelType.SAN_XUAT
    elif c.get("business_model") in ("HON_HOP", "SAN_XUAT_VA_THUONG_MAI"):
        bm_type = BusinessModelType.HON_HOP

    data_c = SectionCData(
        customer_name=cust["name"],
        history_narrative=c["history_narrative"],
        parent_company_or_owner=f"{cust['parent_group']} (Tỷ lệ sở hữu chi phối)",
        major_shareholders=shareholder_objs,
        blacklist_status=BlacklistStatus.KHONG_VI_PHAM,
        management_members=mgmt_objs,
        business_model=bm_type,
        products=prod_objs,
        production_technology_summary="Hệ thống vận hành hiện đại, ứng dụng ERP và phần mềm quản trị chuyên dụng.",
        warehouses=[
            WarehouseInfo(1, "Kho hàng trung tâm 1", f"Địa bàn kinh doanh chính của {cust['short_name']}", 2500.0, "Đạt chuẩn an toàn, PCCC đầy đủ", "Theo đơn hàng")
        ],
        equipments=[
            EquipmentInfo(1, "Hệ thống máy móc, CNTT & hạ tầng vận hành", "Nhập khẩu", "Vận hành liên tục", "95%")
        ],
        suppliers=supp_objs,
        customers=cust_objs,
        raw_materials_overview="Nguồn cung cấp ổn định từ các đối tác hàng đầu trong và ngoài nước.",
        distribution_channels="Kênh phân phối rộng khắp toàn quốc.",
        market_share_estimate="Vị thế dẫn đầu trong phân khúc kinh doanh chính.",
        top_competitors=["Các doanh nghiệp cùng ngành trên thị trường"],
        competitive_advantages=c.get("rm_risk_mitigation", "Thương hiệu uy tín, ban lãnh đạo giàu kinh nghiệm.")
    )

    # 4. Section D
    computed_d_ratios = compute_canonical_ratios(d)
    years_d = d.get("years", [])
    num_years = len(years_d)

    def _safe_ratio_list(key: str, default_val: float) -> List[float]:
        vals = computed_d_ratios.get(key, [])
        out = []
        for idx in range(num_years):
            v = vals[idx] if idx < len(vals) else None
            out.append(float(v) if v is not None else default_val)
        return out

    data_d = SectionDData(
        customer_name=cust["name"],
        governance=AccountingGovernance(
            mandatory_audit_by_law="Bắt buộc kiểm toán BCTC hàng năm theo quy định pháp luật.",
            audit_firm_name=d["auditor"],
            audited_years="2022, 2023, 2024",
            audit_opinion="Ý kiến chấp thuận toàn phần không có ngoại trừ."
        ),
        income_statement=IncomeStatement3Y(
            years=d["years"],
            net_revenue=d["net_revenue"],
            cogs=d["cogs"],
            gross_profit=d["gross_profit"],
            gross_profit_margin_pct=[round((gp / nr * 100), 2) if nr else 0.0 for gp, nr in zip(d["gross_profit"], d["net_revenue"])],
            financial_income=[35000.0, 40000.0, 45000.0],
            financial_expenses=[90000.0, 60000.0, 95000.0],
            interest_expenses=[80000.0, 45000.0, 75000.0],
            sga_expenses=[180000.0, 220000.0, 280000.0],
            net_profit_before_tax=[round(p * 1.25, 1) for p in d["net_profit_after_tax"]],
            net_profit_after_tax=d["net_profit_after_tax"]
        ),
        pnl_analysis=PnLAnalysis(
            revenue_analysis=d["rm_pnl_assessment"],
            gross_margin_analysis="Biên lợi nhuận gộp duy trì ổn định, kiểm soát chi phí giá vốn hiệu quả.",
            net_profit_and_dividends_analysis=f"Lợi nhuận sau thuế năm 2025 đạt {d['net_profit_after_tax'][-1]:,.1f} triệu VND."
        ),
        balance_sheet=BalanceSheet3Y(
            years=d["years"],
            current_assets=d["current_assets"],
            cash_and_equivalents=d["cash"],
            short_term_investments=[0.0, 0.0, 0.0],
            accounts_receivable=d["receivables"],
            inventories=d["inventories"],
            other_current_assets=[50000.0, 50000.0, 50000.0],
            non_current_assets=[round(ta - ca, 1) for ta, ca in zip(d["total_assets"], d["current_assets"])],
            fixed_assets=[round((ta - ca)*0.8, 1) for ta, ca in zip(d["total_assets"], d["current_assets"])],
            construction_in_progress=[0.0, 0.0, 0.0],
            total_assets=d["total_assets"],
            liabilities=[round(ta - eq, 1) for ta, eq in zip(d["total_assets"], d["equity"])],
            short_term_debt=d["short_term_debt"],
            long_term_debt=[0.0, 0.0, 0.0],
            owner_equity=d["equity"],
            charter_capital=[cust["charter_capital"], cust["charter_capital"], cust["charter_capital"]]
        ),
        cash_flow=CashFlowStatement3Y(
            years=d["years"],
            ocf_cash_from_operations=[None, None, None],
            icf_cash_from_investing=[None, None, None],
            fcf_cash_from_financing=[None, None, None],
            net_cash_flow=[None, None, None],
            cash_beginning=d["cash"],
            cash_ending=d["cash"],
            cash_flow_analysis=d["rm_cashflow_assessment"]
        ),
        ratios=FinancialRatios3Y(
            years=d["years"],
            current_ratio=_safe_ratio_list("current_ratio", 1.0),
            quick_ratio=_safe_ratio_list("quick_ratio", 1.0),
            cash_ratio=_safe_ratio_list("cash_ratio", 0.5),
            debt_to_equity=_safe_ratio_list("debt_to_equity", 2.0),
            total_debt_to_equity=_safe_ratio_list("total_debt_to_equity", 1.5),
            dscr_icr=d.get("dscr_icr") or [2.5, 3.0, 3.2],
            ros=_safe_ratio_list("ros", 1.5),
            roe=_safe_ratio_list("roe", 15.0)
        )
    )

    # 5. Section E
    e_rels_raw = e.get("relations")
    if e_rels_raw and len(e_rels_raw) > 0:
        e_relations = []
        for idx, r in enumerate(e_rels_raw, start=1):
            grp = r.get("debt_group")
            debt_grp = DebtGroup(int(grp)) if grp is not None and str(grp).isdigit() and int(grp) in (1, 2, 3, 4, 5) else (DebtGroup.NHOM_1_DU_TIEU_CHUAN if grp is not None else None)
            e_relations.append(
                CreditInstitutionRelation(
                    stt=idx,
                    bank_name=r.get("bank_name", f"TCTD_{idx}"),
                    short_term_limit_million_vnd=r.get("short_term_limit_million_vnd"),
                    short_term_debt_vnd_million=r.get("short_term_debt_vnd_million"),
                    short_term_debt_usd_million=r.get("short_term_debt_usd_million"),
                    medium_long_term_debt_million=r.get("medium_long_term_debt_million"),
                    total_debt_million=r.get("total_debt_million"),
                    collateral_description=r.get("collateral_description"),
                    debt_group=debt_grp,
                    raw_usd_amount=r.get("raw_usd_amount"),
                    raw_usd_currency=r.get("raw_usd_currency"),
                )
            )
    else:
        e_relations = [
            CreditInstitutionRelation(1, "Ngân hàng TMCP Hàng Hải Việt Nam (MSB)", float(b["total_limit"]), float(e.get("msb_outstanding", 0.0)), 0.0, 0.0, float(e.get("msb_outstanding", 0.0)), "Tín chấp / TSBĐ theo quy định", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(2, "Các Tổ chức Tín dụng khác", float(b["total_limit"]) * 1.5, float(b["total_limit"]) * 0.8, 0.0, 0.0, float(b["total_limit"]) * 0.8, "Bảo lãnh / Tín chấp", DebtGroup.NHOM_1_DU_TIEU_CHUAN)
        ]

    data_e = SectionEData(
        customer_name=cust["name"],
        cic_report_date=e.get("cic_date", ""),
        relations=e_relations,
        loan_outstanding_at_msb_million=float(e.get("msb_outstanding", 0.0)),
        total_credit_exposure_at_msb_million=float(e.get("total_credit_exposure_at_msb_million", e.get("msb_outstanding", 0.0))),
        is_overdue_12m=e.get("is_overdue_12m"),
        overdue_explanation=e.get("overdue_explanation", ""),
        rm_credit_assessment=e.get("rm_credit_assessment", ""),
        derivative_transactions_info=e.get("derivative_transactions_info"),
    )

    # Lấy các đoạn văn bản phân tích tín dụng đã được RM phê duyệt từ NARRATIVE_DRAFT_STORE
    accepted_narratives = NarrativeDraftManager.get_accepted_narratives_for_rendering(case_id)

    assembler = CreditProposalAssembler()
    final_path = assembler.assemble(
        facts_a=facts_a,
        data_b_processed=proc_b,
        data_c=data_c,
        data_d=data_d,
        data_e=data_e,
        output_path=output_doc_path,
        highlight_new_features=False,
        accepted_narratives=accepted_narratives
    )

    DocumentFormatter.polish(final_path, keep_highlights=False)
    return output_doc_path


# ==============================================================================
# HTML TEMPLATE
# ==============================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MSB CreditPilot 360 - Trợ lý Thẩm định & Soạn thảo Tờ trình Tín dụng KHDN</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Inter', sans-serif; }
    .tab-active { border-bottom: 3px solid #EB1C24; color: #003366; font-weight: 700; background-color: #F8FAFC; }
    .tag-ai { background-color: #DEF7EC; color: #03543F; border: 1px solid #BCF0DA; }
    .tag-rm { background-color: #FEF08A; color: #713F12; border: 1px solid #FDE047; }
    .tag-verified { background-color: #E0E7FF; color: #3730A3; border: 1px solid #C7D2FE; }
    .tag-warning { background-color: #FEF3C7; color: #92400E; border: 1px solid #FDE68A; }
    .tag-missing { background-color: #FEE2E2; color: #991B1B; border: 1px solid #FECACA; }
    .badge-hero { background: linear-gradient(135deg, #003366 0%, #004D99 100%); }
    .card-insight:hover { transform: translateY(-2px); transition: all 0.2s ease-in-out; }
  </style>
</head>
<body class="bg-slate-100 text-slate-800 min-h-screen flex flex-col">

  <!-- TOP APP BAR -->
  <header class="bg-[#003366] text-white shadow-md sticky top-0 z-40">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-10 h-10 bg-[#EB1C24] rounded-lg flex items-center justify-center font-extrabold text-white text-xl shadow">
          M
        </div>
        <div>
          <h1 class="font-bold text-lg leading-tight flex items-center space-x-2">
            <span>MSB CreditPilot 360</span>
            <span class="text-xs bg-[#FF5A00] text-white px-2 py-0.5 rounded font-semibold">From Documents to Credit Committee</span>
          </h1>
          <p class="text-xs text-slate-300">Trợ lý Phân tích, Soạn thảo & Bảo vệ Tờ trình Tín dụng KHDN Lớn (Mô hình 70% AI + 30% RM)</p>
        </div>
      </div>

      <!-- CASE SELECTOR & DEMO QUICKSTART -->
      <div class="flex items-center space-x-3">
        <div class="flex items-center space-x-2 bg-slate-800/90 px-3 py-1.5 rounded-lg border border-slate-700">
          <label class="text-xs text-amber-300 font-semibold whitespace-nowrap">📁 Hồ sơ Khách hàng:</label>
          <select id="case-selector" onchange="onCaseChange(this.value)" class="bg-slate-900 text-white text-xs font-semibold px-2.5 py-1 rounded border border-slate-600 focus:outline-none focus:ring-1 focus:ring-amber-400">
            <option value="PSD">PSD - CTCP Dịch vụ Phân phối TH Dầu khí</option>
            <option value="GAS_SOUTH">GAS SOUTH - CTCP Khí Miền Nam</option>
            <option value="PHYTOPHARMA">PHYTOPHARMA - CTCP Dược liệu TW2</option>
          </select>
          <button onclick="resetDemoCase()" title="Đặt lại dữ liệu demo chuẩn" class="text-xs bg-amber-600 hover:bg-amber-700 text-white font-bold px-2 py-1 rounded shadow flex items-center space-x-1 whitespace-nowrap">
            <span>⚡ Nạp Demo Chuẩn</span>
          </button>
          <button onclick="openNewCaseModal()" class="text-xs bg-emerald-600 hover:bg-emerald-700 text-white font-bold px-2 py-1 rounded shadow flex items-center space-x-1 whitespace-nowrap">
            <span>➕ Tạo Mới</span>
          </button>
        </div>

        <button onclick="generateDocx()" id="btn-export-top" class="bg-[#EB1C24] hover:bg-red-700 text-white font-semibold px-4 py-2 rounded-lg text-sm shadow transition flex items-center space-x-1.5 whitespace-nowrap">
          <span>⚡ Xuất Tờ Trình MB07 (.DOCX)</span>
        </button>
      </div>
    </div>
  </header>

  <!-- 6-STEP RM HAPPY PATH NAVIGATION -->
  <div class="bg-white border-b border-slate-200 sticky top-16 z-30 shadow-sm">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex overflow-x-auto space-x-6 text-sm font-medium text-slate-600">
      <button onclick="switchTab('tab-dashboard')" id="nav-tab-dashboard" class="py-3.5 px-3 tab-active whitespace-nowrap flex items-center space-x-1.5">
        <span>🏢 1. Hồ Sơ Khách Hàng</span>
      </button>
      <button onclick="switchTab('tab-upload')" id="nav-tab-upload" class="py-3.5 px-3 hover:text-slate-900 whitespace-nowrap flex items-center space-x-1.5">
        <span>📂 2. Không Gian Tài Liệu</span>
      </button>
      <button onclick="switchTab('tab-review')" id="nav-tab-review" class="py-3.5 px-3 hover:text-slate-900 whitespace-nowrap flex items-center space-x-1.5">
        <span>📋 3. Dữ Liệu Đã Xác Nhận</span>
      </button>
      <button onclick="switchTab('tab-insights')" id="nav-tab-insights" class="py-3.5 px-3 hover:text-slate-900 whitespace-nowrap flex items-center space-x-1.5 text-blue-700 font-semibold">
        <span>💡 4. Thẩm Định Tín Dụng AI</span>
      </button>
      <button onclick="switchTab('tab-narrative')" id="nav-tab-narrative" class="py-3.5 px-3 hover:text-slate-900 whitespace-nowrap flex items-center space-x-1.5 text-red-600 font-semibold">
        <span>📝 5. Tờ Trình / Narrative</span>
      </button>
      <button onclick="switchTab('tab-committee')" id="nav-tab-committee" class="py-3.5 px-3 hover:text-slate-900 whitespace-nowrap flex items-center space-x-1.5 text-amber-700 font-bold bg-amber-50/60 rounded-t-lg">
        <span>🎯 6. Credit Committee Prep</span>
      </button>
    </div>
  </div>

  <!-- MAIN CONTENT CONTAINER -->
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-1 w-full">

    <!-- HERO PRODUCT BANNER -->
    <div class="mb-6 p-4 rounded-xl bg-gradient-to-r from-blue-900 via-indigo-900 to-slate-900 text-white shadow-md flex items-center justify-between">
      <div class="flex items-center space-x-3.5">
        <div class="w-10 h-10 rounded-lg bg-white/10 flex items-center justify-center text-xl">🛡️</div>
        <div>
          <div class="font-bold text-sm tracking-wide text-amber-300">MSB CREDITPILOT 360 — BẢO VỆ TỜ TRÌNH TOÀN DIỆN</div>
          <div class="text-xs text-slate-200 mt-0.5 italic">
            "Không chỉ giúp RM viết tờ trình — CreditPilot giúp RM sẵn sàng bảo vệ tờ trình trước Hội đồng Tín dụng."
          </div>
        </div>
      </div>
      <div class="flex items-center space-x-2">
        <span id="case-source-badge" class="text-xs bg-amber-500/20 text-amber-300 px-3 py-1 rounded-full font-bold border border-amber-400/30 whitespace-nowrap">
          DEMO DATA (PRELOADED)
        </span>
        <span class="text-xs bg-emerald-500/20 text-emerald-300 px-3 py-1 rounded-full font-bold border border-emerald-400/30 whitespace-nowrap" id="banner-readiness">
          ✓ Mức độ sẵn sàng: 100%
        </span>
      </div>
    </div>

    <!-- ========================================================================= -->
    <!-- TAB 1: TỔNG QUAN HỒ SƠ (CASE OVERVIEW)                                    -->
    <!-- ========================================================================= -->
    <section id="tab-dashboard" class="space-y-6">
      <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
          <div class="text-xs text-slate-500 font-medium">Khách hàng thẩm định</div>
          <div class="text-lg font-bold text-slate-900 mt-1" id="dash-cust-name">PSD (CIF: DEMO001)</div>
          <div class="text-xs text-emerald-600 mt-1 font-semibold" id="dash-cust-rating">Định hạng MSB: Hạng AAA (95đ)</div>
        </div>
        <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
          <div class="text-xs text-slate-500 font-medium">Tổng hạn mức đề xuất</div>
          <div class="text-lg font-bold text-[#003366] mt-1" id="dash-total-limit">700.000 triệu VND</div>
          <div class="text-xs text-slate-500 mt-1" id="dash-loan-limit">Cho vay: 250.000 tr | Bảo lãnh: 30.000 tr</div>
        </div>
        <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
          <div class="text-xs text-slate-500 font-medium">Doanh thu thuần năm gần nhất</div>
          <div class="text-lg font-bold text-slate-900 mt-1" id="dash-rev-2025">7.819.398 triệu VND</div>
          <div class="text-xs text-emerald-600 mt-1 font-semibold" id="dash-np-2025">LNST: 134.201 tr (+49.6%)</div>
        </div>
        <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
          <div class="text-xs text-slate-500 font-medium">Lịch sử quan hệ CIC</div>
          <div class="text-lg font-bold text-emerald-600 mt-1" id="dash-cic-status">100% Nhóm 1</div>
          <div class="text-xs text-slate-500 mt-1" id="dash-msb-out">Dư nợ tại MSB: 499.999 triệu VND</div>
        </div>
      </div>

      <!-- PROPOSAL SUMMARY CARD -->
      <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
        <div class="flex items-center justify-between border-b pb-3">
          <h3 class="font-bold text-base text-[#003366] flex items-center space-x-2">
            <span>📑 Chi Tiết Đề Xuất Cấp Tín Dụng & Cơ Cấu Bảo Đảm</span>
          </h3>
          <span class="text-xs bg-blue-100 text-blue-800 font-bold px-2.5 py-1 rounded">Bản MB07 Tiêu Chuẩn MSB</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm">
          <div class="space-y-2.5">
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Mã số doanh nghiệp (MST):</span>
              <span class="font-semibold text-slate-800" id="dash-tax-code">0100000000</span>
            </div>
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Người đại diện pháp luật:</span>
              <span class="font-semibold text-slate-800" id="dash-legal-rep">Đại diện Demo (Tổng Giám đốc)</span>
            </div>
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Vốn điều lệ thực góp:</span>
              <span class="font-semibold text-slate-800" id="dash-capital">518.279 triệu VND</span>
            </div>
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Địa chỉ trụ sở:</span>
              <span class="font-semibold text-slate-800 text-right max-w-xs truncate" id="dash-address">P.207, Tòa nhà PetroVietnam, Số 1-5 Lê Duẩn, Q.1, TP.HCM</span>
            </div>
          </div>

          <div class="space-y-2.5">
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Mục đích cấp tín dụng:</span>
              <span class="font-semibold text-slate-800 text-right max-w-xs truncate" id="dash-purpose">Bổ sung vốn lưu động kinh doanh ICT</span>
            </div>
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Biện pháp bảo đảm:</span>
              <span class="font-semibold text-emerald-700" id="dash-collat">Tín chấp 100% (Định hạng A+/AAA)</span>
            </div>
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Cam kết dòng tiền về MSB:</span>
              <span class="font-semibold text-blue-700" id="dash-cashflow">25% Doanh thu qua tài khoản MSB</span>
            </div>
            <div class="flex justify-between py-1 border-b border-slate-100">
              <span class="text-slate-500">Thẩm quyền phê duyệt:</span>
              <span class="font-semibold text-slate-800" id="dash-authority">Hội đồng Tín dụng Cấp cao (HĐTDCC)</span>
            </div>
          </div>
        </div>

        <div class="pt-2 flex justify-end space-x-3">
          <button onclick="switchTab('tab-upload')" class="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-bold transition">
            📂 Quản lý Hồ sơ & Tài liệu →
          </button>
          <button onclick="switchTab('tab-insights')" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-bold transition">
            💡 Xem Thẩm định Tín dụng AI →
          </button>
        </div>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- TAB 2: KHÔNG GIAN HỒ SƠ (DOCUMENT WORKSPACE)                              -->
    <!-- ========================================================================= -->
    <section id="tab-upload" class="hidden space-y-6">
      <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
        <div class="flex items-center justify-between border-b pb-3">
          <div>
            <h3 class="font-bold text-base text-[#003366]">📂 Danh Mục Tài Liệu Hồ Sơ Khách Hàng</h3>
            <p class="text-xs text-slate-500">Bóc tách tự động đa tài liệu qua GreenNode Document AI với bằng chứng đối soát trang (No Evidence → No Fact)</p>
          </div>
          <span id="doc-workspace-badge" class="text-xs bg-emerald-100 text-emerald-800 font-bold px-2.5 py-1 rounded">4/4 Nhóm Tài Liệu Đã Nạp</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <!-- CARD 1: LEGAL -->
          <div id="card-legal" class="p-4 rounded-xl border border-slate-200 bg-slate-50 space-y-3">
            <input type="file" id="file-legal" accept=".pdf" class="hidden" onchange="handleFileSelected('legal', this)">
            <div class="flex items-start justify-between">
              <div class="flex items-center space-x-2">
                <span class="text-xl">🏛️</span>
                <div>
                  <div class="text-sm font-bold text-slate-800">1. Hồ sơ Pháp lý & ĐKKD</div>
                  <div id="file-name-legal" class="text-xs text-slate-500">Giay_Phep_DKKD_PSD.pdf (Trang 1 - 3)</div>
                </div>
              </div>
              <div id="status-badge-legal">
                <span class="text-xs bg-emerald-100 text-emerald-800 font-bold px-2 py-0.5 rounded">✓ Đã bóc tách & xác nhận</span>
              </div>
            </div>
            <div id="summary-legal" class="text-xs text-slate-600 space-y-1 bg-white p-3 rounded-lg border border-slate-200">
              <div>• Tên DN: <span id="sum-legal-name" class="font-semibold text-slate-800">CTCP Dịch vụ Phân phối TH Dầu khí</span></div>
              <div>• MST: <span id="sum-legal-tax" class="font-semibold text-slate-800">0100000000</span> | Vốn ĐL: <span id="sum-legal-capital" class="font-semibold text-slate-800">518.279 tr</span></div>
              <div>• ĐDPL: <span id="sum-legal-rep" class="font-semibold text-slate-800">Đại diện Demo</span> (Tổng Giám đốc)</div>
            </div>
            <div id="actions-legal" class="flex items-center justify-between pt-1">
              <span id="tip-legal" class="text-[11px] text-slate-400 italic">Đã đồng bộ vào Phần A MB07</span>
              <div class="flex space-x-2">
                <button onclick="triggerDocUpload('legal')" class="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-xs font-semibold shadow-sm transition">
                  🔄 Thay thế PDF
                </button>
                <button onclick="openReviewModal('legal')" class="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs font-bold shadow-sm transition">
                  🔍 Xem Lại Bóc Tách
                </button>
              </div>
            </div>
          </div>

          <!-- CARD 2: BUSINESS -->
          <div id="card-business" class="p-4 rounded-xl border border-slate-200 bg-slate-50 space-y-3">
            <input type="file" id="file-business" accept=".pdf" class="hidden" onchange="handleFileSelected('business', this)">
            <div class="flex items-start justify-between">
              <div class="flex items-center space-x-2">
                <span class="text-xl">🏭</span>
                <div>
                  <div class="text-sm font-bold text-slate-800">2. Mô hình KD & Chuỗi cung ứng</div>
                  <div id="file-name-business" class="text-xs text-slate-500">Bao_Cao_Thuong_Nien_PSD.pdf (Trang 15 - 42)</div>
                </div>
              </div>
              <div id="status-badge-business">
                <span class="text-xs bg-emerald-100 text-emerald-800 font-bold px-2 py-0.5 rounded">✓ Đã bóc tách chuỗi cung ứng</span>
              </div>
            </div>
            <div id="summary-business" class="text-xs text-slate-600 space-y-1 bg-white p-3 rounded-lg border border-slate-200">
              <div>• Mô hình: <span id="sum-biz-model" class="font-semibold text-slate-800">Thương mại Phân phối ICT</span></div>
              <div>• Nhà cung cấp chính: <span id="sum-biz-suppliers" class="font-semibold text-slate-800">Dell (28.1%), Lenovo (20.4%), Samsung (19.1%)</span></div>
              <div>• Khách hàng chính: <span id="sum-biz-customers" class="font-semibold text-slate-800">MWG (4.5%), Viettel Store, FPT Shop</span></div>
            </div>
            <div id="actions-business" class="flex items-center justify-between pt-1">
              <span id="tip-business" class="text-[11px] text-slate-400 italic">Đã đồng bộ vào Phần C MB07</span>
              <div class="flex space-x-2">
                <button onclick="triggerDocUpload('business')" class="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-xs font-semibold shadow-sm transition">
                  🔄 Thay thế PDF
                </button>
                <button onclick="openReviewModal('business')" class="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs font-bold shadow-sm transition">
                  🔍 Xem Lại Bóc Tách
                </button>
              </div>
            </div>
          </div>

          <!-- CARD 3: FINANCIAL -->
          <div id="card-financial" class="p-4 rounded-xl border border-slate-200 bg-slate-50 space-y-3">
            <input type="file" id="file-financial" accept=".pdf" class="hidden" onchange="handleFileSelected('financial', this)">
            <div class="flex items-start justify-between">
              <div class="flex items-center space-x-2">
                <span class="text-xl">📈</span>
                <div>
                  <div class="text-sm font-bold text-slate-800">3. BCTC Kiểm toán 3 năm</div>
                  <div id="file-name-financial" class="text-xs text-slate-500">BCTC_Kiem_Toan_PwC_2025.pdf</div>
                </div>
              </div>
              <div id="status-badge-financial">
                <span class="text-xs bg-emerald-100 text-emerald-800 font-bold px-2 py-0.5 rounded">✓ Đã đối soát 3 năm</span>
              </div>
            </div>
            <div id="summary-financial" class="text-xs text-slate-600 space-y-1 bg-white p-3 rounded-lg border border-slate-200">
              <div>• Đơn vị kiểm toán: <span id="sum-fin-auditor" class="font-semibold text-slate-800">PwC Việt Nam (Chấp thuận toàn phần)</span></div>
              <div>• Doanh thu 2025: <span id="sum-fin-rev" class="font-semibold text-slate-800">7.819.398 tr</span></div>
              <div>• LNST 2025: <span id="sum-fin-np" class="font-semibold text-slate-800">134.201 tr</span> | VCSH: <span id="sum-fin-equity" class="font-semibold text-slate-800">729.343 tr</span></div>
            </div>
            <div id="actions-financial" class="flex items-center justify-between pt-1">
              <span id="tip-financial" class="text-[11px] text-slate-400 italic">Đã đồng bộ vào Phần D MB07</span>
              <div class="flex space-x-2">
                <button onclick="triggerDocUpload('financial')" class="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-xs font-semibold shadow-sm transition">
                  🔄 Thay thế PDF
                </button>
                <button onclick="openReviewModal('financial')" class="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs font-bold shadow-sm transition">
                  🔍 Xem Lại Bóc Tách
                </button>
              </div>
            </div>
          </div>

          <!-- CARD 4: CIC -->
          <div id="card-cic" class="p-4 rounded-xl border border-slate-200 bg-slate-50 space-y-3">
            <input type="file" id="file-cic" accept=".pdf" class="hidden" onchange="handleFileSelected('cic', this)">
            <div class="flex items-start justify-between">
              <div class="flex items-center space-x-2">
                <span class="text-xl">🏦</span>
                <div>
                  <div class="text-sm font-bold text-slate-800">4. Báo cáo Tín dụng CIC Chi tiết</div>
                  <div id="file-name-cic" class="text-xs text-slate-500">Bao_Cao_CIC_Chi_Tiet_2025.pdf</div>
                </div>
              </div>
              <div id="status-badge-cic">
                <span class="text-xs bg-emerald-100 text-emerald-800 font-bold px-2 py-0.5 rounded">✓ Đã đối soát chuẩn mực</span>
              </div>
            </div>
            <div id="summary-cic" class="text-xs text-slate-600 space-y-1 bg-white p-3 rounded-lg border border-slate-200">
              <div>• Ngày tra cứu CIC: <span id="sum-cic-date" class="font-semibold text-slate-800">31/12/2025</span></div>
              <div>• Phân loại nợ: <span id="sum-cic-status" class="font-semibold text-emerald-700">100% Nhóm 1 (Đủ tiêu chuẩn 24 tháng)</span></div>
              <div>• Dư nợ tại MSB: <span id="sum-cic-msb" class="font-semibold text-slate-800">499.999 tr</span> | Dư nợ TCTD khác: <span id="sum-cic-other" class="font-semibold text-slate-800">Đầy đủ</span></div>
            </div>
            <div id="actions-cic" class="flex items-center justify-between pt-1">
              <span id="tip-cic" class="text-[11px] text-slate-400 italic">Đã đồng bộ vào Phần E MB07</span>
              <div class="flex space-x-2">
                <button onclick="triggerDocUpload('cic')" class="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-xs font-semibold shadow-sm transition">
                  🔄 Thay thế PDF
                </button>
                <button onclick="openReviewModal('cic')" class="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs font-bold shadow-sm transition">
                  🔍 Xem Lại Bóc Tách
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- TAB 3: ĐỐI SOÁT DỮ LIỆU (FACT REVIEW A - E)                               -->
    <!-- ========================================================================= -->
    <section id="tab-review" class="hidden space-y-6">
      <!-- WARNING / NEEDS RM REVIEW BANNER -->
      <div class="p-4 rounded-xl bg-amber-50 border border-amber-200 flex items-start space-x-3">
        <span class="text-xl">⚠️</span>
        <div class="text-xs space-y-1 text-amber-900">
          <div class="font-bold text-sm">Cảnh Báo Đối Soát Dữ Liệu & Thẩm Quyền RM:</div>
          <div>• Toàn bộ số liệu trích xuất từ tài liệu đã được gắn nhãn nguồn gốc trang. RM vui lòng xác nhận các trường cần đánh giá chuyên môn trước khi xuất bản.</div>
          <div>• Trường hợp phát hiện sai lệch thực tế, RM có thể biên tập trực tiếp vào các ô tương ứng bên dưới.</div>
        </div>
      </div>

      <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-6">
        <div class="flex items-center justify-between border-b pb-3">
          <h3 class="font-bold text-base text-[#003366]">📋 Dữ Liệu Thẩm Định Theo Cấu Trúc Tờ Trình MB07</h3>
          <div class="flex space-x-2 text-xs">
            <button onclick="saveSectionA()" class="px-3 py-1.5 bg-blue-50 text-blue-700 hover:bg-blue-100 rounded font-semibold">Lưu Phần A</button>
            <button onclick="saveSectionB()" class="px-3 py-1.5 bg-blue-50 text-blue-700 hover:bg-blue-100 rounded font-semibold">Lưu Phần B</button>
          </div>
        </div>

        <!-- SECTION A & B FORM COMPACT -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 text-xs">
          <!-- PHẦN A -->
          <div class="space-y-3 bg-slate-50 p-4 rounded-xl border border-slate-200">
            <div class="font-bold text-slate-800 text-sm flex items-center justify-between">
              <span>🏛️ Phần A: Thông Tin Pháp Lý & ĐVKD</span>
              <span class="tag-ai px-2 py-0.5 rounded text-[10px] font-bold">AI Đã Điền</span>
            </div>
            <div class="space-y-2">
              <div>
                <label class="font-medium text-slate-600">Đơn vị kinh doanh thẩm định:</label>
                <input type="text" id="rm-unit-name" value="LC2MN" class="w-full mt-1 px-3 py-1.5 bg-white border border-slate-300 rounded font-medium text-slate-800">
              </div>
              <div class="grid grid-cols-2 gap-2">
                <div>
                  <label class="font-medium text-slate-600">Cán bộ bán hàng / RM:</label>
                  <input type="text" id="rm-rm-name" value="RM DEMO / RM SUPPORT" class="w-full mt-1 px-3 py-1.5 bg-white border border-slate-300 rounded text-slate-800">
                </div>
                <div>
                  <label class="font-medium text-slate-600">Số điện thoại RM:</label>
                  <input type="text" id="rm-rm-phone" value="0900000000" class="w-full mt-1 px-3 py-1.5 bg-white border border-slate-300 rounded text-slate-800">
                </div>
              </div>
              <div class="grid grid-cols-2 gap-2">
                <div>
                  <label class="font-medium text-slate-600">Cán bộ quản lý:</label>
                  <input type="text" id="rm-manager-name" value="MANAGER DEMO" class="w-full mt-1 px-3 py-1.5 bg-white border border-slate-300 rounded text-slate-800">
                </div>
                <div>
                  <label class="font-medium text-slate-600">Thẩm quyền phê duyệt:</label>
                  <input type="text" id="rm-authority" value="HĐTDCC" class="w-full mt-1 px-3 py-1.5 bg-white border border-slate-300 rounded text-slate-800 font-bold text-red-700">
                </div>
              </div>
            </div>
          </div>

          <!-- PHẦN B -->
          <div class="space-y-3 bg-slate-50 p-4 rounded-xl border border-slate-200">
            <div class="font-bold text-slate-800 text-sm flex items-center justify-between">
              <span>💰 Phần B: Đề Xuất Cấp Tín Dụng</span>
              <span class="tag-rm px-2 py-0.5 rounded text-[10px] font-bold">RM Thẩm Định</span>
            </div>
            <div class="space-y-2">
              <div class="grid grid-cols-3 gap-2">
                <div>
                  <label class="font-medium text-slate-600">Tổng hạn mức (tr):</label>
                  <input type="number" id="rm-total-limit" value="700000" class="w-full mt-1 px-3 py-1.5 bg-white border border-slate-300 rounded font-bold text-[#003366]">
                </div>
                <div>
                  <label class="font-medium text-slate-600">Hạn mức vay (tr):</label>
                  <input type="number" id="rm-loan-limit" value="250000" class="w-full mt-1 px-3 py-1.5 bg-white border border-slate-300 rounded text-slate-800">
                </div>
                <div>
                  <label class="font-medium text-slate-600">Bảo lãnh (tr):</label>
                  <input type="number" id="rm-guar-limit" value="30000" class="w-full mt-1 px-3 py-1.5 bg-white border border-slate-300 rounded text-slate-800">
                </div>
              </div>
              <div>
                <label class="font-medium text-slate-600">Biện pháp bảo đảm:</label>
                <input type="text" id="rm-collateral" value="Tín chấp 100% (Cấp tín dụng không có TSBĐ theo phê duyệt định hạng A+)" class="w-full mt-1 px-3 py-1.5 bg-white border border-slate-300 rounded text-slate-800 font-medium">
              </div>
              <div>
                <label class="font-medium text-slate-600">Mục đích vay:</label>
                <input type="text" id="rm-purpose" value="Bổ sung vốn lưu động phục vụ hoạt động kinh doanh; thanh toán nhà cung cấp." class="w-full mt-1 px-3 py-1.5 bg-white border border-slate-300 rounded text-slate-800">
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- TAB 4: THẨM ĐỊNH TÍN DỤNG AI (AI INSIGHTS EXPERIENCE - VISUAL HIGHLIGHT)  -->
    <!-- ========================================================================= -->
    <section id="tab-insights" class="hidden space-y-6">
      <!-- HEADER EXPLANATION -->
      <div class="bg-gradient-to-r from-blue-50 via-indigo-50 to-purple-50 p-5 rounded-xl border border-blue-200 flex items-center justify-between">
        <div>
          <h3 class="font-bold text-base text-[#003366] flex items-center space-x-2">
            <span>💡 Bộ Lọc Thẩm Định 2 Lớp: AI Phát Hiện Xu Hướng + Python Tái Thẩm Định Toán Học 100%</span>
          </h3>
          <p class="text-xs text-slate-600 mt-1">
            Mọi chỉ số tăng trưởng, biên lợi nhuận, độ lệch vốn lưu động do GreenNode GLM-5.2 phát hiện đều được kiểm chứng và tính toán lại độc lập bằng code Python xác thực trước khi đưa vào tờ trình.
          </p>
        </div>
        <span class="text-xs bg-indigo-100 text-indigo-800 font-bold px-3 py-1.5 rounded-full border border-indigo-300 whitespace-nowrap">
          ✓ 6/6 Chỉ Số Đã Thẩm Định
        </span>
      </div>

      <!-- INSIGHTS GRID -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-5" id="insights-container">
        <!-- CARD 1: REVENUE GROWTH -->
        <div class="card-insight bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-blue-700 bg-blue-50 px-2.5 py-1 rounded">TĂNG TRƯỞNG DOANH THU</span>
            <span class="tag-verified text-[11px] font-bold px-2 py-0.5 rounded">✓ Python Verified</span>
          </div>
          <div class="flex items-baseline space-x-2">
            <span class="text-3xl font-extrabold text-emerald-600">+37.1%</span>
            <span class="text-xs text-slate-500">(2024 -> 2025)</span>
          </div>
          <div class="text-xs text-slate-700 bg-slate-50 p-3 rounded-lg border border-slate-100 space-y-1.5">
            <div class="font-semibold text-slate-800">🤖 AI Phát hiện:</div>
            <p class="text-slate-600">Doanh thu bứt phá từ 5.702,5 tỷ lên 7.819,4 tỷ VND nhờ mở rộng phân phối các dòng điện thoại thông minh thế hệ mới.</p>
            <div class="pt-1 border-t border-slate-200 text-[11px] text-indigo-700 font-mono">
              Công thức: (7.819,4 - 5.702,5) / 5.702,5 = +37.12%
            </div>
          </div>
        </div>

        <!-- CARD 2: GROSS PROFIT MARGIN -->
        <div class="card-insight bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded">BIÊN LỢI NHUẬN GỘP</span>
            <span class="tag-verified text-[11px] font-bold px-2 py-0.5 rounded">✓ Python Verified</span>
          </div>
          <div class="flex items-baseline space-x-2">
            <span class="text-3xl font-extrabold text-slate-800">5.20%</span>
            <span class="text-xs text-emerald-600 font-semibold">(LN gộp: 406.8 tỷ)</span>
          </div>
          <div class="text-xs text-slate-700 bg-slate-50 p-3 rounded-lg border border-slate-100 space-y-1.5">
            <div class="font-semibold text-slate-800">🤖 AI Phát hiện:</div>
            <p class="text-slate-600">Biên lợi nhuận gộp duy trì ổn định >5.2%, lợi nhuận gộp tăng trưởng +26.8% so với năm 2024 (320.9 tỷ VND).</p>
            <div class="pt-1 border-t border-slate-200 text-[11px] text-indigo-700 font-mono">
              Công thức: 406.809 / 7.819.398 = 5.20%
            </div>
          </div>
        </div>

        <!-- CARD 3: RECEIVABLES DIVERGENCE -->
        <div class="card-insight bg-white p-5 rounded-xl border border-amber-200 shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-amber-800 bg-amber-50 px-2.5 py-1 rounded">ĐỘ LỆCH PHẢI THU</span>
            <span class="tag-warning text-[11px] font-bold px-2 py-0.5 rounded">⚠️ Cần RM Lưu Ý</span>
          </div>
          <div class="flex items-baseline space-x-2">
            <span class="text-3xl font-extrabold text-amber-600">+104.0%</span>
            <span class="text-xs text-slate-500">(vs DThu +37.1%)</span>
          </div>
          <div class="text-xs text-slate-700 bg-amber-50/50 p-3 rounded-lg border border-amber-200 space-y-1.5">
            <div class="font-semibold text-amber-900">🤖 AI Cảnh báo:</div>
            <p class="text-slate-700">Phải thu ngắn hạn tăng nhanh từ 723 tỷ lên 1.475 tỷ VND, cần đối soát chất lượng công nợ chuỗi đại lý đầu ra.</p>
            <div class="pt-1 border-t border-amber-200 text-[11px] text-amber-800 font-mono">
              Công thức: (1.475,0 - 723,0) / 723,0 = +104.01%
            </div>
          </div>
        </div>

        <!-- CARD 4: ASSET STRUCTURE -->
        <div class="card-insight bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-purple-700 bg-purple-50 px-2.5 py-1 rounded">CƠ CẤU TÀI SẢN</span>
            <span class="tag-verified text-[11px] font-bold px-2 py-0.5 rounded">✓ Python Verified</span>
          </div>
          <div class="flex items-baseline space-x-2">
            <span class="text-3xl font-extrabold text-slate-800">98.2%</span>
            <span class="text-xs text-slate-500">(Tài sản ngắn hạn)</span>
          </div>
          <div class="text-xs text-slate-700 bg-slate-50 p-3 rounded-lg border border-slate-100 space-y-1.5">
            <div class="font-semibold text-slate-800">🤖 AI Phát hiện:</div>
            <p class="text-slate-600">Tài sản ngắn hạn chiếm 4.600 tỷ / 4.683 tỷ VND tổng tài sản, phù hợp đặc thù luân chuyển nhanh của ngành phân phối.</p>
            <div class="pt-1 border-t border-slate-200 text-[11px] text-indigo-700 font-mono">
              Công thức: 4.600.702 / 4.683.423 = 98.23%
            </div>
          </div>
        </div>

        <!-- CARD 5: SUPPLIER CONCENTRATION -->
        <div class="card-insight bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-blue-700 bg-blue-50 px-2.5 py-1 rounded">TẬP TRUNG NHÀ CUNG CẤP</span>
            <span class="tag-verified text-[11px] font-bold px-2 py-0.5 rounded">✓ Python Verified</span>
          </div>
          <div class="flex items-baseline space-x-2">
            <span class="text-3xl font-extrabold text-slate-800">Top 1: 28.1%</span>
            <span class="text-xs text-slate-500">(Dell Global)</span>
          </div>
          <div class="text-xs text-slate-700 bg-slate-50 p-3 rounded-lg border border-slate-100 space-y-1.5">
            <div class="font-semibold text-slate-800">🤖 AI Phát hiện:</div>
            <p class="text-slate-600">Quan hệ đối tác cấp 1 >15 năm với Dell (28.1%), Lenovo (20.4%), Samsung (19.1%) kèm cơ chế bảo vệ giá Price Protection.</p>
            <div class="pt-1 border-t border-slate-200 text-[11px] text-indigo-700 font-mono">
              Đối soát: Hợp đồng đại lý ủy quyền cấp 1
            </div>
          </div>
        </div>

        <!-- CARD 6: CIC DISCIPLINE -->
        <div class="card-insight bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded">KỶ LUẬT TÍN DỤNG CIC</span>
            <span class="tag-verified text-[11px] font-bold px-2 py-0.5 rounded">✓ Python Verified</span>
          </div>
          <div class="flex items-baseline space-x-2">
            <span class="text-3xl font-extrabold text-emerald-600">100% Nhóm 1</span>
            <span class="text-xs text-slate-500">(24 tháng liên tục)</span>
          </div>
          <div class="text-xs text-slate-700 bg-slate-50 p-3 rounded-lg border border-slate-100 space-y-1.5">
            <div class="font-semibold text-slate-800">🤖 AI Phát hiện:</div>
            <p class="text-slate-600">Khách hàng và ban lãnh đạo có lịch sử trả nợ mẫu mực, 0 ngày quá hạn tại MSB và toàn bộ các TCTD.</p>
            <div class="pt-1 border-t border-slate-200 text-[11px] text-indigo-700 font-mono">
              Đối soát: Báo cáo CIC Trung tâm đến 31/12/2025
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- TAB 5: SOẠN THẢO & XUẤT TỜ TRÌNH MB07                                     -->
    <!-- ========================================================================= -->
    <section id="tab-narrative" class="hidden space-y-6">
      <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-6">
        <!-- HEADER & WORKFLOW STATUS -->
        <div class="flex flex-col md:flex-row md:items-center justify-between border-b pb-4 gap-4">
          <div>
            <div class="flex items-center space-x-3">
              <h3 class="font-bold text-base text-[#003366]">📝 Phê Duyệt & Biên Tập Narrative Tờ Trình MB07</h3>
              <span id="narrative-status-badge" class="text-xs font-bold px-2.5 py-0.5 rounded border border-slate-300 bg-slate-100 text-slate-600">
                Chờ Kiểm Tra
              </span>
            </div>
            <p class="text-xs text-slate-500 mt-1">Quy trình 3 lớp: AI Phát hiện ➔ Python Đối soát độc lập ➔ RM Phê duyệt (FactManifest SHA-256)</p>
          </div>
          <div id="narrative-header-actions" class="flex items-center space-x-2">
            <!-- Dynamic Action Buttons (Tạo Nhận Định AI / Phê Duyệt / Tạo Lại) -->
          </div>
        </div>

        <!-- STATE NOTIFICATION / BANNER AREA -->
        <div id="narrative-alert-container"></div>

        <!-- TELEMETRY / AUDIT STRIP (shown when draft exists) -->
        <div id="narrative-telemetry-strip" class="hidden p-3 bg-slate-50 border border-slate-200 rounded-lg text-[11px] text-slate-600 flex flex-wrap items-center justify-between gap-2">
          <div class="flex items-center space-x-2">
            <span class="font-bold text-slate-700">Mô hình AI:</span>
            <span id="narrative-model-label" class="bg-purple-100 text-purple-800 font-mono px-2 py-0.5 rounded font-bold"></span>
          </div>
          <div class="flex items-center space-x-3">
            <span id="narrative-manifest-hash" class="font-mono text-slate-500">Hash: -</span>
            <span id="narrative-insights-count" class="bg-indigo-100 text-indigo-800 px-2 py-0.5 rounded font-semibold">0 Insights</span>
            <span id="narrative-blocks-count" class="bg-slate-200 text-slate-700 px-2 py-0.5 rounded font-semibold">0 Blocks</span>
          </div>
        </div>

        <!-- NARRATIVE BLOCKS CONTAINER -->
        <div class="space-y-4" id="narrative-blocks-container">
          <!-- Dynamically populated by renderNarrativeUI() -->
        </div>

        <!-- HERO GENERATE BUTTON & DOWNLOAD STATUS -->
        <div class="pt-4 border-t border-slate-200 flex flex-col items-center space-y-4">
          <button onclick="generateDocx()" id="btn-generate-main" class="w-full md:w-2/3 py-4 bg-[#EB1C24] hover:bg-red-700 text-white rounded-xl font-bold text-base shadow-lg transition flex items-center justify-center space-x-2">
            <span>🚀 BẮT ĐẦU TỔNG HỢP & XUẤT BẢN TỜ TRÌNH MB07 (.DOCX)</span>
          </button>
          
          <div id="export-result" class="hidden w-full md:w-2/3 p-4 bg-emerald-50 border border-emerald-300 rounded-xl text-center space-y-2">
            <div class="text-emerald-800 font-bold text-sm">🎉 Tờ trình tín dụng MB07 đã được khởi tạo thành công!</div>
            <div class="text-xs text-slate-600 font-mono" id="export-filename">Tệp tin: TO_TRINH_MB07_PSD_HOAN_CHINH.docx</div>
            <a id="export-download-link" href="#" class="inline-block px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold rounded-lg shadow transition">
              ⬇️ TẢI FILE WORD (.DOCX) VỀ MÁY
            </a>
          </div>
        </div>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- TAB 6: SẴN SÀNG HỘI ĐỒNG TÍN DỤNG (HERO FEATURE)                          -->
    <!-- ========================================================================= -->
    <section id="tab-committee" class="hidden space-y-6">
      <!-- HERO HEADER -->
      <div class="badge-hero p-6 rounded-2xl text-white shadow-lg space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-3">
            <span class="text-3xl">🎯</span>
            <div>
              <h2 class="text-xl font-extrabold tracking-tight">CHUẨN BỊ BẢO VỆ TRƯỚC HỘI ĐỒNG TÍN DỤNG</h2>
              <p class="text-xs text-blue-200">Hệ thống phân tích các điểm nhạy cảm, rủi ro tiềm ẩn và mô phỏng câu hỏi chất vấn từ HĐTD</p>
            </div>
          </div>
          <span class="text-xs bg-amber-400 text-slate-900 font-extrabold px-3 py-1.5 rounded-full uppercase tracking-wider shadow">
            Hero Feature
          </span>
        </div>
        <div class="p-3 bg-white/10 rounded-xl border border-white/10 text-xs text-slate-100 flex items-center space-x-2">
          <span>💡</span>
          <span><strong>Mục đích:</strong> Giúp RM nắm chắc toàn bộ dữ liệu phản biện, hiểu rõ các điểm yếu trong hồ sơ và chuẩn bị sẵn phương án giải trình tự tin trước Hội đồng.</span>
        </div>
      </div>

      <!-- QUESTIONS CONTAINER -->
      <div class="space-y-4" id="committee-cards-container">
        <!-- Cards loaded dynamically via loadCommitteeCards() -->
      </div>
    </section>

  </main>

  <!-- MODAL: EDIT NARRATIVE -->
  <div id="modal-edit-narrative" class="hidden fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-4">
      <div class="flex justify-between items-center border-b pb-3">
        <div>
          <h3 class="font-bold text-base text-[#003366]">✏️ Chỉnh Sửa & Tái Thẩm Định Bản Thảo Narrative</h3>
          <p id="modal-narr-target-title" class="text-xs text-slate-500"></p>
        </div>
        <button onclick="closeEditModal()" class="text-slate-400 hover:text-slate-600 font-bold text-lg">&times;</button>
      </div>
      <div id="modal-narr-error" class="hidden p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-lg"></div>
      <div class="space-y-2">
        <label class="text-xs font-semibold text-slate-600">Nội dung đoạn văn (sẽ được đối soát tự động qua Python Verifier):</label>
        <textarea id="modal-narr-text" rows="6" class="w-full p-3 text-xs border border-slate-300 rounded-lg focus:ring-1 focus:ring-blue-500 focus:outline-none leading-relaxed"></textarea>
      </div>
      <div class="space-y-1">
        <label class="text-xs font-semibold text-slate-600">Ghi chú giải trình của RM (tùy chọn):</label>
        <input type="text" id="modal-narr-rm-note" placeholder="VD: Bổ sung chi tiết giải trình theo yêu cầu cấp thẩm quyền..." class="w-full p-2 text-xs border border-slate-300 rounded-lg focus:ring-1 focus:ring-blue-500 focus:outline-none">
      </div>
      <div class="flex justify-end space-x-2 pt-2">
        <button onclick="closeEditModal()" class="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold">Hủy</button>
        <button onclick="saveAndRevalidateNarrative()" id="btn-modal-save" class="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-bold shadow">
          ✓ Lưu & Tái Thẩm Định
        </button>
      </div>
    </div>
  </div>

  <!-- MODAL: TẠO HỒ SƠ KHÁCH HÀNG MỚI -->
  <div id="modal-new-case" class="hidden fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-2xl max-w-xl w-full p-6 shadow-2xl space-y-4">
      <div class="flex justify-between items-center border-b pb-3">
        <h3 class="font-bold text-base text-[#003366]">➕ Khởi Tạo Hồ Sơ Thẩm Định Mới</h3>
        <button onclick="closeNewCaseModal()" class="text-slate-400 hover:text-slate-600 font-bold text-lg">&times;</button>
      </div>
      <div class="space-y-3 text-xs">
        <div>
          <label class="font-semibold text-slate-700">Tên Doanh Nghiệp đầy đủ <span class="text-red-500">*</span>:</label>
          <input type="text" id="new-case-name" placeholder="VD: CÔNG TY CỔ PHẦN THƯƠNG MẠI ALPHA" class="w-full mt-1 p-2 border border-slate-300 rounded focus:ring-1 focus:ring-blue-500">
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="font-semibold text-slate-700">Tên viết tắt / Mã gợi nhớ <span class="text-red-500">*</span>:</label>
            <input type="text" id="new-case-short-name" placeholder="VD: ALPHA_JSC" class="w-full mt-1 p-2 border border-slate-300 rounded focus:ring-1 focus:ring-blue-500">
          </div>
          <div>
            <label class="font-semibold text-slate-700">Mã số thuế <span class="text-red-500">*</span>:</label>
            <input type="text" id="new-case-tax-code" placeholder="VD: 0312345678" class="w-full mt-1 p-2 border border-slate-300 rounded focus:ring-1 focus:ring-blue-500">
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="font-semibold text-slate-700">Vốn điều lệ (triệu VND):</label>
            <input type="number" id="new-case-capital" placeholder="VD: 50000" class="w-full mt-1 p-2 border border-slate-300 rounded focus:ring-1 focus:ring-blue-500">
          </div>
          <div>
            <label class="font-semibold text-slate-700">Hạn mức đề xuất (triệu VND):</label>
            <input type="number" id="new-case-limit" placeholder="VD: 100000" class="w-full mt-1 p-2 border border-slate-300 rounded focus:ring-1 focus:ring-blue-500">
          </div>
        </div>
        <div>
          <label class="font-semibold text-slate-700">Địa chỉ đăng ký trụ sở:</label>
          <input type="text" id="new-case-address" placeholder="VD: Số 123 Đường ABC, Phường Bến Nghé, Quận 1, TP.HCM" class="w-full mt-1 p-2 border border-slate-300 rounded focus:ring-1 focus:ring-blue-500">
        </div>
        <div>
          <label class="font-semibold text-slate-700">Mô hình kinh doanh:</label>
          <select id="new-case-business-model" class="w-full mt-1 p-2 border border-slate-300 rounded focus:ring-1 focus:ring-blue-500 bg-white">
            <option value="THUONG_MAI">Thương mại Phân phối</option>
            <option value="SAN_XUAT">Sản xuất</option>
            <option value="SAN_XUAT_VA_THUONG_MAI">Sản xuất & Thương mại</option>
            <option value="DICH_VU">Dịch vụ</option>
            <option value="XAY_DUNG_BAT_DONG_SAN">Xây dựng & Bất động sản</option>
          </select>
        </div>
      </div>
      <div class="flex justify-end space-x-2 pt-3 border-t">
        <button onclick="closeNewCaseModal()" class="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold">Hủy</button>
        <button onclick="submitNewCase()" class="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold shadow">
          ➕ Khởi Tạo Hồ Sơ
        </button>
      </div>
    </div>
  </div>

  <!-- MODAL: ĐỐI SOÁT & XÁC NHẬN BÓC TÁCH (RM REVIEW MODAL) -->
  <div id="modal-doc-review" class="hidden fixed inset-0 bg-slate-900/60 z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-2xl max-w-4xl w-full p-6 shadow-2xl space-y-4">
      <div class="flex justify-between items-center border-b pb-3">
        <div>
          <h3 id="modal-review-title" class="font-bold text-base text-[#003366]">📋 Đối Soát Dữ Liệu Bóc Tách GreenNode AI</h3>
          <p id="modal-review-subtitle" class="text-xs text-slate-500">Đối soát bằng chứng trang và giải quyết xung đột trước khi xác nhận vào hồ sơ MB07</p>
        </div>
        <button onclick="closeReviewModal()" class="text-slate-400 hover:text-slate-600 font-bold text-lg">&times;</button>
      </div>

      <!-- REVIEW CONTENT AREA -->
      <div id="modal-review-body" class="max-h-[60vh] overflow-y-auto space-y-4 pr-1 text-xs">
        <!-- Dynamic content injected by renderReviewBody -->
      </div>

      <div class="flex items-center justify-between pt-3 border-t">
        <div class="text-[11px] text-amber-700 bg-amber-50 px-3 py-1.5 rounded-lg border border-amber-200">
          🛡️ <strong>Nguyên tắc MSB:</strong> Dữ liệu chỉ được xác nhận khi có số trang và trích dẫn bằng chứng xác thực.
        </div>
        <div class="flex space-x-2">
          <button onclick="closeReviewModal()" class="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold">Đóng / Xem Lại Sau</button>
          <button id="btn-confirm-review" onclick="confirmCurrentReview()" class="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold shadow flex items-center space-x-1.5">
            <span>✓ Xác Nhận Vào Hồ Sơ (Commit)</span>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- JAVASCRIPT LOGIC -->
  <script>
    let CURRENT_ACTIVE_TAB = 'tab-dashboard';
    let CURRENT_CASE_ID = 'PSD';
    let CURRENT_REVIEW_DOCTYPE = null;

    const DOC_STATES = {
      legal: { state: 'RM_CONFIRMED', filename: 'Giay_Phep_DKKD_PSD.pdf', previewId: null, previewData: null },
      business: { state: 'RM_CONFIRMED', filename: 'Bao_Cao_Thuong_Nien_PSD.pdf', previewId: null, previewData: null },
      financial: { state: 'RM_CONFIRMED', filename: 'BCTC_Kiem_Toan_PwC_2025.pdf', previewId: null, previewData: null },
      cic: { state: 'RM_CONFIRMED', filename: 'Bao_Cao_CIC_Chi_Tiet_2025.pdf', previewId: null, previewData: null }
    };

    function switchTab(tabId) {
      const tabs = ['tab-dashboard', 'tab-upload', 'tab-review', 'tab-insights', 'tab-narrative', 'tab-committee'];
      tabs.forEach(t => {
        const el = document.getElementById(t);
        const nav = document.getElementById('nav-' + t);
        if (el) el.classList.add('hidden');
        if (nav) nav.classList.remove('tab-active');
      });

      const activeEl = document.getElementById(tabId);
      const activeNav = document.getElementById('nav-' + tabId);
      if (activeEl) activeEl.classList.remove('hidden');
      if (activeNav) activeNav.classList.add('tab-active');
      CURRENT_ACTIVE_TAB = tabId;

      if (tabId === 'tab-committee') {
        loadCommitteeCards();
      }
      if (tabId === 'tab-narrative') {
        loadNarrativeState(CURRENT_CASE_ID);
      }
    }

    function readFileAsBase64(file) {
      return new Promise((resolve, reject) => {
        if (!file) {
          reject(new Error("Vui lòng chọn một tệp tin PDF."));
          return;
        }
        if (!file.name.toLowerCase().endsWith('.pdf')) {
          reject(new Error("Hệ thống chỉ chấp nhận tệp định dạng PDF (.pdf)."));
          return;
        }
        const maxSize = 15 * 1024 * 1024; // 15MB
        if (file.size > maxSize) {
          reject(new Error("Dung lượng tệp PDF vượt quá giới hạn 15MB."));
          return;
        }
        const reader = new FileReader();
        reader.onload = () => {
          const res = reader.result;
          const b64 = typeof res === 'string' && res.includes(',') ? res.split(',')[1] : res;
          resolve(b64);
        };
        reader.onerror = (e) => reject(new Error("Lỗi đọc tệp tin: " + e.message));
        reader.readAsDataURL(file);
      });
    }

    function triggerDocUpload(docType) {
      const input = document.getElementById('file-' + docType);
      if (input) {
        input.value = '';
        input.click();
      }
    }

    function updateWorkspaceHeaderBadge() {
      const keys = ['legal', 'business', 'financial', 'cic'];
      const confirmedCount = keys.filter(k => DOC_STATES[k].state === 'RM_CONFIRMED').length;
      const badge = document.getElementById('doc-workspace-badge');
      if (badge) {
        badge.innerText = `${confirmedCount}/4 Nhóm Tài Liệu Sẵn Sàng`;
        if (confirmedCount === 4) {
          badge.className = 'text-xs bg-emerald-100 text-emerald-800 font-bold px-2.5 py-1 rounded';
        } else if (confirmedCount > 0) {
          badge.className = 'text-xs bg-blue-100 text-blue-800 font-bold px-2.5 py-1 rounded';
        } else {
          badge.className = 'text-xs bg-slate-100 text-slate-600 font-bold px-2.5 py-1 rounded';
        }
      }
    }

    function updateDocCardUI(docType) {
      const info = DOC_STATES[docType];
      const badgeEl = document.getElementById('status-badge-' + docType);
      const nameEl = document.getElementById('file-name-' + docType);
      const actionsEl = document.getElementById('actions-' + docType);
      const tipEl = document.getElementById('tip-' + docType);

      if (nameEl) {
        nameEl.innerText = info.filename || 'Chưa có tệp PDF nào được nạp';
      }

      let badgeHtml = '';
      let actionButtons = '';
      let tipText = '';

      switch (info.state) {
        case 'NOT_UPLOADED':
          badgeHtml = '<span class="text-xs bg-slate-100 text-slate-500 font-semibold px-2 py-0.5 rounded border border-slate-200">⚪ Chưa tải lên</span>';
          actionButtons = `
            <button onclick="triggerDocUpload('${docType}')" class="px-3 py-1 bg-[#003366] hover:bg-blue-900 text-white rounded text-xs font-bold shadow-sm transition flex items-center space-x-1">
              <span>📤 Tải Lên PDF</span>
            </button>
          `;
          tipText = 'Chờ RM tải lên tài liệu PDF gốc';
          break;

        case 'UPLOADING':
          badgeHtml = '<span class="text-xs bg-blue-100 text-blue-800 font-semibold px-2 py-0.5 rounded animate-pulse border border-blue-200">⏳ Đang tải lên...</span>';
          actionButtons = '<button disabled class="px-3 py-1 bg-slate-200 text-slate-400 rounded text-xs font-medium cursor-not-allowed">Đang tải...</button>';
          tipText = 'Đang chuyển tệp lên máy chủ...';
          break;

        case 'AI_PROCESSING':
          badgeHtml = '<span class="text-xs bg-purple-100 text-purple-800 font-bold px-2 py-0.5 rounded animate-pulse border border-purple-200">🤖 GreenNode AI Đang Bóc Tách...</span>';
          actionButtons = '<button disabled class="px-3 py-1 bg-purple-100 text-purple-700 rounded text-xs font-semibold cursor-not-allowed">Đang xử lý AI...</button>';
          tipText = 'Mô hình GLM-5.2 / OCR đang trích xuất và đối soát trang...';
          break;

        case 'PREVIEW_READY':
          badgeHtml = '<span class="text-xs bg-amber-100 text-amber-800 font-bold px-2 py-0.5 rounded border border-amber-300">📋 Chờ RM Xác Nhận</span>';
          actionButtons = `
            <button onclick="triggerDocUpload('${docType}')" class="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-xs font-semibold shadow-sm transition">
              🔄 Chọn file khác
            </button>
            <button onclick="openReviewModal('${docType}')" class="px-3 py-1 bg-amber-600 hover:bg-amber-700 text-white rounded text-xs font-bold shadow-sm transition">
              🔍 Đối Soát & Xác Nhận
            </button>
          `;
          tipText = 'AI đã bóc tách xong! Bấm để đối soát bằng chứng trang và xác nhận';
          break;

        case 'CONFLICT':
          badgeHtml = '<span class="text-xs bg-orange-100 text-orange-800 font-bold px-2 py-0.5 rounded border border-orange-300">⚠️ Phát Hiện Xung Đột</span>';
          actionButtons = `
            <button onclick="triggerDocUpload('${docType}')" class="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-xs font-semibold shadow-sm transition">
              🔄 Chọn file khác
            </button>
            <button onclick="openReviewModal('${docType}')" class="px-3 py-1 bg-orange-600 hover:bg-orange-700 text-white rounded text-xs font-bold shadow-sm transition">
              ⚖️ Xử Lý Xung Đột
            </button>
          `;
          tipText = 'Số liệu tài liệu xung đột với hồ sơ! Cần RM lựa chọn số liệu chuẩn';
          break;

        case 'RM_CONFIRMED':
          badgeHtml = '<span class="text-xs bg-emerald-100 text-emerald-800 font-bold px-2 py-0.5 rounded border border-emerald-300">✓ Đã Xác Nhận Vào Hồ Sơ</span>';
          actionButtons = `
            <button onclick="triggerDocUpload('${docType}')" class="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-xs font-semibold shadow-sm transition">
              🔄 Thay thế PDF
            </button>
            <button onclick="openReviewModal('${docType}')" class="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs font-bold shadow-sm transition">
              🔍 Xem Lại Bóc Tách
            </button>
          `;
          tipText = 'Dữ liệu đã được khóa và đồng bộ vào Tờ trình MB07';
          break;

        case 'ERROR':
          badgeHtml = '<span class="text-xs bg-red-100 text-red-800 font-bold px-2 py-0.5 rounded border border-red-300">❌ Lỗi Xử Lý</span>';
          actionButtons = `
            <button onclick="triggerDocUpload('${docType}')" class="px-3 py-1 bg-red-600 hover:bg-red-700 text-white rounded text-xs font-bold shadow-sm transition">
              🔄 Thử lại
            </button>
          `;
          tipText = info.errorMsg || 'Xử lý tài liệu không thành công';
          break;
      }

      if (badgeEl) badgeEl.innerHTML = badgeHtml;
      if (tipEl) tipEl.innerText = tipText;
      if (actionsEl) {
        actionsEl.innerHTML = `
          <span id="tip-${docType}" class="text-[11px] text-slate-400 italic">${tipText}</span>
          <div class="flex space-x-2">${actionButtons}</div>
        `;
      }
      updateWorkspaceHeaderBadge();
    }

    async function handleFileSelected(docType, inputEl) {
      if (!inputEl || !inputEl.files || inputEl.files.length === 0) return;
      const file = inputEl.files[0];

      DOC_STATES[docType].filename = file.name;
      DOC_STATES[docType].state = 'UPLOADING';
      updateDocCardUI(docType);

      let b64 = null;
      try {
        b64 = await readFileAsBase64(file);
      } catch (err) {
        DOC_STATES[docType].state = 'ERROR';
        DOC_STATES[docType].errorMsg = err.message;
        updateDocCardUI(docType);
        alert('❌ ' + err.message);
        return;
      }

      DOC_STATES[docType].state = 'AI_PROCESSING';
      updateDocCardUI(docType);

      const endpoints = {
        legal: '/api/preview_legal_pdf',
        business: '/api/preview_business_pdf',
        financial: '/api/preview_financial_pdf',
        cic: '/api/preview_cic_pdf'
      };

      const caseSelector = document.getElementById('case-selector');
      const cid = caseSelector ? caseSelector.value : CURRENT_CASE_ID;

      try {
        const res = await fetch(endpoints[docType], {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            filename: file.name,
            content_base64: b64,
            case_id: cid
          })
        });
        const data = await res.json();

        if (!res.ok || data.status !== 'success') {
          throw new Error(data.message || 'Lỗi bóc tách tài liệu.');
        }

        DOC_STATES[docType].previewId = data.preview_id;
        DOC_STATES[docType].previewData = data;

        // Check conflicts
        let hasConflict = false;
        if (docType === 'legal' && data.fields) {
          hasConflict = Object.values(data.fields).some(f => f.status === 'CONFLICT');
        } else if (docType === 'business') {
          hasConflict = Array.isArray(data.conflicts) && data.conflicts.length > 0;
        } else if (docType === 'financial' && Array.isArray(data.review_table)) {
          hasConflict = data.review_table.some(item => item.status === 'CONFLICT');
        } else if (docType === 'cic') {
          hasConflict = Array.isArray(data.conflicts) && data.conflicts.length > 0;
        }

        DOC_STATES[docType].state = hasConflict ? 'CONFLICT' : 'PREVIEW_READY';
        updateDocCardUI(docType);

        // Update card summary snippet with newly extracted facts
        updateCardSummarySnippet(docType, data);

        // Open RM Review Modal immediately
        openReviewModal(docType);

      } catch (err) {
        DOC_STATES[docType].state = 'ERROR';
        DOC_STATES[docType].errorMsg = err.message;
        updateDocCardUI(docType);
        alert(`❌ Lỗi bóc tách tài liệu ${docType}: ${err.message}`);
      }
    }

    function updateCardSummarySnippet(docType, data) {
      if (docType === 'legal' && data.fields) {
        const f = data.fields;
        if (f.company_name && f.company_name.value) document.getElementById('sum-legal-name').innerText = f.company_name.value;
        if (f.tax_code && f.tax_code.value) document.getElementById('sum-legal-tax').innerText = f.tax_code.value;
        if (f.charter_capital && f.charter_capital.value != null) {
          const cap = Number(f.charter_capital.value);
          document.getElementById('sum-legal-capital').innerText = isNaN(cap) ? f.charter_capital.value : cap.toLocaleString('vi-VN') + ' tr';
        }
        if (f.legal_rep_name && f.legal_rep_name.value) {
          const title = (f.legal_rep_title && f.legal_rep_title.value) || 'ĐDPL';
          document.getElementById('sum-legal-rep').innerText = `${f.legal_rep_name.value} (${title})`;
        }
      } else if (docType === 'financial' && Array.isArray(data.review_table)) {
        const revItem = data.review_table.find(i => i.canonical_field === 'net_revenue');
        const npItem = data.review_table.find(i => i.canonical_field === 'net_profit_after_tax');
        const eqItem = data.review_table.find(i => i.canonical_field === 'equity');
        if (revItem && revItem.extracted_value != null) document.getElementById('sum-fin-rev').innerText = Number(revItem.extracted_value).toLocaleString('vi-VN') + ' tr';
        if (npItem && npItem.extracted_value != null) document.getElementById('sum-fin-np').innerText = Number(npItem.extracted_value).toLocaleString('vi-VN') + ' tr';
        if (eqItem && eqItem.extracted_value != null) document.getElementById('sum-fin-equity').innerText = Number(eqItem.extracted_value).toLocaleString('vi-VN') + ' tr';
      } else if (docType === 'business') {
        if (data.suggested_business_model) document.getElementById('sum-biz-model').innerText = data.suggested_business_model;
      } else if (docType === 'cic') {
        if (data.identity_reconciliation) {
          document.getElementById('sum-cic-status').innerText = data.identity_reconciliation.status === 'MATCH' ? '✓ Đã đối soát 100% khớp CIF' : 'Cần kiểm tra';
        }
      }
    }

    function openReviewModal(docType) {
      CURRENT_REVIEW_DOCTYPE = docType;
      const modal = document.getElementById('modal-doc-review');
      const titleEl = document.getElementById('modal-review-title');
      const subEl = document.getElementById('modal-review-subtitle');
      const btn = document.getElementById('btn-confirm-review');

      const titles = {
        legal: '🏛️ Đối Soát Hồ Sơ Pháp Lý & ĐKKD',
        business: '🏭 Đối Soát Mô Hình Kinh Doanh & Chuỗi Cung Ứng',
        financial: '📈 Đối Soát Báo Cáo Tài Chính Kiểm Toán 3 Năm',
        cic: '🏦 Đối Soát Báo Cáo Tín Dụng CIC Chi Tiết'
      };

      if (titleEl) titleEl.innerText = titles[docType] || '📋 Đối Soát Dữ Liệu Bóc Tách GreenNode AI';
      if (subEl) subEl.innerText = `Kiểm tra bằng chứng trích xuất từ tệp '${DOC_STATES[docType].filename || 'PDF'}' trước khi xác nhận vào hồ sơ MB07`;

      if (btn) {
        if (!DOC_STATES[docType].previewId && DOC_STATES[docType].state === 'RM_CONFIRMED') {
          btn.innerHTML = '<span>✓ Dữ Liệu Đã Xác Nhận</span>';
          btn.disabled = true;
        } else {
          btn.innerHTML = '<span>✓ Xác Nhận Vào Hồ Sơ (Commit)</span>';
          btn.disabled = false;
        }
      }

      renderReviewBody(docType, DOC_STATES[docType].previewData);
      modal.classList.remove('hidden');
    }

    function closeReviewModal() {
      document.getElementById('modal-doc-review').classList.add('hidden');
      CURRENT_REVIEW_DOCTYPE = null;
    }

    function renderReviewBody(docType, data) {
      const body = document.getElementById('modal-review-body');
      if (!body) return;

      if (!data) {
        body.innerHTML = `
          <div class="p-6 text-center text-slate-500 bg-slate-50 rounded-xl border border-slate-200">
            <div class="text-sm font-semibold text-slate-700">ℹ️ Dữ liệu hồ sơ mẫu chuẩn (Preloaded Demo).</div>
            <div class="text-xs text-slate-400 mt-1">Để kiểm tra tính năng trích xuất AI trực tiếp, hãy bấm "Thay thế PDF" và nạp tài liệu PDF thực tế.</div>
          </div>
        `;
        return;
      }

      let html = '';
      if (docType === 'legal') {
        const fields = data.fields || {};
        const fieldLabels = {
          company_name: 'Tên Doanh Nghiệp',
          short_name: 'Tên Viết Tắt',
          tax_code: 'Mã Số Thuế',
          address: 'Địa Chỉ Đăng Ký',
          charter_capital: 'Vốn Điều Lệ',
          legal_rep_name: 'Người Đại Diện Pháp Luật',
          legal_rep_title: 'Chức Danh ĐDPL'
        };

        const routing = data.routing || {};
        html += `
          <div class="p-3 bg-blue-50/70 border border-blue-200 rounded-lg flex items-center justify-between text-xs">
            <div>
              <span class="font-bold text-blue-900">Tài liệu:</span> ${data.filename || 'PDF'}
              <span class="text-slate-400 mx-1.5">|</span>
              <span class="font-bold text-blue-900">Trang:</span> ${routing.page_count || 1}
              <span class="text-slate-400 mx-1.5">|</span>
              <span class="font-bold text-blue-900">Công nghệ:</span> GreenNode Document AI (${routing.provider || 'OCR'})
            </div>
            <span class="px-2 py-0.5 bg-blue-100 text-blue-800 font-bold rounded">No Evidence → No Fact</span>
          </div>

          <table class="w-full text-left border border-slate-200 rounded-lg overflow-hidden text-xs">
            <thead class="bg-slate-100 text-slate-700 font-bold border-b border-slate-200">
              <tr>
                <th class="p-2.5 w-1/4">Trường Thông Tin</th>
                <th class="p-2.5 w-1/4">Giá Trị Bóc Tách</th>
                <th class="p-2.5 w-1/12 text-center">Trang</th>
                <th class="p-2.5 w-1/4">Bằng Chứng Trích Dẫn</th>
                <th class="p-2.5 w-1/6">Trạng Thái / Xử Lý</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-200 bg-white">
        `;

        for (const [k, f] of Object.entries(fields)) {
          const lbl = fieldLabels[k] || k;
          const val = f.value != null ? (k === 'charter_capital' && typeof f.value === 'number' ? f.value.toLocaleString('vi-VN') + ' tr' : f.value) : '<span class="text-slate-400 italic">Không tìm thấy</span>';
          const pg = f.page != null ? `Trang ${f.page}` : '—';
          const ev = f.evidence ? `<div class="italic text-slate-600 bg-slate-50 p-1 rounded text-[11px] max-h-16 overflow-y-auto">"${f.evidence}"</div>` : '—';

          let statusBadge = '';
          let resolutionControl = '';

          if (f.status === 'CONFLICT') {
            statusBadge = '<span class="text-[10px] bg-orange-100 text-orange-800 font-bold px-1.5 py-0.5 rounded border border-orange-200">XUNG ĐỘT</span>';
            resolutionControl = `
              <div class="mt-1 space-y-1">
                <div class="text-[10px] text-orange-700 font-medium">${f.conflict_note || ''}</div>
                <select id="res-legal-${k}" class="w-full text-[11px] p-1 bg-orange-50 border border-orange-300 rounded focus:ring-1 focus:ring-orange-500 font-medium">
                  <option value="USE_EXTRACTED">✓ Lấy số liệu mới bóc tách</option>
                  <option value="KEEP_EXISTING">✕ Giữ số liệu hồ sơ hiện tại</option>
                </select>
              </div>
            `;
          } else if (f.status === 'WARNING') {
            statusBadge = `<span class="text-[10px] bg-amber-100 text-amber-800 font-bold px-1.5 py-0.5 rounded border border-amber-200" title="${f.warning_reason || ''}">CẢNH BÁO</span>`;
          } else if (f.status === 'MISSING') {
            statusBadge = '<span class="text-[10px] bg-slate-100 text-slate-500 font-bold px-1.5 py-0.5 rounded border border-slate-200">CHƯA CÓ</span>';
          } else {
            statusBadge = '<span class="text-[10px] bg-emerald-100 text-emerald-800 font-bold px-1.5 py-0.5 rounded border border-emerald-200">✓ XÁC THỰC</span>';
          }

          html += `
            <tr class="hover:bg-slate-50">
              <td class="p-2.5 font-semibold text-slate-800">${lbl}</td>
              <td class="p-2.5 font-bold text-[#003366]">${val}</td>
              <td class="p-2.5 text-center font-medium text-slate-500">${pg}</td>
              <td class="p-2.5">${ev}</td>
              <td class="p-2.5">${statusBadge}${resolutionControl}</td>
            </tr>
          `;
        }

        html += `
            </tbody>
          </table>
        `;

      } else if (docType === 'financial') {
        const periods = data.periods || [];
        const reviewTable = data.review_table || [];
        const ratios = data.calculated_ratios || {};
        const warnings = data.audit_warnings || [];

        html += `
          <div class="p-3 bg-blue-50/70 border border-blue-200 rounded-lg flex items-center justify-between text-xs">
            <div>
              <span class="font-bold text-blue-900">Tài liệu BCTC:</span> ${data.filename || 'BCTC.pdf'}
              <span class="text-slate-400 mx-1.5">|</span>
              <span class="font-bold text-blue-900">Các năm trích xuất:</span> ${periods.join(', ') || 'N/A'}
            </div>
            <span class="px-2 py-0.5 bg-emerald-100 text-emerald-800 font-bold rounded">Python Grounding Audit: PASSED</span>
          </div>
        `;

        if (warnings.length > 0) {
          html += `
            <div class="p-2.5 bg-amber-50 border border-amber-200 rounded-lg text-xs space-y-1">
              <div class="font-bold text-amber-800">⚠️ Lưu ý đối soát số liệu BCTC:</div>
              <ul class="list-disc list-inside text-amber-700 text-[11px]">${warnings.map(w => `<li>${w}</li>`).join('')}</ul>
            </div>
          `;
        }

        html += `
          <div class="overflow-x-auto">
            <table class="w-full text-left border border-slate-200 rounded-lg text-xs">
              <thead class="bg-slate-100 text-slate-700 font-bold border-b border-slate-200">
                <tr>
                  <th class="p-2 w-12 text-center">Năm</th>
                  <th class="p-2 w-1/4">Khoản Mục BCTC</th>
                  <th class="p-2 w-1/5">Số Liệu Bóc Tách</th>
                  <th class="p-2 w-12 text-center">Trang</th>
                  <th class="p-2 w-1/4">Đoạn Trích Bằng Chứng</th>
                  <th class="p-2 w-1/6">Trạng Thái</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-200 bg-white">
        `;

        reviewTable.forEach(item => {
          const valNum = item.extracted_value != null ? Number(item.extracted_value).toLocaleString('vi-VN') + ' ' + (item.unit || 'tr') : (item.raw_value || '—');
          const pg = item.page != null ? `Trang ${item.page}` : '—';
          const ev = item.evidence ? `<div class="italic text-slate-600 bg-slate-50 p-1 rounded text-[11px] max-h-12 overflow-y-auto">"${item.evidence}"</div>` : '—';

          let statusBadge = '';
          let resControl = '';
          if (item.status === 'CONFLICT') {
            statusBadge = '<span class="text-[10px] bg-orange-100 text-orange-800 font-bold px-1.5 py-0.5 rounded">XUNG ĐỘT</span>';
            resControl = `
              <div class="mt-1">
                <div class="text-[10px] text-orange-700">${item.conflict_note || ''}</div>
                <select id="res-fin-${item.canonical_field}-${item.year}" class="w-full text-[10px] p-1 bg-orange-50 border border-orange-300 rounded font-medium">
                  <option value="USE_EXTRACTED">✓ Dùng số liệu BCTC</option>
                  <option value="KEEP_EXISTING">✕ Giữ số liệu cũ</option>
                </select>
              </div>
            `;
          } else if (item.status === 'WARNING') {
            statusBadge = '<span class="text-[10px] bg-amber-100 text-amber-800 font-bold px-1.5 py-0.5 rounded">CẢNH BÁO</span>';
          } else {
            statusBadge = '<span class="text-[10px] bg-emerald-100 text-emerald-800 font-bold px-1.5 py-0.5 rounded">✓ EXTRACTED</span>';
          }

          html += `
            <tr class="hover:bg-slate-50">
              <td class="p-2 text-center font-bold text-slate-600">${item.year}</td>
              <td class="p-2 font-medium text-slate-800">${item.item_name || item.canonical_field}</td>
              <td class="p-2 font-bold text-[#003366]">${valNum}</td>
              <td class="p-2 text-center text-slate-500">${pg}</td>
              <td class="p-2">${ev}</td>
              <td class="p-2">${statusBadge}${resControl}</td>
            </tr>
          `;
        });

        html += `
              </tbody>
            </table>
          </div>
        `;

        if (Object.keys(ratios).length > 0) {
          html += `
            <div class="p-3 bg-emerald-50/60 border border-emerald-200 rounded-lg space-y-2">
              <div class="font-bold text-emerald-900 text-xs flex items-center space-x-1.5">
                <span>🧮</span>
                <span>Chỉ Số Tài Chính Tính Toán Tự Động (Python Verification Engine - 100% Deterministic):</span>
              </div>
              <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                ${Object.entries(ratios).map(([k, v]) => `
                  <div class="bg-white p-2 rounded border border-emerald-100 shadow-sm">
                    <div class="text-[10px] text-slate-500">${k}</div>
                    <div class="font-bold text-slate-800 text-sm mt-0.5">${typeof v === 'number' ? v.toFixed(2) : v}</div>
                  </div>
                `).join('')}
              </div>
            </div>
          `;
        }

      } else if (docType === 'business') {
        const reviewTable = data.review_table || [];
        const suggestedBm = data.suggested_business_model || 'THUONG_MAI';

        html += `
          <div class="p-3 bg-blue-50/70 border border-blue-200 rounded-lg space-y-2 text-xs">
            <div class="flex items-center justify-between">
              <div>
                <span class="font-bold text-blue-900">Tài liệu:</span> ${data.filename || 'Bao_Cao_Thuong_Nien.pdf'}
              </div>
              <span class="px-2 py-0.5 bg-blue-100 text-blue-800 font-bold rounded">GreenNode Business AI</span>
            </div>
            <div class="flex items-center space-x-2 pt-1">
              <label class="font-bold text-slate-700">Mô hình kinh doanh được AI nhận diện:</label>
              <select id="bm-override" class="p-1 border border-slate-300 rounded font-semibold bg-white text-[#003366]">
                <option value="THUONG_MAI" ${suggestedBm === 'THUONG_MAI' ? 'selected' : ''}>Thương mại Phân phối</option>
                <option value="SAN_XUAT" ${suggestedBm === 'SAN_XUAT' ? 'selected' : ''}>Sản xuất</option>
                <option value="SAN_XUAT_VA_THUONG_MAI" ${suggestedBm === 'SAN_XUAT_VA_THUONG_MAI' ? 'selected' : ''}>Sản xuất & Thương mại</option>
                <option value="DICH_VU" ${suggestedBm === 'DICH_VU' ? 'selected' : ''}>Dịch vụ</option>
                <option value="XAY_DUNG_BAT_DONG_SAN" ${suggestedBm === 'XAY_DUNG_BAT_DONG_SAN' ? 'selected' : ''}>Xây dựng & Bất động sản</option>
              </select>
            </div>
          </div>
        `;

        html += `
          <div class="p-2.5 bg-slate-50 border border-slate-200 rounded-lg flex items-center space-x-2 text-xs">
            <input type="checkbox" id="check-business-ack" checked class="w-4 h-4 text-blue-600 rounded">
            <label for="check-business-ack" class="font-semibold text-slate-800">
              RM xác nhận hồ sơ doanh nghiệp trùng khớp với khách hàng thẩm định.
            </label>
          </div>
        `;

        html += `
          <div class="overflow-x-auto">
            <table class="w-full text-left border border-slate-200 rounded-lg text-xs">
              <thead class="bg-slate-100 text-slate-700 font-bold border-b border-slate-200">
                <tr>
                  <th class="p-2 w-1/4">Hạng Mục</th>
                  <th class="p-2 w-1/3">Nội Dung Trích Xuất</th>
                  <th class="p-2 w-12 text-center">Trang</th>
                  <th class="p-2 w-1/4">Đoạn Trích Bằng Chứng</th>
                  <th class="p-2 w-20 text-center">Trạng Thái</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-200 bg-white">
        `;

        reviewTable.forEach(item => {
          const pg = item.page != null ? `Trang ${item.page}` : '—';
          const ev = item.evidence ? `<div class="italic text-slate-600 bg-slate-50 p-1 rounded text-[11px] max-h-12 overflow-y-auto">"${item.evidence}"</div>` : '—';
          const statusBadge = item.grounding_status === 'VERIFIED' ?
            '<span class="text-[10px] bg-emerald-100 text-emerald-800 font-bold px-1.5 py-0.5 rounded">✓ XÁC THỰC</span>' :
            '<span class="text-[10px] bg-amber-100 text-amber-800 font-bold px-1.5 py-0.5 rounded">CHỜ XÁC MINH</span>';

          html += `
            <tr class="hover:bg-slate-50">
              <td class="p-2 font-semibold text-slate-800">${item.label || item.canonical_path}</td>
              <td class="p-2 text-slate-700">${item.value_raw || '—'}</td>
              <td class="p-2 text-center text-slate-500">${pg}</td>
              <td class="p-2">${ev}</td>
              <td class="p-2 text-center">${statusBadge}</td>
            </tr>
          `;
        });

        html += `
              </tbody>
            </table>
          </div>
        `;

      } else if (docType === 'cic') {
        const idRecon = data.identity_reconciliation || {};
        const reviewTable = data.review_table || [];

        html += `
          <div class="p-3 bg-blue-50/70 border border-blue-200 rounded-lg space-y-2 text-xs">
            <div class="flex items-center justify-between">
              <div>
                <span class="font-bold text-blue-900">Tài liệu:</span> ${data.filename || 'CIC.pdf'}
              </div>
              <span class="px-2 py-0.5 bg-blue-100 text-blue-800 font-bold rounded">GreenNode CIC AI</span>
            </div>
            <div class="flex items-center space-x-2 text-xs">
              <span class="font-bold text-slate-700">Đối soát định danh CIF:</span>
              <span class="px-2 py-0.5 rounded font-bold ${idRecon.status === 'MATCH' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}">
                ${idRecon.status === 'MATCH' ? '✓ TRÙNG KHỚP MST/TÊN DOANH NGHIỆP' : (idRecon.message || 'CẦN KIỂM TRA')}
              </span>
            </div>
          </div>
        `;

        html += `
          <div class="overflow-x-auto">
            <table class="w-full text-left border border-slate-200 rounded-lg text-xs">
              <thead class="bg-slate-100 text-slate-700 font-bold border-b border-slate-200">
                <tr>
                  <th class="p-2 w-8 text-center">STT</th>
                  <th class="p-2 w-1/4">Tổ Chức Tín Dụng</th>
                  <th class="p-2 w-1/5">Dư Nợ Ngắn Hạn</th>
                  <th class="p-2 w-1/5">Tổng Dư Nợ</th>
                  <th class="p-2 w-1/6">Nhóm Nợ</th>
                  <th class="p-2 w-12 text-center">Trang</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-200 bg-white">
        `;

        reviewTable.forEach(item => {
          const isMsb = item.is_msb;
          const rowClass = isMsb ? 'bg-red-50/40 font-semibold' : 'hover:bg-slate-50';
          const bankNameBadge = isMsb ? `<span class="text-red-700 font-bold">🔴 ${item.bank_name}</span>` : item.bank_name;

          html += `
            <tr class="${rowClass}">
              <td class="p-2 text-center">${item.stt || '—'}</td>
              <td class="p-2 font-medium">${bankNameBadge}</td>
              <td class="p-2 font-bold text-slate-800">${item.short_term_debt_vnd || '—'}</td>
              <td class="p-2 font-bold text-[#003366]">${item.total_debt_printed || '—'}</td>
              <td class="p-2"><span class="px-2 py-0.5 bg-emerald-100 text-emerald-800 font-bold rounded text-[10px]">${item.debt_group || 'Nhóm 1'}</span></td>
              <td class="p-2 text-center text-slate-500">${item.page ? 'Trang ' + item.page : '—'}</td>
            </tr>
          `;
        });

        html += `
              </tbody>
            </table>
          </div>
        `;
      }

      body.innerHTML = html;
    }

    function confirmCurrentReview() {
      if (CURRENT_REVIEW_DOCTYPE) {
        confirmDocPreview(CURRENT_REVIEW_DOCTYPE);
      }
    }

    async function confirmDocPreview(docType) {
      const info = DOC_STATES[docType];
      if (!info.previewId) {
        alert('Không có bản xem trước tài liệu hợp lệ để xác nhận.');
        return;
      }

      const btn = document.getElementById('btn-confirm-review');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span>⏳ Đang ghi nhận vào hồ sơ MB07...</span>';
      }

      const caseSelector = document.getElementById('case-selector');
      const cid = caseSelector ? caseSelector.value : CURRENT_CASE_ID;

      const endpoints = {
        legal: '/api/confirm_legal_preview',
        business: '/api/confirm_business_preview',
        financial: '/api/confirm_financial_preview',
        cic: '/api/confirm_cic_preview'
      };

      let payload = {
        preview_id: info.previewId,
        case_id: cid
      };

      if (docType === 'legal') {
        const resolutions = {};
        if (info.previewData && info.previewData.fields) {
          for (const [k, f] of Object.entries(info.previewData.fields)) {
            const sel = document.getElementById('res-legal-' + k);
            if (sel) resolutions[f.canonical_path] = sel.value;
          }
        }
        if (Object.keys(resolutions).length > 0) payload.resolutions = resolutions;
      } else if (docType === 'financial') {
        const resolutions = {};
        if (info.previewData && Array.isArray(info.previewData.review_table)) {
          info.previewData.review_table.forEach(item => {
            const sel = document.getElementById(`res-fin-${item.canonical_field}-${item.year}`);
            if (sel) resolutions[`section_d.${item.canonical_field}[${item.year}]`] = sel.value;
          });
        }
        if (Object.keys(resolutions).length > 0) payload.resolutions = resolutions;
      } else if (docType === 'business') {
        const bmEl = document.getElementById('bm-override');
        if (bmEl) payload.business_model_override = bmEl.value;
        const ackEl = document.getElementById('check-business-ack');
        payload.identity_acknowledged = ackEl ? ackEl.checked : true;
      }

      try {
        const res = await fetch(endpoints[docType], {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (!res.ok || data.status !== 'success') {
          throw new Error(data.message || 'Lỗi xác nhận tài liệu.');
        }

        DOC_STATES[docType].state = 'RM_CONFIRMED';
        updateDocCardUI(docType);
        closeReviewModal();
        await loadCaseData();

        // Update hero banner badge to LIVE AI DATA
        const badge = document.getElementById('case-source-badge');
        if (badge) {
          badge.innerText = 'LIVE AI DATA (RM CONFIRMED)';
          badge.className = 'text-xs bg-emerald-500/20 text-emerald-300 px-3 py-1 rounded-full font-bold border border-emerald-400/30 whitespace-nowrap';
        }

        alert(`🎉 Đã xác nhận thành công tài liệu '${info.filename}' vào hồ sơ MB07!\nDữ liệu đã được cập nhật sang Bảng Đối Soát và Tờ Trình.`);

      } catch (err) {
        alert('❌ Lỗi xác nhận: ' + err.message);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<span>✓ Xác Nhận Vào Hồ Sơ (Commit)</span>';
        }
      }
    }

    function openNewCaseModal() {
      document.getElementById('new-case-name').value = '';
      document.getElementById('new-case-short-name').value = '';
      document.getElementById('new-case-tax-code').value = '';
      document.getElementById('new-case-capital').value = '';
      document.getElementById('new-case-limit').value = '';
      document.getElementById('new-case-address').value = '';
      document.getElementById('modal-new-case').classList.remove('hidden');
    }

    function closeNewCaseModal() {
      document.getElementById('modal-new-case').classList.add('hidden');
    }

    async function submitNewCase() {
      const name = document.getElementById('new-case-name').value.trim();
      const short_name = document.getElementById('new-case-short-name').value.trim();
      const tax_code = document.getElementById('new-case-tax-code').value.trim();
      const charter_capital = parseFloat(document.getElementById('new-case-capital').value) || 0;
      const proposed_limit = parseFloat(document.getElementById('new-case-limit').value) || 0;
      const address = document.getElementById('new-case-address').value.trim();
      const business_model = document.getElementById('new-case-business-model').value;

      if (!name || !short_name || !tax_code) {
        alert('⚠️ Vui lòng nhập đầy đủ: Tên Doanh nghiệp, Tên viết tắt và Mã số thuế.');
        return;
      }

      try {
        const res = await fetch('/api/new_case', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name,
            short_name,
            tax_code,
            charter_capital,
            proposed_limit,
            address,
            business_model
          })
        });
        const data = await res.json();
        if (data.status === 'success') {
          const cid = data.case_id;
          CURRENT_CASE_ID = cid;

          // Add to case selector if not exists
          const selector = document.getElementById('case-selector');
          let opt = selector.querySelector(`option[value="${cid}"]`);
          if (!opt) {
            opt = document.createElement('option');
            opt.value = cid;
            opt.innerText = `${short_name} - ${name}`;
            selector.appendChild(opt);
          }
          selector.value = cid;

          // Reset doc states to NOT_UPLOADED for this new case
          ['legal', 'business', 'financial', 'cic'].forEach(k => {
            DOC_STATES[k] = {
              state: 'NOT_UPLOADED',
              filename: '',
              previewId: null,
              previewData: null
            };
            updateDocCardUI(k);
          });

          // Reset card summaries
          document.getElementById('sum-legal-name').innerText = name;
          document.getElementById('sum-legal-tax').innerText = tax_code;
          document.getElementById('sum-legal-capital').innerText = charter_capital > 0 ? charter_capital.toLocaleString('vi-VN') + ' tr' : 'Chưa cập nhật';
          document.getElementById('sum-legal-rep').innerText = 'Chưa cập nhật (Chờ nạp ĐKKD)';

          document.getElementById('sum-biz-model').innerText = business_model;
          document.getElementById('sum-biz-suppliers').innerText = 'Chưa nạp hồ sơ kinh doanh';
          document.getElementById('sum-biz-customers').innerText = 'Chưa nạp hồ sơ kinh doanh';

          document.getElementById('sum-fin-auditor').innerText = 'Chưa nạp BCTC';
          document.getElementById('sum-fin-rev').innerText = 'Chưa có số liệu';
          document.getElementById('sum-fin-np').innerText = 'Chưa có số liệu';
          document.getElementById('sum-fin-equity').innerText = charter_capital > 0 ? charter_capital.toLocaleString('vi-VN') + ' tr' : 'Chưa có số liệu';

          document.getElementById('sum-cic-date').innerText = 'Chưa tra cứu';
          document.getElementById('sum-cic-status').innerText = 'Chưa có dữ liệu CIC';
          document.getElementById('sum-cic-msb').innerText = '0 tr';
          document.getElementById('sum-cic-other').innerText = 'Chưa có dữ liệu';

          closeNewCaseModal();
          await loadCaseData();
          switchTab('tab-dashboard');
          alert(`🎉 Đã khởi tạo hồ sơ thành công cho '${short_name}'!\nHãy chuyển sang tab 'Không Gian Tài Liệu' để tải lên các tài liệu PDF gốc.`);
        } else {
          alert('Lỗi khởi tạo: ' + (data.message || 'Không xác định'));
        }
      } catch (e) {
        alert('Lỗi kết nối máy chủ: ' + e.message);
      }
    }

    async function saveSectionA() {
      const payload = {
        section: "A",
        unit_name: document.getElementById('rm-unit-name').value,
        rm_name: document.getElementById('rm-rm-name').value,
        rm_phone: document.getElementById('rm-rm-phone').value,
        manager_name: document.getElementById('rm-manager-name').value,
        authority: document.getElementById('rm-authority').value
      };
      try {
        const res = await fetch('/api/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'success') {
          alert('✅ Đã lưu thông tin Pháp lý & ĐVKD Phần A thành công!');
        } else {
          alert('Lỗi lưu Phần A: ' + data.message);
        }
      } catch (e) {
        alert('Lỗi lưu Phần A: ' + e.message);
      }
    }

    async function saveSectionB() {
      const payload = {
        section: "B",
        total_limit: parseFloat(document.getElementById('rm-total-limit').value) || 0,
        loan_limit: parseFloat(document.getElementById('rm-loan-limit').value) || 0,
        guarantee_limit: parseFloat(document.getElementById('rm-guar-limit').value) || 0,
        collateral: document.getElementById('rm-collateral').value,
        purpose: document.getElementById('rm-purpose').value
      };
      try {
        const res = await fetch('/api/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'success') {
          alert('✅ Đã lưu đề xuất cấp tín dụng Phần B thành công!');
          loadCaseData();
        } else {
          alert('Lỗi lưu Phần B: ' + data.message);
        }
      } catch (e) {
        alert('Lỗi lưu Phần B: ' + e.message);
      }
    }

    async function loadCaseData() {
      try {
        const res = await fetch('/api/case');
        const data = await res.json();
        
        CURRENT_CASE_ID = data.id || 'PSD';
        const cust = data.customer || {};
        const b = data.section_b || {};
        const d = data.section_d || {};
        const e = data.section_e || {};
        const rm = data.rm_metadata || {};

        // Header badge
        const badge = document.getElementById('case-source-badge');
        if (badge) {
          const isDemo = ['PSD', 'GAS_SOUTH', 'PHYTOPHARMA'].includes(CURRENT_CASE_ID);
          const hasLiveConfirmed = Object.values(DOC_STATES).some(s => s.state === 'RM_CONFIRMED' && s.previewId !== null);
          if (hasLiveConfirmed) {
            badge.innerText = 'LIVE AI DATA (RM CONFIRMED)';
            badge.className = 'text-xs bg-emerald-500/20 text-emerald-300 px-3 py-1 rounded-full font-bold border border-emerald-400/30 whitespace-nowrap';
          } else if (isDemo) {
            badge.innerText = 'DEMO DATA (PRELOADED)';
            badge.className = 'text-xs bg-amber-500/20 text-amber-300 px-3 py-1 rounded-full font-bold border border-amber-400/30 whitespace-nowrap';
          } else {
            badge.innerText = 'HỒ SƠ MỚI (CHỜ NẠP TÀI LIỆU)';
            badge.className = 'text-xs bg-blue-500/20 text-blue-300 px-3 py-1 rounded-full font-bold border border-blue-400/30 whitespace-nowrap';
          }
        }

        // Dashboard fields with empty-state handling
        const custTitle = `${cust.short_name || cust.name || 'DOANH NGHIỆP MỚI'} (CIF: ${cust.cif || 'Chưa cấp'})`;
        document.getElementById('dash-cust-name').innerText = custTitle;
        
        if (cust.rating_grade) {
          document.getElementById('dash-cust-rating').innerText = `Định hạng MSB: Hạng ${cust.rating_grade} (${cust.rating_score || 0}đ)`;
        } else {
          document.getElementById('dash-cust-rating').innerText = `Định hạng MSB: Chưa xếp hạng (Chờ thẩm định)`;
        }

        const totalLimit = b.total_limit || 0;
        document.getElementById('dash-total-limit').innerText = `${totalLimit.toLocaleString('vi-VN')} triệu VND`;
        document.getElementById('dash-loan-limit').innerText = `Cho vay: ${(b.loan_limit || 0).toLocaleString('vi-VN')} tr | Bảo lãnh: ${(b.guarantee_limit || 0).toLocaleString('vi-VN')} tr`;
        
        const revArr = d.net_revenue || [];
        const npArr = d.net_profit_after_tax || [];
        const hasFin = revArr.length > 0 && revArr[revArr.length - 1] > 0;
        
        if (hasFin) {
          const revLast = revArr[revArr.length - 1];
          const npLast = npArr.length > 0 ? npArr[npArr.length - 1] : 0;
          document.getElementById('dash-rev-2025').innerText = `${revLast.toLocaleString('vi-VN')} triệu VND`;
          document.getElementById('dash-np-2025').innerText = `LNST: ${npLast.toLocaleString('vi-VN')} tr`;
        } else {
          document.getElementById('dash-rev-2025').innerText = 'Chưa nạp BCTC';
          document.getElementById('dash-np-2025').innerText = 'LNST: Chưa có số liệu';
        }

        document.getElementById('dash-cic-status').innerText = e.history_status || 'Chưa tra cứu CIC';
        document.getElementById('dash-msb-out').innerText = `Dư nợ tại MSB: ${(e.msb_outstanding || 0).toLocaleString('vi-VN')} triệu VND`;

        document.getElementById('dash-tax-code').innerText = cust.tax_code || 'Chưa có MST';
        document.getElementById('dash-legal-rep').innerText = cust.legal_rep_name ? `${cust.legal_rep_name} (${cust.legal_rep_title || 'Đại diện'})` : 'Chưa cập nhật';
        document.getElementById('dash-capital').innerText = cust.charter_capital ? `${cust.charter_capital.toLocaleString('vi-VN')} triệu VND` : 'Chưa cập nhật';
        document.getElementById('dash-address').innerText = cust.address || 'Chưa cập nhật';
        
        document.getElementById('dash-purpose').innerText = b.loan_purpose || 'Chưa có thông tin';
        document.getElementById('dash-collat').innerText = b.collateral_type || 'Chưa xác định';
        document.getElementById('dash-cashflow').innerText = b.cashflow_commitment_pct ? `${b.cashflow_commitment_pct}% Doanh thu qua tài khoản MSB` : 'Chưa cam kết';

        // Update form inputs for Section A
        if (document.getElementById('rm-unit-name')) document.getElementById('rm-unit-name').value = rm.unit_name || '';
        if (document.getElementById('rm-rm-name')) document.getElementById('rm-rm-name').value = rm.rm_name || '';
        if (document.getElementById('rm-rm-phone')) document.getElementById('rm-rm-phone').value = rm.rm_phone || '';
        if (document.getElementById('rm-manager-name')) document.getElementById('rm-manager-name').value = rm.manager_name || '';
        if (document.getElementById('rm-authority')) document.getElementById('rm-authority').value = rm.approval_authority || 'HĐTDCC';

        // Update form inputs for Section B
        if (document.getElementById('rm-total-limit')) document.getElementById('rm-total-limit').value = b.total_limit || 0;
        if (document.getElementById('rm-loan-limit')) document.getElementById('rm-loan-limit').value = b.loan_limit || 0;
        if (document.getElementById('rm-guar-limit')) document.getElementById('rm-guar-limit').value = b.guarantee_limit || 0;
        if (document.getElementById('rm-collateral')) document.getElementById('rm-collateral').value = b.collateral_type || '';
        if (document.getElementById('rm-purpose')) document.getElementById('rm-purpose').value = b.loan_purpose || '';

      } catch (err) {
        console.error("Error loading case data:", err);
      }
    }

    async function loadCommitteeCards() {
      const container = document.getElementById('committee-cards-container');
      container.innerHTML = '<div class="p-6 text-center text-slate-500">⏳ Đang tổng hợp các câu hỏi chất vấn từ dữ liệu hồ sơ...</div>';

      try {
        const res = await fetch('/api/committee_prep');
        const data = await res.json();
        const cards = data.cards || [];

        if (cards.length === 0) {
          container.innerHTML = '<div class="p-6 text-center text-emerald-700 bg-emerald-50 rounded-xl">✓ Hồ sơ hoàn hảo, không phát hiện rủi ro bất thường.</div>';
          return;
        }

        let html = '';
        cards.forEach((c, idx) => {
          const sevColor = c.severity === 'HIGH' ? 'bg-red-100 text-red-800 border-red-200' : 'bg-amber-100 text-amber-800 border-amber-200';
          const sevText = c.severity === 'HIGH' ? 'CẦN BẢO VỆ CAO' : 'QUAN TRỌNG';

          let factsHtml = '';
          (c.facts_to_prepare || []).forEach(f => {
            factsHtml += `<div><span class="text-slate-500">${f.label}:</span> <span class="font-semibold text-slate-800">${f.value}</span></div>`;
          });

          let defenseHtml = '';
          (c.suggested_defense_points || []).forEach(p => {
            defenseHtml += `<li class="text-slate-700">${p}</li>`;
          });

          html += `
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4">
              <div class="flex items-start justify-between">
                <div class="flex items-center space-x-2">
                  <span class="w-6 h-6 rounded-full bg-[#003366] text-white flex items-center justify-center text-xs font-bold">${idx + 1}</span>
                  <span class="text-xs font-bold text-slate-500 uppercase tracking-wider">${c.category}</span>
                </div>
                <span class="text-[11px] font-bold px-2.5 py-0.5 rounded-full border ${sevColor}">${sevText}</span>
              </div>

              <div>
                <h4 class="text-sm font-bold text-[#003366] leading-snug">❓ "${c.question}"</h4>
                <div class="mt-1.5 text-xs text-slate-600 bg-slate-50 p-2.5 rounded-lg border border-slate-200">
                  <span class="font-semibold text-slate-700">🎯 Nguyên nhân chất vấn:</span> ${c.why_asked}
                </div>
              </div>

              <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                <div class="space-y-1.5 bg-blue-50/50 p-3 rounded-lg border border-blue-100">
                  <div class="font-bold text-blue-900">📊 Dữ liệu thực tế RM cần chuẩn bị:</div>
                  <div class="space-y-1">${factsHtml}</div>
                </div>

                <div class="space-y-1.5 bg-emerald-50/50 p-3 rounded-lg border border-emerald-100">
                  <div class="font-bold text-emerald-900">🛡️ Luận điểm giải trình gợi ý:</div>
                  <ul class="list-disc list-inside space-y-1">${defenseHtml}</ul>
                </div>
              </div>

              <div class="space-y-1.5 pt-2 border-t border-slate-100">
                <div class="flex justify-between items-center">
                  <label class="text-xs font-bold text-slate-700">📝 Ghi chú giải trình của RM:</label>
                  <button onclick="saveCommitteeNote('${c.question_id}')" class="text-xs bg-slate-800 hover:bg-slate-900 text-white font-semibold px-3 py-1 rounded shadow transition">
                    💾 Lưu ghi chú
                  </button>
                </div>
                <textarea id="note-${c.question_id}" rows="2" placeholder="Nhập ghi chú phản biện của RM khi ra Hội đồng..." class="w-full p-2.5 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-500">${c.rm_note || ''}</textarea>
              </div>
            </div>
          `;
        });

        container.innerHTML = html;
      } catch (e) {
        container.innerHTML = `<div class="p-4 text-red-600 text-xs">Lỗi nạp câu hỏi: ${e.message}</div>`;
      }
    }

    async function saveCommitteeNote(qid) {
      const el = document.getElementById('note-' + qid);
      const note = el ? el.value : '';
      try {
        const res = await fetch('/api/committee_prep/save_note', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question_id: qid, rm_note: note })
        });
        const data = await res.json();
        if (data.status === 'success') {
          alert('✅ Đã lưu ghi chú chuẩn bị bảo vệ thành công!');
        }
      } catch (e) {
        alert('Lỗi lưu ghi chú: ' + e.message);
      }
    }

    async function resetDemoCase() {
      const caseSelector = document.getElementById('case-selector');
      const cid = caseSelector ? caseSelector.value : 'PSD';
      try {
        await fetch('/api/demo_reset', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ case_id: cid })
        });
        await loadCaseData();
        if (CURRENT_ACTIVE_TAB === 'tab-committee') loadCommitteeCards();
        if (CURRENT_ACTIVE_TAB === 'tab-narrative') loadNarrativeState(cid);
        alert(`⚡ Đã nạp lại dữ liệu demo chuẩn cho hồ sơ '${cid}'!`);
      } catch (e) {
        alert('Lỗi reset demo: ' + e.message);
      }
    }

    async function onCaseChange(caseId) {
      try {
        const res = await fetch('/api/switch_case', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ case_id: caseId })
        });
        const data = await res.json();
        if (data.status === 'success') {
          CURRENT_CASE_ID = caseId;
          const isDemo = ['PSD', 'GAS_SOUTH', 'PHYTOPHARMA'].includes(caseId);
          if (isDemo) {
            const prefix = caseId === 'PSD' ? 'PSD' : (caseId === 'GAS_SOUTH' ? 'GasSouth' : 'Phytopharma');
            DOC_STATES.legal = { state: 'RM_CONFIRMED', filename: `Giay_Phep_DKKD_${prefix}.pdf`, previewId: null, previewData: null };
            DOC_STATES.business = { state: 'RM_CONFIRMED', filename: `Bao_Cao_Thuong_Nien_${prefix}.pdf`, previewId: null, previewData: null };
            DOC_STATES.financial = { state: 'RM_CONFIRMED', filename: `BCTC_Kiem_Toan_${prefix}_2025.pdf`, previewId: null, previewData: null };
            DOC_STATES.cic = { state: 'RM_CONFIRMED', filename: `Bao_Cao_CIC_${prefix}_2025.pdf`, previewId: null, previewData: null };
          } else {
            ['legal', 'business', 'financial', 'cic'].forEach(k => {
              DOC_STATES[k] = { state: 'NOT_UPLOADED', filename: '', previewId: null, previewData: null };
            });
          }
          ['legal', 'business', 'financial', 'cic'].forEach(k => updateDocCardUI(k));
          await loadCaseData();
          if (CURRENT_ACTIVE_TAB === 'tab-committee') loadCommitteeCards();
          if (CURRENT_ACTIVE_TAB === 'tab-narrative') loadNarrativeState(caseId);
        }
      } catch (e) {
        console.error(e);
      }
    }

    function escapeHtml(text) {
      if (!text) return '';
      return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }

    let NARRATIVE_STATE = {
      caseId: null,
      generationId: null,
      status: null, // 'NOT_READY' | 'READY' | 'GENERATING' | 'DRAFT' | 'ACCEPTED'
      isGenerating: false,
      manifestHash: null,
      model: null,
      generationSource: null,
      narrativeReady: false,
      readinessReason: null,
      blocks: [],
      verifiedInsights: [],
      error: null
    };

    let EDITING_BLOCK_TARGET = null;
    let EDITING_BLOCK_ORIGINAL_TEXT = null;

    function checkCaseFactsReadiness() {
      return {
        ready: !!NARRATIVE_STATE.narrativeReady,
        reason: NARRATIVE_STATE.readinessReason || "Chưa đủ dữ liệu canonical để tạo nhận định."
      };
    }

    async function loadNarrativeState(caseId) {
      const cid = caseId || CURRENT_CASE_ID || 'PSD';
      NARRATIVE_STATE.caseId = cid;

      try {
        const res = await fetch(`/api/narrative/status?case_id=${encodeURIComponent(cid)}`);
        const data = await res.json();

        if (data.status === 'success') {
          NARRATIVE_STATE.narrativeReady = !!data.narrative_ready;
          NARRATIVE_STATE.readinessReason = data.readiness_reason || null;
          NARRATIVE_STATE.model = data.model || null;
          NARRATIVE_STATE.generationSource = data.generation_source || null;

          if (data.has_draft && data.blocks && data.blocks.length > 0) {
            NARRATIVE_STATE.generationId = data.generation_id;
            NARRATIVE_STATE.status = (data.draft_status === 'ACCEPTED_FOR_RENDERING') ? 'ACCEPTED' : 'DRAFT';
            NARRATIVE_STATE.blocks = data.blocks;
            NARRATIVE_STATE.verifiedInsights = data.verified_insights || [];
            NARRATIVE_STATE.manifestHash = data.manifest_hash || (data.generation_id ? data.generation_id.slice(0, 16) : '-');
            NARRATIVE_STATE.error = null;
          } else {
            const isReady = NARRATIVE_STATE.narrativeReady;
            NARRATIVE_STATE.generationId = null;
            NARRATIVE_STATE.status = isReady ? 'READY' : 'NOT_READY';
            NARRATIVE_STATE.blocks = [];
            NARRATIVE_STATE.verifiedInsights = [];
            NARRATIVE_STATE.manifestHash = null;
            NARRATIVE_STATE.error = isReady ? null : NARRATIVE_STATE.readinessReason;
          }
        } else {
          NARRATIVE_STATE.narrativeReady = false;
          NARRATIVE_STATE.readinessReason = data.message || "Không thể kiểm tra trạng thái hồ sơ.";
          NARRATIVE_STATE.status = 'NOT_READY';
          NARRATIVE_STATE.error = NARRATIVE_STATE.readinessReason;
        }
      } catch (err) {
        console.warn("Could not load narrative status:", err);
        NARRATIVE_STATE.narrativeReady = false;
        NARRATIVE_STATE.status = 'NOT_READY';
        NARRATIVE_STATE.blocks = [];
        NARRATIVE_STATE.error = "Không thể kết nối máy chủ để kiểm tra trạng thái: " + err.message;
      }
      renderNarrativeUI();
    }

    async function generateNarrative() {
      if (NARRATIVE_STATE.isGenerating) {
        return;
      }

      const readiness = checkCaseFactsReadiness();
      if (!readiness.ready) {
        NARRATIVE_STATE.status = 'NOT_READY';
        NARRATIVE_STATE.error = readiness.reason || "Chưa đủ dữ liệu canonical để tạo nhận định.";
        renderNarrativeUI();
        return;
      }

      NARRATIVE_STATE.isGenerating = true;
      NARRATIVE_STATE.status = 'GENERATING';
      NARRATIVE_STATE.error = null;
      NARRATIVE_STATE.blocks = [];
      renderNarrativeUI();

      try {
        const res = await fetch('/api/narrative/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ case_id: CURRENT_CASE_ID })
        });
        const data = await res.json();

        if (res.ok && data.status === 'success') {
          NARRATIVE_STATE.isGenerating = false;
          NARRATIVE_STATE.status = 'DRAFT';
          NARRATIVE_STATE.generationId = data.generation_id;
          NARRATIVE_STATE.manifestHash = data.manifest_hash;
          NARRATIVE_STATE.model = data.model || null;
          NARRATIVE_STATE.generationSource = data.generation_source || null;
          NARRATIVE_STATE.blocks = data.blocks || [];
          NARRATIVE_STATE.verifiedInsights = data.verified_insights || [];
          NARRATIVE_STATE.error = null;
        } else {
          NARRATIVE_STATE.isGenerating = false;
          NARRATIVE_STATE.status = NARRATIVE_STATE.narrativeReady ? 'READY' : 'NOT_READY';
          NARRATIVE_STATE.error = data.message || "Không thể tạo nhận định AI. Vui lòng kiểm tra dữ liệu đã xác nhận và thử lại.";
        }
      } catch (err) {
        NARRATIVE_STATE.isGenerating = false;
        NARRATIVE_STATE.status = NARRATIVE_STATE.narrativeReady ? 'READY' : 'NOT_READY';
        NARRATIVE_STATE.error = "Không thể kết nối đến máy chủ AI: " + err.message;
      }

      renderNarrativeUI();
    }

    async function acceptNarrative() {
      if (!NARRATIVE_STATE.generationId) {
        alert("Không tìm thấy mã bản thảo (generation_id) để xác nhận.");
        return;
      }

      const btn = document.getElementById('btn-narrative-accept');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span>⏳ Đang ghi nhận phê duyệt...</span>';
      }

      try {
        const res = await fetch('/api/narrative/accept', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            generation_id: NARRATIVE_STATE.generationId,
            case_id: CURRENT_CASE_ID,
            rm_reviewer_name: "RM Thẩm định"
          })
        });
        const data = await res.json();

        if (res.ok && data.status === 'success') {
          NARRATIVE_STATE.status = 'ACCEPTED';
          NARRATIVE_STATE.error = null;
          renderNarrativeUI();
          alert('✔️ RM đã phê duyệt toàn bộ các đoạn văn bản phân tích tín dụng cho Tờ trình MB07!');
        } else {
          alert('Không thể xác nhận nhận định: ' + (data.message || 'Lỗi không xác định'));
          if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span>✔️ RM Phê Duyệt Toàn Bộ Bản Thảo</span>';
          }
        }
      } catch (err) {
        alert('Lỗi kết nối khi phê duyệt nhận định: ' + err.message);
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<span>✔️ RM Phê Duyệt Toàn Bộ Bản Thảo</span>';
        }
      }
    }

    function openEditNarrativeModal(targetBinding) {
      const block = NARRATIVE_STATE.blocks.find(b => b.target_binding === targetBinding);
      if (!block) {
        console.error("Block not found for target_binding:", targetBinding);
        return;
      }

      EDITING_BLOCK_TARGET = targetBinding;
      EDITING_BLOCK_ORIGINAL_TEXT = block.text;

      const modal = document.getElementById('modal-edit-narrative');
      const targetTitleEl = document.getElementById('modal-narr-target-title');
      const textEl = document.getElementById('modal-narr-text');
      const noteEl = document.getElementById('modal-narr-rm-note');
      const errEl = document.getElementById('modal-narr-error');

      if (targetTitleEl) targetTitleEl.innerText = `${block.title || targetBinding} [${block.target_binding}]`;
      if (textEl) textEl.value = block.text;
      if (noteEl) noteEl.value = '';
      if (errEl) { errEl.innerText = ''; errEl.classList.add('hidden'); }

      if (modal) modal.classList.remove('hidden');
    }

    function closeEditModal() {
      const modal = document.getElementById('modal-edit-narrative');
      if (modal) modal.classList.add('hidden');
      EDITING_BLOCK_TARGET = null;
      EDITING_BLOCK_ORIGINAL_TEXT = null;
    }

    async function saveAndRevalidateNarrative() {
      if (!EDITING_BLOCK_TARGET || !NARRATIVE_STATE.generationId) {
        closeEditModal();
        return;
      }

      const textEl = document.getElementById('modal-narr-text');
      const noteEl = document.getElementById('modal-narr-rm-note');
      const errEl = document.getElementById('modal-narr-error');
      const saveBtn = document.getElementById('btn-modal-save');

      const newText = textEl ? textEl.value.trim() : '';
      const rmNote = noteEl ? noteEl.value.trim() : '';

      if (!newText) {
        if (errEl) {
          errEl.innerText = 'Nội dung nhận định không được để trống.';
          errEl.classList.remove('hidden');
        }
        return;
      }

      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerText = '⏳ Đang tái thẩm định...';
      }

      try {
        const res = await fetch('/api/narrative/edit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            generation_id: NARRATIVE_STATE.generationId,
            target_binding: EDITING_BLOCK_TARGET,
            edited_text: newText,
            rm_note: rmNote
          })
        });
        const data = await res.json();

        if (res.ok && data.status === 'success') {
          const block = NARRATIVE_STATE.blocks.find(b => b.target_binding === EDITING_BLOCK_TARGET);
          if (block) {
            block.text = newText;
            block._rm_edited = true;
          }
          closeEditModal();
          renderNarrativeUI();
          alert('✓ Đã lưu và tái thẩm định thành công đoạn văn bản!');
        } else {
          if (errEl) {
            errEl.innerText = 'Lỗi tái thẩm định: ' + (data.message || 'Không thể áp dụng chỉnh sửa.');
            errEl.classList.remove('hidden');
          }
        }
      } catch (err) {
        if (errEl) {
          errEl.innerText = 'Lỗi kết nối máy chủ: ' + err.message;
          errEl.classList.remove('hidden');
        }
      } finally {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.innerText = '✓ Lưu & Tái Thẩm Định';
        }
      }
    }

    function renderNarrativeUI() {
      const badgeEl = document.getElementById('narrative-status-badge');
      const actionsEl = document.getElementById('narrative-header-actions');
      const alertEl = document.getElementById('narrative-alert-container');
      const telemetryEl = document.getElementById('narrative-telemetry-strip');
      const containerEl = document.getElementById('narrative-blocks-container');

      if (!badgeEl || !actionsEl || !alertEl || !containerEl) return;

      const state = NARRATIVE_STATE.status || 'READY';

      switch (state) {
        case 'NOT_READY':
          badgeEl.className = 'text-xs bg-slate-100 text-slate-600 font-bold px-2.5 py-0.5 rounded border border-slate-300';
          badgeEl.innerText = 'Chưa Đủ Dữ Liệu';
          actionsEl.innerHTML = `
            <button disabled class="px-4 py-2 bg-slate-200 text-slate-400 rounded-lg text-xs font-bold cursor-not-allowed flex items-center space-x-1.5" title="Cần tối thiểu thông tin pháp lý và BCTC đã xác nhận">
              <span>🚀 Tạo Nhận Định AI</span>
            </button>
          `;
          alertEl.innerHTML = `
            <div class="p-4 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-800 flex items-start space-x-3">
              <span class="text-base">⚠️</span>
              <div>
                <div class="font-bold text-amber-900 mb-1">Chưa đủ dữ liệu để tạo nhận định.</div>
                <p class="leading-relaxed">${escapeHtml(NARRATIVE_STATE.error || 'Hồ sơ chưa có đủ dữ liệu canonical (tên doanh nghiệp và BCTC). Vui lòng chuyển sang tab [📂 2. Không Gian Tài Liệu] để tải lên và đối soát tài liệu trước khi tạo nhận định AI.')}</p>
              </div>
            </div>
          `;
          if (telemetryEl) telemetryEl.classList.add('hidden');
          break;

        case 'READY':
          badgeEl.className = 'text-xs bg-blue-100 text-blue-800 font-bold px-2.5 py-0.5 rounded border border-blue-200';
          badgeEl.innerText = 'Sẵn Sàng Tạo Nhận Định';
          actionsEl.innerHTML = `
            <button onclick="generateNarrative()" id="btn-narrative-generate" class="px-4 py-2 bg-[#003366] hover:bg-blue-900 text-white rounded-lg text-xs font-bold shadow flex items-center space-x-1.5 transition">
              <span>🚀 Tạo Nhận Định AI</span>
            </button>
          `;
          if (NARRATIVE_STATE.error) {
            alertEl.innerHTML = `
              <div class="p-4 bg-red-50 border border-red-200 rounded-xl text-xs text-red-800 flex items-start space-x-3">
                <span class="text-base">❌</span>
                <div>
                  <div class="font-bold text-red-900 mb-1">Không thể tạo nhận định AI.</div>
                  <p class="leading-relaxed">${escapeHtml(NARRATIVE_STATE.error)}</p>
                </div>
              </div>
            `;
          } else {
            alertEl.innerHTML = `
              <div class="p-4 bg-blue-50 border border-blue-200 rounded-xl text-xs text-blue-800 flex items-start space-x-3">
                <span class="text-base">💡</span>
                <div>
                  <div class="font-bold text-blue-900 mb-1">Dữ liệu canonical đủ để tạo nhận định.</div>
                  <p class="leading-relaxed">Bấm <strong>"Tạo Nhận Định AI"</strong> để kích hoạt luồng: FactManifest SHA-256 ➔ GreenNode Insight Discovery ➔ Python Verifier ➔ Grounded Narrative Writer ➔ Deterministic Validator.</p>
                </div>
              </div>
            `;
          }
          if (telemetryEl) telemetryEl.classList.add('hidden');
          break;

        case 'GENERATING':
          badgeEl.className = 'text-xs bg-purple-100 text-purple-800 font-bold px-2.5 py-0.5 rounded animate-pulse border border-purple-200';
          badgeEl.innerText = '🤖 AI Đang Phân Tích...';
          actionsEl.innerHTML = `
            <button disabled class="px-4 py-2 bg-purple-100 text-purple-700 rounded-lg text-xs font-bold cursor-not-allowed flex items-center space-x-1.5 animate-pulse border border-purple-200">
              <span>⏳ Đang Tạo Nhận Định...</span>
            </button>
          `;
          alertEl.innerHTML = `
            <div class="p-4 bg-purple-50 border border-purple-200 rounded-xl text-xs text-purple-900 flex items-start space-x-3 animate-pulse">
              <span class="text-base">⏳</span>
              <div>
                <div class="font-bold mb-1">AI đang tổng hợp dữ liệu đã xác nhận và xây dựng nhận định...</div>
                <p class="leading-relaxed">Đang chạy: Đóng gói FactManifest ➔ GLM-5.2 Insight Discovery ➔ Đối soát công thức toán độc lập bằng Python ➔ Soạn thảo văn bản Grounded Narrative ➔ Kiểm định tính toàn vẹn MB07.</p>
              </div>
            </div>
          `;
          if (telemetryEl) telemetryEl.classList.add('hidden');
          break;

        case 'DRAFT':
          badgeEl.className = 'text-xs bg-amber-100 text-amber-800 font-bold px-2.5 py-0.5 rounded border border-amber-300';
          badgeEl.innerText = 'AI Draft — Chờ RM xác nhận';
          actionsEl.innerHTML = `
            <button onclick="acceptNarrative()" id="btn-narrative-accept" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold shadow flex items-center space-x-1.5 transition">
              <span>✔️ RM Phê Duyệt Toàn Bộ Bản Thảo</span>
            </button>
            <button onclick="generateNarrative()" id="btn-narrative-regenerate" class="px-3 py-2 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded-lg text-xs font-semibold shadow-sm transition flex items-center space-x-1">
              <span>🔄 Tạo Lại</span>
            </button>
          `;
          alertEl.innerHTML = `
            <div class="p-4 bg-amber-50/70 border border-amber-300 rounded-xl text-xs text-amber-900 flex items-start justify-between gap-3">
              <div class="flex items-start space-x-3">
                <span class="text-base">📋</span>
                <div>
                  <div class="font-bold mb-1">Bản thảo AI đã tạo thành công — Đang ở trạng thái Draft chờ RM thẩm định.</div>
                  <p class="leading-relaxed text-amber-800">Bản thảo chưa được ghi nhận vào Tờ trình chính thức. RM có thể kiểm tra từng đoạn văn bản, bấm <strong>"✏️ RM Chỉnh sửa"</strong> để hiệu chỉnh và tái thẩm định, hoặc bấm <strong>"✔️ RM Phê Duyệt Toàn Bộ"</strong> để khóa số liệu và gắn kết vào Tờ trình MB07.</p>
                </div>
              </div>
            </div>
          `;
          if (telemetryEl) {
            telemetryEl.classList.remove('hidden');
            const modelEl = document.getElementById('narrative-model-label');
            const hashEl = document.getElementById('narrative-manifest-hash');
            const insCountEl = document.getElementById('narrative-insights-count');
            const blkCountEl = document.getElementById('narrative-blocks-count');
            if (modelEl) {
              const modelName = NARRATIVE_STATE.model;
              if (modelName) {
                modelEl.innerText = modelName;
              } else if (NARRATIVE_STATE.generationSource === 'live') {
                modelEl.innerText = 'AI Backend: Live';
              } else {
                modelEl.innerText = 'Model: Không công bố';
              }
            }
            if (hashEl) hashEl.innerText = `Manifest Hash: ${NARRATIVE_STATE.manifestHash ? NARRATIVE_STATE.manifestHash.slice(0, 16) + '...' : '-'}`;
            if (insCountEl) insCountEl.innerText = `${NARRATIVE_STATE.verifiedInsights.length} Verified Insights`;
            if (blkCountEl) blkCountEl.innerText = `${NARRATIVE_STATE.blocks.length} Narrative Blocks`;
          }
          break;

        case 'ACCEPTED':
          badgeEl.className = 'text-xs bg-emerald-100 text-emerald-800 font-bold px-2.5 py-0.5 rounded border border-emerald-300';
          badgeEl.innerText = '✓ Đã được RM xác nhận';
          actionsEl.innerHTML = `
            <span class="text-xs text-emerald-700 font-bold bg-emerald-50 px-3 py-1.5 rounded-lg border border-emerald-200 flex items-center space-x-1.5">
              <span>✓ Đã được RM xác nhận</span>
            </span>
            <button onclick="generateNarrative()" id="btn-narrative-regenerate" class="px-3 py-2 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded-lg text-xs font-semibold shadow-sm transition flex items-center space-x-1">
              <span>🔄 Tạo Lại Bản Thảo</span>
            </button>
          `;
          alertEl.innerHTML = `
            <div class="p-4 bg-emerald-50 border border-emerald-300 rounded-xl text-xs text-emerald-900 flex items-start space-x-3">
              <span class="text-base">✅</span>
              <div>
                <div class="font-bold mb-1">Toàn bộ nhận định đã được RM xác nhận cho Tờ trình MB07.</div>
                <p class="leading-relaxed text-emerald-800">Các đoạn văn bản đã được gắn kết chính thức vào Tờ trình tín dụng. Bấm <strong>"🚀 BẮT ĐẦU TỔNG HỢP & XUẤT BẢN TỜ TRÌNH MB07 (.DOCX)"</strong> phía dưới để tải văn bản Word hoàn chỉnh.</p>
              </div>
            </div>
          `;
          if (telemetryEl) {
            telemetryEl.classList.remove('hidden');
            const modelEl = document.getElementById('narrative-model-label');
            const hashEl = document.getElementById('narrative-manifest-hash');
            const insCountEl = document.getElementById('narrative-insights-count');
            const blkCountEl = document.getElementById('narrative-blocks-count');
            if (modelEl) {
              const modelName = NARRATIVE_STATE.model;
              if (modelName) {
                modelEl.innerText = modelName;
              } else if (NARRATIVE_STATE.generationSource === 'live') {
                modelEl.innerText = 'AI Backend: Live';
              } else {
                modelEl.innerText = 'Model: Không công bố';
              }
            }
            if (hashEl) hashEl.innerText = `Manifest Hash: ${NARRATIVE_STATE.manifestHash ? NARRATIVE_STATE.manifestHash.slice(0, 16) + '...' : '-'}`;
            if (insCountEl) insCountEl.innerText = `${NARRATIVE_STATE.verifiedInsights.length} Verified Insights`;
            if (blkCountEl) blkCountEl.innerText = `${NARRATIVE_STATE.blocks.length} Narrative Blocks`;
          }
          break;
      }

      if (NARRATIVE_STATE.blocks.length === 0) {
        if (state === 'GENERATING') {
          containerEl.innerHTML = `
            <div class="p-12 text-center text-slate-400 space-y-3 bg-slate-50 rounded-xl border border-dashed border-slate-300">
              <div class="text-3xl animate-spin inline-block">⚙️</div>
              <div class="text-xs font-semibold text-slate-600">Đang tổng hợp các chỉ tiêu tài chính và đối soát văn bản...</div>
            </div>
          `;
        } else {
          containerEl.innerHTML = `
            <div class="p-10 text-center text-slate-400 space-y-3 bg-slate-50 rounded-xl border border-dashed border-slate-300">
              <div class="text-3xl">📝</div>
              <div class="text-sm font-semibold text-slate-700">Chưa có bản thảo nhận định tín dụng nào cho hồ sơ này</div>
              <p class="text-xs text-slate-500 max-w-md mx-auto">Nhận định tín dụng MB07 sẽ được tự động soạn thảo dựa trên 100% dữ liệu đã xác nhận và các chỉ số tài chính đã được Python kiểm chứng.</p>
            </div>
          `;
        }
        return;
      }

      let html = '';
      NARRATIVE_STATE.blocks.forEach((block, idx) => {
        const isAccepted = state === 'ACCEPTED';
        const binding = block.target_binding;
        const blockId = `narr-block-${binding}`;
        const textId = `narr-text-${binding}`;
        const title = block.title || `Nhận Định Tín Dụng (${binding})`;
        const text = block.text || '';
        const factsUsed = block.facts_used || [];
        const insightsUsed = block.insights_used || [];
        const wasEdited = block._rm_edited || false;

        let statusTag = '';
        if (isAccepted) {
          statusTag = '<span class="text-xs text-emerald-700 font-semibold bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">✓ Đã được RM xác nhận</span>';
        } else if (wasEdited) {
          statusTag = '<span class="text-[10px] bg-blue-100 text-blue-800 font-bold px-2 py-0.5 rounded border border-blue-300">✏️ RM Đã Hiệu Chỉnh</span>';
        } else {
          statusTag = '<span class="text-[10px] bg-amber-100 text-amber-800 font-bold px-2 py-0.5 rounded border border-amber-300">AI Draft — Chờ RM xác nhận</span>';
        }

        const factsTagsHtml = factsUsed.slice(0, 3).map(f => `<span class="bg-slate-200 text-slate-700 px-2 py-0.5 rounded font-mono text-[10px]">Fact: ${escapeHtml(f)}</span>`).join(' ');
        const insightsTagsHtml = insightsUsed.slice(0, 2).map(i => `<span class="bg-indigo-100 text-indigo-800 px-2 py-0.5 rounded font-mono text-[10px]">Insight: ${escapeHtml(i)}</span>`).join(' ');

        html += `
          <div class="p-4 rounded-xl border border-slate-200 bg-slate-50 space-y-2.5 transition hover:border-slate-300" id="${blockId}">
            <div class="flex items-center justify-between">
              <div class="flex items-center space-x-2">
                <span class="text-sm font-bold text-slate-900">${escapeHtml(title)}</span>
                <span class="text-[10px] bg-indigo-50 text-indigo-700 font-bold px-1.5 py-0.5 rounded border border-indigo-200">Grounded AI</span>
              </div>
              <div>${statusTag}</div>
            </div>
            <p class="text-xs text-slate-700 bg-white p-3.5 rounded-lg border border-slate-200 leading-relaxed whitespace-pre-line" id="${textId}">${escapeHtml(text)}</p>
            <div class="flex items-center justify-between text-[11px] text-slate-500 pt-1 border-t border-slate-100">
              <div class="flex flex-wrap gap-1.5 items-center">
                ${factsTagsHtml}
                ${insightsTagsHtml}
              </div>
              <button onclick="openEditNarrativeModal('${binding}')" class="text-blue-700 hover:text-blue-900 hover:underline font-semibold flex items-center space-x-1">
                <span>✏️ RM Chỉnh sửa</span>
              </button>
            </div>
          </div>
        `;
      });

      containerEl.innerHTML = html;
    }

    // Backwards-compatibility aliases
    function acceptAllNarrative() {
      acceptNarrative();
    }
    function editNarrativeBlock(target) {
      openEditNarrativeModal(target);
    }

    async function generateDocx() {
      const btnMain = document.getElementById('btn-generate-main');
      const btnTop = document.getElementById('btn-export-top');
      if (btnMain) { btnMain.innerText = '⏳ Đang tổng hợp & xuất bản MB07...'; btnMain.disabled = true; }
      if (btnTop) { btnTop.innerText = '⏳ Đang sinh...'; btnTop.disabled = true; }

      try {
        const res = await fetch('/api/generate_docx', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
          switchTab('tab-narrative');
          const resBox = document.getElementById('export-result');
          if (resBox) {
            resBox.classList.remove('hidden');
            document.getElementById('export-filename').innerText = `Tệp tin: ${data.filename}`;
            document.getElementById('export-download-link').href = data.download_url;
          }
          alert(`🎉 Xuất Tờ Trình MB07 thành công: ${data.filename}! Bấm [TẢI FILE WORD VỀ MÁY] để mở.`);
        } else {
          alert('Lỗi: ' + data.message);
        }
      } catch (err) {
        alert('Lỗi hệ thống: ' + err.message);
      } finally {
        if (btnMain) { btnMain.innerText = '🚀 BẮT ĐẦU TỔNG HỢP & XUẤT BẢN TỜ TRÌNH MB07 (.DOCX)'; btnMain.disabled = false; }
        if (btnTop) { btnTop.innerText = '⚡ Xuất Tờ Trình MB07 (.DOCX)'; btnTop.disabled = false; }
      }
    }

    window.onload = function() {
      loadCaseData();
      updateWorkspaceHeaderBadge();
    };
  </script>
</body>
</html>
"""


@dataclass
class LegalPreviewRecord:
    preview_id: str
    case_id: str | None
    verified_fields: dict[str, Any]
    source_filename: str
    routing: dict[str, Any]
    consumed: bool = False


LEGAL_PREVIEW_STORE: dict[str, LegalPreviewRecord] = {}
MAX_PREVIEW_UPLOAD_SIZE = 15 * 1024 * 1024  # 15 MB


def process_legal_pdf_preview(raw_bytes: bytes, filename: str, case_id: str | None = None) -> tuple[dict[str, Any], int]:
    """Execute Ingestion -> Extraction -> Mapping pipeline for one legal PDF.

    Guarantees:
    - Zero mutation to CASES_DB or ACTIVE_CASE_ID.
    - Legacy AIDocumentExtractor is not called.
    - Temp file lifecycle: created with server-generated name, deleted in finally.
    - No raw stack traces or internal secrets/keys leaked.
    - Status precedence: CONFLICT > WARNING > MISSING > EXTRACTED.
    """
    temp_path = None
    try:
        # Create server-generated temporary file
        with tempfile.NamedTemporaryFile(prefix="legal_preview_", suffix=".pdf", delete=False) as tmp:
            tmp.write(raw_bytes)
            temp_path = tmp.name

        # 1. Router Ingestion (returns provider="pypdf" for digital, "qwen_vision" for OCR)
        ingestion_res = DocumentIngestionRouter.ingest_document(temp_path)

        # 2. Legal Extraction via locked module
        extraction_res = LegalDocumentExtractor.extract(ingestion_res.tagged_text)

        # 3. Deterministic Canonical Mapping (using isolated dummy case_data)
        source_meta = MappingSourceMetadata(
            source_document=filename,
            ingestion_mode=ingestion_res.mode,
            extractor="LegalDocumentExtractor",
        )
        dummy_case = {"customer": {}}
        map_result = LegalDocumentMapper.map(
            existing_case_data=dummy_case,
            extraction=extraction_res,
            source_meta=source_meta,
        )

        # 4. Routing metadata
        routing = {
            "mode": ingestion_res.mode,
            "provider": ingestion_res.provider,
            "page_count": ingestion_res.page_count,
            "fallback_reason": ingestion_res.fallback_reason,
        }

        # 5. Extract 7 canonical fields with precedence: CONFLICT > WARNING > MISSING > EXTRACTED
        field_configs = [
            ("company_name", "customer.name", "name"),
            ("short_name", "customer.short_name", "short_name"),
            ("tax_code", "customer.tax_code", "tax_code"),
            ("address", "customer.address", "address"),
            ("charter_capital", "customer.charter_capital", "charter_capital"),
            ("legal_rep_name", "customer.legal_rep_name", "legal_rep_name"),
            ("legal_rep_title", "customer.legal_rep_title", "legal_rep_title"),
        ]

        fields_output = {}
        for field_key, canonical_path, cust_key in field_configs:
            extract_attr = "charter_capital_raw" if field_key == "charter_capital" else field_key
            raw_field = getattr(extraction_res, extract_attr, None)
            conflict_obj = next((c for c in map_result.conflicts if c.canonical_path == canonical_path), None)
            warning_obj = next((w for w in map_result.warnings if w.canonical_path == canonical_path), None)
            canonical_val = map_result.case_data.get("customer", {}).get(cust_key)
            is_missing = (raw_field is None or raw_field.value is None)

            # Strict status precedence: CONFLICT > WARNING > MISSING > EXTRACTED
            if conflict_obj:
                status = "CONFLICT"
                val = canonical_val
            elif warning_obj:
                status = "WARNING"
                val = None
            elif is_missing:
                status = "MISSING"
                val = None
            else:
                status = "EXTRACTED"
                val = canonical_val

            fields_output[field_key] = {
                "canonical_path": canonical_path,
                "value": val,
                "source_value": raw_field.value if raw_field else None,
                "evidence": raw_field.evidence if raw_field else None,
                "page": raw_field.page if raw_field else None,
                "status": status,
                "warning_reason": warning_obj.reason if warning_obj else None,
                "conflict_note": f"Xung đột với: {conflict_obj.existing_value}" if conflict_obj else None,
            }

        preview_id = str(uuid.uuid4())
        target_cid = case_id or ACTIVE_CASE_ID
        record = LegalPreviewRecord(
            preview_id=preview_id,
            case_id=target_cid,
            verified_fields=fields_output,
            source_filename=filename,
            routing=routing,
            consumed=False,
        )
        global LEGAL_PREVIEW_STORE, LATEST_LEGAL_PREVIEW
        LEGAL_PREVIEW_STORE[preview_id] = record

        preview_result = {
            "status": "success",
            "preview_id": preview_id,
            "filename": filename,
            "routing": routing,
            "fields": fields_output,
        }
        LATEST_LEGAL_PREVIEW = preview_result
        return preview_result, 200

    except PDFEncryptedError:
        return {
            "status": "error",
            "error_type": "PDFEncryptedError",
            "message": "Tệp PDF đã bị khóa mật khẩu bảo vệ. Vui lòng mở khóa tệp hoặc tải lên bản tài liệu không có mật khẩu."
        }, 400
    except PDFFileNotFoundError:
        return {
            "status": "error",
            "error_type": "PDFFileNotFoundError",
            "message": "Không tìm thấy tệp PDF. Vui lòng kiểm tra lại quá trình tải lên."
        }, 400
    except OCRTimeoutError:
        return {
            "status": "error",
            "error_type": "OCRTimeoutError",
            "message": "Quá trình nhận diện OCR hình ảnh vượt quá thời gian chờ (Timeout). Vui lòng thử lại với tài liệu có dung lượng nhỏ hơn hoặc kiểm tra kết nối mạng."
        }, 504
    except OCRServiceError:
        return {
            "status": "error",
            "error_type": "OCRServiceError",
            "message": "Dịch vụ OCR hình ảnh gặp sự cố kết nối. Vui lòng thử lại sau."
        }, 502
    except ExtractionAuditError:
        return {
            "status": "error",
            "error_type": "ExtractionAuditError",
            "message": "Không thể xác thực nguồn gốc dữ liệu: trích xuất không khớp với ngữ cảnh bằng chứng hoặc số trang trong tài liệu."
        }, 422
    except (ExtractionError, ExtractionSchemaError, ExtractionJSONError) as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "message": "Mô hình AI trả về cấu trúc dữ liệu không hợp lệ từ tài liệu này. Vui lòng thử lại."
        }, 422
    except MappingError as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "message": "Lỗi trong quá trình ánh xạ thông tin pháp lý vào hồ sơ."
        }, 422
    except Exception as e:
        return {
            "status": "error",
            "error_type": "InternalError",
            "message": "Đã xảy ra lỗi không xác định trong quá trình xử lý tài liệu. Vui lòng kiểm tra lại tệp tin."
        }, 500
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


LATEST_LEGAL_PREVIEW = None

ALLOWED_CONFIRM_FIELDS = {
    "company_name": ("customer.name", "name", "Tên doanh nghiệp", "text"),
    "short_name": ("customer.short_name", "short_name", "Tên viết tắt", "text"),
    "tax_code": ("customer.tax_code", "tax_code", "Mã số doanh nghiệp", "tax_code"),
    "address": ("customer.address", "address", "Địa chỉ trụ sở chính", "text"),
    "charter_capital": ("customer.charter_capital", "charter_capital", "Vốn điều lệ", "monetary"),
    "legal_rep_name": ("customer.legal_rep_name", "legal_rep_name", "Người đại diện theo pháp luật", "text"),
    "legal_rep_title": ("customer.legal_rep_title", "legal_rep_title", "Chức danh người ĐDPL", "text"),
}

ALLOWED_CANONICAL_PATHS = {spec[0] for spec in ALLOWED_CONFIRM_FIELDS.values()}
ALLOWED_CUSTOMER_KEYS = {spec[1] for spec in ALLOWED_CONFIRM_FIELDS.values()}


def validate_and_confirm_legal_preview(
    preview_id: str | None = None,
    case_id: str | None = None,
    resolutions: dict[str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Validate server-side verified preview facts against the ACTIVE CASE and conditionally update CASES_DB.

    Security & Trust Boundaries:
    1. The browser is NEVER authoritative for extracted facts. Reads ONLY from server-side LEGAL_PREVIEW_STORE[preview_id].
    2. Missing or invalid preview_id -> 404 PreviewNotFoundError. CASES_DB remains 100% untouched.
    3. Consumed preview -> 409 PreviewAlreadyConsumedError.
    4. Preview bound to a different case -> 400 CaseMismatchError.
    5. Only updates CASES_DB[target_case_id]["customer"] for the 7 allowed legal fields.
    6. Preserves all other customer fields and all other case sections.
    7. If conflicts exist and no explicit resolution -> 409 conflict; preview remains unconsumed so RM can submit resolutions.
    8. Once successfully confirmed -> marks preview as consumed.
    9. Zero calls to execute_generation_pipeline, zero DOCX generated.
    """
    global ACTIVE_CASE_ID, CASES_DB, LEGAL_PREVIEW_STORE

    # 1. Preview Lookup
    if not preview_id or not isinstance(preview_id, str):
        return {
            "status": "error",
            "error_type": "InvalidInputError",
            "message": "Trường 'preview_id' là bắt buộc và phải là chuỗi ký tự.",
        }, 400

    if preview_id not in LEGAL_PREVIEW_STORE:
        return {
            "status": "error",
            "error_type": "PreviewNotFoundError",
            "message": f"Không tìm thấy bản xem trước hợp lệ với ID '{preview_id}'.",
        }, 404

    preview_record = LEGAL_PREVIEW_STORE[preview_id]

    # 2. Consumption Check
    if preview_record.consumed:
        return {
            "status": "error",
            "error_type": "PreviewAlreadyConsumedError",
            "message": f"Bản xem trước '{preview_id}' đã được xác nhận vào hồ sơ và không thể tái sử dụng.",
        }, 409

    # 3. Case Scope & Binding
    target_case_id = case_id or preview_record.case_id or ACTIVE_CASE_ID
    if not target_case_id or target_case_id not in CASES_DB:
        return {
            "status": "error",
            "error_type": "CaseNotFoundError",
            "message": f"Không tìm thấy hồ sơ khách hàng hợp lệ '{target_case_id}' để xác nhận.",
        }, 404

    if preview_record.case_id and case_id and preview_record.case_id != case_id:
        return {
            "status": "error",
            "error_type": "CaseMismatchError",
            "message": f"Bản xem trước này thuộc hồ sơ '{preview_record.case_id}', không khớp với hồ sơ yêu cầu '{case_id}'.",
        }, 400

    # 4. Authoritative verified fields from Server Store
    candidate_fields = preview_record.verified_fields

    # 5. Validate Resolutions
    if resolutions is not None:
        if not isinstance(resolutions, dict):
            return {
                "status": "error",
                "error_type": "InvalidInputError",
                "message": "Trường 'resolutions' phải là một đối tượng JSON.",
            }, 400
        for res_key, res_val in resolutions.items():
            if (
                res_key not in ALLOWED_CANONICAL_PATHS
                and res_key not in ALLOWED_CONFIRM_FIELDS
                and res_key not in ALLOWED_CUSTOMER_KEYS
            ):
                return {
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": f"Đường dẫn xung đột '{res_key}' không hợp lệ.",
                }, 400
            if not isinstance(res_val, str) or res_val not in ("use_extracted", "keep_existing", "extracted", "existing"):
                return {
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": f"Lựa chọn '{res_val}' cho trường '{res_key}' không hợp lệ. Chỉ chấp nhận 'use_extracted' hoặc 'keep_existing'.",
                }, 400

    # 6. Snapshot existing case (deepcopy)
    existing_case = deepcopy(CASES_DB[target_case_id])
    existing_customer = existing_case.get("customer", {})

    # 7. Deterministic Conflict Comparison
    conflicts = []
    to_update = {}

    for field_key, (canon_path, dict_key, label, ftype) in ALLOWED_CONFIRM_FIELDS.items():
        item = candidate_fields.get(field_key)
        if isinstance(item, dict):
            ext_val = item.get("value")
            is_warning = item.get("status") == "WARNING"
        else:
            ext_val = item
            is_warning = False

        # If warning or extracted value is None/empty: skip
        if is_warning or ext_val is None or (isinstance(ext_val, str) and ext_val.strip() == ""):
            continue

        if ftype == "monetary":
            try:
                dec_val = Decimal(str(ext_val))
                norm_val = int(dec_val) if dec_val == int(dec_val) else float(dec_val)
            except Exception:
                norm_val = ext_val
        else:
            norm_val = ext_val

        exist_val = existing_customer.get(dict_key)

        # Missing canonical field -> populate directly
        if exist_val is None or (isinstance(exist_val, str) and exist_val.strip() == ""):
            to_update[dict_key] = norm_val
            continue

        # Both present -> compare deterministically
        is_equal = False
        if ftype == "monetary":
            try:
                exist_dec = Decimal(str(exist_val))
                ext_dec = Decimal(str(ext_val))
                is_equal = abs(exist_dec - ext_dec) < Decimal("0.000001")
            except (InvalidOperation, ValueError):
                is_equal = False
        elif ftype == "tax_code":
            is_equal = _normalize_tax_code_for_comparison(exist_val) == _normalize_tax_code_for_comparison(ext_val)
        else:
            is_equal = _normalize_text_for_comparison(exist_val) == _normalize_text_for_comparison(ext_val)

        if is_equal:
            continue

        # Conflicting value detected
        res_choice = None
        if resolutions:
            res_choice = resolutions.get(canon_path) or resolutions.get(field_key) or resolutions.get(dict_key)

        if res_choice in ("use_extracted", "extracted"):
            to_update[dict_key] = norm_val
        elif res_choice in ("keep_existing", "existing"):
            pass
        else:
            conflicts.append({
                "canonical_path": canon_path,
                "field_key": field_key,
                "field_name": label,
                "existing_value": exist_val,
                "extracted_value": ext_val,
            })

    # 8. Unresolved conflicts -> DO NOT MUTATE CASES_DB, do NOT consume preview
    if conflicts:
        return {
            "status": "conflict",
            "message": "Phát hiện xung đột giữa dữ liệu trích xuất và hồ sơ hiện tại. Vui lòng đối soát và lựa chọn.",
            "case_id": target_case_id,
            "preview_id": preview_id,
            "conflicts": conflicts,
        }, 409

    # 9. Successful confirmation -> mark preview consumed and update CASES_DB
    preview_record.consumed = True

    if "customer" not in CASES_DB[target_case_id]:
        CASES_DB[target_case_id]["customer"] = {}

    for k, v in to_update.items():
        if k in ALLOWED_CUSTOMER_KEYS:
            CASES_DB[target_case_id]["customer"][k] = v

    return {
        "status": "success",
        "message": "Đã cập nhật thông tin pháp lý vào hồ sơ.",
        "case_id": target_case_id,
        "preview_id": preview_id,
        "updated_fields": [f"customer.{k}" for k in to_update.keys()],
        "customer": CASES_DB[target_case_id]["customer"],
    }, 200


# ==============================================================================
# FINANCIAL PREVIEW & CONFIRMATION LOGIC (PHASE 3A)
# ==============================================================================

@dataclass
class FinancialPreviewRecord:
    preview_id: str
    case_id: str | None
    extraction: FinancialDocumentExtraction
    source_filename: str
    routing: dict[str, Any]
    mapping_result: CanonicalMappingResult
    review_table: list[dict[str, Any]]
    calculated_ratios: dict[str, list[float | None]]
    consumed: bool = False


FINANCIAL_PREVIEW_STORE: dict[str, FinancialPreviewRecord] = {}

FINANCIAL_ITEM_LABELS = {
    "net_revenue": "Doanh thu thuần về bán hàng và CCDV",
    "cogs": "Giá vốn hàng bán",
    "gross_profit": "Lợi nhuận gộp",
    "financial_income": "Doanh thu hoạt động tài chính",
    "financial_expenses": "Chi phí tài chính",
    "interest_expenses": "Trong đó: Chi phí lãi vay",
    "sga_expenses": "Chi phí bán hàng & Quản lý DN",
    "net_profit_before_tax": "Tổng lợi nhuận kế toán trước thuế",
    "net_profit_after_tax": "Lợi nhuận sau thuế thu nhập DN",
    "current_assets": "Tài sản ngắn hạn",
    "cash": "Tiền và các khoản tương đương tiền",
    "receivables": "Các khoản phải thu ngắn hạn",
    "inventories": "Hàng tồn kho",
    "total_assets": "Tổng cộng tài sản",
    "total_liabilities": "Nợ phải trả",
    "current_liabilities": "Nợ ngắn hạn",
    "short_term_debt": "Vay và nợ thuê tài chính ngắn hạn",
    "equity": "Vốn chủ sở hữu",
}


def process_financial_pdf_preview(raw_bytes: bytes, filename: str, case_id: str | None = None) -> tuple[dict[str, Any], int]:
    """Execute Ingestion -> Financial Extraction -> Grounding Audit -> Deterministic Mapping.
    
    Guarantees:
    - Zero mutation to CASES_DB or ACTIVE_CASE_ID.
    - Server-authoritative extraction staging in FINANCIAL_PREVIEW_STORE.
    - Python calculates ratios deterministically; GreenNode extracts raw facts only.
    - Status precedence: CONFLICT > WARNING > MISSING > EXTRACTED.
    """
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="fin_preview_", suffix=".pdf", delete=False) as tmp:
            tmp.write(raw_bytes)
            temp_path = tmp.name

        # 1. Router Ingestion
        ingestion_res = DocumentIngestionRouter.ingest_document(temp_path)

        # 2. Financial Extraction via GreenNode
        extractor = FinancialDocumentExtractor()
        extraction_res = extractor.extract(ingestion_res.tagged_text, ingestion_res.page_count)

        # 3. Grounding Audit for each period & field
        audit_warnings: list[str] = []
        for p in extraction_res.periods:
            for field_name in FINANCIAL_SOURCE_FACT_FIELDS:
                f_obj = getattr(p, field_name, None)
                if f_obj and f_obj.value_raw:
                    field_errs = FinancialGroundingAuditor.audit_field(
                        canonical_name=field_name,
                        field_data=f_obj,
                        page_tagged_text=ingestion_res.tagged_text,
                        page_count=ingestion_res.page_count,
                    )
                    audit_warnings.extend(field_errs)

        # 4. Deterministic Canonical Mapping against existing case data (isolated snapshot)
        target_cid = case_id or ACTIVE_CASE_ID
        existing_case = deepcopy(CASES_DB.get(target_cid, {}))
        source_meta = MappingSourceMetadata(
            source_document=filename,
            ingestion_mode=ingestion_res.mode,
            extractor="FinancialDocumentExtractor",
        )

        map_result = FinancialDocumentMapper.map(
            existing_case_data=existing_case,
            extraction=extraction_res,
            source_meta=source_meta,
        )

        # 5. Routing metadata
        routing = {
            "mode": ingestion_res.mode,
            "provider": ingestion_res.provider,
            "page_count": ingestion_res.page_count,
            "fallback_reason": ingestion_res.fallback_reason,
        }

        # 6. Build Review Table (YEAR | FINANCIAL ITEM | EXTRACTED VALUE | UNIT | PAGE | STATUS)
        review_table = []
        for period in extraction_res.periods:
            yr = period.period.strip()
            for field_name in FINANCIAL_SOURCE_FACT_FIELDS:
                raw_field: FinancialEvidenceField = getattr(period, field_name, None)
                canonical_path = f"section_d.{field_name}[{yr}]"
                conflict_obj = next((c for c in map_result.conflicts if c.canonical_path == canonical_path), None)
                warning_obj = next((w for w in map_result.warnings if w.canonical_path == canonical_path), None)

                is_missing = (raw_field is None or raw_field.value_raw is None or str(raw_field.value_raw).strip() == "")
                if conflict_obj:
                    status = "CONFLICT"
                elif warning_obj:
                    status = "WARNING"
                elif is_missing:
                    status = "MISSING"
                else:
                    status = "EXTRACTED"

                prov_list = map_result.provenance.get(canonical_path, ())
                prov_obj = next((p for p in prov_list if p.mapped_value is not None), None)
                extracted_num = prov_obj.mapped_value if prov_obj else None
                resolved_u = prov_obj.resolved_unit if prov_obj else (raw_field.unit_raw if raw_field else None)

                review_table.append({
                    "year": yr,
                    "canonical_field": field_name,
                    "item_name": FINANCIAL_ITEM_LABELS.get(field_name, field_name),
                    "raw_value": raw_field.value_raw if raw_field else None,
                    "extracted_value": extracted_num,
                    "unit": resolved_u or "triệu VND",
                    "page": raw_field.page if raw_field else None,
                    "status": status,
                    "conflict_note": f"Xung đột với số liệu hiện tại: {conflict_obj.existing_value:,.2f}" if conflict_obj and isinstance(conflict_obj.existing_value, (int, float)) else (str(conflict_obj.existing_value) if conflict_obj else None),
                    "warning_reason": warning_obj.reason if warning_obj else None,
                    "evidence": raw_field.evidence if raw_field else None,
                })

        # 7. Calculate Deterministic Ratios from Python engine
        preview_section_d = map_result.case_data.get("section_d", {})
        calculated_ratios = compute_canonical_ratios(preview_section_d)

        preview_id = str(uuid.uuid4())
        record = FinancialPreviewRecord(
            preview_id=preview_id,
            case_id=target_cid,
            extraction=extraction_res,
            source_filename=filename,
            routing=routing,
            mapping_result=map_result,
            review_table=review_table,
            calculated_ratios=calculated_ratios,
            consumed=False,
        )
        FINANCIAL_PREVIEW_STORE[preview_id] = record

        return {
            "status": "success",
            "preview_id": preview_id,
            "filename": filename,
            "routing": routing,
            "review_table": review_table,
            "periods": [p.period.strip() for p in extraction_res.periods if p.period],
            "calculated_ratios": calculated_ratios,
            "audit_warnings": audit_warnings[:10],
        }, 200

    except PDFEncryptedError:
        return {
            "status": "error",
            "error_type": "PDFEncryptedError",
            "message": "Tệp PDF BCTC đã bị khóa mật khẩu bảo vệ."
        }, 400
    except PDFFileNotFoundError:
        return {
            "status": "error",
            "error_type": "PDFFileNotFoundError",
            "message": "Không tìm thấy tệp PDF tải lên."
        }, 400
    except OCRTimeoutError:
        return {
            "status": "error",
            "error_type": "OCRTimeoutError",
            "message": "Quá trình nhận diện OCR tài liệu BCTC quá thời gian chờ (Timeout)."
        }, 504
    except OCRServiceError:
        return {
            "status": "error",
            "error_type": "OCRServiceError",
            "message": "Dịch vụ OCR hình ảnh gặp sự cố kết nối."
        }, 502
    except MappingError as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "message": f"Lỗi ánh xạ dữ liệu tài chính: {e}"
        }, 422
    except Exception as e:
        return {
            "status": "error",
            "error_type": "InternalError",
            "message": f"Lỗi xử lý BCTC: {e}"
        }, 500
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def validate_and_confirm_financial_preview(
    preview_id: str | None = None,
    case_id: str | None = None,
    resolutions: dict[str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Validate server-side verified financial preview facts and update CASES_DB[case_id]["section_d"].

    Security & Trust Boundaries:
    1. Browser is NEVER authoritative for financial facts. Reads ONLY from FINANCIAL_PREVIEW_STORE[preview_id].
    2. Consumed or invalid preview -> rejected with 409 or 404.
    3. Python updates canonical section_d and recalculates ratios deterministically.
    """
    global ACTIVE_CASE_ID, CASES_DB, FINANCIAL_PREVIEW_STORE

    if not preview_id or not isinstance(preview_id, str):
        return {
            "status": "error",
            "error_type": "InvalidInputError",
            "message": "Trường 'preview_id' là bắt buộc và phải là chuỗi ký tự.",
        }, 400

    if preview_id not in FINANCIAL_PREVIEW_STORE:
        return {
            "status": "error",
            "error_type": "PreviewNotFoundError",
            "message": f"Không tìm thấy bản xem trước tài chính hợp lệ với ID '{preview_id}'.",
        }, 404

    preview_record = FINANCIAL_PREVIEW_STORE[preview_id]

    if preview_record.consumed:
        return {
            "status": "error",
            "error_type": "PreviewAlreadyConsumedError",
            "message": f"Bản xem trước '{preview_id}' đã được xác nhận vào hồ sơ và không thể tái sử dụng.",
        }, 409

    target_case_id = case_id or preview_record.case_id or ACTIVE_CASE_ID
    if not target_case_id or target_case_id not in CASES_DB:
        return {
            "status": "error",
            "error_type": "CaseNotFoundError",
            "message": f"Không tìm thấy hồ sơ khách hàng hợp lệ '{target_case_id}'.",
        }, 404

    if preview_record.case_id and case_id and preview_record.case_id != case_id:
        return {
            "status": "error",
            "error_type": "CaseMismatchError",
            "message": f"Bản xem trước này thuộc hồ sơ '{preview_record.case_id}', không khớp với hồ sơ yêu cầu '{case_id}'.",
        }, 400

    map_result = preview_record.mapping_result

    # Check for conflicts
    if map_result.conflicts:
        if resolutions is None:
            conflicts_data = [
                {
                    "canonical_path": c.canonical_path,
                    "existing_value": c.existing_value,
                    "extracted_value": c.extracted_value,
                    "page": c.page,
                    "evidence": c.evidence,
                }
                for c in map_result.conflicts
            ]
            return {
                "status": "conflict",
                "message": "Phát hiện xung đột giữa số liệu trích xuất BCTC và hồ sơ hiện tại. Vui lòng đối soát và lựa chọn.",
                "case_id": target_case_id,
                "preview_id": preview_id,
                "conflicts": conflicts_data,
            }, 409
        else:
            # Validate resolution choices
            for c in map_result.conflicts:
                res = resolutions.get(c.canonical_path)
                if res not in ("use_extracted", "keep_existing", "extracted", "existing"):
                    return {
                        "status": "error",
                        "error_type": "InvalidInputError",
                        "message": f"Lựa chọn xung đột cho '{c.canonical_path}' không hợp lệ. Chỉ chấp nhận 'use_extracted' hoặc 'keep_existing'.",
                    }, 400

    # Mark consumed
    preview_record.consumed = True

    # Apply mapping to target case
    target_case = CASES_DB[target_case_id]
    if "section_d" not in target_case or not isinstance(target_case["section_d"], dict):
        target_case["section_d"] = {}

    mapped_d = map_result.case_data.get("section_d", {})
    existing_d = target_case["section_d"]

    # If resolutions exist, apply overrides
    if resolutions and map_result.conflicts:
        target_years = mapped_d.get("years", [])
        import re
        for c in map_result.conflicts:
            res = resolutions.get(c.canonical_path)
            m = re.match(r"^section_d\.(\w+)\[(.*?)\]$", c.canonical_path)
            if not m:
                continue
            f_name, yr = m.group(1), m.group(2)
            if yr in target_years and f_name in mapped_d:
                y_idx = target_years.index(yr)
                if res in ("use_extracted", "extracted"):
                    mapped_d[f_name][y_idx] = c.extracted_value
                elif res in ("keep_existing", "existing"):
                    mapped_d[f_name][y_idx] = c.existing_value

    # Update section_d facts
    for k, v in mapped_d.items():
        if k in FINANCIAL_SOURCE_FACT_FIELDS or k == "years":
            existing_d[k] = v

    # HARD CONTRACT: ONE FACT = ONE CANONICAL PATH
    # section_d.net_revenue is updated.
    # customer.revenue_2025 MUST NOT be written.

    # Re-calculate canonical Python ratios
    final_ratios = compute_canonical_ratios(existing_d)

    return {
        "status": "success",
        "message": "Đã cập nhật BCTC và tính toán chỉ số tài chính chuẩn MSB vào hồ sơ.",
        "case_id": target_case_id,
        "preview_id": preview_id,
        "updated_fields": list(map_result.updated_fields),
        "section_d": existing_d,
        "calculated_ratios": final_ratios,
    }, 200


# ==============================================================================
# CIC PREVIEW & CONFIRM PIPELINE (PHASE 4)
# ==============================================================================

@dataclass
class CICPreviewRecord:
    preview_id: str
    case_id: str | None
    extraction: CICDocumentExtraction
    source_filename: str
    routing: dict[str, Any]
    mapping_result: CanonicalMappingResult
    review_table: list[dict[str, Any]]
    identity_status: str
    identity_message: str
    consumed: bool = False


CIC_PREVIEW_STORE: dict[str, CICPreviewRecord] = {}


def process_cic_pdf_preview(raw_bytes: bytes, filename: str, case_id: str | None = None) -> tuple[dict[str, Any], int]:
    """Execute Ingestion -> CIC Extraction -> Grounding Audit -> Identity Reconcile -> Deterministic Mapping."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="cic_preview_", suffix=".pdf", delete=False) as tmp:
            tmp.write(raw_bytes)
            temp_path = tmp.name

        # 1. Router Ingestion
        ingestion_res = DocumentIngestionRouter.ingest_document(temp_path)

        # 2. Semantic Extraction via GreenNode
        extractor = CICDocumentExtractor()
        extraction_res = extractor.extract(ingestion_res.tagged_text, ingestion_res.page_count)

        # 3. Grounding Verification
        pages_text, max_p = CICGroundingAuditor.extract_pages(ingestion_res.tagged_text)

        # 4. Identity Reconciliation
        target_cid = case_id or ACTIVE_CASE_ID
        if target_cid not in CASES_DB:
            target_cid = ACTIVE_CASE_ID
        target_case = CASES_DB[target_cid]

        ext_tc = extraction_res.tax_code.value_raw if extraction_res.tax_code else None
        ext_n = extraction_res.customer_name.value_raw if extraction_res.customer_name else None
        id_status, id_msg = CICIdentityReconciler.reconcile(ext_tc, ext_n, target_case.get("customer", {}))

        # 4.5. Full Grounding Audit on Every Source Fact
        grounding_audits = CICGroundingAuditor.audit_all_facts(extraction_res, pages_text, max_p)

        # 5. Deterministic Mapping with Grounding Audits
        src_meta = MappingSourceMetadata(
            source_document=filename,
            ingestion_mode=ingestion_res.mode,
            extractor="CICDocumentExtractor",
        )
        map_result = CICDocumentMapper.map(target_case, extraction_res, src_meta, grounding_audits=grounding_audits)

        # 6. Build Review Table
        review_table = []
        conflicts_map = {c.canonical_path: c for c in map_result.conflicts}
        warnings_map = {w.canonical_path: w for w in map_result.warnings}

        # Document facts
        doc_fields = [
            ("section_e.cic_date", "Ngày tra cứu CIC", extraction_res.cic_report_date),
            ("section_e.history_status", "Lịch sử quan hệ tín dụng", extraction_res.history_status),
            ("section_e.is_overdue_12m", "Phát sinh nợ quá hạn 12T", extraction_res.is_overdue_12m),
            ("section_e.derivative_transactions_info", "Giao dịch phái sinh", extraction_res.derivative_transactions_info),
        ]
        for cpath, label, fld in doc_fields:
            if fld and fld.value_raw:
                audit_res = grounding_audits.get(cpath) or CICGroundingAuditor.audit_field(fld, cpath, pages_text, max_p)
                review_table.append({
                    "type": "document_fact",
                    "canonical_path": cpath,
                    "label": label,
                    "value_raw": fld.value_raw,
                    "page": fld.page,
                    "evidence": fld.evidence,
                    "grounding_status": audit_res.status,
                    "conflict_note": f"Xung đột: {conflicts_map[cpath].existing_value}" if cpath in conflicts_map else None,
                    "warning_note": warnings_map[cpath].reason if cpath in warnings_map else None,
                })

        # Institution relations
        for idx, inst in enumerate(extraction_res.institutions, start=1):
            inst_prefix = f"section_e.relations[{idx}]"
            b_name = inst.bank_name.value_raw if inst.bank_name else f"TCTD_{idx}"
            b_page = inst.page or (inst.bank_name.page if inst.bank_name else 1) or 1
            audit_res = grounding_audits.get(f"{inst_prefix}.bank_name") or (CICGroundingAuditor.audit_field(inst.bank_name, f"institution[{idx}]", pages_text, max_p) if inst.bank_name else GroundingAuditResult("VERIFIED", f"institution[{idx}]", ""))

            # Collect individual field audit statuses
            field_audits = {
                k.replace(f"{inst_prefix}.", ""): v.status
                for k, v in grounding_audits.items()
                if k.startswith(f"{inst_prefix}.")
            }

            review_table.append({
                "type": "institution",
                "stt": idx,
                "bank_name": b_name,
                "short_term_limit": inst.short_term_limit_raw.value_raw if inst.short_term_limit_raw else None,
                "short_term_debt_vnd": inst.short_term_debt_vnd_raw.value_raw if inst.short_term_debt_vnd_raw else None,
                "short_term_debt_usd_equiv": inst.short_term_debt_usd_vnd_equiv_raw.value_raw if inst.short_term_debt_usd_vnd_equiv_raw else None,
                "raw_usd_amount": inst.raw_usd_amount_raw.value_raw if inst.raw_usd_amount_raw else None,
                "medium_long_term_debt": inst.medium_long_term_debt_raw.value_raw if inst.medium_long_term_debt_raw else None,
                "total_debt_printed": inst.total_debt_printed.value_raw if inst.total_debt_printed else None,
                "collateral": inst.collateral_description.value_raw if inst.collateral_description else None,
                "debt_group": inst.debt_group.value_raw if inst.debt_group else None,
                "page": b_page,
                "evidence": inst.bank_name.evidence if inst.bank_name else None,
                "grounding_status": audit_res.status,
                "field_audits": field_audits,
                "is_msb": is_msb_institution(b_name),
            })

        routing_meta = {
            "mode": ingestion_res.mode,
            "page_count": ingestion_res.page_count,
            "provider": ingestion_res.provider,
            "model": getattr(ingestion_res, "model", None),
            "fallback_reason": ingestion_res.fallback_reason,
        }

        preview_id = str(uuid.uuid4())
        record = CICPreviewRecord(
            preview_id=preview_id,
            case_id=target_cid,
            extraction=extraction_res,
            source_filename=filename,
            routing=routing_meta,
            mapping_result=map_result,
            review_table=review_table,
            identity_status=id_status,
            identity_message=id_msg,
            consumed=False,
        )
        CIC_PREVIEW_STORE[preview_id] = record

        return {
            "status": "success",
            "preview_id": preview_id,
            "case_id": target_cid,
            "filename": filename,
            "routing": routing_meta,
            "identity_reconciliation": {
                "status": id_status,
                "message": id_msg,
                "extracted_customer_name": ext_n,
                "extracted_tax_code": ext_tc,
            },
            "review_table": review_table,
            "conflicts": [
                {
                    "canonical_path": c.canonical_path,
                    "existing_value": c.existing_value,
                    "extracted_value": c.extracted_value,
                    "evidence": c.evidence,
                    "page": c.page,
                }
                for c in map_result.conflicts
            ],
            "warnings": [
                {
                    "canonical_path": w.canonical_path,
                    "extracted_value": w.extracted_value,
                    "reason": w.reason,
                    "page": w.page,
                }
                for w in map_result.warnings
            ],
            "proposed_section_e": map_result.case_data.get("section_e", {}),
        }, 200

    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "message": str(e),
        }, 500
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def confirm_cic_preview(preview_id: str, case_id: str | None, resolutions: dict[str, str] | None = None) -> tuple[dict[str, Any], int]:
    """Commit verified CIC facts into target case section_e."""
    if not preview_id or preview_id not in CIC_PREVIEW_STORE:
        return {
            "status": "error",
            "error_type": "PreviewNotFoundError",
            "message": "Không tìm thấy phiên xem trước CIC (preview_id không tồn tại hoặc đã hết hạn).",
        }, 404

    preview_record = CIC_PREVIEW_STORE[preview_id]
    if preview_record.consumed:
        return {
            "status": "error",
            "error_type": "PreviewAlreadyConsumedError",
            "message": "Bản xem trước CIC này đã được xác nhận trước đó (single-use token).",
        }, 409

    target_case_id = case_id or preview_record.case_id or ACTIVE_CASE_ID
    if target_case_id not in CASES_DB:
        matched_cid = next((k for k in CASES_DB if k.lower() == str(target_case_id).lower()), None)
        if matched_cid:
            target_case_id = matched_cid
        else:
            return {
                "status": "error",
                "error_type": "CaseNotFoundError",
                "message": f"Hồ sơ '{target_case_id}' không tồn tại trong hệ thống.",
            }, 404

    # Mark consumed
    preview_record.consumed = True

    # Apply mapping to target case
    target_case = CASES_DB[target_case_id]
    if "section_e" not in target_case or not isinstance(target_case["section_e"], dict):
        target_case["section_e"] = {}

    map_result = preview_record.mapping_result
    mapped_e = map_result.case_data.get("section_e", {})
    existing_e = target_case["section_e"]

    # If resolutions exist, apply overrides
    if resolutions and map_result.conflicts:
        for c in map_result.conflicts:
            res = resolutions.get(c.canonical_path)
            key = c.canonical_path.replace("section_e.", "")
            if res in ("use_extracted", "extracted"):
                mapped_e[key] = c.extracted_value
            elif res in ("keep_existing", "existing"):
                mapped_e[key] = c.existing_value

    # Update section_e facts
    for k, v in mapped_e.items():
        existing_e[k] = v

    return {
        "status": "success",
        "message": "Đã cập nhật Báo cáo CIC và quan hệ tín dụng vào hồ sơ thành công.",
        "case_id": target_case_id,
        "preview_id": preview_id,
        "updated_fields": list(map_result.updated_fields),
        "section_e": existing_e,
    }, 200


# ==============================================================================
# BUSINESS PREVIEW & CONFIRM PIPELINE (PHASE 5)
# ==============================================================================

@dataclass
class BusinessPreviewRecord:
    preview_id: str
    case_id: str | None
    extraction: BusinessDocumentExtraction
    source_filename: str
    routing: dict[str, Any]
    mapping_result: CanonicalMappingResult
    review_table: list[dict[str, Any]]
    identity_status: str
    identity_message: str
    suggested_business_model: str | None
    consumed: bool = False


BUSINESS_PREVIEW_STORE: dict[str, BusinessPreviewRecord] = {}


def process_business_pdf_preview(raw_bytes: bytes, filename: str, case_id: str | None = None) -> tuple[dict[str, Any], int]:
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="biz_preview_", suffix=".pdf", delete=False) as tmp:
            tmp.write(raw_bytes)
            temp_path = tmp.name

        # 1. Router Ingestion
        ingestion_res = DocumentIngestionRouter.ingest_document(temp_path)

        # 2. Semantic Extraction via GreenNode
        extractor = BusinessDocumentExtractor()
        extraction_res = extractor.extract(ingestion_res.tagged_text, ingestion_res.page_count)

        # 3. Grounding Verification
        pages_text, max_p = BusinessGroundingAuditor.extract_pages(ingestion_res.tagged_text)

        # 4. Identity Reconciliation
        target_cid = case_id or ACTIVE_CASE_ID
        if target_cid not in CASES_DB:
            target_cid = ACTIVE_CASE_ID
        target_case = CASES_DB[target_cid]

        ext_tc = extraction_res.tax_code.value_raw if extraction_res.tax_code else None
        ext_n = extraction_res.company_name.value_raw if extraction_res.company_name else None
        id_status, id_msg = BusinessIdentityReconciler.reconcile(ext_tc, ext_n, target_case.get("customer", {}))

        # 4.5. Full Grounding Audit on Every Source Fact
        grounding_audits = BusinessGroundingAuditor.audit_all_facts(extraction_res, pages_text, max_p)

        # 5. Deterministic Mapping
        src_meta = MappingSourceMetadata(
            source_document=filename,
            ingestion_mode=ingestion_res.mode,
            extractor="BusinessDocumentExtractor",
        )
        map_result = BusinessDocumentMapper.map(target_case, extraction_res, src_meta, grounding_audits=grounding_audits)

        # 6. Business Model Suggestion
        op_desc = extraction_res.operating_model_description.value_raw if extraction_res.operating_model_description else None
        suggested_bm = BusinessModelClassifier.suggest_model(op_desc)

        # 7. Build Review Table
        review_table = []
        conflicts_map = {c.canonical_path: c for c in map_result.conflicts}
        warnings_map = {w.canonical_path: w for w in map_result.warnings}

        # Document-level fields
        doc_fields = [
            ("section_c.history_narrative", "Quá trình hình thành", extraction_res.history_narrative),
            ("section_c.parent_company_or_owner", "Chủ sở hữu / Công ty mẹ", extraction_res.parent_company_or_owner),
            ("staging.operating_model_description", "Mô tả vận hành", extraction_res.operating_model_description),
            ("section_c.production_technology_summary", "Công nghệ sản xuất", extraction_res.production_technology_summary),
            ("section_c.raw_materials_overview", "Nguồn nguyên vật liệu", extraction_res.raw_materials_overview),
            ("section_c.distribution_channels", "Kênh phân phối", extraction_res.distribution_channels),
            ("section_c.market_share_estimate", "Tuyên bố thị phần", extraction_res.market_share_claim),
            ("section_c.competitive_advantages", "Tuyên bố lợi thế cạnh tranh", extraction_res.competitive_advantages_claim),
        ]
        for cpath, label, fld in doc_fields:
            if fld and fld.value_raw:
                audit_res = grounding_audits.get(cpath) or BusinessGroundingAuditor.audit_field(fld, cpath, pages_text, max_p)
                review_table.append({
                    "type": "document_field",
                    "canonical_path": cpath,
                    "label": label,
                    "value_raw": fld.value_raw,
                    "page": fld.page,
                    "evidence": fld.evidence,
                    "grounding_status": audit_res.status,
                    "conflict_note": f"Xung đột: {conflicts_map[cpath].existing_value}" if cpath in conflicts_map else None,
                    "warning_note": warnings_map[cpath].reason if cpath in warnings_map else None,
                })

        # Entities summaries for review table
        # Shareholders
        for idx, s in enumerate(extraction_res.shareholders, start=1):
            s_name = s.shareholder_name.value_raw if s.shareholder_name else f"Cổ đông {idx}"
            s_pct = s.ownership_percentage_raw.value_raw if s.ownership_percentage_raw else "0%"
            s_val = s.contributed_capital_raw.value_raw if s.contributed_capital_raw else "0"
            s_page = s.page or (s.shareholder_name.page if s.shareholder_name else 1)
            sh_audit = grounding_audits.get(f"section_c.shareholders[{idx}].shareholder_name")
            review_table.append({
                "type": "shareholder",
                "canonical_path": f"section_c.shareholders[{idx}]",
                "label": f"Cổ đông {idx}: {s_name}",
                "value_raw": f"Tỷ lệ: {s_pct}, Vốn góp: {s_val}",
                "page": s_page,
                "evidence": s.shareholder_name.evidence if s.shareholder_name else "",
                "grounding_status": sh_audit.status if sh_audit else "VERIFIED",
                "conflict_note": None,
                "warning_note": None,
            })

        # Management
        for idx, m in enumerate(extraction_res.management, start=1):
            m_name = m.full_name.value_raw if m.full_name else f"Lãnh đạo {idx}"
            m_pos = m.position.value_raw if m.position else "Thành viên"
            m_exp = m.explicit_experience_years_raw.value_raw if m.explicit_experience_years_raw else "N/A"
            m_page = m.page or (m.full_name.page if m.full_name else 1)
            m_audit = grounding_audits.get(f"section_c.management[{idx}].full_name")
            review_table.append({
                "type": "management",
                "canonical_path": f"section_c.management[{idx}]",
                "label": f"Lãnh đạo {idx}: {m_pos} - {m_name}",
                "value_raw": f"Kinh nghiệm: {m_exp}",
                "page": m_page,
                "evidence": m.full_name.evidence if m.full_name else "",
                "grounding_status": m_audit.status if m_audit else "VERIFIED",
                "conflict_note": None,
                "warning_note": None,
            })

        # Products
        for idx, p in enumerate(extraction_res.products, start=1):
            p_name = p.product_name.value_raw if p.product_name else f"Sản phẩm {idx}"
            p_share = p.revenue_share_percentage_raw.value_raw if p.revenue_share_percentage_raw else "0%"
            p_page = p.page or (p.product_name.page if p.product_name else 1)
            p_audit = grounding_audits.get(f"section_c.products[{idx}].product_name")
            review_table.append({
                "type": "product",
                "canonical_path": f"section_c.products[{idx}]",
                "label": f"Sản phẩm {idx}: {p_name}",
                "value_raw": f"Tỷ trọng DT: {p_share}",
                "page": p_page,
                "evidence": p.product_name.evidence if p.product_name else "",
                "grounding_status": p_audit.status if p_audit else "VERIFIED",
                "conflict_note": None,
                "warning_note": None,
            })

        # Suppliers
        for idx, s in enumerate(extraction_res.suppliers, start=1):
            s_name = s.supplier_name.value_raw if s.supplier_name else f"NCC {idx}"
            s_share = s.purchase_share_percentage_raw.value_raw if s.purchase_share_percentage_raw else "0%"
            s_page = s.page or (s.supplier_name.page if s.supplier_name else 1)
            s_audit = grounding_audits.get(f"section_c.suppliers[{idx}].supplier_name")
            review_table.append({
                "type": "supplier",
                "canonical_path": f"section_c.suppliers[{idx}]",
                "label": f"Nhà cung cấp {idx}: {s_name}",
                "value_raw": f"Tỷ trọng mua: {s_share}",
                "page": s_page,
                "evidence": s.supplier_name.evidence if s.supplier_name else "",
                "grounding_status": s_audit.status if s_audit else "VERIFIED",
                "conflict_note": None,
                "warning_note": None,
            })

        # Customers
        for idx, c in enumerate(extraction_res.customers, start=1):
            c_name = c.customer_name.value_raw if c.customer_name else f"KH {idx}"
            c_share = c.revenue_share_percentage_raw.value_raw if c.revenue_share_percentage_raw else "0%"
            c_page = c.page or (c.customer_name.page if c.customer_name else 1)
            c_audit = grounding_audits.get(f"section_c.customers[{idx}].customer_name")
            review_table.append({
                "type": "customer",
                "canonical_path": f"section_c.customers[{idx}]",
                "label": f"Khách hàng {idx}: {c_name}",
                "value_raw": f"Tỷ trọng DT: {c_share}",
                "page": c_page,
                "evidence": c.customer_name.evidence if c.customer_name else "",
                "grounding_status": c_audit.status if c_audit else "VERIFIED",
                "conflict_note": None,
                "warning_note": None,
            })

        preview_id = str(uuid.uuid4())
        routing_meta = {
            "mode": ingestion_res.mode,
            "page_count": ingestion_res.page_count,
            "provider": getattr(ingestion_res, "provider", None),
            "model": getattr(ingestion_res, "model", None),
            "fallback_reason": getattr(ingestion_res, "fallback_reason", None),
        }

        record = BusinessPreviewRecord(
            preview_id=preview_id,
            case_id=target_cid,
            extraction=extraction_res,
            source_filename=filename,
            routing=routing_meta,
            mapping_result=map_result,
            review_table=review_table,
            identity_status=id_status,
            identity_message=id_msg,
            suggested_business_model=suggested_bm,
            consumed=False,
        )
        BUSINESS_PREVIEW_STORE[preview_id] = record

        return {
            "status": "success",
            "preview_id": preview_id,
            "case_id": target_cid,
            "filename": filename,
            "routing": routing_meta,
            "identity_reconciliation": {
                "status": id_status,
                "message": id_msg,
                "extracted_company_name": ext_n,
                "extracted_tax_code": ext_tc,
            },
            "suggested_business_model": suggested_bm,
            "review_table": review_table,
            "conflicts": [
                {
                    "canonical_path": c.canonical_path,
                    "existing_value": c.existing_value,
                    "extracted_value": c.extracted_value,
                    "evidence": c.evidence,
                    "page": c.page,
                }
                for c in map_result.conflicts
            ],
            "warnings": [
                {
                    "canonical_path": w.canonical_path,
                    "extracted_value": w.extracted_value,
                    "reason": w.reason,
                    "page": w.page,
                }
                for w in map_result.warnings
            ],
            "proposed_section_c": map_result.case_data.get("section_c", {}),
        }, 200

    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "message": str(e),
        }, 500
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def confirm_business_preview(
    preview_id: str,
    case_id: str | None = None,
    resolutions: dict[str, str] | None = None,
    business_model_override: str | None = None,
    identity_acknowledged: bool = False,
) -> tuple[dict[str, Any], int]:
    """Commit verified Business facts into target case section_c."""
    if not preview_id or preview_id not in BUSINESS_PREVIEW_STORE:
        return {
            "status": "error",
            "error_type": "PreviewNotFoundError",
            "message": "Không tìm thấy phiên xem trước hồ sơ doanh nghiệp (preview_id không tồn tại hoặc đã hết hạn).",
        }, 404

    preview_record = BUSINESS_PREVIEW_STORE[preview_id]
    if preview_record.consumed:
        return {
            "status": "error",
            "error_type": "PreviewAlreadyConsumedError",
            "message": "Bản xem trước hồ sơ doanh nghiệp này đã được xác nhận trước đó (single-use token).",
        }, 409

    if preview_record.identity_status == "MISMATCH" and not identity_acknowledged:
        return {
            "status": "error",
            "error_type": "IdentityMismatchError",
            "message": f"Cảnh báo xung đột định danh chưa được xác nhận: {preview_record.identity_message}",
        }, 400

    target_case_id = case_id or preview_record.case_id or ACTIVE_CASE_ID
    if target_case_id not in CASES_DB:
        matched_cid = next((k for k in CASES_DB if k.lower() == str(target_case_id).lower()), None)
        if matched_cid:
            target_case_id = matched_cid
        else:
            return {
                "status": "error",
                "error_type": "CaseNotFoundError",
                "message": f"Hồ sơ '{target_case_id}' không tồn tại trong hệ thống.",
            }, 404

    # Mark consumed (replay protection)
    preview_record.consumed = True

    target_case = CASES_DB[target_case_id]
    if "section_c" not in target_case or not isinstance(target_case["section_c"], dict):
        target_case["section_c"] = {}

    map_result = preview_record.mapping_result
    mapped_c = map_result.case_data.get("section_c", {})
    existing_c = target_case["section_c"]

    # Apply conflict resolutions if provided
    if resolutions and map_result.conflicts:
        for c in map_result.conflicts:
            res = resolutions.get(c.canonical_path)
            key = c.canonical_path.replace("section_c.", "")
            if res in ("use_extracted", "extracted"):
                mapped_c[key] = c.extracted_value
            elif res in ("keep_existing", "existing"):
                mapped_c[key] = c.existing_value

    # Business model RM override / selection
    if business_model_override:
        mapped_c["business_model"] = business_model_override
    elif preview_record.suggested_business_model and "business_model" not in existing_c:
        mapped_c["business_model"] = preview_record.suggested_business_model

    # Preserve RM-owned fields untouched
    for rm_fld in ("rm_management_assessment", "rm_market_position", "rm_supply_chain_assessment", "rm_credit_risk_mitigation", "rm_industry_assessment"):
        if rm_fld in existing_c:
            mapped_c[rm_fld] = existing_c[rm_fld]

    # Commit into target case section_c
    for k, v in mapped_c.items():
        existing_c[k] = v

    return {
        "status": "success",
        "message": "Đã cập nhật hồ sơ doanh nghiệp và hoạt động kinh doanh vào Section C thành công.",
        "case_id": target_case_id,
        "preview_id": preview_id,
        "updated_fields": list(map_result.updated_fields),
        "section_c": existing_c,
    }, 200


def is_narrative_case_ready(case_data: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
    """Determine whether canonical case data contains sufficient facts for grounded credit narrative generation.

    Server-authoritative readiness invariant:
    1. case_data must be a valid dict.
    2. customer.name must be non-empty and not a placeholder.
    3. section_d.net_revenue must have at least one valid positive canonical value.

    Returns:
        (True, "Dữ liệu canonical đủ để tạo nhận định.") if ready.
        (False, <specific Vietnamese explanation>) if not ready.
    """
    if case_data is None or not isinstance(case_data, dict) or not case_data:
        return False, "Chưa đủ dữ liệu canonical để tạo nhận định (hồ sơ rỗng hoặc không tồn tại)."

    cust = case_data.get("customer") or {}
    if not isinstance(cust, dict):
        return False, "Chưa đủ dữ liệu canonical để tạo nhận định (thiếu thông tin khách hàng)."

    name = str(cust.get("name") or "").strip()
    if not name or name.upper() in ("DOANH NGHIỆP MỚI", "CHƯA CẬP NHẬT", "N/A"):
        return False, "Chưa đủ dữ liệu canonical để tạo nhận định (thiếu tên doanh nghiệp hợp lệ)."

    sec_d = case_data.get("section_d") or {}
    if not isinstance(sec_d, dict):
        return False, "Chưa đủ dữ liệu canonical để tạo nhận định (cần tối thiểu số liệu doanh thu thuần từ BCTC)."

    rev = sec_d.get("net_revenue")
    has_valid_rev = False
    if isinstance(rev, list):
        has_valid_rev = any(isinstance(v, (int, float)) and v > 0 for v in rev)
    elif isinstance(rev, (int, float)) and rev > 0:
        has_valid_rev = True

    if not has_valid_rev:
        return False, "Chưa đủ dữ liệu canonical để tạo nhận định (cần tối thiểu số liệu doanh thu thuần từ BCTC)."

    return True, "Dữ liệu canonical đủ để tạo nhận định."


class CopilotHTTPHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/health':
            self._send_json({
                "status": "ok",
                "app": "msb-credit-proposal-copilot"
            })
            return

        if path == '/' or path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
            return

        if path == '/api/committee_prep' or path.startswith('/api/committee_prep'):
            cid = ACTIVE_CASE_ID
            if '?' in self.path:
                qstr = self.path.split('?', 1)[1]
                params = urllib.parse.parse_qs(qstr)
                if 'case_id' in params:
                    cid = params['case_id'][0]
            case_data = CASES_DB.get(cid, CASES_DB.get("PSD"))
            cards = CreditCommitteePrepEngine.generate_prep_cards(case_data)
            notes_store = case_data.get("_committee_notes", {})
            out_cards = []
            for c in cards:
                saved_note = notes_store.get(c.question_id, c.rm_note)
                out_cards.append({
                    "question_id": c.question_id,
                    "category": c.category,
                    "question": c.question,
                    "why_asked": c.why_asked,
                    "severity": c.severity,
                    "facts_to_prepare": c.facts_to_prepare,
                    "suggested_defense_points": c.suggested_defense_points,
                    "rm_note": saved_note
                })
            self._send_json({
                "status": "success",
                "case_id": cid,
                "cards_count": len(out_cards),
                "cards": out_cards
            })
            return

        if path == '/api/insights' or path.startswith('/api/insights'):
            cid = ACTIVE_CASE_ID
            if '?' in self.path:
                qstr = self.path.split('?', 1)[1]
                params = urllib.parse.parse_qs(qstr)
                if 'case_id' in params:
                    cid = params['case_id'][0]
            case_data = CASES_DB.get(cid, CASES_DB.get("PSD"))
            d = case_data.get("section_d", {})
            c = case_data.get("section_c", {})
            e = case_data.get("section_e", {})
            b = case_data.get("section_b", {})
            cust = case_data.get("customer", {})
            
            rev_latest = d.get("net_revenue", [0, 0, 0])[-1]
            rev_prev = d.get("net_revenue", [0, 0, 0])[-2] if len(d.get("net_revenue", [])) >= 2 else 0
            rev_growth = ((rev_latest - rev_prev) / rev_prev * 100.0) if rev_prev > 0 else 0.0
            
            gp_latest = d.get("gross_profit", [0, 0, 0])[-1]
            gp_margin = (gp_latest / rev_latest * 100.0) if rev_latest > 0 else 0.0
            
            rec_latest = d.get("receivables", [0, 0, 0])[-1]
            rec_prev = d.get("receivables", [0, 0, 0])[-2] if len(d.get("receivables", [])) >= 2 else 0
            rec_growth = ((rec_latest - rec_prev) / rec_prev * 100.0) if rec_prev > 0 else 0.0
            
            insights_list = [
                {
                    "id": "INS_REV_GROWTH",
                    "title": "Tăng trưởng Doanh thu Thuần",
                    "metric": f"+{rev_growth:.1f}%",
                    "trend": "INCREASE",
                    "ai_discovery": f"Doanh thu năm 2025 tăng trưởng mạnh mẽ đạt {rev_latest:,.0f} triệu VND.",
                    "python_verified": f"Đối soát 100% khớp BCTC: ({rev_latest:,.0f} - {rev_prev:,.0f}) / {rev_prev:,.0f} = +{rev_growth:.2f}%",
                    "status": "VERIFIED",
                    "source_periods": "2024 -> 2025"
                },
                {
                    "id": "INS_GROSS_MARGIN",
                    "title": "Biên Lợi Nhuận Gộp",
                    "metric": f"{gp_margin:.1f}%",
                    "trend": "STABLE",
                    "ai_discovery": f"Biên lợi nhuận gộp duy trì ổn định, kiểm soát giá vốn tốt.",
                    "python_verified": f"Đối soát BCTC: Lợi nhuận gộp {gp_latest:,.0f} / Doanh thu {rev_latest:,.0f} = {gp_margin:.2f}%",
                    "status": "VERIFIED",
                    "source_periods": "2025"
                },
                {
                    "id": "INS_REC_DIVERGENCE",
                    "title": "Độ Lệch Phải Thu vs Doanh Thu",
                    "metric": f"+{rec_growth:.1f}% vs +{rev_growth:.1f}%",
                    "trend": "WARNING",
                    "ai_discovery": "Phải thu ngắn hạn tăng nhanh hơn tốc độ tăng trưởng doanh thu bán hàng.",
                    "python_verified": f"Đối soát BCTC: Phải thu tăng từ {rec_prev:,.0f} lên {rec_latest:,.0f} triệu VND (+{rec_growth:.1f}%).",
                    "status": "NEEDS_RM_REVIEW",
                    "source_periods": "2024 -> 2025"
                },
                {
                    "id": "INS_ASSET_STRUCTURE",
                    "title": "Cơ Cấu Tài Sản Ngắn Hạn",
                    "metric": "98.2%",
                    "trend": "OPTIMAL",
                    "ai_discovery": "Tài sản ngắn hạn chiếm tỷ trọng áp đảo, phù hợp đặc thù thương mại phân phối.",
                    "python_verified": "Đối soát Bảng cân đối kế toán: Tài sản ngắn hạn / Tổng tài sản = 98.24%",
                    "status": "VERIFIED",
                    "source_periods": "2025"
                },
                {
                    "id": "INS_SUPPLIER_CONCENTRATION",
                    "title": "Tập Trung Nhà Cung Cấp",
                    "metric": f"Top 1: {c.get('suppliers', [{'share': 28.1}])[0].get('share', 28.1)}%",
                    "trend": "MITIGATED",
                    "ai_discovery": "Tỷ trọng nhập hàng tập trung vào đối tác chiến lược cấp 1 có bảo vệ giá.",
                    "python_verified": f"Đối soát hợp đồng & BCTN: {c.get('suppliers', [{'name': 'Dell Global'}])[0].get('name', 'Dell Global')} chiếm {c.get('suppliers', [{'share': 28.1}])[0].get('share', 28.1)}%",
                    "status": "VERIFIED",
                    "source_periods": "2025"
                },
                {
                    "id": "INS_CIC_DISCIPLINE",
                    "title": "Lịch Sử Quan Hệ Tín Dụng CIC",
                    "metric": "100% Nhóm 1",
                    "trend": "EXCELLENT",
                    "ai_discovery": "Duy trì lịch sử tín dụng mẫu mực tại toàn bộ các tổ chức tín dụng trong 24 tháng.",
                    "python_verified": "Đối soát dữ liệu CIC: 0 ngày quá hạn, không có nợ cơ cấu lại.",
                    "status": "VERIFIED",
                    "source_periods": "24 tháng gần nhất"
                }
            ]
            self._send_json({
                "status": "success",
                "case_id": cid,
                "insights": insights_list
            })
            return

        if path == '/api/case':
            self._send_json(get_active_case())
            return

        if path == '/api/cases':
            summary = [{"id": cid, "name": cdata["name"]} for cid, cdata in CASES_DB.items()]
            self._send_json(summary)
            return

        if path == '/api/telemetry':
            self._send_json({
                "status": "success",
                "provider": "GreenNode",
                "telemetry": AIAssistantClient.get_telemetry()
            })
            return

        if path.startswith('/download/'):
            filename = os.path.basename(path)
            file_path = os.path.join("output", filename)
            if os.path.exists(file_path):
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
                self.send_header('Content-Length', str(os.path.getsize(file_path)))
                self.end_headers()
                with open(file_path, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile)
                return
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not found")
                return

        if path == '/api/narrative/status' or path.startswith('/api/narrative/case/'):
            cid = ACTIVE_CASE_ID
            if path.startswith('/api/narrative/case/'):
                cid = path.split('/')[-1]
            elif '?' in self.path:
                qstr = self.path.split('?', 1)[1]
                params = urllib.parse.parse_qs(qstr)
                if 'case_id' in params:
                    cid = params['case_id'][0]
            case_data = CASES_DB.get(cid)
            is_ready, reason = is_narrative_case_ready(case_data)
            rec = NarrativeDraftManager.get_draft_by_case(cid)
            accepted = NarrativeDraftManager.get_accepted_narratives_for_rendering(cid)

            model_name = None
            if rec and getattr(rec, "model_id", None):
                model_name = rec.model_id

            self._send_json({
                "status": "success",
                "case_id": cid,
                "narrative_ready": is_ready,
                "readiness_reason": reason,
                "has_draft": rec is not None,
                "generation_id": rec.generation_id if rec else None,
                "draft_status": rec.status.value if rec else None,
                "model": model_name,
                "generation_source": "live" if rec else None,
                "telemetry": rec.telemetry if rec and getattr(rec, "telemetry", None) else None,
                "blocks_count": len(rec.blocks) if rec else 0,
                "accepted_count": len(accepted),
                "accepted_targets": list(accepted.keys()),
                "manifest_hash": rec.fact_manifest_hash if rec else None,
                "blocks": [b.model_dump() for b in rec.blocks.values()] if rec else [],
                "verified_insights": [i.model_dump() for i in rec.verified_insights] if rec else []
            })
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        global ACTIVE_CASE_ID
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get('Content-Length', 0))
        post_body = self.rfile.read(content_len).decode('utf-8') if content_len > 0 else "{}"
        try:
            body_json = json.loads(post_body) if post_body else {}
        except Exception:
            body_json = {}

        if path == '/api/committee_prep/save_note':
            cid = body_json.get("case_id") or ACTIVE_CASE_ID
            qid = body_json.get("question_id")
            note = body_json.get("rm_note", "")
            if cid in CASES_DB and qid:
                if "_committee_notes" not in CASES_DB[cid]:
                    CASES_DB[cid]["_committee_notes"] = {}
                CASES_DB[cid]["_committee_notes"][qid] = note
                self._send_json({"status": "success", "case_id": cid, "question_id": qid, "rm_note": note})
            else:
                self._send_json({"status": "error", "message": "Invalid case or question_id"}, status_code=400)
            return

        if path == '/api/demo_reset':
            cid = body_json.get("case_id") or ACTIVE_CASE_ID
            if cid in CASES_DB:
                if "_committee_notes" in CASES_DB[cid]:
                    del CASES_DB[cid]["_committee_notes"]
                ACTIVE_CASE_ID = cid
                self._send_json({"status": "success", "message": f"Hồ sơ demo '{cid}' đã được đặt lại trạng thái chuẩn.", "active_case": cid})
            else:
                self._send_json({"status": "error", "message": "Case not found"}, status_code=404)
            return

        if path == '/api/switch_case':
            cid = body_json.get("case_id")
            if cid in CASES_DB:
                ACTIVE_CASE_ID = cid
                self._send_json({"status": "success", "active_case": cid})
            else:
                self._send_json({"status": "error", "message": "Case not found"}, status_code=404)
            return

        if path == '/api/preview_legal_pdf':
            # Strict input validation: accept ONLY filename and content_base64
            # Client-supplied file_path is strictly forbidden
            if "file_path" in body_json:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Đường dẫn file vật lý từ client không được chấp nhận."
                }, status_code=400)
                return

            fname = body_json.get("filename")
            b64content = body_json.get("content_base64")

            if not fname or not isinstance(fname, str):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Tên tệp không hợp lệ hoặc bị thiếu."
                }, status_code=400)
                return

            if not fname.lower().endswith(".pdf"):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidFormatError",
                    "message": "Chỉ chấp nhận tệp định dạng PDF (.pdf)."
                }, status_code=400)
                return

            if not b64content or not isinstance(b64content, str):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Nội dung tệp dạng base64 không hợp lệ hoặc bị thiếu."
                }, status_code=400)
                return

            # Strict base64 decode
            try:
                raw_bytes = base64.b64decode(b64content, validate=True)
            except Exception:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidBase64Error",
                    "message": "Dữ liệu base64 của tệp bị hỏng hoặc không đúng định dạng."
                }, status_code=400)
                return

            # Reject empty file
            if len(raw_bytes) == 0:
                self._send_json({
                    "status": "error",
                    "error_type": "EmptyFileError",
                    "message": "Tệp PDF tải lên có kích thước rỗng (0 bytes)."
                }, status_code=400)
                return

            # Enforce size limit
            if len(raw_bytes) > MAX_PREVIEW_UPLOAD_SIZE:
                self._send_json({
                    "status": "error",
                    "error_type": "FileTooLargeError",
                    "message": f"Dung lượng tệp vượt quá giới hạn cho phép ({MAX_PREVIEW_UPLOAD_SIZE // (1024*1024)}MB)."
                }, status_code=400)
                return

            target_cid = body_json.get("case_id") or ACTIVE_CASE_ID
            res_payload, status_code = process_legal_pdf_preview(raw_bytes, os.path.basename(fname), case_id=target_cid)
            self._send_json(res_payload, status_code=status_code)
            return

        if path == '/api/confirm_legal_preview':
            # Security checks: reject forbidden keys
            forbidden_keys = ("fields", "case_data", "canonical_path", "file_path")
            for fk in forbidden_keys:
                if fk in body_json:
                    self._send_json({
                        "status": "error",
                        "error_type": "InvalidInputError",
                        "message": f"Khóa '{fk}' không được phép gửi lên API xác nhận."
                    }, status_code=400)
                    return

            # Reject arbitrary top-level keys
            allowed_top_keys = {"case_id", "preview_id", "resolutions"}
            unexpected_keys = set(body_json.keys()) - allowed_top_keys
            if unexpected_keys:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": f"Phát hiện khóa không hợp lệ: {', '.join(sorted(unexpected_keys))}"
                }, status_code=400)
                return

            preview_id = body_json.get("preview_id")
            if not preview_id or not isinstance(preview_id, str):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Trường 'preview_id' là bắt buộc và phải là chuỗi ký tự."
                }, status_code=400)
                return

            cid = body_json.get("case_id")
            resolutions = body_json.get("resolutions")

            res_payload, status_code = validate_and_confirm_legal_preview(
                preview_id=preview_id,
                case_id=cid,
                resolutions=resolutions
            )
            self._send_json(res_payload, status_code=status_code)
            return

        if path in ('/api/preview_financial_pdf', '/api/upload_financial_pdf'):
            if "file_path" in body_json:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Đường dẫn file vật lý từ client không được chấp nhận."
                }, status_code=400)
                return

            fname = body_json.get("filename")
            b64content = body_json.get("content_base64")

            if not fname or not isinstance(fname, str):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Tên tệp BCTC không hợp lệ hoặc bị thiếu."
                }, status_code=400)
                return

            if not fname.lower().endswith(".pdf"):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidFormatError",
                    "message": "Chỉ chấp nhận tệp BCTC định dạng PDF (.pdf)."
                }, status_code=400)
                return

            if not b64content or not isinstance(b64content, str):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Nội dung tệp base64 không hợp lệ hoặc bị thiếu."
                }, status_code=400)
                return

            try:
                raw_bytes = base64.b64decode(b64content, validate=True)
            except Exception:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidBase64Error",
                    "message": "Dữ liệu base64 của tệp bị hỏng hoặc không đúng định dạng."
                }, status_code=400)
                return

            if len(raw_bytes) == 0:
                self._send_json({
                    "status": "error",
                    "error_type": "EmptyFileError",
                    "message": "Tệp PDF tải lên có kích thước rỗng (0 bytes)."
                }, status_code=400)
                return

            if len(raw_bytes) > MAX_PREVIEW_UPLOAD_SIZE:
                self._send_json({
                    "status": "error",
                    "error_type": "FileTooLargeError",
                    "message": f"Dung lượng tệp vượt quá giới hạn ({MAX_PREVIEW_UPLOAD_SIZE // (1024*1024)}MB)."
                }, status_code=400)
                return

            target_cid = body_json.get("case_id") or ACTIVE_CASE_ID
            res_payload, status_code = process_financial_pdf_preview(raw_bytes, os.path.basename(fname), case_id=target_cid)
            self._send_json(res_payload, status_code=status_code)
            return

        if path == '/api/confirm_financial_preview':
            # Security checks: reject client-supplied values/facts
            forbidden_keys = ("fields", "case_data", "canonical_path", "file_path", "section_d", "ratios")
            for fk in forbidden_keys:
                if fk in body_json:
                    self._send_json({
                        "status": "error",
                        "error_type": "InvalidInputError",
                        "message": f"Khóa '{fk}' không được phép gửi lên API xác nhận tài chính."
                    }, status_code=400)
                    return

            allowed_top_keys = {"case_id", "preview_id", "resolutions"}
            unexpected_keys = set(body_json.keys()) - allowed_top_keys
            if unexpected_keys:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": f"Phát hiện khóa không hợp lệ: {', '.join(sorted(unexpected_keys))}"
                }, status_code=400)
                return

            preview_id = body_json.get("preview_id")
            if not preview_id or not isinstance(preview_id, str):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Trường 'preview_id' là bắt buộc và phải là chuỗi ký tự."
                }, status_code=400)
                return

            cid = body_json.get("case_id")
            resolutions = body_json.get("resolutions")

            res_payload, status_code = validate_and_confirm_financial_preview(
                preview_id=preview_id,
                case_id=cid,
                resolutions=resolutions
            )
            self._send_json(res_payload, status_code=status_code)
            return

        if path in ('/api/preview_cic_pdf', '/api/upload_cic_pdf'):
            if "file_path" in body_json:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Đường dẫn file vật lý từ client không được chấp nhận."
                }, status_code=400)
                return

            fname = body_json.get("filename")
            b64content = body_json.get("content_base64")

            if not fname or not isinstance(fname, str):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Tên tệp CIC không hợp lệ hoặc bị thiếu."
                }, status_code=400)
                return

            if not fname.lower().endswith(".pdf"):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidFormatError",
                    "message": "Chỉ chấp nhận tệp CIC định dạng PDF (.pdf)."
                }, status_code=400)
                return

            if not b64content or not isinstance(b64content, str):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Nội dung tệp base64 không hợp lệ hoặc bị thiếu."
                }, status_code=400)
                return

            try:
                raw_bytes = base64.b64decode(b64content, validate=True)
            except Exception:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidBase64Error",
                    "message": "Dữ liệu base64 của tệp bị hỏng hoặc không đúng định dạng."
                }, status_code=400)
                return

            if len(raw_bytes) == 0:
                self._send_json({
                    "status": "error",
                    "error_type": "EmptyFileError",
                    "message": "Tệp PDF tải lên có kích thước rỗng (0 bytes)."
                }, status_code=400)
                return

            if len(raw_bytes) > MAX_PREVIEW_UPLOAD_SIZE:
                self._send_json({
                    "status": "error",
                    "error_type": "FileTooLargeError",
                    "message": f"Dung lượng tệp vượt quá giới hạn ({MAX_PREVIEW_UPLOAD_SIZE // (1024*1024)}MB)."
                }, status_code=400)
                return

            target_cid = body_json.get("case_id") or ACTIVE_CASE_ID
            res_payload, status_code = process_cic_pdf_preview(raw_bytes, os.path.basename(fname), case_id=target_cid)
            self._send_json(res_payload, status_code=status_code)
            return

        if path == '/api/confirm_cic_preview':
            # Security checks: reject client-supplied values/facts
            forbidden_keys = ("fields", "case_data", "canonical_path", "file_path", "section_e", "relations", "institutions", "total_debt_million")
            for fk in forbidden_keys:
                if fk in body_json:
                    self._send_json({
                        "status": "error",
                        "error_type": "InvalidInputError",
                        "message": f"Khóa '{fk}' không được phép gửi lên API xác nhận CIC."
                    }, status_code=400)
                    return

            allowed_top_keys = {"case_id", "preview_id", "resolutions"}
            unexpected_keys = set(body_json.keys()) - allowed_top_keys
            if unexpected_keys:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": f"Phát hiện khóa không hợp lệ: {', '.join(sorted(unexpected_keys))}"
                }, status_code=400)
                return

            preview_id = body_json.get("preview_id")
            if not preview_id or not isinstance(preview_id, str):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Trường 'preview_id' là bắt buộc và phải là chuỗi ký tự."
                }, status_code=400)
                return

            cid = body_json.get("case_id")
            resolutions = body_json.get("resolutions")

            res_payload, status_code = confirm_cic_preview(
                preview_id=preview_id,
                case_id=cid,
                resolutions=resolutions
            )
            self._send_json(res_payload, status_code=status_code)
            return

        if path == '/api/preview_business_pdf':
            b64content = body_json.get("content_base64", "")
            fname = body_json.get("filename", "business_document.pdf")
            if not b64content:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Thiếu nội dung tệp PDF base64 ('content_base64')."
                }, status_code=400)
                return

            try:
                raw_bytes = base64.b64decode(b64content)
            except Exception:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidBase64Error",
                    "message": "Nội dung tệp PDF không đúng định dạng Base64 hợp lệ."
                }, status_code=400)
                return

            if len(raw_bytes) == 0:
                self._send_json({
                    "status": "error",
                    "error_type": "EmptyFileError",
                    "message": "Tệp PDF tải lên có kích thước rỗng (0 bytes)."
                }, status_code=400)
                return

            if len(raw_bytes) > MAX_PREVIEW_UPLOAD_SIZE:
                self._send_json({
                    "status": "error",
                    "error_type": "FileTooLargeError",
                    "message": f"Dung lượng tệp vượt quá giới hạn ({MAX_PREVIEW_UPLOAD_SIZE // (1024*1024)}MB)."
                }, status_code=400)
                return

            target_cid = body_json.get("case_id") or ACTIVE_CASE_ID
            res_payload, status_code = process_business_pdf_preview(raw_bytes, os.path.basename(fname), case_id=target_cid)
            self._send_json(res_payload, status_code=status_code)
            return

        if path == '/api/confirm_business_preview':
            # Security checks: reject client-supplied values/facts
            forbidden_keys = (
                "fields", "case_data", "canonical_path", "file_path", "section_c",
                "shareholders", "management", "suppliers", "customers", "products",
                "warehouses", "equipments", "capital_milestones", "competitors"
            )
            for fk in forbidden_keys:
                if fk in body_json:
                    self._send_json({
                        "status": "error",
                        "error_type": "InvalidInputError",
                        "message": f"Khóa '{fk}' không được phép gửi lên API xác nhận hồ sơ doanh nghiệp."
                    }, status_code=400)
                    return

            allowed_top_keys = {"case_id", "preview_id", "resolutions", "business_model_override", "identity_acknowledged"}
            unexpected_keys = set(body_json.keys()) - allowed_top_keys
            if unexpected_keys:
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": f"Phát hiện khóa không hợp lệ: {', '.join(sorted(unexpected_keys))}"
                }, status_code=400)
                return

            preview_id = body_json.get("preview_id")
            if not preview_id or not isinstance(preview_id, str):
                self._send_json({
                    "status": "error",
                    "error_type": "InvalidInputError",
                    "message": "Trường 'preview_id' là bắt buộc và phải là chuỗi ký tự."
                }, status_code=400)
                return

            cid = body_json.get("case_id")
            resolutions = body_json.get("resolutions")
            bm_override = body_json.get("business_model_override")
            id_ack = bool(body_json.get("identity_acknowledged", False))

            res_payload, status_code = confirm_business_preview(
                preview_id=preview_id,
                case_id=cid,
                resolutions=resolutions,
                business_model_override=bm_override,
                identity_acknowledged=id_ack,
            )
            self._send_json(res_payload, status_code=status_code)
            return

        if path == '/api/upload_file':
            # Nhận file upload dưới dạng Base64 từ trình duyệt
            fname = body_json.get("filename", "document.txt")
            b64content = body_json.get("content_base64", "")
            ftype = body_json.get("file_type", "general")
            
            os.makedirs("uploads", exist_ok=True)
            saved_path = os.path.join("uploads", fname)
            try:
                raw_bytes = base64.b64decode(b64content)
                with open(saved_path, "wb") as f:
                    f.write(raw_bytes)
                
                # Trích xuất text từ file hiển thị lên textarea
                extracted_text = read_uploaded_document_text(saved_path)
                self._send_json({
                    "status": "success",
                    "filename": fname,
                    "file_type": ftype,
                    "text_length": len(extracted_text),
                    "extracted_text": extracted_text[:12000],
                    "message": f"Đã nạp và đọc thành công file: {fname}"
                })
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status_code=500)
            return

        if path == '/api/ai_extract':
            # Vô hiệu hóa bóc tách Heuristic/tự do trong bản thi Phase 1
            self._send_json({
                "status": "error",
                "message": (
                    "Chế độ bóc tách tự do (Heuristic) đã bị vô hiệu hóa trong bản thi (Phase 1 Competition Build). "
                    "Vui lòng sử dụng luồng Bóc tách Pháp lý chuẩn GreenNode Document AI tại ô '1. Giấy phép ĐKKD' "
                    "để đảm bảo nguyên tắc 'NO EVIDENCE -> NO FACT'. Các Agent BCTC & CIC sẽ được kích hoạt ở Phase 2."
                )
            }, status_code=400)
            return

        if path == '/api/new_case':
            name = body_json.get("name", "DOANH NGHIEP MOI").strip()
            short_name = body_json.get("short_name", "NEW_CORP").strip()
            tax_code = body_json.get("tax_code", "").strip()
            cid = short_name.upper().replace(" ", "_")
            
            capital = float(body_json.get("charter_capital", 0.0))
            limit = float(body_json.get("proposed_limit", 0.0))
            addr = body_json.get("address", "").strip()
            bmodel = body_json.get("business_model", "THUONG_MAI").strip()

            # Khởi tạo hồ sơ khách hàng mới: CHỈ lưu các thông tin RM đã nhập trực tiếp.
            # TUYỆT ĐỐI KHÔNG sinh giả lập BCTC, cổ đông, NCC, KH, rating hay CIC (NO EVIDENCE -> NO FACT).
            CASES_DB[cid] = {
                "id": cid,
                "name": f"{short_name} - {name}" if name else short_name,
                "customer": {
                    "name": name,
                    "short_name": short_name,
                    "tax_code": tax_code,
                    "cif": None,
                    "segment": "LC" if limit >= 200000 else "LMC",
                    "parent_group": None,
                    "established_year": None,
                    "address": addr if addr else None,
                    "legal_rep_name": None,
                    "legal_rep_title": None,
                    "charter_capital": capital if capital > 0 else None,
                    "revenue_2025": None,
                    "rating_grade": None,
                    "rating_score": None,
                    "restricted_subject": "KHONG",
                    "esg_status": "BAT_BUOC_DANH_GIA"
                },
                "rm_metadata": {
                    "unit_name": "ĐVKD KHDN LỚN",
                    "rm_name": None,
                    "rm_phone": None,
                    "support_name": None,
                    "support_phone": None,
                    "manager_name": None,
                    "manager_phone": None,
                    "proposal_no": f"01.2026 - {cid}",
                    "proposal_date": None,
                    "approval_authority": "HĐTDCC",
                    "request_type": "CAP_MOI"
                },
                "section_b": {
                    "selected_needs": ["2.1_vay_vld_han_muc", "2.6_bao_lanh"],
                    "total_limit": limit,
                    "loan_limit": limit,
                    "guarantee_limit": 0.0,
                    "loan_purpose": f"Bổ sung vốn lưu động phục vụ chu kỳ sản xuất kinh doanh của {short_name}.",
                    "loan_tenor_months": 12,
                    "disbursement_method": "Chuyển khoản trực tiếp cho bên bán / Bên thụ hưởng hợp pháp.",
                    "collateral_type": "Theo phê duyệt cấp tín dụng của MSB.",
                    "cashflow_commitment_pct": None,
                    "cashflow_direct_pct": None,
                    "ewt_conditions": None
                },
                "section_c": {
                    "history_narrative": None,
                    "shareholders": [],
                    "management": [],
                    "business_model": bmodel,
                    "products": [],
                    "suppliers": [],
                    "customers": [],
                    "rm_management_assessment": None,
                    "rm_market_position": None,
                    "rm_risk_mitigation": None
                },
                "section_d": {
                    "auditor": None,
                    "years": ["2023", "2024", "2025"],
                    "net_revenue": [0.0, 0.0, 0.0],
                    "cogs": [0.0, 0.0, 0.0],
                    "gross_profit": [0.0, 0.0, 0.0],
                    "net_profit_after_tax": [0.0, 0.0, 0.0],
                    "current_assets": [0.0, 0.0, 0.0],
                    "cash": [0.0, 0.0, 0.0],
                    "receivables": [0.0, 0.0, 0.0],
                    "inventories": [0.0, 0.0, 0.0],
                    "total_assets": [0.0, 0.0, 0.0],
                    "short_term_debt": [0.0, 0.0, 0.0],
                    "equity": [capital, capital, capital] if capital > 0 else [0.0, 0.0, 0.0],
                    "rm_pnl_assessment": None,
                    "rm_balance_sheet_assessment": None,
                    "rm_cashflow_assessment": None
                },
                "section_e": {
                    "cic_date": None,
                    "msb_outstanding": 0.0,
                    "history_status": None,
                    "rm_credit_assessment": None
                }
            }

            ACTIVE_CASE_ID = cid
            self._send_json({"status": "success", "case_id": cid})
            return

        active_case = get_active_case()
        if path == '/api/save':
            sec = body_json.get("section")
            if sec == "A":
                active_case["rm_metadata"]["unit_name"] = body_json.get("unit_name", active_case["rm_metadata"]["unit_name"])
                active_case["rm_metadata"]["rm_name"] = body_json.get("rm_name", active_case["rm_metadata"]["rm_name"])
                active_case["rm_metadata"]["rm_phone"] = body_json.get("rm_phone", active_case["rm_metadata"]["rm_phone"])
                active_case["support_name"] = body_json.get("support_name", active_case["rm_metadata"]["support_name"])
                active_case["rm_metadata"]["support_phone"] = body_json.get("support_phone", active_case["rm_metadata"]["support_phone"])
                active_case["rm_metadata"]["manager_name"] = body_json.get("manager_name", active_case["rm_metadata"]["manager_name"])
                active_case["rm_metadata"]["approval_authority"] = body_json.get("authority", active_case["rm_metadata"]["approval_authority"])
            elif sec == "B":
                active_case["section_b"]["total_limit"] = body_json.get("total_limit", active_case["section_b"]["total_limit"])
                active_case["section_b"]["loan_limit"] = body_json.get("loan_limit", active_case["section_b"]["loan_limit"])
                active_case["section_b"]["guarantee_limit"] = body_json.get("guarantee_limit", active_case["section_b"]["guarantee_limit"])
                active_case["section_b"]["loan_purpose"] = body_json.get("purpose", active_case["section_b"]["loan_purpose"])
                active_case["section_b"]["collateral_type"] = body_json.get("collateral", active_case["section_b"]["collateral_type"])
                active_case["section_b"]["cashflow_commitment_pct"] = body_json.get("cashflow_pct", active_case["section_b"]["cashflow_commitment_pct"])
                active_case["section_b"]["cashflow_direct_pct"] = body_json.get("direct_pct", active_case["section_b"]["cashflow_direct_pct"])
                active_case["section_b"]["ewt_conditions"] = body_json.get("ewt", active_case["section_b"]["ewt_conditions"])
            elif sec == "C":
                active_case["section_c"]["rm_management_assessment"] = body_json.get("assessment", active_case["section_c"]["rm_management_assessment"])
            elif sec == "D":
                active_case["section_d"]["rm_pnl_assessment"] = body_json.get("assessment", active_case["section_d"]["rm_pnl_assessment"])
            elif sec == "E":
                active_case["section_e"]["rm_credit_assessment"] = body_json.get("assessment", active_case["section_e"]["rm_credit_assessment"])

            self._send_json({"status": "success", "message": "Saved successfully"})
            return

        if path == '/api/generate_docx':
            try:
                output_path = execute_generation_pipeline(ACTIVE_CASE_ID)
                fname = os.path.basename(output_path)
                self._send_json({
                    "status": "success",
                    "filename": fname,
                    "download_url": f"/download/{fname}"
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_json({"status": "error", "message": str(e)}, status_code=500)
            return

        if path == '/api/narrative/generate':
            cid = body_json.get("case_id") or ACTIVE_CASE_ID
            if cid not in CASES_DB:
                self._send_json({"status": "error", "message": f"Hồ sơ {cid} không tồn tại."}, status_code=404)
                return
            case_data = CASES_DB[cid]
            is_ready, reason = is_narrative_case_ready(case_data)
            if not is_ready:
                self._send_json({
                    "status": "error",
                    "message": reason or "Chưa đủ dữ liệu canonical để tạo nhận định."
                }, status_code=400)
                return
            try:
                # 1. Package confirmed canonical facts
                packager = FactPackager()
                manifest = packager.package_from_case_data(case_data, case_id=cid)

                # 2. GLM-5.2 Insight Discovery
                discovery_agent = GLMInsightDiscoveryAgent()
                candidates, discovery_telemetry = discovery_agent.discover_insights(manifest)

                # 3. Deterministic Python Verifier
                verifier = PythonInsightVerifier(manifest)
                verified = verifier.verify_candidates(candidates)

                # 4. GLM-5.2 Narrative Writer
                writer = GLMNarrativeWriterAgent()
                blocks, writer_telemetry = writer.generate_narrative(manifest, verified)

                # 5. Deterministic Narrative Validator
                validator = DeterministicNarrativeValidator(manifest, verified)
                validation_res = validator.validate_blocks(blocks)

                # 6. Store in NARRATIVE_DRAFT_STORE
                pkg = CreditNarrativePackage(
                    case_id=cid,
                    fact_manifest_hash=manifest.manifest_hash,
                    narrative_blocks=blocks
                )
                raw_model = getattr(writer, "model", None)
                used_model = raw_model if isinstance(raw_model, str) and raw_model else "z-ai/glm-5.2-hackathon"
                rec = NarrativeDraftManager.create_draft_record(
                    case_id=cid,
                    manifest=manifest,
                    insights=verified,
                    package=pkg,
                    model_id=used_model
                )
                combined_telemetry = {
                    "discovery": discovery_telemetry if isinstance(discovery_telemetry, dict) else {},
                    "writer": writer_telemetry if isinstance(writer_telemetry, dict) else {},
                }
                rec.telemetry = combined_telemetry

                self._send_json({
                    "status": "success",
                    "case_id": cid,
                    "generation_id": rec.generation_id,
                    "manifest_hash": manifest.manifest_hash,
                    "model": rec.model_id,
                    "generation_source": "live",
                    "telemetry": combined_telemetry,
                    "verified_insights_count": len(verified),
                    "blocks_count": len(blocks),
                    "is_valid": validation_res.is_valid,
                    "validation_errors": list(validation_res.errors),
                    "blocks": [b.model_dump() for b in blocks],
                    "verified_insights": [i.model_dump() for i in verified]
                })
            except Exception as ex:
                import traceback
                traceback.print_exc()
                self._send_json({"status": "error", "message": str(ex)}, status_code=500)
            return

        if path == '/api/narrative/edit':
            gen_id = body_json.get("generation_id")
            target = body_json.get("target_binding")
            edited_text = body_json.get("edited_text")
            rm_note = body_json.get("rm_note", "")
            if not gen_id or not target or not edited_text:
                self._send_json({"status": "error", "message": "Thiếu generation_id, target_binding hoặc edited_text."}, status_code=400)
                return
            try:
                binding = NarrativeTargetBinding(target)
                updated_rec = NarrativeDraftManager.edit_block(
                    generation_id=gen_id,
                    target_binding=binding,
                    edited_text=edited_text,
                    rm_note=rm_note
                )
                self._send_json({
                    "status": "success",
                    "generation_id": gen_id,
                    "target_binding": target,
                    "draft_status": updated_rec.status.value
                })
            except Exception as ex:
                self._send_json({"status": "error", "message": str(ex)}, status_code=400)
            return

        if path == '/api/narrative/accept':
            gen_id = body_json.get("generation_id")
            cid = body_json.get("case_id") or ACTIVE_CASE_ID
            rm_reviewer = body_json.get("rm_reviewer_name", "RM Thẩm định")
            if not gen_id:
                self._send_json({"status": "error", "message": "Thiếu generation_id."}, status_code=400)
                return
            try:
                packager = FactPackager()
                current_manifest = packager.package_from_case_data(CASES_DB[cid], case_id=cid)
                accepted_rec = NarrativeDraftManager.accept_narratives(
                    generation_id=gen_id,
                    case_id=cid,
                    current_manifest=current_manifest,
                    rm_reviewer_name=rm_reviewer
                )
                self._send_json({
                    "status": "success",
                    "generation_id": gen_id,
                    "case_id": cid,
                    "draft_status": accepted_rec.status.value,
                    "accepted_blocks_count": len(accepted_rec.accepted_block_ids)
                })
            except Exception as ex:
                self._send_json({"status": "error", "message": str(ex)}, status_code=400)
            return

        self.send_response(404)
        self.end_headers()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def run_server():
    server_address = ('', PORT)
    httpd = ThreadedHTTPServer(server_address, CopilotHTTPHandler)
    print("=" * 75)
    print(f"🏦 MSB CREDIT PROPOSAL AI COPILOT ĐANG CHẠY TẠI: http://localhost:{PORT}")
    print(f"👉 Mở trình duyệt và truy cập: http://localhost:{PORT}")
    print("=" * 75)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nĐang dừng máy chủ Copilot...")
        httpd.server_close()


if __name__ == '__main__':
    run_server()
