# -*- coding: utf-8 -*-
"""Real GreenNode CIC Document Extractor for Vietnamese CIC Reports.

Module: msb_eb_copilot.src.extraction.cic_extraction
Strict Boundary:
- GreenNode populates SOURCE_FACT fields only.
- GreenNode is FORBIDDEN from calculating totals or aggregating facilities.
- Multi-bank records preserved without flattening or losing facility details.
- Strict Pydantic models with ConfigDict(extra="forbid").
- Verbatim evidence-backed provenance (value_raw, semantic_label, evidence, page).
- Tri-state overdue boolean (True, False, None).
- Currency-safe USD handling (VND-equivalent required for total inclusion).
"""

from __future__ import annotations
import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from msb_eb_copilot.src.ai_client import AIAssistantClient


# ==============================================================================
# 1. STAGING DATA MODELS (Strict Pydantic, extra="forbid")
# ==============================================================================

class CICEvidenceField(BaseModel):
    """Evidence-backed extraction for one CIC fact."""
    model_config = ConfigDict(extra="forbid")

    value_raw: Optional[str] = Field(None, description="Raw literal string from document, e.g. '15.000.000.000', 'Nhóm 1'")
    semantic_label: Optional[str] = Field(None, description="Exact field label or header, e.g. 'Dư nợ ngắn hạn VND'")
    evidence: Optional[str] = Field(None, description="Verbatim text snippet containing the fact")
    page: Optional[int] = Field(None, description="Physical 1-indexed page number")


class CICFacilityItem(BaseModel):
    """Individual credit contract or facility item under a bank."""
    model_config = ConfigDict(extra="forbid")

    bank_name: Optional[CICEvidenceField] = None
    facility_code: Optional[CICEvidenceField] = None
    facility_type: Optional[CICEvidenceField] = None
    credit_limit_raw: Optional[CICEvidenceField] = None
    outstanding_vnd_raw: Optional[CICEvidenceField] = None
    outstanding_usd_raw: Optional[CICEvidenceField] = None
    usd_vnd_equiv_raw: Optional[CICEvidenceField] = None
    collateral: Optional[CICEvidenceField] = None
    debt_group: Optional[CICEvidenceField] = None
    page: Optional[int] = None


class CICInstitutionItem(BaseModel):
    """Institution-level summary row for a Financial Institution (TCTD)."""
    model_config = ConfigDict(extra="forbid")

    bank_name: Optional[CICEvidenceField] = None
    short_term_limit_raw: Optional[CICEvidenceField] = None
    short_term_debt_vnd_raw: Optional[CICEvidenceField] = None
    short_term_debt_usd_vnd_equiv_raw: Optional[CICEvidenceField] = None
    raw_usd_amount_raw: Optional[CICEvidenceField] = None
    medium_long_term_debt_raw: Optional[CICEvidenceField] = None
    total_debt_printed: Optional[CICEvidenceField] = None
    collateral_description: Optional[CICEvidenceField] = None
    debt_group: Optional[CICEvidenceField] = None
    facilities: List[CICFacilityItem] = Field(default_factory=list)
    page: Optional[int] = None


class CICDocumentExtraction(BaseModel):
    """Root extraction staging schema for a CIC report."""
    model_config = ConfigDict(extra="forbid")

    customer_name: Optional[CICEvidenceField] = None
    tax_code: Optional[CICEvidenceField] = None
    cic_report_date: Optional[CICEvidenceField] = None
    customer_highest_debt_group: Optional[CICEvidenceField] = None
    history_status: Optional[CICEvidenceField] = None
    is_overdue_12m: Optional[CICEvidenceField] = None
    derivative_transactions_info: Optional[CICEvidenceField] = None
    institutions: List[CICInstitutionItem] = Field(default_factory=list)
    facilities: List[CICFacilityItem] = Field(default_factory=list)


# ==============================================================================
# 2. DETERMINISTIC GROUNDING AUDITOR
# ==============================================================================

