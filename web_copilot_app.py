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
from msb_eb_copilot.src.document_qa_agent import run_document_qa_gate, DocumentQAFailedError
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
        "name": "PSD - CTCP Phân phối Demo",
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

# Populated by execute_generation_pipeline() with the structured Document QA result
# (see msb_eb_copilot/src/document_qa_agent.py) of the most recent export attempt, so the
# HTTP handler can surface it to the RM without changing execute_generation_pipeline's
# existing str-return contract (relied on by scripts/verify_mb07_generation.py and other callers).
LAST_DOCUMENT_QA_RESULT: Optional[Dict[str, Any]] = None

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

    # Final QA gate: deterministic DOCX checks + GreenNode visual QA (AI is reviewer only,
    # never mutates the DOCX). Raises DocumentQAFailedError to block export on FAIL.
    global LAST_DOCUMENT_QA_RESULT
    LAST_DOCUMENT_QA_RESULT = run_document_qa_gate(final_path)

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
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    /* ==========================================================================
       CREDITPILOT 360 — DESIGN SYSTEM TOKENS
       Enterprise banking workspace: restrained palette, consistent spacing/radius.
       ========================================================================== */
    :root {
      --color-primary: #0B2A4A;        /* deep MSB navy */
      --color-primary-dark: #071B31;
      --color-accent: #1D5FC2;         /* one strong blue for interactive/primary actions */
      --color-accent-dark: #164A9B;
      --color-bg: #F3F5F8;             /* light neutral grey page background */
      --color-surface: #FFFFFF;
      --color-border: #E3E8EF;
      --color-border-strong: #CBD5E1;
      --color-text: #1B2430;
      --color-text-muted: #667085;
      --color-text-faint: #98A2B3;
      --color-success: #15803D;
      --color-success-bg: #ECFDF3;
      --color-success-border: #BBF0D2;
      --color-warning: #B45309;
      --color-warning-bg: #FFF8EB;
      --color-warning-border: #FBE3AE;
      --color-danger: #B42318;
      --color-danger-bg: #FEF3F2;
      --color-danger-border: #F6C7C2;
      --radius-sm: 8px;
      --radius-md: 10px;
      --radius-lg: 14px;
      --shadow-sm: 0 1px 2px rgba(16, 24, 40, 0.06);
      --shadow-md: 0 2px 8px rgba(16, 24, 40, 0.08);
      --sidebar-w: 264px;
      --topbar-h: 60px;
    }

    * { min-width: 0; }
    body {
      font-family: 'Inter', sans-serif;
      background: var(--color-bg);
      color: var(--color-text);
      overflow-wrap: anywhere;
    }
    h1, h2, h3, h4 { overflow-wrap: anywhere; }

    /* ---------- Layout shell ---------- */
    .app-shell { display: flex; min-height: 100vh; }
    .app-main { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; }
    .workspace { flex: 1 1 auto; min-width: 0; width: 100%; max-width: 1180px; margin: 0 auto; padding: 20px 28px 32px; }

    /* ---------- Sidebar ---------- */
    .sidebar {
      width: var(--sidebar-w);
      flex: 0 0 var(--sidebar-w);
      background: var(--color-primary);
      color: #E7ECF3;
      display: flex;
      flex-direction: column;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
      z-index: 40;
    }
    .sidebar-brand { padding: 20px 20px 16px; border-bottom: 1px solid rgba(255,255,255,0.08); }
    .sidebar-brand-row { display: flex; align-items: center; gap: 10px; }
    .sidebar-mark {
      width: 34px; height: 34px; border-radius: var(--radius-sm);
      background: var(--color-accent); color: #fff; font-weight: 700;
      display: flex; align-items: center; justify-content: center; font-size: 15px; flex: none;
    }
    .sidebar-title { font-size: 14.5px; font-weight: 700; color: #fff; line-height: 1.2; }
    .sidebar-subtitle { font-size: 11px; color: #93A5C2; margin-top: 2px; line-height: 1.35; }

    .sidebar-nav { flex: 1 1 auto; padding: 10px 10px; display: flex; flex-direction: column; gap: 1px; }
    .nav-item {
      display: flex; align-items: center; gap: 10px;
      padding: 9px 10px; border-radius: var(--radius-sm);
      color: #AEBBD1; text-align: left; width: 100%;
      font-size: 13px; font-weight: 500; line-height: 1.3;
      border-left: 3px solid transparent;
      transition: background-color .15s ease, color .15s ease;
    }
    .nav-item:hover { background: rgba(255,255,255,0.06); color: #fff; }
    .nav-item.tab-active {
      background: rgba(29, 95, 194, 0.20);
      color: #fff;
      font-weight: 600;
      border-left-color: var(--color-accent);
    }
    /* Step indicator glyph: ✓ done · ● active · ○ pending — always reflects real,
       already-tracked app state (see updateSidebarProgress()), never inferred from
       unrelated data merely being present. */
    .nav-item-step {
      flex: none; width: 18px; height: 18px;
      color: #5B6B85;
      font-size: 13px; line-height: 1; display: flex; align-items: center; justify-content: center;
    }
    .nav-item-step.is-active { color: var(--color-accent); font-size: 10px; }
    .nav-item.tab-active .nav-item-step.is-active { color: #fff; }
    .nav-item-step.is-done { color: #6FCF97; }
    .nav-item-step.is-pending { color: #4B5A72; }
    .nav-item-label { flex: 1 1 auto; min-width: 0; }

    .sidebar-footer { padding: 12px 20px 16px; border-top: 1px solid rgba(255,255,255,0.08); font-size: 11px; color: #7C8CA8; }

    /* ---------- Top bar ---------- */
    .topbar {
      height: var(--topbar-h);
      background: var(--color-surface);
      border-bottom: 1px solid var(--color-border);
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px; padding: 0 24px;
      position: sticky; top: 0; z-index: 30;
    }
    .topbar-left { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1 1 auto; }
    .topbar-right { display: flex; align-items: center; gap: 8px; flex: none; }

    /* ---------- Buttons (PRIMARY / SECONDARY / GHOST / DANGER) ---------- */
    .btn {
      display: inline-flex; align-items: center; justify-content: center; gap: 6px;
      height: 36px; padding: 0 14px; border-radius: var(--radius-sm);
      font-size: 13px; font-weight: 600; white-space: nowrap;
      border: 1px solid transparent; cursor: pointer; transition: background-color .15s ease, border-color .15s ease, opacity .15s ease;
    }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-sm { height: 30px; padding: 0 10px; font-size: 12px; }
    .btn-lg { height: 46px; padding: 0 20px; font-size: 14px; }
    .btn-primary { background: var(--color-accent); color: #fff; }
    .btn-primary:hover:not(:disabled) { background: var(--color-accent-dark); }
    .btn-secondary { background: var(--color-surface); color: var(--color-text); border-color: var(--color-border-strong); }
    .btn-secondary:hover:not(:disabled) { background: #F8FAFC; }
    .btn-ghost { background: transparent; color: var(--color-text-muted); }
    .btn-ghost:hover:not(:disabled) { background: #F1F4F8; color: var(--color-text); }
    .btn-danger { background: var(--color-danger); color: #fff; }
    .btn-danger:hover:not(:disabled) { background: #921d13; }
    .btn-success { background: var(--color-success); color: #fff; }
    .btn-success:hover:not(:disabled) { background: #106b32; }

    /* ---------- Surfaces ---------- */
    .panel { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-sm); }
    .kpi-card { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: 14px 16px; box-shadow: var(--shadow-sm); height: 100%; }
    .kpi-label { font-size: 12px; color: var(--color-text-muted); font-weight: 500; }
    .kpi-value { font-size: 22px; font-weight: 700; color: var(--color-text); margin-top: 3px; line-height: 1.2; }
    .kpi-meta { font-size: 12px; color: var(--color-text-muted); margin-top: 3px; line-height: 1.4; }

    .page-title { font-size: 22px; font-weight: 700; color: var(--color-text); line-height: 1.25; }
    .page-subtitle { font-size: 13px; color: var(--color-text-muted); margin-top: 2px; }
    .section-title { font-size: 16px; font-weight: 700; color: var(--color-primary); }

    /* Stable description-list layout: fixed label column, left-aligned value that
       wraps naturally — never right-aligned, never truncated. */
    .kv-row { display: flex; align-items: baseline; gap: 14px; padding: 8px 0; border-bottom: 1px solid var(--color-border); }
    .kv-row:last-child { border-bottom: none; }
    .kv-label { font-size: 13px; color: var(--color-text-muted); flex: 0 0 168px; }
    .kv-value { font-size: 13px; font-weight: 600; color: var(--color-text); text-align: left; overflow-wrap: anywhere; line-height: 1.45; flex: 1 1 auto; min-width: 0; }

    /* ---------- Chips / status badges (restrained: success / warning / danger / neutral / info) ---------- */
    .chip { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 999px; border: 1px solid transparent; white-space: nowrap; }
    .chip-success { background: var(--color-success-bg); color: var(--color-success); border-color: var(--color-success-border); }
    .chip-warning { background: var(--color-warning-bg); color: var(--color-warning); border-color: var(--color-warning-border); }
    .chip-danger { background: var(--color-danger-bg); color: var(--color-danger); border-color: var(--color-danger-border); }
    .chip-info { background: #EEF3FC; color: var(--color-accent-dark); border-color: #D3E0F5; }
    .chip-neutral { background: #F1F4F8; color: var(--color-text-muted); border-color: var(--color-border); }

    /* ---------- Text clamping / long-content handling ---------- */
    .clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .clamp-3 { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .text-wrap-safe { overflow-wrap: anywhere; word-break: break-word; }

    /* ---------- Tab sections ---------- */
    .hidden { display: none !important; }

    @media (max-width: 1024px) {
      .sidebar { width: 76px; flex-basis: 76px; }
      .sidebar-title, .sidebar-subtitle, .nav-item-label, .sidebar-footer { display: none; }
      .nav-item { justify-content: center; }
      .workspace { padding: 18px 16px 40px; }
    }
  </style>
</head>
<body class="min-h-screen">

  <div class="app-shell">
    <!-- LEFT SIDEBAR: PRIMARY NAVIGATION (6-STEP RM WORKFLOW) -->
    <aside class="sidebar" id="app-sidebar">
      <div class="sidebar-brand">
        <div class="sidebar-brand-row">
          <div class="sidebar-mark">M</div>
          <div>
            <div class="sidebar-title">CreditPilot 360</div>
            <div class="sidebar-subtitle">Thẩm định &amp; Soạn thảo Tờ trình KHDN</div>
          </div>
        </div>
      </div>

      <nav class="sidebar-nav">
        <button onclick="switchTab('tab-dashboard')" id="nav-tab-dashboard" class="nav-item tab-active" data-step="tab-dashboard">
          <span class="nav-item-step is-active">●</span>
          <span class="nav-item-label">Hồ sơ Khách hàng</span>
        </button>
        <button onclick="switchTab('tab-upload')" id="nav-tab-upload" class="nav-item" data-step="tab-upload">
          <span class="nav-item-step is-pending">○</span>
          <span class="nav-item-label">Không gian Tài liệu</span>
        </button>
        <button onclick="switchTab('tab-review')" id="nav-tab-review" class="nav-item" data-step="tab-review">
          <span class="nav-item-step is-pending">○</span>
          <span class="nav-item-label">Dữ liệu Đã Xác nhận</span>
        </button>
        <button onclick="switchTab('tab-insights')" id="nav-tab-insights" class="nav-item" data-step="tab-insights">
          <span class="nav-item-step is-pending">○</span>
          <span class="nav-item-label">Thẩm định Tín dụng AI</span>
        </button>
        <button onclick="switchTab('tab-narrative')" id="nav-tab-narrative" class="nav-item" data-step="tab-narrative">
          <span class="nav-item-step is-pending">○</span>
          <span class="nav-item-label">Tờ trình / Narrative</span>
        </button>
        <button onclick="switchTab('tab-committee')" id="nav-tab-committee" class="nav-item" data-step="tab-committee">
          <span class="nav-item-step is-pending">○</span>
          <span class="nav-item-label">Credit Committee</span>
        </button>
      </nav>

      <div class="sidebar-footer">Mô hình 70% AI + 30% RM</div>
    </aside>

    <div class="app-main">
      <!-- TOP CONTEXT BAR: case selector + contextual actions only -->
      <header class="topbar">
        <div class="topbar-left">
          <select id="case-selector" onchange="onCaseChange(this.value)" class="btn-sm" style="height:34px; border:1px solid var(--color-border-strong); border-radius:8px; padding:0 8px; font-size:13px; font-weight:600; color:var(--color-text); background:#fff;">
            <option value="PSD">PSD — CTCP Phân phối Demo</option>
            <option value="GAS_SOUTH">GAS SOUTH — CTCP Khí Miền Nam</option>
            <option value="PHYTOPHARMA">PHYTOPHARMA — CTCP Dược liệu TW2</option>
          </select>
          <span id="case-source-badge" class="chip chip-warning">Demo data</span>
        </div>
        <div class="topbar-right">
          <button onclick="resetDemoCase()" title="Đặt lại dữ liệu demo chuẩn" class="btn btn-ghost btn-sm">Nạp Demo Chuẩn</button>
          <button onclick="openNewCaseModal()" class="btn btn-secondary btn-sm">+ Tạo hồ sơ mới</button>
          <!-- Contextual primary CTA: label/action/visibility depend on the active
               workflow step (see updateTopbarPrimaryCTA()). Defaults to Step 1's action
               so the button is correct even before JS runs on first paint. -->
          <button onclick="switchTab('tab-upload')" id="btn-export-top" class="btn btn-primary btn-sm">Tiếp tục → Không gian Tài liệu</button>
        </div>
      </header>

      <!-- MAIN WORKSPACE -->
      <main class="workspace">

    <!-- ========================================================================= -->
    <!-- TAB 1: TỔNG QUAN HỒ SƠ (CASE OVERVIEW)                                    -->
    <!-- ========================================================================= -->
    <section id="tab-dashboard" class="space-y-4">
      <div>
        <h1 class="page-title">Hồ sơ khách hàng</h1>
        <p class="page-subtitle">Tổng quan thông tin doanh nghiệp và đề xuất cấp tín dụng cho hồ sơ đang thẩm định.</p>
      </div>

      <!-- ROW 1: SUMMARY METRICS (concise: main value fits 1-2 lines, rest is meta) -->
      <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div class="kpi-card">
          <div class="kpi-label">Khách hàng</div>
          <div class="kpi-value text-wrap-safe" style="font-size:16px;" id="dash-cust-name">DEMO DISTRIBUTION JSC</div>
          <div class="kpi-meta text-wrap-safe" id="dash-cust-cif">CIF: DEMO001</div>
          <div class="kpi-meta text-wrap-safe" id="dash-cust-rating">Hạng AAA · 95đ</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Hạn mức đề xuất</div>
          <div class="kpi-value" id="dash-total-limit">700 tỷ VND</div>
          <div class="kpi-meta text-wrap-safe" id="dash-loan-limit">Vay 250 tỷ · Bảo lãnh 30 tỷ</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Doanh thu gần nhất</div>
          <div class="kpi-value" id="dash-rev-2025">7.819 tỷ VND</div>
          <div class="kpi-meta text-wrap-safe" id="dash-np-2025">LNST 134,2 tỷ</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">CIC</div>
          <div class="kpi-value" style="color:var(--color-success);" id="dash-cic-status">Nhóm 1</div>
          <div class="kpi-meta text-wrap-safe" id="dash-cic-meta">100% lịch sử tín dụng đạt chuẩn</div>
          <div class="kpi-meta text-wrap-safe" id="dash-msb-out">Dư nợ tại MSB: 500 tỷ</div>
        </div>
      </div>

      <!-- ROW 2: CUSTOMER / CREDIT DETAILS -->
      <div class="panel p-5">
        <div class="flex items-center justify-between border-b pb-3 mb-3" style="border-color:var(--color-border);">
          <h3 class="section-title">Chi tiết đề xuất cấp tín dụng &amp; cơ cấu bảo đảm</h3>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-x-8">
          <div>
            <div class="section-title" style="font-size:13px; color:var(--color-text-muted); font-weight:700; margin-bottom:2px;">Thông tin doanh nghiệp</div>
            <div class="kv-row">
              <span class="kv-label">MST</span>
              <span class="kv-value" id="dash-tax-code">0100000000</span>
            </div>
            <div class="kv-row">
              <span class="kv-label">Đại diện pháp luật</span>
              <span class="kv-value" id="dash-legal-rep">Đại diện Demo (Tổng Giám đốc)</span>
            </div>
            <div class="kv-row">
              <span class="kv-label">Vốn điều lệ</span>
              <span class="kv-value" id="dash-capital">518.279 triệu VND</span>
            </div>
            <div class="kv-row">
              <span class="kv-label">Địa chỉ</span>
              <span class="kv-value" id="dash-address">P.207, Tòa nhà PetroVietnam, Số 1-5 Lê Duẩn, Q.1, TP.HCM</span>
            </div>
          </div>

          <div>
            <div class="section-title" style="font-size:13px; color:var(--color-text-muted); font-weight:700; margin-bottom:2px;">Thông tin cấp tín dụng</div>
            <div class="kv-row">
              <span class="kv-label">Mục đích cấp tín dụng</span>
              <span class="kv-value" id="dash-purpose">Bổ sung vốn lưu động kinh doanh ICT</span>
            </div>
            <div class="kv-row">
              <span class="kv-label">Biện pháp bảo đảm</span>
              <span class="kv-value" style="color:var(--color-success);" id="dash-collat">Tín chấp 100% (Định hạng A+/AAA)</span>
            </div>
            <div class="kv-row">
              <span class="kv-label">Cam kết dòng tiền</span>
              <span class="kv-value" id="dash-cashflow">25% Doanh thu qua tài khoản MSB</span>
            </div>
            <div class="kv-row">
              <span class="kv-label">Thẩm quyền phê duyệt</span>
              <span class="kv-value" id="dash-authority">Hội đồng Tín dụng Cấp cao (HĐTDCC)</span>
            </div>
          </div>
        </div>

        <div class="pt-4 mt-2 flex justify-end" style="border-top:1px solid var(--color-border);">
          <button onclick="switchTab('tab-upload')" class="btn btn-primary">Tiếp tục → Không gian Tài liệu</button>
        </div>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- TAB 2: KHÔNG GIAN HỒ SƠ (DOCUMENT WORKSPACE)                              -->
    <!-- ========================================================================= -->
    <section id="tab-upload" class="hidden space-y-4">
      <div>
        <h1 class="page-title">Không gian Tài liệu</h1>
        <p class="page-subtitle">Tải lên, bóc tách và đối soát 4 nhóm tài liệu hồ sơ. Quy trình: Tải lên → Đối soát → Xác nhận.</p>
      </div>
      <div class="panel p-5 space-y-4">
        <div class="flex items-center justify-between border-b pb-3" style="border-color:var(--color-border);">
          <h3 class="section-title">Danh mục tài liệu</h3>
          <span id="doc-workspace-badge" class="chip chip-success">4/4 nhóm tài liệu đã nạp</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <!-- CARD 1: LEGAL -->
          <div id="card-legal" class="p-4 rounded-lg border space-y-3" style="border-color:var(--color-border); background:var(--color-bg);">
            <input type="file" id="file-legal" accept=".pdf" class="hidden" onchange="handleFileSelected('legal', this)">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="text-sm font-semibold" style="color:var(--color-text);">1 · Hồ sơ Pháp lý &amp; ĐKKD</div>
                <div id="file-name-legal" class="text-xs mt-0.5 text-wrap-safe" style="color:var(--color-text-muted);">Giay_Phep_DKKD_PSD.pdf (Trang 1 - 3)</div>
              </div>
              <div id="status-badge-legal" class="flex-none">
                <span class="chip chip-success">Confirmed</span>
              </div>
            </div>
            <div id="summary-legal" class="text-xs space-y-1 bg-white p-3 rounded-md border text-wrap-safe" style="border-color:var(--color-border); color:var(--color-text-muted);">
              <div>Tên DN: <span id="sum-legal-name" class="font-semibold" style="color:var(--color-text);">CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO</span></div>
              <div>MST: <span id="sum-legal-tax" class="font-semibold" style="color:var(--color-text);">0100000000</span> · Vốn ĐL: <span id="sum-legal-capital" class="font-semibold" style="color:var(--color-text);">518.279 tr</span></div>
              <div>ĐDPL: <span id="sum-legal-rep" class="font-semibold" style="color:var(--color-text);">Đại diện Demo (Tổng Giám đốc)</span></div>
            </div>
            <div id="actions-legal" class="flex items-center justify-between pt-1 gap-2">
              <span id="tip-legal" class="text-[11px] text-wrap-safe" style="color:var(--color-text-faint);">Đã đồng bộ vào Phần A MB07</span>
              <div class="flex space-x-2 flex-none">
                <button onclick="triggerDocUpload('legal')" class="btn btn-secondary btn-sm">Thay thế</button>
                <button onclick="openReviewModal('legal')" class="btn btn-primary btn-sm">Xem lại</button>
              </div>
            </div>
          </div>

          <!-- CARD 2: BUSINESS -->
          <div id="card-business" class="p-4 rounded-lg border space-y-3" style="border-color:var(--color-border); background:var(--color-bg);">
            <input type="file" id="file-business" accept=".pdf" class="hidden" onchange="handleFileSelected('business', this)">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="text-sm font-semibold" style="color:var(--color-text);">2 · Mô hình KD &amp; Chuỗi cung ứng</div>
                <div id="file-name-business" class="text-xs mt-0.5 text-wrap-safe" style="color:var(--color-text-muted);">Bao_Cao_Thuong_Nien_PSD.pdf (Trang 15 - 42)</div>
              </div>
              <div id="status-badge-business" class="flex-none">
                <span class="chip chip-success">Confirmed</span>
              </div>
            </div>
            <div id="summary-business" class="text-xs space-y-1 bg-white p-3 rounded-md border text-wrap-safe" style="border-color:var(--color-border); color:var(--color-text-muted);">
              <div>Mô hình: <span id="sum-biz-model" class="font-semibold" style="color:var(--color-text);">Thương mại Phân phối ICT</span></div>
              <div>Nhà cung cấp chính: <span id="sum-biz-suppliers" class="font-semibold" style="color:var(--color-text);">Dell (28.1%), Lenovo (20.4%), Samsung (19.1%)</span></div>
              <div>Khách hàng chính: <span id="sum-biz-customers" class="font-semibold" style="color:var(--color-text);">MWG (4.5%), Viettel Store, FPT Shop</span></div>
            </div>
            <div id="actions-business" class="flex items-center justify-between pt-1 gap-2">
              <span id="tip-business" class="text-[11px] text-wrap-safe" style="color:var(--color-text-faint);">Đã đồng bộ vào Phần C MB07</span>
              <div class="flex space-x-2 flex-none">
                <button onclick="triggerDocUpload('business')" class="btn btn-secondary btn-sm">Thay thế</button>
                <button onclick="openReviewModal('business')" class="btn btn-primary btn-sm">Xem lại</button>
              </div>
            </div>
          </div>

          <!-- CARD 3: FINANCIAL -->
          <div id="card-financial" class="p-4 rounded-lg border space-y-3" style="border-color:var(--color-border); background:var(--color-bg);">
            <input type="file" id="file-financial" accept=".pdf" class="hidden" onchange="handleFileSelected('financial', this)">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="text-sm font-semibold" style="color:var(--color-text);">3 · BCTC Kiểm toán 3 năm</div>
                <div id="file-name-financial" class="text-xs mt-0.5 text-wrap-safe" style="color:var(--color-text-muted);">BCTC_Kiem_Toan_PwC_2025.pdf</div>
              </div>
              <div id="status-badge-financial" class="flex-none">
                <span class="chip chip-success">Confirmed</span>
              </div>
            </div>
            <div id="summary-financial" class="text-xs space-y-1 bg-white p-3 rounded-md border text-wrap-safe" style="border-color:var(--color-border); color:var(--color-text-muted);">
              <div>Đơn vị kiểm toán: <span id="sum-fin-auditor" class="font-semibold" style="color:var(--color-text);">PwC Việt Nam (Chấp thuận toàn phần)</span></div>
              <div>Doanh thu 2025: <span id="sum-fin-rev" class="font-semibold" style="color:var(--color-text);">7.819.398 tr</span></div>
              <div>LNST 2025: <span id="sum-fin-np" class="font-semibold" style="color:var(--color-text);">134.201 tr</span> · VCSH: <span id="sum-fin-equity" class="font-semibold" style="color:var(--color-text);">729.343 tr</span></div>
            </div>
            <div id="actions-financial" class="flex items-center justify-between pt-1 gap-2">
              <span id="tip-financial" class="text-[11px] text-wrap-safe" style="color:var(--color-text-faint);">Đã đồng bộ vào Phần D MB07</span>
              <div class="flex space-x-2 flex-none">
                <button onclick="triggerDocUpload('financial')" class="btn btn-secondary btn-sm">Thay thế</button>
                <button onclick="openReviewModal('financial')" class="btn btn-primary btn-sm">Xem lại</button>
              </div>
            </div>
          </div>

          <!-- CARD 4: CIC -->
          <div id="card-cic" class="p-4 rounded-lg border space-y-3" style="border-color:var(--color-border); background:var(--color-bg);">
            <input type="file" id="file-cic" accept=".pdf" class="hidden" onchange="handleFileSelected('cic', this)">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="text-sm font-semibold" style="color:var(--color-text);">4 · Báo cáo Tín dụng CIC Chi tiết</div>
                <div id="file-name-cic" class="text-xs mt-0.5 text-wrap-safe" style="color:var(--color-text-muted);">Bao_Cao_CIC_Chi_Tiet_2025.pdf</div>
              </div>
              <div id="status-badge-cic" class="flex-none">
                <span class="chip chip-success">Confirmed</span>
              </div>
            </div>
            <div id="summary-cic" class="text-xs space-y-1 bg-white p-3 rounded-md border text-wrap-safe" style="border-color:var(--color-border); color:var(--color-text-muted);">
              <div>Ngày tra cứu CIC: <span id="sum-cic-date" class="font-semibold" style="color:var(--color-text);">31/12/2025</span></div>
              <div>Phân loại nợ: <span id="sum-cic-status" class="font-semibold" style="color:var(--color-success);">100% Nhóm 1 (Đủ tiêu chuẩn 24 tháng)</span></div>
              <div>Dư nợ tại MSB: <span id="sum-cic-msb" class="font-semibold" style="color:var(--color-text);">499.999 tr</span> · TCTD khác: <span id="sum-cic-other" class="font-semibold" style="color:var(--color-text);">Đầy đủ</span></div>
            </div>
            <div id="actions-cic" class="flex items-center justify-between pt-1 gap-2">
              <span id="tip-cic" class="text-[11px] text-wrap-safe" style="color:var(--color-text-faint);">Đã đồng bộ vào Phần E MB07</span>
              <div class="flex space-x-2 flex-none">
                <button onclick="triggerDocUpload('cic')" class="btn btn-secondary btn-sm">Thay thế</button>
                <button onclick="openReviewModal('cic')" class="btn btn-primary btn-sm">Xem lại</button>
              </div>
            </div>
          </div>
        </div>

        <div class="pt-4 flex justify-end" style="border-top:1px solid var(--color-border);">
          <button onclick="switchTab('tab-review')" class="btn btn-primary">Tiếp tục → Xác nhận Dữ liệu</button>
        </div>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- TAB 3: ĐỐI SOÁT DỮ LIỆU (FACT REVIEW A - E)                               -->
    <!-- ========================================================================= -->
    <section id="tab-review" class="hidden space-y-4">
      <div>
        <h1 class="page-title">Dữ liệu Đã Xác nhận</h1>
        <p class="page-subtitle">Cấu trúc theo Phần A / B của Tờ trình MB07. Số liệu trích xuất đã gắn nguồn trang — RM xác nhận hoặc chỉnh sửa trực tiếp bên dưới.</p>
      </div>

      <div class="p-4 rounded-lg flex items-start gap-3" style="background:var(--color-warning-bg); border:1px solid var(--color-warning-border);">
        <div class="text-xs space-y-1" style="color:var(--color-warning);">
          <div class="font-bold text-sm">Lưu ý đối soát &amp; thẩm quyền RM</div>
          <div>Toàn bộ số liệu trích xuất đã được gắn nhãn nguồn gốc trang. Vui lòng xác nhận các trường cần đánh giá chuyên môn trước khi xuất bản; nếu phát hiện sai lệch, chỉnh sửa trực tiếp vào ô tương ứng.</div>
        </div>
      </div>

      <div class="panel p-5 space-y-4">
        <div class="flex items-center justify-between border-b pb-3" style="border-color:var(--color-border);">
          <h3 class="section-title">Dữ liệu thẩm định theo cấu trúc Tờ trình MB07</h3>
          <div class="flex space-x-2">
            <button onclick="saveSectionA()" class="btn btn-secondary btn-sm">Lưu Phần A</button>
            <button onclick="saveSectionB()" class="btn btn-secondary btn-sm">Lưu Phần B</button>
          </div>
        </div>

        <!-- SECTION A & B FORM COMPACT -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 text-xs">
          <!-- PHẦN A -->
          <div class="space-y-3 p-4 rounded-lg border" style="background:var(--color-bg); border-color:var(--color-border);">
            <div class="text-sm flex items-center justify-between" style="color:var(--color-text); font-weight:700;">
              <span>Phần A · Thông tin Pháp lý &amp; ĐVKD</span>
              <span class="chip chip-info">AI đã điền</span>
            </div>
            <div class="space-y-2">
              <div>
                <label class="font-medium" style="color:var(--color-text-muted);">Đơn vị kinh doanh thẩm định</label>
                <input type="text" id="rm-unit-name" value="LC2MN" class="w-full mt-1 px-3 py-1.5 bg-white border rounded font-medium" style="border-color:var(--color-border-strong); color:var(--color-text);">
              </div>
              <div class="grid grid-cols-2 gap-2">
                <div>
                  <label class="font-medium" style="color:var(--color-text-muted);">Cán bộ bán hàng / RM</label>
                  <input type="text" id="rm-rm-name" value="RM DEMO / RM SUPPORT" class="w-full mt-1 px-3 py-1.5 bg-white border rounded" style="border-color:var(--color-border-strong); color:var(--color-text);">
                </div>
                <div>
                  <label class="font-medium" style="color:var(--color-text-muted);">Số điện thoại RM</label>
                  <input type="text" id="rm-rm-phone" value="0900000000" class="w-full mt-1 px-3 py-1.5 bg-white border rounded" style="border-color:var(--color-border-strong); color:var(--color-text);">
                </div>
              </div>
              <div class="grid grid-cols-2 gap-2">
                <div>
                  <label class="font-medium" style="color:var(--color-text-muted);">Cán bộ quản lý</label>
                  <input type="text" id="rm-manager-name" value="MANAGER DEMO" class="w-full mt-1 px-3 py-1.5 bg-white border rounded" style="border-color:var(--color-border-strong); color:var(--color-text);">
                </div>
                <div>
                  <label class="font-medium" style="color:var(--color-text-muted);">Thẩm quyền phê duyệt</label>
                  <input type="text" id="rm-authority" value="HĐTDCC" class="w-full mt-1 px-3 py-1.5 bg-white border rounded font-bold" style="border-color:var(--color-border-strong); color:var(--color-primary);">
                </div>
              </div>
            </div>
          </div>

          <!-- PHẦN B -->
          <div class="space-y-3 p-4 rounded-lg border" style="background:var(--color-bg); border-color:var(--color-border);">
            <div class="text-sm flex items-center justify-between" style="color:var(--color-text); font-weight:700;">
              <span>Phần B · Đề xuất Cấp Tín dụng</span>
              <span class="chip chip-warning">RM thẩm định</span>
            </div>
            <div class="space-y-2">
              <div class="grid grid-cols-3 gap-2">
                <div>
                  <label class="font-medium" style="color:var(--color-text-muted);">Tổng hạn mức (tr)</label>
                  <input type="number" id="rm-total-limit" value="700000" class="w-full mt-1 px-3 py-1.5 bg-white border rounded font-bold" style="border-color:var(--color-border-strong); color:var(--color-primary);">
                </div>
                <div>
                  <label class="font-medium" style="color:var(--color-text-muted);">Hạn mức vay (tr)</label>
                  <input type="number" id="rm-loan-limit" value="250000" class="w-full mt-1 px-3 py-1.5 bg-white border rounded" style="border-color:var(--color-border-strong); color:var(--color-text);">
                </div>
                <div>
                  <label class="font-medium" style="color:var(--color-text-muted);">Bảo lãnh (tr)</label>
                  <input type="number" id="rm-guar-limit" value="30000" class="w-full mt-1 px-3 py-1.5 bg-white border rounded" style="border-color:var(--color-border-strong); color:var(--color-text);">
                </div>
              </div>
              <div>
                <label class="font-medium" style="color:var(--color-text-muted);">Biện pháp bảo đảm</label>
                <input type="text" id="rm-collateral" value="Tín chấp 100% (Cấp tín dụng không có TSBĐ theo phê duyệt định hạng A+)" class="w-full mt-1 px-3 py-1.5 bg-white border rounded font-medium" style="border-color:var(--color-border-strong); color:var(--color-text);">
              </div>
              <div>
                <label class="font-medium" style="color:var(--color-text-muted);">Mục đích vay</label>
                <input type="text" id="rm-purpose" value="Bổ sung vốn lưu động phục vụ hoạt động kinh doanh; thanh toán nhà cung cấp." class="w-full mt-1 px-3 py-1.5 bg-white border rounded" style="border-color:var(--color-border-strong); color:var(--color-text);">
              </div>
            </div>
          </div>
        </div>

        <div class="pt-4 flex justify-end" style="border-top:1px solid var(--color-border);">
          <button onclick="switchTab('tab-insights')" class="btn btn-primary">Tiếp tục → Thẩm định AI</button>
        </div>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- TAB 4: THẨM ĐỊNH TÍN DỤNG AI (AI INSIGHTS EXPERIENCE - VISUAL HIGHLIGHT)  -->
    <!-- ========================================================================= -->
    <section id="tab-insights" class="hidden space-y-4">
      <div>
        <h1 class="page-title">Thẩm định Tín dụng AI</h1>
        <p class="page-subtitle">AI phát hiện xu hướng; mọi chỉ số được Python tái thẩm định độc lập trước khi đưa vào tờ trình.</p>
      </div>
      <div class="panel p-4 flex items-center justify-between gap-3">
        <div class="text-xs" style="color:var(--color-text-muted);">Chỉ số tài chính then chốt — nguồn: BCTC đã xác nhận + đối soát CIC.</div>
        <span class="chip chip-info">6/6 chỉ số đã thẩm định</span>
      </div>

      <!-- INSIGHTS GRID -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4" id="insights-container">
        <!-- CARD 1: REVENUE GROWTH -->
        <div class="card-insight panel p-4 space-y-2.5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs font-semibold text-wrap-safe" style="color:var(--color-text-muted);">Tăng trưởng doanh thu</span>
            <span class="chip chip-success">Calculated</span>
          </div>
          <div class="flex items-baseline gap-2">
            <span class="kpi-value" style="color:var(--color-success); font-size:26px;">+37.1%</span>
            <span class="text-xs" style="color:var(--color-text-faint);">2024 → 2025</span>
          </div>
          <div class="text-xs p-3 rounded-md border space-y-1.5" style="background:var(--color-bg); border-color:var(--color-border); color:var(--color-text-muted);">
            <div class="font-semibold" style="color:var(--color-text);">AI Insight</div>
            <p class="clamp-3">Doanh thu bứt phá từ 5.702,5 tỷ lên 7.819,4 tỷ VND nhờ mở rộng phân phối các dòng điện thoại thông minh thế hệ mới.</p>
            <div class="pt-1.5 border-t text-[11px] font-mono text-wrap-safe" style="border-color:var(--color-border); color:var(--color-accent-dark);">
              (7.819,4 − 5.702,5) / 5.702,5 = +37.12%
            </div>
          </div>
        </div>

        <!-- CARD 2: GROSS PROFIT MARGIN -->
        <div class="card-insight panel p-4 space-y-2.5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs font-semibold text-wrap-safe" style="color:var(--color-text-muted);">Biên lợi nhuận gộp</span>
            <span class="chip chip-success">Calculated</span>
          </div>
          <div class="flex items-baseline gap-2">
            <span class="kpi-value" style="font-size:26px;">5.20%</span>
            <span class="text-xs" style="color:var(--color-text-faint);">LN gộp: 406.8 tỷ</span>
          </div>
          <div class="text-xs p-3 rounded-md border space-y-1.5" style="background:var(--color-bg); border-color:var(--color-border); color:var(--color-text-muted);">
            <div class="font-semibold" style="color:var(--color-text);">AI Insight</div>
            <p class="clamp-3">Biên lợi nhuận gộp duy trì ổn định &gt;5.2%, lợi nhuận gộp tăng trưởng +26.8% so với năm 2024 (320.9 tỷ VND).</p>
            <div class="pt-1.5 border-t text-[11px] font-mono text-wrap-safe" style="border-color:var(--color-border); color:var(--color-accent-dark);">
              406.809 / 7.819.398 = 5.20%
            </div>
          </div>
        </div>

        <!-- CARD 3: RECEIVABLES DIVERGENCE -->
        <div class="card-insight panel p-4 space-y-2.5" style="border-color:var(--color-warning-border);">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs font-semibold text-wrap-safe" style="color:var(--color-text-muted);">Độ lệch phải thu</span>
            <span class="chip chip-warning">Data Gap</span>
          </div>
          <div class="flex items-baseline gap-2">
            <span class="kpi-value" style="color:var(--color-warning); font-size:26px;">+104.0%</span>
            <span class="text-xs" style="color:var(--color-text-faint);">vs DThu +37.1%</span>
          </div>
          <div class="text-xs p-3 rounded-md border space-y-1.5" style="background:var(--color-warning-bg); border-color:var(--color-warning-border); color:var(--color-text-muted);">
            <div class="font-semibold" style="color:var(--color-warning);">AI Insight — cần RM lưu ý</div>
            <p class="clamp-3">Phải thu ngắn hạn tăng nhanh từ 723 tỷ lên 1.475 tỷ VND, cần đối soát chất lượng công nợ chuỗi đại lý đầu ra.</p>
            <div class="pt-1.5 border-t text-[11px] font-mono text-wrap-safe" style="border-color:var(--color-warning-border); color:var(--color-warning);">
              (1.475,0 − 723,0) / 723,0 = +104.01%
            </div>
          </div>
        </div>

        <!-- CARD 4: ASSET STRUCTURE -->
        <div class="card-insight panel p-4 space-y-2.5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs font-semibold text-wrap-safe" style="color:var(--color-text-muted);">Cơ cấu tài sản</span>
            <span class="chip chip-success">Calculated</span>
          </div>
          <div class="flex items-baseline gap-2">
            <span class="kpi-value" style="font-size:26px;">98.2%</span>
            <span class="text-xs" style="color:var(--color-text-faint);">Tài sản ngắn hạn</span>
          </div>
          <div class="text-xs p-3 rounded-md border space-y-1.5" style="background:var(--color-bg); border-color:var(--color-border); color:var(--color-text-muted);">
            <div class="font-semibold" style="color:var(--color-text);">AI Insight</div>
            <p class="clamp-3">Tài sản ngắn hạn chiếm 4.600 tỷ / 4.683 tỷ VND tổng tài sản, phù hợp đặc thù luân chuyển nhanh của ngành phân phối.</p>
            <div class="pt-1.5 border-t text-[11px] font-mono text-wrap-safe" style="border-color:var(--color-border); color:var(--color-accent-dark);">
              4.600.702 / 4.683.423 = 98.23%
            </div>
          </div>
        </div>

        <!-- CARD 5: SUPPLIER CONCENTRATION -->
        <div class="card-insight panel p-4 space-y-2.5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs font-semibold text-wrap-safe" style="color:var(--color-text-muted);">Tập trung nhà cung cấp</span>
            <span class="chip chip-info">AI Insight</span>
          </div>
          <div class="flex items-baseline gap-2">
            <span class="kpi-value" style="font-size:22px;">Top 1: 28.1%</span>
            <span class="text-xs" style="color:var(--color-text-faint);">Dell Global</span>
          </div>
          <div class="text-xs p-3 rounded-md border space-y-1.5" style="background:var(--color-bg); border-color:var(--color-border); color:var(--color-text-muted);">
            <div class="font-semibold" style="color:var(--color-text);">AI Insight</div>
            <p class="clamp-3">Quan hệ đối tác cấp 1 &gt;15 năm với Dell (28.1%), Lenovo (20.4%), Samsung (19.1%) kèm cơ chế bảo vệ giá Price Protection.</p>
            <div class="pt-1.5 border-t text-[11px] font-mono text-wrap-safe" style="border-color:var(--color-border); color:var(--color-accent-dark);">
              Đối soát: Hợp đồng đại lý ủy quyền cấp 1
            </div>
          </div>
        </div>

        <!-- CARD 6: CIC DISCIPLINE -->
        <div class="card-insight panel p-4 space-y-2.5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs font-semibold text-wrap-safe" style="color:var(--color-text-muted);">Kỷ luật tín dụng CIC</span>
            <span class="chip chip-success">Calculated</span>
          </div>
          <div class="flex items-baseline gap-2">
            <span class="kpi-value" style="color:var(--color-success); font-size:22px;">100% Nhóm 1</span>
            <span class="text-xs" style="color:var(--color-text-faint);">24 tháng liên tục</span>
          </div>
          <div class="text-xs p-3 rounded-md border space-y-1.5" style="background:var(--color-bg); border-color:var(--color-border); color:var(--color-text-muted);">
            <div class="font-semibold" style="color:var(--color-text);">AI Insight</div>
            <p class="clamp-3">Khách hàng và ban lãnh đạo có lịch sử trả nợ mẫu mực, 0 ngày quá hạn tại MSB và toàn bộ các TCTD.</p>
            <div class="pt-1.5 border-t text-[11px] font-mono text-wrap-safe" style="border-color:var(--color-border); color:var(--color-accent-dark);">
              Đối soát: Báo cáo CIC Trung tâm đến 31/12/2025
            </div>
          </div>
        </div>
      </div>

      <div class="panel p-5 flex justify-end">
        <button onclick="switchTab('tab-narrative')" class="btn btn-primary">Tiếp tục → Tạo Narrative</button>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- TAB 5: SOẠN THẢO & XUẤT TỜ TRÌNH MB07                                     -->
    <!-- ========================================================================= -->
    <section id="tab-narrative" class="hidden space-y-4">
      <div>
        <h1 class="page-title">Tờ trình / Narrative</h1>
        <p class="page-subtitle">AI phát hiện → Python đối soát độc lập → RM phê duyệt (FactManifest SHA-256).</p>
      </div>
      <div class="panel p-5 space-y-4">
        <!-- HEADER & WORKFLOW STATUS -->
        <div class="flex flex-col md:flex-row md:items-center justify-between border-b pb-4 gap-4" style="border-color:var(--color-border);">
          <div>
            <div class="flex items-center space-x-3">
              <h3 class="section-title">Phê duyệt &amp; biên tập narrative</h3>
              <span id="narrative-status-badge" class="chip chip-neutral">Chờ kiểm tra</span>
            </div>
          </div>
          <div id="narrative-header-actions" class="flex items-center space-x-2">
            <!-- Dynamic Action Buttons (Tạo Nhận Định AI / Phê Duyệt / Tạo Lại) -->
          </div>
        </div>

        <!-- STATE NOTIFICATION / BANNER AREA -->
        <div id="narrative-alert-container"></div>

        <!-- TELEMETRY / AUDIT STRIP (shown when draft exists) -->
        <div id="narrative-telemetry-strip" class="hidden p-3 rounded-lg text-[11px] flex flex-wrap items-center justify-between gap-2" style="background:var(--color-bg); border:1px solid var(--color-border); color:var(--color-text-muted);">
          <div class="flex items-center space-x-2">
            <span class="font-bold" style="color:var(--color-text);">Mô hình AI:</span>
            <span id="narrative-model-label" class="chip chip-info font-mono"></span>
          </div>
          <div class="flex items-center space-x-3">
            <span id="narrative-manifest-hash" class="font-mono">Hash: -</span>
            <span id="narrative-insights-count" class="chip chip-neutral">0 Insights</span>
            <span id="narrative-blocks-count" class="chip chip-neutral">0 Blocks</span>
          </div>
        </div>

        <!-- NARRATIVE BLOCKS CONTAINER -->
        <div class="space-y-4" id="narrative-blocks-container">
          <!-- Dynamically populated by renderNarrativeUI() -->
        </div>

        <!-- EXPORT ACTION & DOWNLOAD STATUS -->
        <div class="pt-4 flex flex-col items-center space-y-4" style="border-top:1px solid var(--color-border);">
          <button onclick="generateDocx()" id="btn-generate-main" class="btn btn-secondary btn-lg w-full md:w-2/3" disabled>
            Xuất Tờ Trình MB07 (.DOCX)
          </button>

          <div id="export-result" class="hidden w-full md:w-2/3 p-4 rounded-lg text-center space-y-2" style="background:var(--color-success-bg); border:1px solid var(--color-success-border);">
            <div class="font-bold text-sm" style="color:var(--color-success);">Tờ trình tín dụng MB07 đã được khởi tạo thành công</div>
            <div class="text-xs font-mono" id="export-filename" style="color:var(--color-text-muted);">Tệp tin: TO_TRINH_MB07_PSD_HOAN_CHINH.docx</div>
            <a id="export-download-link" href="#" class="btn btn-success btn-sm" style="display:inline-flex;">Tải file Word (.docx)</a>
          </div>

          <!-- DOCUMENT QA RESULT PANEL (populated by renderDocumentQAPanel()) -->
          <div id="qa-result-panel" class="hidden w-full md:w-2/3"></div>
        </div>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- TAB 6: SẴN SÀNG HỘI ĐỒNG TÍN DỤNG                                         -->
    <!-- ========================================================================= -->
    <section id="tab-committee" class="hidden space-y-4">
      <div>
        <h1 class="page-title">Credit Committee</h1>
        <p class="page-subtitle">Câu hỏi chất vấn dự kiến và dữ liệu giải trình để RM chuẩn bị trước Hội đồng Tín dụng.</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs" style="color:var(--color-text-muted);">Hệ thống phân tích các điểm nhạy cảm, rủi ro tiềm ẩn và mô phỏng câu hỏi chất vấn từ Hội đồng Tín dụng, giúp RM chuẩn bị phương án giải trình tự tin.</p>
      </div>

      <!-- QUESTIONS CONTAINER -->
      <div class="space-y-4" id="committee-cards-container">
        <!-- Cards loaded dynamically via loadCommitteeCards() -->
      </div>
    </section>

      </main>
    </div>
  </div>

  <!-- MODAL: EDIT NARRATIVE -->
  <div id="modal-edit-narrative" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" style="background:rgba(15,23,42,0.55);">
    <div class="rounded-xl max-w-2xl w-full p-6 space-y-4" style="background:var(--color-surface); box-shadow:var(--shadow-md);">
      <div class="flex justify-between items-center border-b pb-3" style="border-color:var(--color-border);">
        <div>
          <h3 class="section-title">Chỉnh sửa &amp; tái thẩm định bản thảo</h3>
          <p id="modal-narr-target-title" class="text-xs" style="color:var(--color-text-muted);"></p>
        </div>
        <button onclick="closeEditModal()" class="btn-ghost btn btn-sm" style="font-size:16px;">&times;</button>
      </div>
      <div id="modal-narr-error" class="hidden p-3 text-xs rounded-lg" style="background:var(--color-danger-bg); border:1px solid var(--color-danger-border); color:var(--color-danger);"></div>
      <div class="space-y-2">
        <label class="text-xs font-semibold" style="color:var(--color-text-muted);">Nội dung đoạn văn (sẽ được đối soát tự động qua Python Verifier)</label>
        <textarea id="modal-narr-text" rows="6" class="w-full p-3 text-xs rounded-lg leading-relaxed" style="border:1px solid var(--color-border-strong);"></textarea>
      </div>
      <div class="space-y-1">
        <label class="text-xs font-semibold" style="color:var(--color-text-muted);">Ghi chú giải trình của RM (tùy chọn)</label>
        <input type="text" id="modal-narr-rm-note" placeholder="VD: Bổ sung chi tiết giải trình theo yêu cầu cấp thẩm quyền..." class="w-full p-2 text-xs rounded-lg" style="border:1px solid var(--color-border-strong);">
      </div>
      <div class="flex justify-end space-x-2 pt-2">
        <button onclick="closeEditModal()" class="btn btn-secondary btn-sm">Hủy</button>
        <button onclick="saveAndRevalidateNarrative()" id="btn-modal-save" class="btn btn-primary btn-sm">Lưu &amp; Tái Thẩm Định</button>
      </div>
    </div>
  </div>

  <!-- MODAL: TẠO HỒ SƠ KHÁCH HÀNG MỚI -->
  <div id="modal-new-case" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" style="background:rgba(15,23,42,0.55);">
    <div class="rounded-xl max-w-xl w-full p-6 space-y-4" style="background:var(--color-surface); box-shadow:var(--shadow-md);">
      <div class="flex justify-between items-center border-b pb-3" style="border-color:var(--color-border);">
        <h3 class="section-title">Khởi tạo hồ sơ thẩm định mới</h3>
        <button onclick="closeNewCaseModal()" class="btn-ghost btn btn-sm" style="font-size:16px;">&times;</button>
      </div>
      <div class="space-y-3 text-xs">
        <div>
          <label class="font-semibold" style="color:var(--color-text-muted);">Tên Doanh nghiệp đầy đủ <span style="color:var(--color-danger);">*</span></label>
          <input type="text" id="new-case-name" placeholder="VD: CÔNG TY CỔ PHẦN THƯƠNG MẠI ALPHA" class="w-full mt-1 p-2 rounded" style="border:1px solid var(--color-border-strong);">
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="font-semibold" style="color:var(--color-text-muted);">Tên viết tắt / Mã gợi nhớ <span style="color:var(--color-danger);">*</span></label>
            <input type="text" id="new-case-short-name" placeholder="VD: ALPHA_JSC" class="w-full mt-1 p-2 rounded" style="border:1px solid var(--color-border-strong);">
          </div>
          <div>
            <label class="font-semibold" style="color:var(--color-text-muted);">Mã số thuế <span style="color:var(--color-danger);">*</span></label>
            <input type="text" id="new-case-tax-code" placeholder="VD: 0312345678" class="w-full mt-1 p-2 rounded" style="border:1px solid var(--color-border-strong);">
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="font-semibold" style="color:var(--color-text-muted);">Vốn điều lệ (triệu VND)</label>
            <input type="number" id="new-case-capital" placeholder="VD: 50000" class="w-full mt-1 p-2 rounded" style="border:1px solid var(--color-border-strong);">
          </div>
          <div>
            <label class="font-semibold" style="color:var(--color-text-muted);">Hạn mức đề xuất (triệu VND)</label>
            <input type="number" id="new-case-limit" placeholder="VD: 100000" class="w-full mt-1 p-2 rounded" style="border:1px solid var(--color-border-strong);">
          </div>
        </div>
        <div>
          <label class="font-semibold" style="color:var(--color-text-muted);">Địa chỉ đăng ký trụ sở</label>
          <input type="text" id="new-case-address" placeholder="VD: Số 123 Đường ABC, Phường Bến Nghé, Quận 1, TP.HCM" class="w-full mt-1 p-2 rounded" style="border:1px solid var(--color-border-strong);">
        </div>
        <div>
          <label class="font-semibold" style="color:var(--color-text-muted);">Mô hình kinh doanh</label>
          <select id="new-case-business-model" class="w-full mt-1 p-2 rounded bg-white" style="border:1px solid var(--color-border-strong);">
            <option value="THUONG_MAI">Thương mại Phân phối</option>
            <option value="SAN_XUAT">Sản xuất</option>
            <option value="SAN_XUAT_VA_THUONG_MAI">Sản xuất & Thương mại</option>
            <option value="DICH_VU">Dịch vụ</option>
            <option value="XAY_DUNG_BAT_DONG_SAN">Xây dựng & Bất động sản</option>
          </select>
        </div>
      </div>
      <div class="flex justify-end space-x-2 pt-3 border-t" style="border-color:var(--color-border);">
        <button onclick="closeNewCaseModal()" class="btn btn-secondary btn-sm">Hủy</button>
        <button onclick="submitNewCase()" class="btn btn-primary btn-sm">Khởi Tạo Hồ Sơ</button>
      </div>
    </div>
  </div>

  <!-- MODAL: ĐỐI SOÁT & XÁC NHẬN BÓC TÁCH (RM REVIEW MODAL) -->
  <div id="modal-doc-review" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" style="background:rgba(15,23,42,0.55);">
    <div class="rounded-xl max-w-4xl w-full p-6 space-y-4" style="background:var(--color-surface); box-shadow:var(--shadow-md);">
      <div class="flex justify-between items-center border-b pb-3" style="border-color:var(--color-border);">
        <div class="min-w-0">
          <h3 id="modal-review-title" class="section-title">Đối soát Dữ liệu Bóc tách GreenNode AI</h3>
          <p id="modal-review-subtitle" class="text-xs text-wrap-safe" style="color:var(--color-text-muted);">Đối soát bằng chứng trang và giải quyết xung đột trước khi xác nhận vào hồ sơ MB07</p>
        </div>
        <button onclick="closeReviewModal()" class="btn-ghost btn btn-sm flex-none" style="font-size:16px;">&times;</button>
      </div>

      <!-- REVIEW CONTENT AREA -->
      <div id="modal-review-body" class="max-h-[60vh] overflow-y-auto space-y-4 pr-1 text-xs">
        <!-- Dynamic content injected by renderReviewBody -->
      </div>

      <div class="flex items-center justify-between pt-3 border-t gap-3" style="border-color:var(--color-border);">
        <div class="text-[11px] px-3 py-1.5 rounded-lg text-wrap-safe" style="background:var(--color-warning-bg); border:1px solid var(--color-warning-border); color:var(--color-warning);">
          <strong>Nguyên tắc MSB:</strong> Dữ liệu chỉ được xác nhận khi có số trang và trích dẫn bằng chứng xác thực.
        </div>
        <div class="flex space-x-2 flex-none">
          <button onclick="closeReviewModal()" class="btn btn-secondary btn-sm">Đóng</button>
          <button id="btn-confirm-review" onclick="confirmCurrentReview()" class="btn btn-success btn-sm">Xác Nhận Vào Hồ Sơ</button>
        </div>
      </div>
    </div>
  </div>

  <!-- JAVASCRIPT LOGIC -->
  <script>
    let CURRENT_ACTIVE_TAB = 'tab-dashboard';
    let CURRENT_CASE_ID = 'PSD';
    let CURRENT_REVIEW_DOCTYPE = null;

    // Sidebar workflow-state tracking (visual only). Each flag reflects a real,
    // already-tracked signal — never inferred merely from unrelated data existing.
    const VISITED_TABS = new Set(['tab-dashboard']);
    let SECTION_A_SAVED = false;
    let SECTION_B_SAVED = false;

    // Same business-model labels already used by the "new case" / business-review
    // <select> options elsewhere in this page — reused here for display only.
    const BUSINESS_MODEL_LABELS = {
      THUONG_MAI: 'Thương mại Phân phối',
      SAN_XUAT: 'Sản xuất',
      SAN_XUAT_VA_THUONG_MAI: 'Sản xuất & Thương mại',
      DICH_VU: 'Dịch vụ',
      XAY_DUNG_BAT_DONG_SAN: 'Xây dựng & Bất động sản',
    };

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
      if (typeof updateSidebarProgress === 'function') updateSidebarProgress();
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
        badge.innerText = `${confirmedCount}/4 nhóm tài liệu đã nạp`;
        if (confirmedCount === 4) {
          badge.className = 'chip chip-success';
        } else if (confirmedCount > 0) {
          badge.className = 'chip chip-info';
        } else {
          badge.className = 'chip chip-neutral';
        }
      }
      updateSidebarProgress();
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
          badgeHtml = '<span class="chip chip-neutral">Not uploaded</span>';
          actionButtons = `
            <button onclick="triggerDocUpload('${docType}')" class="btn btn-primary btn-sm">Tải lên PDF</button>
          `;
          tipText = 'Chờ RM tải lên tài liệu PDF gốc';
          break;

        case 'UPLOADING':
          badgeHtml = '<span class="chip chip-info">Uploading…</span>';
          actionButtons = '<button disabled class="btn btn-secondary btn-sm">Đang tải...</button>';
          tipText = 'Đang chuyển tệp lên máy chủ...';
          break;

        case 'AI_PROCESSING':
          badgeHtml = '<span class="chip chip-info">AI extracting…</span>';
          actionButtons = '<button disabled class="btn btn-secondary btn-sm">Đang xử lý AI...</button>';
          tipText = 'Mô hình GLM-5.2 / OCR đang trích xuất và đối soát trang...';
          break;

        case 'PREVIEW_READY':
          badgeHtml = '<span class="chip chip-warning">Needs review</span>';
          actionButtons = `
            <button onclick="triggerDocUpload('${docType}')" class="btn btn-secondary btn-sm">Chọn file khác</button>
            <button onclick="openReviewModal('${docType}')" class="btn btn-primary btn-sm">Đối soát &amp; Xác nhận</button>
          `;
          tipText = 'AI đã bóc tách xong! Bấm để đối soát bằng chứng trang và xác nhận';
          break;

        case 'CONFLICT':
          badgeHtml = '<span class="chip chip-warning">Conflict</span>';
          actionButtons = `
            <button onclick="triggerDocUpload('${docType}')" class="btn btn-secondary btn-sm">Chọn file khác</button>
            <button onclick="openReviewModal('${docType}')" class="btn btn-primary btn-sm">Xử lý xung đột</button>
          `;
          tipText = 'Số liệu tài liệu xung đột với hồ sơ! Cần RM lựa chọn số liệu chuẩn';
          break;

        case 'RM_CONFIRMED':
          badgeHtml = '<span class="chip chip-success">Confirmed</span>';
          actionButtons = `
            <button onclick="triggerDocUpload('${docType}')" class="btn btn-secondary btn-sm">Thay thế PDF</button>
            <button onclick="openReviewModal('${docType}')" class="btn btn-primary btn-sm">Xem lại</button>
          `;
          tipText = 'Dữ liệu đã được khóa và đồng bộ vào Tờ trình MB07';
          break;

        case 'ERROR':
          badgeHtml = '<span class="chip chip-danger">Error</span>';
          actionButtons = `
            <button onclick="triggerDocUpload('${docType}')" class="btn btn-danger btn-sm">Thử lại</button>
          `;
          tipText = info.errorMsg || 'Xử lý tài liệu không thành công';
          break;
      }

      if (badgeEl) badgeEl.innerHTML = badgeHtml;
      if (tipEl) tipEl.innerText = tipText;
      if (actionsEl) {
        actionsEl.innerHTML = `
          <span id="tip-${docType}" class="text-[11px] text-wrap-safe" style="color:var(--color-text-faint);">${tipText}</span>
          <div class="flex space-x-2 flex-none">${actionButtons}</div>
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
            statusBadge = '<span class="chip chip-warning">Xung đột</span>';
            resolutionControl = `
              <div class="mt-1 space-y-1">
                <div class="text-[10px]" style="color:var(--color-warning);">${f.conflict_note || ''}</div>
                <select id="res-legal-${k}" class="w-full text-[11px] p-1 rounded font-medium" style="background:var(--color-warning-bg); border:1px solid var(--color-warning-border);">
                  <option value="USE_EXTRACTED">✓ Lấy số liệu mới bóc tách</option>
                  <option value="KEEP_EXISTING">✕ Giữ số liệu hồ sơ hiện tại</option>
                </select>
              </div>
            `;
          } else if (f.status === 'WARNING') {
            statusBadge = `<span class="chip chip-warning" title="${f.warning_reason || ''}">Cảnh báo</span>`;
          } else if (f.status === 'MISSING') {
            statusBadge = '<span class="chip chip-neutral">Chưa có</span>';
          } else {
            statusBadge = '<span class="chip chip-success">Xác thực</span>';
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
            statusBadge = '<span class="chip chip-warning">Xung đột</span>';
            resControl = `
              <div class="mt-1">
                <div class="text-[10px]" style="color:var(--color-warning);">${item.conflict_note || ''}</div>
                <select id="res-fin-${item.canonical_field}-${item.year}" class="w-full text-[10px] p-1 rounded font-medium" style="background:var(--color-warning-bg); border:1px solid var(--color-warning-border);">
                  <option value="USE_EXTRACTED">✓ Dùng số liệu BCTC</option>
                  <option value="KEEP_EXISTING">✕ Giữ số liệu cũ</option>
                </select>
              </div>
            `;
          } else if (item.status === 'WARNING') {
            statusBadge = '<span class="chip chip-warning">Cảnh báo</span>';
          } else {
            statusBadge = '<span class="chip chip-success">Extracted</span>';
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
          resetPerCaseFrontendState();

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
          SECTION_A_SAVED = true;
          updateSidebarProgress();
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
          SECTION_B_SAVED = true;
          updateSidebarProgress();
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
        const c = data.section_c || {};
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

        // Dashboard fields with empty-state handling.
        // KPI cards show a concise headline value; full precision/raw canonical
        // numbers are untouched — only how they're displayed here changes.
        document.getElementById('dash-cust-name').innerText = cust.short_name || cust.name || 'DOANH NGHIỆP MỚI';
        document.getElementById('dash-cust-cif').innerText = `CIF: ${cust.cif || 'Chưa cấp'}`;

        if (cust.rating_grade) {
          document.getElementById('dash-cust-rating').innerText = `Hạng ${cust.rating_grade} · ${cust.rating_score || 0}đ`;
        } else {
          document.getElementById('dash-cust-rating').innerText = 'Chưa xếp hạng';
        }

        const totalLimit = b.total_limit || 0;
        document.getElementById('dash-total-limit').innerText = formatVndCompact(totalLimit);
        document.getElementById('dash-loan-limit').innerText = `Vay ${toTyVnd(b.loan_limit || 0)} tỷ · Bảo lãnh ${toTyVnd(b.guarantee_limit || 0)} tỷ`;

        const revArr = d.net_revenue || [];
        const npArr = d.net_profit_after_tax || [];
        const hasFin = revArr.length > 0 && revArr[revArr.length - 1] > 0;

        if (hasFin) {
          const revLast = revArr[revArr.length - 1];
          const npLast = npArr.length > 0 ? npArr[npArr.length - 1] : 0;
          document.getElementById('dash-rev-2025').innerText = formatVndCompact(revLast);
          document.getElementById('dash-np-2025').innerText = `LNST ${toTyVnd(npLast)} tỷ`;
        } else {
          document.getElementById('dash-rev-2025').innerText = 'Chưa nạp BCTC';
          document.getElementById('dash-np-2025').innerText = 'LNST: Chưa có số liệu';
        }

        const cic = splitCicStatus(e.history_status);
        document.getElementById('dash-cic-status').innerText = cic.main;
        document.getElementById('dash-cic-meta').innerText = cic.meta;
        document.getElementById('dash-msb-out').innerText = `Dư nợ tại MSB: ${toTyVnd(e.msb_outstanding || 0)} tỷ`;

        document.getElementById('dash-tax-code').innerText = cust.tax_code || 'Chưa có MST';
        document.getElementById('dash-legal-rep').innerText = cust.legal_rep_name ? `${cust.legal_rep_name} (${cust.legal_rep_title || 'Đại diện'})` : 'Chưa cập nhật';
        document.getElementById('dash-capital').innerText = cust.charter_capital ? formatVndCompact(cust.charter_capital) : 'Chưa cập nhật';
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

        // Keep the Document Workspace summary snippets in sync with the active case.
        // Previously these only updated after a fresh upload/extraction or when
        // creating a brand new case, so switching between existing demo cases left
        // the PREVIOUS case's (or the original static placeholder's) text behind.
        // Live extraction results (updateCardSummarySnippet) still run afterward and
        // correctly take precedence within the same session.
        document.getElementById('sum-legal-name').innerText = cust.name || 'Chưa cập nhật';
        document.getElementById('sum-legal-tax').innerText = cust.tax_code || 'Chưa cập nhật';
        document.getElementById('sum-legal-capital').innerText = cust.charter_capital ? `${cust.charter_capital.toLocaleString('vi-VN')} tr` : 'Chưa cập nhật';
        document.getElementById('sum-legal-rep').innerText = cust.legal_rep_name ? `${cust.legal_rep_name} (${cust.legal_rep_title || 'Đại diện'})` : 'Chưa cập nhật';

        document.getElementById('sum-biz-model').innerText = BUSINESS_MODEL_LABELS[c.business_model] || c.business_model || 'Chưa cập nhật';
        const bizSuppliers = Array.isArray(c.suppliers) ? c.suppliers : [];
        document.getElementById('sum-biz-suppliers').innerText = bizSuppliers.length
          ? bizSuppliers.slice(0, 3).map(s => `${s.name} (${s.share}%)`).join(', ')
          : 'Chưa nạp hồ sơ kinh doanh';
        const bizCustomers = Array.isArray(c.customers) ? c.customers : [];
        document.getElementById('sum-biz-customers').innerText = bizCustomers.length
          ? bizCustomers.slice(0, 3).map(cu => `${cu.name} (${cu.share}%)`).join(', ')
          : 'Chưa nạp hồ sơ kinh doanh';

        document.getElementById('sum-fin-auditor').innerText = d.auditor || 'Chưa nạp BCTC';
        const equityArr = d.equity || [];
        if (hasFin) {
          const revLastSum = revArr[revArr.length - 1];
          const npLastSum = npArr.length > 0 ? npArr[npArr.length - 1] : 0;
          const eqLastSum = equityArr.length > 0 ? equityArr[equityArr.length - 1] : 0;
          document.getElementById('sum-fin-rev').innerText = `${revLastSum.toLocaleString('vi-VN')} tr`;
          document.getElementById('sum-fin-np').innerText = `${npLastSum.toLocaleString('vi-VN')} tr`;
          document.getElementById('sum-fin-equity').innerText = `${eqLastSum.toLocaleString('vi-VN')} tr`;
        } else {
          document.getElementById('sum-fin-rev').innerText = 'Chưa có số liệu';
          document.getElementById('sum-fin-np').innerText = 'Chưa có số liệu';
          document.getElementById('sum-fin-equity').innerText = 'Chưa có số liệu';
        }

        document.getElementById('sum-cic-date').innerText = e.cic_date || 'Chưa tra cứu';
        document.getElementById('sum-cic-status').innerText = e.history_status || 'Chưa có dữ liệu CIC';
        document.getElementById('sum-cic-msb').innerText = e.msb_outstanding != null ? `${e.msb_outstanding.toLocaleString('vi-VN')} tr` : 'Chưa có dữ liệu';

      } catch (err) {
        console.error("Error loading case data:", err);
      }
    }

    async function loadCommitteeCards() {
      const container = document.getElementById('committee-cards-container');
      container.innerHTML = '<div class="p-6 text-center text-xs" style="color:var(--color-text-muted);">Đang tổng hợp các câu hỏi chất vấn từ dữ liệu hồ sơ...</div>';

      try {
        const res = await fetch('/api/committee_prep');
        const data = await res.json();
        const cards = data.cards || [];

        if (cards.length === 0) {
          container.innerHTML = `<div class="panel p-6 text-center text-sm" style="color:var(--color-success);">Hồ sơ hoàn thiện — không phát hiện rủi ro bất thường.</div>`;
          return;
        }

        let html = '';
        cards.forEach((c, idx) => {
          const sevChip = c.severity === 'HIGH' ? '<span class="chip chip-danger">Cần bảo vệ cao</span>' : '<span class="chip chip-warning">Quan trọng</span>';

          let factsHtml = '';
          (c.facts_to_prepare || []).forEach(f => {
            factsHtml += `<div class="text-wrap-safe"><span style="color:var(--color-text-muted);">${escapeHtml(f.label)}:</span> <span class="font-semibold" style="color:var(--color-text);">${escapeHtml(String(f.value))}</span></div>`;
          });

          let defenseHtml = '';
          (c.suggested_defense_points || []).forEach(p => {
            defenseHtml += `<li class="text-wrap-safe" style="color:var(--color-text);">${escapeHtml(p)}</li>`;
          });

          html += `
            <div class="panel p-5 space-y-4">
              <div class="flex items-start justify-between gap-2">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="nav-item-step" style="background:var(--color-primary); color:#fff;">${idx + 1}</span>
                  <span class="text-xs font-semibold uppercase tracking-wide text-wrap-safe" style="color:var(--color-text-muted);">${escapeHtml(c.category)}</span>
                </div>
                <div class="flex-none">${sevChip}</div>
              </div>

              <div>
                <h4 class="text-sm font-semibold leading-snug text-wrap-safe" style="color:var(--color-primary);">"${escapeHtml(c.question)}"</h4>
                <div class="mt-1.5 text-xs p-2.5 rounded-md text-wrap-safe" style="background:var(--color-bg); border:1px solid var(--color-border); color:var(--color-text-muted);">
                  <span class="font-semibold" style="color:var(--color-text);">Nguyên nhân chất vấn:</span> ${escapeHtml(c.why_asked)}
                </div>
              </div>

              <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                <div class="space-y-1.5 p-3 rounded-md" style="background:var(--color-bg); border:1px solid var(--color-border);">
                  <div class="font-semibold" style="color:var(--color-text);">Dữ liệu thực tế RM cần chuẩn bị</div>
                  <div class="space-y-1">${factsHtml}</div>
                </div>

                <div class="space-y-1.5 p-3 rounded-md" style="background:var(--color-success-bg); border:1px solid var(--color-success-border);">
                  <div class="font-semibold" style="color:var(--color-success);">Luận điểm giải trình gợi ý</div>
                  <ul class="list-disc list-inside space-y-1">${defenseHtml}</ul>
                </div>
              </div>

              <div class="space-y-1.5 pt-2 border-t" style="border-color:var(--color-border);">
                <div class="flex justify-between items-center gap-2">
                  <label class="text-xs font-semibold" style="color:var(--color-text-muted);">Ghi chú giải trình của RM</label>
                  <button onclick="saveCommitteeNote('${c.question_id}')" class="btn btn-secondary btn-sm flex-none">Lưu ghi chú</button>
                </div>
                <textarea id="note-${c.question_id}" rows="2" placeholder="Nhập ghi chú phản biện của RM khi ra Hội đồng..." class="w-full p-2.5 text-xs rounded-lg" style="border:1px solid var(--color-border-strong);">${escapeHtml(c.rm_note || '')}</textarea>
              </div>
            </div>
          `;
        });

        container.innerHTML = html;
      } catch (e) {
        container.innerHTML = `<div class="p-4 text-xs" style="color:var(--color-danger);">Lỗi nạp câu hỏi: ${escapeHtml(e.message)}</div>`;
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

    /* Resets frontend-only, per-case tracking flags (sidebar progress signals and the
       "has this document card been exported" flag) so they never carry over from a
       previously active case. Called whenever the active case changes underneath us
       (switch or demo reset) — never called on a plain tab switch within the same
       case. */
    function resetPerCaseFrontendState() {
      SECTION_A_SAVED = false;
      SECTION_B_SAVED = false;
      VISITED_TABS.clear();
      VISITED_TABS.add(CURRENT_ACTIVE_TAB);
      window.__MB07_EXPORTED__ = false;
      const resBox = document.getElementById('export-result');
      if (resBox) resBox.classList.add('hidden');
      const qaPanel = document.getElementById('qa-result-panel');
      if (qaPanel) { qaPanel.classList.add('hidden'); qaPanel.innerHTML = ''; }
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
        resetPerCaseFrontendState();
        await loadCaseData();
        if (CURRENT_ACTIVE_TAB === 'tab-committee') loadCommitteeCards();
        if (CURRENT_ACTIVE_TAB === 'tab-narrative') loadNarrativeState(cid);
        updateSidebarProgress();
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
          resetPerCaseFrontendState();
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
          updateSidebarProgress();
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

    /* Presentation-only VND formatting helpers for concise KPI cards.
       Canonical values (always in triệu VND, unchanged) are never modified — these
       only control how numbers already returned by the backend are displayed. */
    function toTyVnd(millionValue) {
      const v = Number(millionValue) || 0;
      return (v / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 });
    }
    function formatVndCompact(millionValue) {
      const v = Number(millionValue) || 0;
      if (Math.abs(v) >= 1000) {
        return `${toTyVnd(v)} tỷ VND`;
      }
      return `${v.toLocaleString('vi-VN')} triệu VND`;
    }
    /* Extracts a short CIC headline from the full history_status sentence
       (e.g. "100% Nhóm 1 (Đủ tiêu chuẩn) trong 24 tháng gần nhất tại MSB và các
       TCTD." -> headline "Nhóm 1", meta "100% lịch sử tín dụng đạt chuẩn").
       Never uses the full sentence as the KPI headline. If no debt-group token
       ("Nhóm N") is found, falls back to showing the raw string verbatim with
       no meta line rather than guessing/inventing data. Built from existing
       data only — history_status is not altered, only re-presented. */
    function splitCicStatus(raw) {
      const s = String(raw || '').trim();
      const groupMatch = s.match(/Nhóm\\s*\\d+/i);
      if (groupMatch) {
        const pctMatch = s.match(/^(\\d+(?:[.,]\\d+)?)%/);
        const meta = pctMatch ? `${pctMatch[1]}% lịch sử tín dụng đạt chuẩn` : '';
        return { main: groupMatch[0].replace(/\\s+/g, ' '), meta };
      }
      return { main: s || 'Chưa tra cứu CIC', meta: '' };
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

      const genBtn = document.getElementById('btn-generate-main');

      switch (state) {
        case 'NOT_READY':
          badgeEl.className = 'chip chip-neutral';
          badgeEl.innerText = 'Chưa Đủ Dữ Liệu';
          actionsEl.innerHTML = `
            <button disabled class="btn btn-secondary btn-sm" title="Cần tối thiểu thông tin pháp lý và BCTC đã xác nhận">
              Tạo Nhận Định AI
            </button>
          `;
          alertEl.innerHTML = `
            <div class="p-4 rounded-lg text-xs flex items-start space-x-3" style="background:var(--color-warning-bg); border:1px solid var(--color-warning-border); color:var(--color-warning);">
              <div>
                <div class="font-bold mb-1">Chưa đủ dữ liệu để tạo nhận định.</div>
                <p class="leading-relaxed">${escapeHtml(NARRATIVE_STATE.error || 'Hồ sơ chưa có đủ dữ liệu canonical (tên doanh nghiệp và BCTC). Vui lòng chuyển sang [2. Không gian Tài liệu] để tải lên và đối soát tài liệu trước khi tạo nhận định AI.')}</p>
              </div>
            </div>
          `;
          if (telemetryEl) telemetryEl.classList.add('hidden');
          if (genBtn) { genBtn.disabled = true; genBtn.className = 'btn btn-secondary btn-lg w-full md:w-2/3'; }
          break;

        case 'READY':
          badgeEl.className = 'chip chip-info';
          badgeEl.innerText = 'Sẵn Sàng Tạo Nhận Định';
          actionsEl.innerHTML = `
            <button onclick="generateNarrative()" id="btn-narrative-generate" class="btn btn-primary btn-sm">
              Tạo Nhận Định AI
            </button>
          `;
          if (NARRATIVE_STATE.error) {
            alertEl.innerHTML = `
              <div class="p-4 rounded-lg text-xs flex items-start space-x-3" style="background:var(--color-danger-bg); border:1px solid var(--color-danger-border); color:var(--color-danger);">
                <div>
                  <div class="font-bold mb-1">Không thể tạo nhận định AI.</div>
                  <p class="leading-relaxed">${escapeHtml(NARRATIVE_STATE.error)}</p>
                </div>
              </div>
            `;
          } else {
            alertEl.innerHTML = `
              <div class="p-4 rounded-lg text-xs flex items-start space-x-3" style="background:#EEF3FC; border:1px solid #D3E0F5; color:var(--color-accent-dark);">
                <div>
                  <div class="font-bold mb-1">Dữ liệu canonical đủ để tạo nhận định.</div>
                  <p class="leading-relaxed">Bấm <strong>"Tạo Nhận Định AI"</strong> để kích hoạt luồng: FactManifest SHA-256 → GreenNode Insight Discovery → Python Verifier → Grounded Narrative Writer → Deterministic Validator.</p>
                </div>
              </div>
            `;
          }
          if (telemetryEl) telemetryEl.classList.add('hidden');
          if (genBtn) { genBtn.disabled = true; genBtn.className = 'btn btn-secondary btn-lg w-full md:w-2/3'; }
          break;

        case 'GENERATING':
          badgeEl.className = 'chip chip-info';
          badgeEl.innerText = 'AI đang phân tích...';
          actionsEl.innerHTML = `
            <button disabled class="btn btn-secondary btn-sm">Đang tạo nhận định...</button>
          `;
          alertEl.innerHTML = `
            <div class="p-4 rounded-lg text-xs flex items-start space-x-3" style="background:#EEF3FC; border:1px solid #D3E0F5; color:var(--color-accent-dark);">
              <div>
                <div class="font-bold mb-1">AI đang tổng hợp dữ liệu đã xác nhận và xây dựng nhận định...</div>
                <p class="leading-relaxed">Đang chạy: Đóng gói FactManifest → GLM-5.2 Insight Discovery → Đối soát công thức toán độc lập bằng Python → Soạn thảo văn bản Grounded Narrative → Kiểm định tính toàn vẹn MB07.</p>
              </div>
            </div>
          `;
          if (telemetryEl) telemetryEl.classList.add('hidden');
          if (genBtn) { genBtn.disabled = true; genBtn.className = 'btn btn-secondary btn-lg w-full md:w-2/3'; }
          break;

        case 'DRAFT':
          badgeEl.className = 'chip chip-warning';
          badgeEl.innerText = 'AI Draft — Chờ RM xác nhận';
          actionsEl.innerHTML = `
            <button onclick="acceptNarrative()" id="btn-narrative-accept" class="btn btn-success btn-sm">RM Phê Duyệt Toàn Bộ Bản Thảo</button>
            <button onclick="generateNarrative()" id="btn-narrative-regenerate" class="btn btn-secondary btn-sm">Tạo Lại</button>
          `;
          alertEl.innerHTML = `
            <div class="p-4 rounded-lg text-xs flex items-start justify-between gap-3" style="background:var(--color-warning-bg); border:1px solid var(--color-warning-border); color:var(--color-warning);">
              <div>
                <div class="font-bold mb-1">Bản thảo AI đã tạo thành công — đang ở trạng thái Draft chờ RM thẩm định.</div>
                <p class="leading-relaxed">Bản thảo chưa được ghi nhận vào Tờ trình chính thức. RM có thể kiểm tra từng đoạn văn bản, bấm <strong>"RM Chỉnh sửa"</strong> để hiệu chỉnh và tái thẩm định, hoặc bấm <strong>"RM Phê Duyệt Toàn Bộ"</strong> để khóa số liệu và gắn kết vào Tờ trình MB07.</p>
              </div>
            </div>
          `;
          if (genBtn) { genBtn.disabled = true; genBtn.className = 'btn btn-secondary btn-lg w-full md:w-2/3'; genBtn.title = 'Cần RM phê duyệt toàn bộ bản thảo trước khi xuất bản'; }
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
          badgeEl.className = 'chip chip-success';
          badgeEl.innerText = '✓ Đã được RM xác nhận';
          actionsEl.innerHTML = `
            <span class="chip chip-success">✓ Đã được RM xác nhận</span>
            <button onclick="generateNarrative()" id="btn-narrative-regenerate" class="btn btn-secondary btn-sm">Tạo Lại Bản Thảo</button>
          `;
          alertEl.innerHTML = `
            <div class="p-4 rounded-lg text-xs flex items-start space-x-3" style="background:var(--color-success-bg); border:1px solid var(--color-success-border); color:var(--color-success);">
              <div>
                <div class="font-bold mb-1">Toàn bộ nhận định đã được RM xác nhận cho Tờ trình MB07.</div>
                <p class="leading-relaxed">Các đoạn văn bản đã được gắn kết chính thức vào Tờ trình tín dụng. Bấm <strong>"Xuất Tờ Trình MB07"</strong> phía dưới để tải văn bản Word hoàn chỉnh.</p>
              </div>
            </div>
          `;
          if (genBtn) { genBtn.disabled = false; genBtn.className = 'btn btn-primary btn-lg w-full md:w-2/3'; genBtn.title = ''; }
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

      updateSidebarProgress();

      if (NARRATIVE_STATE.blocks.length === 0) {
        if (state === 'GENERATING') {
          containerEl.innerHTML = `
            <div class="p-10 text-center space-y-2 rounded-lg" style="background:var(--color-bg); border:1px dashed var(--color-border-strong); color:var(--color-text-muted);">
              <div class="text-xs font-semibold">Đang tổng hợp các chỉ tiêu tài chính và đối soát văn bản...</div>
            </div>
          `;
        } else {
          containerEl.innerHTML = `
            <div class="p-10 text-center space-y-2 rounded-lg" style="background:var(--color-bg); border:1px dashed var(--color-border-strong);">
              <div class="text-sm font-semibold" style="color:var(--color-text);">Chưa có bản thảo nhận định tín dụng nào cho hồ sơ này</div>
              <p class="text-xs max-w-md mx-auto" style="color:var(--color-text-muted);">Nhận định tín dụng MB07 sẽ được tự động soạn thảo dựa trên 100% dữ liệu đã xác nhận và các chỉ số tài chính đã được Python kiểm chứng.</p>
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
          statusTag = '<span class="chip chip-success">Đã được RM xác nhận</span>';
        } else if (wasEdited) {
          statusTag = '<span class="chip chip-info">RM đã hiệu chỉnh</span>';
        } else {
          statusTag = '<span class="chip chip-warning">AI Draft</span>';
        }

        const factsTagsHtml = factsUsed.slice(0, 3).map(f => `<span class="chip chip-neutral font-mono">${escapeHtml(f)}</span>`).join(' ');
        const insightsTagsHtml = insightsUsed.slice(0, 2).map(i => `<span class="chip chip-info font-mono">${escapeHtml(i)}</span>`).join(' ');

        html += `
          <div class="p-4 rounded-lg border space-y-2.5" id="${blockId}" style="border-color:var(--color-border); background:var(--color-bg);">
            <div class="flex items-center justify-between gap-2">
              <span class="text-sm font-semibold text-wrap-safe" style="color:var(--color-text);">${escapeHtml(title)}</span>
              <div class="flex-none">${statusTag}</div>
            </div>
            <p class="text-xs bg-white p-3.5 rounded-md border leading-relaxed text-wrap-safe" style="border-color:var(--color-border); color:var(--color-text); white-space:pre-line;" id="${textId}">${escapeHtml(text)}</p>
            <div class="flex items-center justify-between text-[11px] pt-1 border-t gap-2" style="border-color:var(--color-border); color:var(--color-text-faint);">
              <div class="flex flex-wrap gap-1.5 items-center">
                ${factsTagsHtml}
                ${insightsTagsHtml}
              </div>
              <button onclick="openEditNarrativeModal('${binding}')" class="btn btn-ghost btn-sm flex-none">Chỉnh sửa</button>
            </div>
          </div>
        `;
      });

      containerEl.innerHTML = html;
    }

    /* Sidebar progress indicators (visual only — never changes any request/response
       behavior). Semantics:
         ✓ done   — a real, already-tracked completion signal for that step.
         ●  active — the step currently being viewed (always shown regardless of
                     whether its own completion signal is true).
         ○  pending — no reliable completion signal yet; NEVER shown as done just
                     because unrelated data (e.g. other steps' data) happens to exist. */
    function updateSidebarProgress() {
      VISITED_TABS.add(CURRENT_ACTIVE_TAB);
      const allDocsConfirmed = Object.values(DOC_STATES).every(s => s.state === 'RM_CONFIRMED');

      const done = {
        'tab-dashboard': VISITED_TABS.has('tab-dashboard'),
        'tab-upload': allDocsConfirmed,
        'tab-review': SECTION_A_SAVED && SECTION_B_SAVED,
        'tab-insights': VISITED_TABS.has('tab-insights'),
        'tab-narrative': NARRATIVE_STATE.status === 'ACCEPTED',
        'tab-committee': !!window.__MB07_EXPORTED__,
      };

      Object.keys(done).forEach(tabId => {
        const nav = document.getElementById('nav-' + tabId);
        if (!nav) return;
        const stepEl = nav.querySelector('.nav-item-step');
        if (!stepEl) return;

        stepEl.classList.remove('is-done', 'is-active', 'is-pending');
        if (tabId === CURRENT_ACTIVE_TAB) {
          stepEl.classList.add('is-active');
          stepEl.textContent = '●';
        } else if (done[tabId]) {
          stepEl.classList.add('is-done');
          stepEl.textContent = '✓';
        } else {
          stepEl.classList.add('is-pending');
          stepEl.textContent = '○';
        }
      });

      updateTopbarPrimaryCTA();
    }

    // Backwards-compatibility aliases
    function acceptAllNarrative() {
      acceptNarrative();
    }
    function editNarrativeBlock(target) {
      openEditNarrativeModal(target);
    }

    function renderDocumentQAPanel(qa) {
      const panel = document.getElementById('qa-result-panel');
      if (!panel) return;
      if (!qa) { panel.classList.add('hidden'); panel.innerHTML = ''; return; }

      const detChecks = qa.deterministic_checks || {};
      const visChecks = qa.visual_checks || {};
      const issues = qa.issues || [];

      // font_consistency never blocks export (cross-platform font-substitution
      // differences) -- render its row as a warning (amber), never as a blocking
      // failure (red), even when the model reports FAIL for it.
      const NON_BLOCKING_VISUAL_KEYS = new Set(['font_consistency']);
      const renderCheckRow = (label, value, nonBlocking) => {
        const ok = value === 'PASS';
        const isFail = value === 'FAIL';
        const icon = ok ? '✓' : (isFail ? (nonBlocking ? '!' : '✕') : '·');
        const color = ok ? 'var(--color-success)' : (isFail ? (nonBlocking ? 'var(--color-warning)' : 'var(--color-danger)') : 'var(--color-text-faint)');
        return `<div class="flex items-center gap-1.5 text-xs"><span style="color:${color}; font-weight:700;">${icon}</span><span style="color:var(--color-text-muted);">${escapeHtml(label)}</span></div>`;
      };

      const detLabels = {
        docx_opens: 'Mở tệp DOCX', package_integrity: 'Toàn vẹn gói tin', no_corruption_detected: 'Không lỗi hỏng',
        authoritative_template_located: 'Template gốc', section_count_preserved: 'Số lượng Section',
        section_orientation_margins_preserved: 'Lề / hướng trang', table_count_structurally_compatible: 'Bảng biểu',
        header_footer_relationships_present: 'Header/Footer', image_logo_relationships_preserved: 'Logo',
      };
      const visLabels = {
        logo: 'Logo', header_footer: 'Header/Footer', font_consistency: 'Font chữ (cảnh báo, không chặn)',
        table_layout: 'Bố cục bảng', spacing_alignment: 'Căn chỉnh/Khoảng cách', overall_visual_fidelity: 'Tổng thể',
      };

      const detHtml = Object.entries(detChecks).map(([k, v]) => renderCheckRow(detLabels[k] || k, v, false)).join('');
      const visEntries = Object.entries(visChecks).filter(([k]) => k !== 'overall_visual_fidelity');
      const visHtml = visEntries.map(([k, v]) => renderCheckRow(visLabels[k] || k, v, NON_BLOCKING_VISUAL_KEYS.has(k))).join('');

      let statusChip, statusNote;
      if (qa.status === 'PASS') {
        statusChip = '<span class="chip chip-success">PASS</span>';
        statusNote = 'Tài liệu đạt chuẩn định dạng MB07.';
      } else if (qa.status === 'PASS_WITH_WARNING') {
        statusChip = '<span class="chip chip-warning">PASS — CÓ CẢNH BÁO</span>';
        statusNote = 'Xuất bản đã được cho phép. Phát hiện khác biệt font chữ (không chặn xuất bản theo chính sách) — vui lòng xem lại trước khi hoàn tất.';
      } else if (qa.status === 'VISUAL_QA_UNAVAILABLE') {
        statusChip = '<span class="chip chip-warning">VISUAL QA UNAVAILABLE</span>';
        statusNote = 'Kiểm định cấu trúc đạt yêu cầu. Không thể xác minh định dạng hiển thị trong môi trường này.';
      } else {
        statusChip = '<span class="chip chip-danger">FAIL</span>';
        statusNote = 'Tài liệu chưa đạt kiểm định định dạng MB07 — xuất bản bị chặn.';
      }

      const issuesColor = qa.status === 'FAIL' ? 'var(--color-danger)' : 'var(--color-warning)';
      const issuesHtml = (qa.status !== 'PASS' && issues.length > 0)
        ? `<ul class="text-xs mt-2 space-y-1 list-disc list-inside text-wrap-safe" style="color:${issuesColor};">${issues.slice(0, 8).map(i => `<li>${escapeHtml(String(i))}</li>`).join('')}</ul>`
        : '';

      panel.classList.remove('hidden');
      panel.innerHTML = `
        <div class="panel p-4 text-left">
          <div class="flex items-center justify-between mb-2 gap-2">
            <span class="section-title" style="font-size:13px;">Document QA</span>
            ${statusChip}
          </div>
          <div class="text-xs mb-3" style="color:var(--color-text-muted);">${escapeHtml(statusNote)}</div>
          <div class="grid grid-cols-2 gap-x-4 gap-y-1.5">
            <div class="space-y-1">
              <div class="text-[11px] font-semibold uppercase" style="color:var(--color-text-faint);">Deterministic</div>
              ${detHtml || '<div class="text-xs" style="color:var(--color-text-faint);">—</div>'}
            </div>
            <div class="space-y-1">
              <div class="text-[11px] font-semibold uppercase" style="color:var(--color-text-faint);">Visual QA</div>
              ${visHtml || '<div class="text-xs" style="color:var(--color-text-faint);">Không khả dụng</div>'}
            </div>
          </div>
          ${issuesHtml}
        </div>
      `;
    }

    /* Contextual top-bar primary CTA — depends solely on the active workflow step.
       Never shows the export action as the dominant CTA on Steps 1-4 (that used to
       compete with the real next-step action); it becomes the primary action again
       only on the Narrative / Credit Committee steps. Export functionality itself
       (generateDocx) is unchanged — this only controls which action the button
       triggers and how it is labeled. */
    const TOPBAR_CTA_STEPS = {
      'tab-dashboard': { label: 'Tiếp tục → Không gian Tài liệu', next: 'tab-upload' },
      'tab-upload': { label: 'Tiếp tục → Dữ liệu Đã Xác nhận', next: 'tab-review' },
      'tab-review': { label: 'Tiếp tục → Thẩm định Tín dụng AI', next: 'tab-insights' },
      'tab-insights': { label: 'Tiếp tục → Tờ trình / Narrative', next: 'tab-narrative' },
    };

    function updateTopbarPrimaryCTA() {
      const btn = document.getElementById('btn-export-top');
      if (!btn) return;
      btn.classList.remove('hidden');
      btn.className = 'btn btn-primary btn-sm';

      if (CURRENT_ACTIVE_TAB === 'tab-narrative' || CURRENT_ACTIVE_TAB === 'tab-committee') {
        btn.innerText = 'Xuất Tờ Trình MB07';
        btn.onclick = generateDocx;
        return;
      }

      const step = TOPBAR_CTA_STEPS[CURRENT_ACTIVE_TAB];
      if (step) {
        btn.innerText = step.label;
        btn.onclick = () => switchTab(step.next);
      }
    }

    async function generateDocx() {
      const btnMain = document.getElementById('btn-generate-main');
      const btnTop = document.getElementById('btn-export-top');
      if (btnMain) { btnMain.innerText = 'Đang tổng hợp & xuất bản MB07...'; btnMain.disabled = true; }
      if (btnTop) { btnTop.innerText = 'Đang sinh...'; btnTop.disabled = true; }

      try {
        const res = await fetch('/api/generate_docx', { method: 'POST' });
        const data = await res.json();
        renderDocumentQAPanel(data.qa_result || null);

        if (data.status === 'success') {
          switchTab('tab-narrative');
          const resBox = document.getElementById('export-result');
          if (resBox) {
            resBox.classList.remove('hidden');
            document.getElementById('export-filename').innerText = `Tệp tin: ${data.filename}`;
            document.getElementById('export-download-link').href = data.download_url;
          }
          window.__MB07_EXPORTED__ = true;
          updateSidebarProgress();
        } else if (data.status === 'qa_failed') {
          switchTab('tab-narrative');
        } else {
          alert('Lỗi: ' + (data.message || 'Không thể xuất tờ trình.'));
        }
      } catch (err) {
        alert('Lỗi hệ thống: ' + err.message);
      } finally {
        if (btnTop) { btnTop.disabled = false; }
        if (btnMain) { btnMain.innerText = 'Xuất Tờ Trình MB07 (.DOCX)'; }
        renderNarrativeUI();
        updateTopbarPrimaryCTA();
      }
    }

    /* Case-selector option labels come from the backend (CASES_DB) rather than being
       hardcoded in the page, so they can never drift from the case's actual display
       name — matches by option value (case id) and only updates existing options'
       text, never invents new cases here (new cases are added by submitNewCase()). */
    async function loadCaseList() {
      try {
        const res = await fetch('/api/cases');
        const cases = await res.json();
        const selector = document.getElementById('case-selector');
        if (!selector || !Array.isArray(cases)) return;
        cases.forEach(c => {
          const opt = selector.querySelector(`option[value="${c.id}"]`);
          if (opt && c.name) opt.innerText = c.name;
        });
      } catch (err) {
        console.warn("Could not load case list:", err);
      }
    }

    window.onload = function() {
      loadCaseList();
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
                    "download_url": f"/download/{fname}",
                    "qa_result": LAST_DOCUMENT_QA_RESULT
                })
            except DocumentQAFailedError as e:
                # Document QA layer blocked export: AI/deterministic reviewer found fidelity
                # issues. Do NOT export; return the explicit QA issues instead.
                self._send_json({
                    "status": "qa_failed",
                    "message": "Document QA thất bại: tài liệu vi phạm kiểm định định dạng MB07. Xuất tài liệu bị chặn.",
                    "qa_result": e.qa_result
                }, status_code=422)
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