@dataclass
class GroundingAuditResult:
    status: str  # "VERIFIED", "WARNING", "REJECTED", "MISSING"
    field_name: str
    message: str = ""
    value_raw: Optional[str] = None
    page: Optional[int] = None
    reason: Optional[str] = None

    def __post_init__(self):
        if self.reason and not self.message:
            self.message = self.reason
        elif self.message and not self.reason:
            self.reason = self.message

    @property
    def extracted_value(self) -> Optional[str]:
        return self.value_raw


class CICGroundingAuditor:
    """Verifies that extracted facts appear verbatim on the physical page text."""

    @classmethod
    def audit_field(
        cls,
        field: Optional[CICEvidenceField],
        field_name: str,
        pages_text: Dict[int, str],
        page_count: int,
    ) -> GroundingAuditResult:
        if field is None or field.value_raw is None or not str(field.value_raw).strip():
            return GroundingAuditResult("MISSING", field_name, "Fact not present in document.")

        if field.page is None:
            return GroundingAuditResult("REJECTED", field_name, "Fact missing page attribution.")

        if field.page < 1 or field.page > page_count:
            return GroundingAuditResult("REJECTED", field_name, f"Page {field.page} out of bounds (1..{page_count}).")

        if not field.evidence or not field.evidence.strip():
            return GroundingAuditResult("REJECTED", field_name, "Fact missing supporting evidence.")

        page_content = pages_text.get(field.page, "")
        norm_page = cls._norm(page_content)
        norm_ev = cls._norm(field.evidence)

        norm_val = cls._norm(str(field.value_raw)).strip()

        # 1. Contiguous exact match of evidence
        if norm_ev in norm_page:
            return GroundingAuditResult("VERIFIED", field_name, "Evidence verified on source page.", field.value_raw, field.page)

        # 2. Whitespace-collapsed & punctuation-insensitive match
        clean_page = re.sub(r"\s+", " ", norm_page)
        clean_ev = re.sub(r"\s+", " ", norm_ev)
        if clean_ev in clean_page:
            return GroundingAuditResult("VERIFIED", field_name, "Evidence verified on source page.", field.value_raw, field.page)

        punc_page = re.sub(r"[^\w\s]", "", clean_page)
        punc_ev = re.sub(r"[^\w\s]", "", clean_ev)
        if punc_ev in punc_page:
            return GroundingAuditResult("VERIFIED", field_name, "Evidence verified on source page.", field.value_raw, field.page)

        # 3. Table-structure / Cell grounding:
        # In tabular CIC sections, header and cell value are separated in linear PDF text stream.
        # Verify that:
        # a) The exact raw value (or its core digits/words) appears on the page.
        # b) Significant words from the evidence snippet also appear on the same page.
        clean_val = re.sub(r"\s+", " ", norm_val)
        punc_val = re.sub(r"[^\w\s]", "", clean_val).strip()

        val_found = (
            clean_val in clean_page
            or (punc_val and punc_val in punc_page)
            or (clean_val in ("false", "true") and any(w in clean_page for w in ("không", "quá hạn", "nợ xấu")))
        )

        if not val_found:
            return GroundingAuditResult(
                "REJECTED",
                field_name,
                f"Value '{field.value_raw}' not found on page {field.page}.",
                field.value_raw,
                field.page,
            )

        # Check significant evidence tokens (excluding colons, numbers, common symbols)
        ev_tokens = [w for w in re.findall(r"\w+", clean_ev) if len(w) > 1 and not w.isdigit()]
        if ev_tokens:
            matched_tokens = sum(1 for tok in ev_tokens if tok in clean_page)
            if matched_tokens / len(ev_tokens) < 0.6:
                return GroundingAuditResult(
                    "REJECTED",
                    field_name,
                    f"Evidence snippet tokens not verified on page {field.page}.",
                    field.value_raw,
                    field.page,
                )

        return GroundingAuditResult("VERIFIED", field_name, "Evidence verified on source page.", field.value_raw, field.page)

    @classmethod
    def audit_all_facts(
        cls,
        extraction: CICDocumentExtraction,
        pages_text: Dict[int, str],
        page_count: int,
    ) -> Dict[str, GroundingAuditResult]:
        """Systematically audits every individual non-null fact extracted across document and institutions.
        
        Principle: NO EVIDENCE -> NO FACT.
        Every non-null SOURCE_FACT has its own GroundingAuditResult.
        Do NOT consider an institution verified just because bank_name is verified.
        """
        results: Dict[str, GroundingAuditResult] = {}

        # 1. Document-level facts
        doc_fields = [
            ("customer.tax_code", extraction.tax_code),
            ("customer.name", extraction.customer_name),
            ("section_e.cic_date", extraction.cic_report_date),
            ("section_e.highest_debt_group", extraction.customer_highest_debt_group),
            ("section_e.history_status", extraction.history_status),
            ("section_e.is_overdue_12m", extraction.is_overdue_12m),
            ("section_e.derivative_transactions_info", extraction.derivative_transactions_info),
        ]
        for cpath, fld in doc_fields:
            if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                results[cpath] = cls.audit_field(fld, cpath, pages_text, page_count)

        # 2. Institution-level facts
        for idx, inst in enumerate(extraction.institutions, start=1):
            prefix = f"section_e.relations[{idx}]"
            inst_fields = [
                (f"{prefix}.bank_name", inst.bank_name),
                (f"{prefix}.short_term_limit", inst.short_term_limit_raw),
                (f"{prefix}.short_term_debt_vnd", inst.short_term_debt_vnd_raw),
                (f"{prefix}.short_term_debt_usd_equiv", inst.short_term_debt_usd_vnd_equiv_raw),
                (f"{prefix}.raw_usd_amount", inst.raw_usd_amount_raw),
                (f"{prefix}.medium_long_term_debt", inst.medium_long_term_debt_raw),
                (f"{prefix}.total_debt_printed", inst.total_debt_printed),
                (f"{prefix}.collateral_description", inst.collateral_description),
                (f"{prefix}.debt_group", inst.debt_group),
            ]
            for fpath, fld in inst_fields:
                if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                    results[fpath] = cls.audit_field(fld, fpath, pages_text, page_count)

            # Audit any nested facilities inside the institution
            for f_idx, fac in enumerate(inst.facilities or [], start=1):
                fac_prefix = f"{prefix}.facilities[{f_idx}]"
                fac_fields = [
                    (f"{fac_prefix}.bank_name", fac.bank_name),
                    (f"{fac_prefix}.credit_limit", fac.credit_limit_raw),
                    (f"{fac_prefix}.outstanding_vnd", fac.outstanding_vnd_raw),
                    (f"{fac_prefix}.collateral", fac.collateral),
                    (f"{fac_prefix}.term", fac.term),
                ]
                for ffpath, fld in fac_fields:
                    if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                        results[ffpath] = cls.audit_field(fld, ffpath, pages_text, page_count)

        # 3. Document-level facilities (if separate)
        for f_idx, fac in enumerate(extraction.facilities or [], start=1):
            fac_prefix = f"facilities[{f_idx}]"
            fac_fields = [
                (f"{fac_prefix}.bank_name", fac.bank_name),
                (f"{fac_prefix}.credit_limit", fac.credit_limit_raw),
                (f"{fac_prefix}.outstanding_vnd", fac.outstanding_vnd_raw),
                (f"{fac_prefix}.collateral", fac.collateral),
                (f"{fac_prefix}.term", fac.term),
            ]
            for ffpath, fld in fac_fields:
                if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                    results[ffpath] = cls.audit_field(fld, ffpath, pages_text, page_count)

        return results

    @staticmethod
    def _norm(txt: str) -> str:
        return unicodedata.normalize("NFC", txt or "").lower()

    @classmethod
    def extract_pages(cls, tagged_text: str) -> Tuple[Dict[int, str], int]:
        pages: Dict[int, str] = {}
        chunks = re.split(r"\[PAGE\s+(\d+)\]", tagged_text, flags=re.IGNORECASE)
        # chunks: [before_page_1, '1', page_1_text, '2', page_2_text, ...]
        if len(chunks) >= 3:
            for i in range(1, len(chunks), 2):
                try:
                    p_num = int(chunks[i])
                    p_txt = chunks[i + 1] if i + 1 < len(chunks) else ""
                    pages[p_num] = p_txt
                except ValueError:
                    continue
        else:
            pages[1] = tagged_text

        max_p = max(pages.keys()) if pages else 1
        return pages, max_p


# ==============================================================================
# 3. DETERMINISTIC NORMALIZER & UNIT RESOLVER
# ==============================================================================

class CICNormalizer:
    """Normalizes monetary values to Triệu VND, parses debt groups and dates."""

    CANONICAL_TARGET_UNIT = "triệu VND"

    @classmethod
    def parse_monetary(
        cls,
        raw_val: Optional[str],
        unit_hint: Optional[str] = None,
    ) -> Tuple[Optional[float], Optional[str]]:
        """Parse raw numeric text and convert deterministically to Triệu VND."""
        if raw_val is None or not str(raw_val).strip():
            return None, None

        cleaned = str(raw_val).strip()
        if cleaned in ("-", "—", "N/A", "null", "None", ""):
            return None, None

        # Check explicit zero
        if cleaned in ("0", "0.0", "0,0", "00"):
            return 0.0, None

        # Determine number format (Vietnamese dots for thousands vs standard commas)
        # Remove currency words if in raw string
        num_str = re.sub(r"(?i)\b(vnd|vnđ|đồng|triệu|nghìn|tỷ|usd)\b", "", cleaned).strip()
        
        # Determine thousand separator:
        if "." in num_str and "," in num_str:
            if num_str.rfind(",") > num_str.rfind("."):
                # e.g. 1.500,50
                num_str = num_str.replace(".", "").replace(",", ".")
            else:
                # e.g. 1,500.50
                num_str = num_str.replace(",", "")
        elif "." in num_str:
            parts = num_str.split(".")
            if all(len(p) == 3 for p in parts[1:]):
                # 15.000.000.000 -> Vietnamese thousand separators
                num_str = "".join(parts)
            elif len(parts) == 2 and len(parts[1]) <= 2:
                # Decimal dot: 15.5
                pass
            else:
                num_str = "".join(parts)
        elif "," in num_str:
            parts = num_str.split(",")
            if all(len(p) == 3 for p in parts[1:]):
                # 15,000,000,000
                num_str = "".join(parts)
            elif len(parts) == 2 and len(parts[1]) <= 2:
                # Decimal comma: 15,5 -> 15.5
                num_str = parts[0] + "." + parts[1]
            else:
                num_str = "".join(parts)

        num_str = re.sub(r"[^\d.-]", "", num_str)
        if not num_str or num_str in ("-", "."):
            return None, f"Invalid numeric content: '{raw_val}'"

        try:
            val = Decimal(num_str)
        except InvalidOperation as e:
            return None, f"Decimal conversion error for '{raw_val}': {e}"

        # Resolve unit scale to Triệu VND
        unit_str = (unit_hint or "").lower().strip()
        if "tỷ" in unit_str or "ty" in unit_str:
            factor = Decimal("1000")
        elif "triệu" in unit_str or "trieu" in unit_str:
            factor = Decimal("1")
        elif "nghìn" in unit_str or "nghin" in unit_str or "ngàn" in unit_str:
            factor = Decimal("0.001")
        elif "vnd" in unit_str or "vnđ" in unit_str or "đồng" in unit_str or not unit_str:
            # Default is VND in Vietnamese banking documents if magnitude > 100,000
            if abs(val) >= Decimal("100000"):
                factor = Decimal("0.000001")
            else:
                # If small number without unit, treat as Triệu VND
                factor = Decimal("1")
        else:
            factor = Decimal("0.000001")

        norm_val = val * factor
        return float(norm_val.quantize(Decimal("0.01"))), None

    @classmethod
    def parse_debt_group(cls, raw_val: Optional[str]) -> Optional[int]:
        """Strictly extracts integer 1..5 for debt group without inference."""
        if not raw_val:
            return None
        m = re.search(r"\b([1-5])\b", str(raw_val))
        if m:
            return int(m.group(1))
        return None

    @classmethod
    def parse_tri_state_overdue(cls, raw_val: Optional[str], evidence: Optional[str] = None) -> Optional[bool]:
        """Parses 12-month overdue status into True, False, or None. Never infers."""
        combined = f"{raw_val or ''} {evidence or ''}".lower()
        if not combined.strip():
            return None

        # Check explicit negative statement
        neg_patterns = [
            "không có nợ quá hạn",
            "không phát sinh nợ quá hạn",
            "không phát sinh quá hạn",
            "không có nợ cần chú ý",
            "không có nợ xấu",
            "chưa phát sinh quá hạn",
            "thanh toán đầy đủ đúng hạn",
        ]
        if any(p in combined for p in neg_patterns):
            return False

        # Check explicit positive overdue
        pos_patterns = [
            "có nợ quá hạn",
            "phát sinh nợ quá hạn",
            "phát sinh quá hạn",
            "nợ quá hạn",
            "nhóm 2 do quá hạn",
            "chậm thanh toán",
        ]
        if any(p in combined for p in pos_patterns):
            return True

        if raw_val and str(raw_val).strip().lower() in ("true", "có", "yes"):
            return True
        if raw_val and str(raw_val).strip().lower() in ("false", "không", "no"):
            return False

        return None


# ==============================================================================
# 4. CUSTOMER IDENTITY RECONCILIATION
# ==============================================================================

class CICIdentityReconciler:
    """Verifies that CIC document belongs to the active case customer.
    
    Hard Rule: Never overwrites case customer fields.
    """

    @classmethod
    def reconcile(
        cls,
        extracted_tax_code: Optional[str],
        extracted_name: Optional[str],
        case_customer: Dict[str, Any],
    ) -> Tuple[str, str]:
        case_tc = case_customer.get("tax_code", "")
        case_name = case_customer.get("name", "")

        norm_ext_tc = re.sub(r"[^0-9]", "", extracted_tax_code or "")
        norm_case_tc = re.sub(r"[^0-9]", "", case_tc or "")

        if not norm_ext_tc:
            return "WARNING", "Báo cáo CIC không có thông tin Mã số thuế rõ ràng để đối soát."

        if norm_case_tc and norm_ext_tc != norm_case_tc:
            return (
                "MISMATCH",
                f"CẢNH BÁO XUNG ĐỘT DANH TÍNH: Mã số thuế trên CIC ({norm_ext_tc}) KHÔNG TRÙNG KHỚP với hồ sơ khách hàng ({norm_case_tc})!",
            )

        norm_ext_n = cls._norm_name(extracted_name or "")
        norm_case_n = cls._norm_name(case_name or "")

        if norm_case_n and norm_ext_n and (norm_ext_n not in norm_case_n and norm_case_n not in norm_ext_n):
            return (
                "WARNING",
                f"Tên doanh nghiệp trên CIC ('{extracted_name}') có sự khác biệt so với hồ sơ ('{case_name}').",
            )

        return "MATCH", "Mã số thuế và tên doanh nghiệp trùng khớp với hồ sơ khách hàng."

    @staticmethod
    def _norm_name(name: str) -> str:
        norm = unicodedata.normalize("NFD", name)
        norm = "".join(c for c in norm if unicodedata.category(c) != "Mn")
        norm = re.sub(r"[^A-Z0-9\s]", " ", norm.upper())
        return " ".join(norm.split())


# ==============================================================================
# 5. GREENNODE CIC DOCUMENT EXTRACTOR
# ==============================================================================

CIC_EXTRACTION_SYSTEM_PROMPT = """Bạn là Chuyên gia AI Giám định Báo cáo Thông tin Tín dụng (CIC) của Ngân hàng TMCP Hàng Hải Việt Nam (MSB).
Nhiệm vụ của bạn là trích xuất CHÍNH XÁC các Sự thật Nguồn (SOURCE_FACT) từ văn bản Báo cáo CIC được cung cấp.

============================================================
QUY TẮC BẮT BUỘC (STRICT EXTRACTION BOUNDARIES)
============================================================
1. NGUYÊN TẮC TUYỆT ĐỐI: NO EVIDENCE -> NULL
   - Chỉ trích xuất thông tin xuất hiện rõ ràng trên văn bản.
   - Nếu một mục không có số liệu hoặc không được đề cập, bắt buộc trả về null.
   - TUYỆT ĐỐI KHÔNG SUY DIỄN:
     * Không suy diễn "không có nợ quá hạn" thành Nhóm 1 nếu văn bản không ghi nhóm nợ.
     * Không suy diễn "Nhóm 1" thành "không có nợ quá hạn trong 12 tháng".
     * Không tự ý cộng dồn hay nhân chia số liệu (Python sẽ tự tính toán).
     * Không quyết định phê duyệt hay nhận xét tốt/xấu về khách hàng.

2. CẤU TRÚC ĐA TỔ CHỨC TÍN DỤNG (MULTI-BANK):
   - Trích xuất danh sách `institutions` theo từng Tổ chức tín dụng (Ngân hàng, Chi nhánh).
   - Giữ nguyên tên TCTD như hiển thị trong tài liệu (ví dụ: "Ngân hàng TMCP Ngoại thương Việt Nam - CN Thăng Long").
   - Nếu có bảng tổng hợp theo từng TCTD: trích xuất vào `institutions`.
   - Nếu có chi tiết từng hợp đồng/khoản vay (`facilities`): trích xuất đầy đủ chi tiết vào danh sách `facilities`.
   - Giữ nguyên số liệu gốc `value_raw`, bằng chứng trích dẫn `evidence`, và số trang vật lý `page`.

3. TIỀN TỆ VÀ USD:
   - Nếu có khoản nợ USD có ghi rõ "quy đổi VND": điền vào `short_term_debt_usd_vnd_equiv_raw`.
   - Nếu chỉ ghi USD đơn thuần (ví dụ "$50,000 USD"): điền vào `raw_usd_amount_raw`. TUYỆT ĐỐI KHÔNG TỰ QUY ĐỔI TỶ GIÁ.

4. NHÓM NỢ VÀ QUÁ HẠN:
   - `debt_group`: Chỉ lấy nhóm nợ gắn liền với TCTD đó (từ 1 đến 5). Không sao chép nhóm nợ chung của toàn bộ khách hàng vào từng ngân hàng.
   - `customer_highest_debt_group`: Trích xuất nhóm nợ cao nhất của toàn khách hàng nếu có ở phần đầu báo cáo.
   - `is_overdue_12m`: Trích xuất rõ "true", "false", hoặc null nếu không đề cập.

5. ĐỊNH DẠNG ĐẦU RA:
   - Trả về DUY NHẤT một khối JSON hợp lệ tuân thủ schema dưới đây.
   - KHÔNG bọc thêm lời giải thích hay markdown thừa ngoài ```json ... ```.

Schema mẫu:
```json
{
  "customer_name": {"value_raw": "CÔNG TY CP...", "semantic_label": "Tên khách hàng", "evidence": "Tên khách hàng: CÔNG TY...", "page": 1},
  "tax_code": {"value_raw": "0109876543", "semantic_label": "Mã số thuế", "evidence": "Mã số thuế: 0109876543", "page": 1},
  "cic_report_date": {"value_raw": "28/02/2026", "semantic_label": "Thời điểm tra cứu", "evidence": "Thời điểm tra cứu: 28/02/2026", "page": 1},
  "customer_highest_debt_group": {"value_raw": "Nhóm 1", "semantic_label": "Nhóm nợ cao nhất", "evidence": "Nhóm nợ cao nhất: Nhóm 1", "page": 1},
  "history_status": {"value_raw": "Trong 24 tháng gần nhất không có nợ xấu", "semantic_label": "Lịch sử tín dụng", "evidence": "Trong 24 tháng gần nhất...", "page": 1},
  "is_overdue_12m": {"value_raw": "false", "semantic_label": "Lịch sử nợ quá hạn 12T", "evidence": "Khách hàng không có nợ quá hạn trong 12 tháng qua", "page": 1},
  "derivative_transactions_info": null,
  "institutions": [
    {
      "bank_name": {"value_raw": "Ngân hàng TMCP Hàng Hải Việt Nam (MSB) - CN Hà Nội", "semantic_label": "Tên TCTD", "evidence": "MSB - CN Hà Nội", "page": 2},
      "short_term_limit_raw": {"value_raw": "10.000.000.000", "semantic_label": "Hạn mức", "evidence": "Hạn mức: 10.000.000.000", "page": 2},
      "short_term_debt_vnd_raw": {"value_raw": "5.200.000.000", "semantic_label": "Dư nợ ngắn hạn VND", "evidence": "Dư nợ VND: 5.200.000.000", "page": 2},
      "short_term_debt_usd_vnd_equiv_raw": null,
      "raw_usd_amount_raw": null,
      "medium_long_term_debt_raw": {"value_raw": "2.000.000.000", "semantic_label": "Dư nợ TDH", "evidence": "Dư nợ TDH: 2.000.000.000", "page": 2},
      "total_debt_printed": {"value_raw": "7.200.000.000", "semantic_label": "Tổng dư nợ", "evidence": "Tổng dư nợ: 7.200.000.000", "page": 2},
      "collateral_description": {"value_raw": "HĐTG và Hàng tồn kho", "semantic_label": "TSBĐ", "evidence": "TSBĐ: HĐTG và Hàng tồn kho", "page": 2},
      "debt_group": {"value_raw": "1", "semantic_label": "Nhóm nợ", "evidence": "Nhóm 1", "page": 2},
      "facilities": [],
      "page": 2
    }
  ],
  "facilities": []
}
```
"""


class CICDocumentExtractor:
    """Orchestrates GreenNode CIC document extraction with grounding verification."""

    def __init__(self, ai_client: Optional[Any] = None):
        self.ai_client = ai_client

    def extract(self, tagged_text: str, page_count: int, api_key: Optional[str] = None) -> CICDocumentExtraction:
        user_prompt = f"""Hãy đọc kỹ toàn bộ văn bản Báo cáo Thông tin Tín dụng (CIC) dưới đây (đã phân chia theo thẻ [PAGE X]):

{tagged_text}

Trích xuất toàn bộ các sự thật nguồn tín dụng, hạn mức, dư nợ và quan hệ TCTD theo đúng hướng dẫn hệ thống. Bắt buộc trả về JSON hợp lệ."""

        if self.ai_client and hasattr(self.ai_client, "chat"):
            resp_text = self.ai_client.chat(
                system_prompt=CIC_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=4096,
                api_key=api_key,
                operation="cic_extraction",
            )
        else:
            resp_text = AIAssistantClient.chat(
                system_prompt=CIC_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=4096,
                api_key=api_key,
                operation="cic_extraction",
            )

        cleaned_json = resp_text.strip()
        if cleaned_json.startswith("```"):
            cleaned_json = re.sub(r"^```(?:json)?\s*", "", cleaned_json)
            cleaned_json = re.sub(r"\s*```$", "", cleaned_json)

        try:
            raw_dict = json.loads(cleaned_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"GreenNode returned invalid JSON for CIC extraction: {e}\nRaw: {resp_text[:300]}")

        return CICDocumentExtraction.model_validate(raw_dict)
