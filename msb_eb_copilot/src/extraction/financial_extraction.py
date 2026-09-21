# -*- coding: utf-8 -*-
"""Real GreenNode Financial Document Extractor for Vietnamese BCTC.

Module: msb_eb_copilot.src.extraction.financial_extraction
Strict Boundary:
- GreenNode populates SOURCE_FACT fields only.
- GreenNode is FORBIDDEN from calculating ratios, MB09, or RORWA metrics.
- Two-stage numeric parsing: Lexical parsing + Accounting semantic interpretation.
- Per-fact grounded unit resolution with explicit evidence.
- Corroboration: Semantic label + Statement context + optional Accounting Code.
"""

from __future__ import annotations
import os
import json
import re
import unicodedata
import threading
import concurrent.futures
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field, model_validator

from msb_eb_copilot.src.ai_client import AIAssistantClient
from msb_eb_copilot.src.ingestion.pdf_ocr import OCR_UNREADABLE_PAGE_MARKER


# ==============================================================================
# 1. STAGING DATA MODELS (Separate from Canonical case_data)
# ==============================================================================

class FinancialEvidenceField(BaseModel):
    """Evidence-backed extraction for one financial line item."""
    value_raw: Optional[str] = Field(None, description="Raw numeric string from document, e.g. '120.000.000.000'")
    semantic_label: Optional[str] = Field(None, description="Exact line item text, e.g. 'Doanh thu thuần'")
    accounting_code: Optional[str] = Field(None, description="Optional accounting indicator code, e.g. '10'")
    unit_raw: Optional[str] = Field(None, description="Unit indicated for this field/table, e.g. 'VND'")
    unit_evidence: Optional[str] = Field(None, description="Exact text snippet proving unit, e.g. 'Đơn vị tính: VND'")
    evidence: Optional[str] = Field(None, description="Verbatim text snippet containing the line item and value")
    page: Optional[int] = Field(None, description="Physical 1-indexed page number")


class FinancialUnitInfo(BaseModel):
    """Grounded unit information at page or document level.

    Kept STRICT on purpose: unit_raw/evidence/page are all mandatory. A
    FinancialUnitInfo instance is either fully grounded provenance, or it simply
    does not exist (see _normalize_unit_dict_or_raise / FinancialDocumentExtraction's
    model_validator(mode="before"), which normalizes raw LLM output BEFORE this
    model's own strict validation runs, so a half-populated record from the LLM
    never reaches this class at all -- it is either dropped as absence or
    rejected as an explicit provenance error upstream)."""
    unit_raw: str = Field(..., description="Raw unit text, e.g. 'VND', 'triệu đồng'")
    evidence: str = Field(..., description="Verbatim snippet where unit appears")
    page: int = Field(..., description="Page number where unit evidence was found")


def _is_blank_unit_value(value: Any) -> bool:
    """None or a whitespace-only string is treated as blank/absent. Any other
    value (including a populated string, or a non-string like an int page
    number) is NOT blank."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _normalize_unit_dict_or_raise(raw_unit: Any, *, context: str) -> Any:
    """Normalizes ONE raw unit-info record (a page_units entry or document_unit)
    BEFORE FinancialUnitInfo's own strict validation runs.

    Policy (Zero Silent Fallback -- never fabricate, never silently accept a
    half-populated record):
    - None -> None (already absent, nothing to do).
    - Already a validated FinancialUnitInfo instance (e.g. from
      merge_financial_extractions, which builds these programmatically, not from
      raw LLM JSON) -> returned unchanged; it can never be "partial" since
      Pydantic already enforced its required fields when it was built.
    - Not a dict (and not None/a FinancialUnitInfo) -> returned unchanged; this is
      a malformed shape unrelated to null-handling, so Pydantic's own field type
      validation reports it naturally.
    - unit_raw AND evidence both blank (None or whitespace-only) -> effectively
      empty/no evidence at all -> None (dropped), REGARDLESS of whether `page`
      happens to be populated -- `page` alone carries no unit provenance, and
      this is exactly the confirmed production shape (e.g. {"unit_raw": null,
      "evidence": null, "page": 21}).
    - unit_raw non-blank AND evidence non-blank AND page non-blank -> fully
      present -> returned unchanged (no fabrication, no mutation).
    - Any other combination (exactly one of unit_raw/evidence present, or both
      present but page missing) -> partially populated -> raise ValueError
      (surfaces as a pydantic ValidationError from the caller's
      model_validator, and from there as the existing FinancialChunkExtractionError
      at the GreenNode chunk-extraction call site) -- provenance is incomplete
      and must fail loudly, never be silently accepted.
    """
    if raw_unit is None:
        return None
    if isinstance(raw_unit, FinancialUnitInfo):
        return raw_unit
    if not isinstance(raw_unit, dict):
        return raw_unit

    unit_raw = raw_unit.get("unit_raw")
    evidence = raw_unit.get("evidence")
    page = raw_unit.get("page")

    unit_raw_blank = _is_blank_unit_value(unit_raw)
    evidence_blank = _is_blank_unit_value(evidence)

    if unit_raw_blank and evidence_blank:
        return None

    page_blank = _is_blank_unit_value(page)
    if (not unit_raw_blank) and (not evidence_blank) and (not page_blank):
        return raw_unit

    raise ValueError(
        f"{context}: bản ghi đơn vị tính (unit) chỉ có dữ liệu bằng chứng một phần "
        f"(unit_raw={unit_raw!r}, evidence={evidence!r}, page={page!r}). Một bản ghi "
        f"unit phải đầy đủ cả 3 trường (unit_raw, evidence, page) hoặc hoàn toàn "
        f"vắng mặt -- không được chấp nhận trạng thái nửa vời."
    )


class FinancialPeriodExtraction(BaseModel):
    """Raw financial statement extraction for one explicit period."""
    period: str = Field(..., description="Explicit year label, e.g. '2025', '2024'")
    
    # P&L Raw Items (Mẫu B02-DN)
    net_revenue: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    cogs: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    gross_profit: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    financial_income: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    financial_expenses: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    interest_expenses: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    sga_expenses: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    net_profit_before_tax: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    net_profit_after_tax: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    
    # Balance Sheet Raw Items (Mẫu B01-DN)
    current_assets: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    cash: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    receivables: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    inventories: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    total_assets: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    total_liabilities: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    current_liabilities: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    short_term_debt: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)
    equity: FinancialEvidenceField = Field(default_factory=FinancialEvidenceField)


class FinancialDocumentExtraction(BaseModel):
    """Complete verified staging model for an extracted financial document."""
    document_title: Optional[str] = Field(None, description="Extracted document title / header")
    periods: List[FinancialPeriodExtraction] = Field(default_factory=list)
    page_units: Dict[int, FinancialUnitInfo] = Field(default_factory=dict, description="Grounded units per page")
    document_unit: Optional[FinancialUnitInfo] = Field(None, description="Document-wide fallback unit")

    @model_validator(mode="before")
    @classmethod
    def _normalize_units_before_validation(cls, data: Any) -> Any:
        """Deterministic pre-validation normalization for page_units/document_unit
        (see _normalize_unit_dict_or_raise for the exact policy). Runs on EVERY
        construction path (model_validate() from raw LLM JSON, direct keyword
        construction from merge_financial_extractions, the default empty
        constructor, ...) since it lives on the model itself rather than only in
        the GreenNode chunk pre-processing step -- so the invariant "a unit record
        is either fully present or fully absent" holds everywhere, not just for
        one call site. Never fabricates a unit from another page/level; only
        drops effectively-empty records or raises on partial ones."""
        if not isinstance(data, dict):
            return data

        data = dict(data)  # never mutate the caller's original dict in place

        if "document_unit" in data:
            data["document_unit"] = _normalize_unit_dict_or_raise(
                data["document_unit"], context="document_unit"
            )

        page_units = data.get("page_units")
        if isinstance(page_units, dict):
            normalized_page_units: Dict[Any, Any] = {}
            for page_key, unit_val in page_units.items():
                normalized = _normalize_unit_dict_or_raise(unit_val, context=f"page_units[{page_key}]")
                if normalized is not None:
                    normalized_page_units[page_key] = normalized
                # else: effectively empty -- entry dropped entirely, not fabricated, not kept.
            data["page_units"] = normalized_page_units

        return data


# ==============================================================================
# 2. TWO-STAGE NUMERIC PARSER & ACCOUNTING INTERPRETER
# ==============================================================================

@dataclass(frozen=True)
class LexicalFinancialToken:
    """Stage A: Pure lexical decomposition of financial number token."""
    raw_token: str
    cleaned_digits: str
    is_negative: bool
    is_parentheses: bool
    is_dash: bool
    is_zero: bool
    is_empty: bool


class LexicalFinancialNumberParser:
    """Deterministic lexical parser for Vietnamese financial numbers."""

    @staticmethod
    def parse_token(raw_text: Any) -> Tuple[Optional[LexicalFinancialToken], Optional[str]]:
        if raw_text is None:
            return LexicalFinancialToken("", "", False, False, False, False, True), None

        s = unicodedata.normalize("NFC", str(raw_text)).strip()
        if not s or s == "":
            return LexicalFinancialToken("", "", False, False, False, False, True), None

        # Detect accounting dash / hyphen
        if s in ("-", "–", "—", "- -", "---"):
            return LexicalFinancialToken(s, "", False, False, True, False, False), None

        # Check for parentheses indicating negative: e.g. (1.250.000)
        is_parentheses = False
        m_paren = re.match(r"^\s*\(\s*(.*?)\s*\)\s*$", s)
        if m_paren:
            is_parentheses = True
            inner = m_paren.group(1).strip()
        else:
            inner = s

        # Check for leading minus sign
        is_negative = False
        if inner.startswith("-") or inner.startswith("–") or inner.startswith("—"):
            is_negative = True
            inner = inner[1:].strip()

        # Remove thousand separators:
        # In Vietnamese accounting: dot is thousand separator (120.000.000), comma is decimal.
        # If space separated: 120 000 000
        # If English style: 120,000,000
        cleaned = re.sub(r"[\s]", "", inner)
        
        # Detect if dot is thousand or decimal
        # Standard Vietnamese: "120.000.000" or "120.000.000,50"
        if "." in cleaned and "," in cleaned:
            # European/Vietnamese convention: 1.250,50
            dot_idx = cleaned.rfind(".")
            comma_idx = cleaned.rfind(",")
            if dot_idx < comma_idx:
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                # US convention: 1,250.50
                cleaned = cleaned.replace(",", "")
        elif "." in cleaned:
            parts = cleaned.split(".")
            # If parts after dot are 3 digits, it's thousand separator: 120.000.000
            if all(len(p) == 3 for p in parts[1:]):
                cleaned = cleaned.replace(".", "")
            elif len(parts) == 2 and len(parts[1]) != 3:
                # Decimal point: e.g. 120.5
                pass
            else:
                cleaned = cleaned.replace(".", "")
        elif "," in cleaned:
            parts = cleaned.split(",")
            if all(len(p) == 3 for p in parts[1:]):
                cleaned = cleaned.replace(",", "")
            elif len(parts) == 2:
                # Comma decimal: 120,5 -> 120.5
                cleaned = cleaned.replace(",", ".")

        # Check if digits exist
        if not re.search(r"\d", cleaned):
            return None, f"No numeric digits in token: '{raw_text}'"

        # Check for invalid characters
        if re.search(r"[^\d.]", cleaned):
            return None, f"Invalid characters in numeric token: '{raw_text}'"

        is_zero = (cleaned == "0" or cleaned == "0.0" or set(cleaned) == {"0", "."})

        return LexicalFinancialToken(
            raw_token=s,
            cleaned_digits=cleaned,
            is_negative=is_negative or is_parentheses,
            is_parentheses=is_parentheses,
            is_dash=False,
            is_zero=is_zero,
            is_empty=False,
        ), None


class AccountingSemanticInterpreter:
    """Stage B: Accounting semantic interpretation of lexical token."""

    @staticmethod
    def interpret(token: LexicalFinancialToken) -> Tuple[Optional[Decimal], Optional[str]]:
        if token.is_empty:
            return None, None

        if token.is_dash:
            # Accounting convention: dash signifies missing or zero depending on account.
            # In strict grounding: treat as missing (None) to avoid fabricating facts.
            return None, None

        if token.is_zero:
            return Decimal("0"), None

        try:
            val = Decimal(token.cleaned_digits)
            if token.is_negative:
                val = -val
            return val, None
        except InvalidOperation as e:
            return None, f"Decimal conversion failure for '{token.raw_token}': {e}"


# ==============================================================================
# 3. PER-FACT GROUNDED UNIT RESOLVER
# ==============================================================================

class FinancialUnitResolver:
    """Resolves grounded unit per financial fact and normalizes to triệu VND."""

    CANONICAL_TARGET_UNIT = "triệu VND"

    @classmethod
    def resolve_and_normalize(
        cls,
        amount: Decimal,
        field_unit: Optional[str],
        page_unit: Optional[FinancialUnitInfo],
        doc_unit: Optional[FinancialUnitInfo],
    ) -> Tuple[Optional[Decimal], Optional[str], Optional[str], Optional[str]]:
        """Resolve unit via hierarchy: field unit -> page unit -> doc unit.
        
        Returns:
            (normalized_amount_million_vnd, resolved_unit, unit_evidence, error_reason)
        """
        resolved_unit = None
        unit_evidence = None

        if field_unit and field_unit.strip():
            resolved_unit = field_unit.strip()
            unit_evidence = f"Field unit: {field_unit}"
        elif page_unit is not None:
            resolved_unit = page_unit.unit_raw
            unit_evidence = page_unit.evidence
        elif doc_unit is not None:
            resolved_unit = doc_unit.unit_raw
            unit_evidence = doc_unit.evidence

        if not resolved_unit:
            return None, None, None, "No grounded currency unit found for this fact or its page/document."

        norm_u = unicodedata.normalize("NFC", resolved_unit).strip().lower()

        # Deterministic multipliers to triệu VND:
        # VND / đồng -> / 1,000,000
        # nghìn đồng / 1.000 VND -> / 1,000
        # triệu đồng / triệu VND -> 1.0
        # tỷ đồng / tỷ VND -> * 1,000
        if re.search(r"\btỷ\b|\bty\b", norm_u):
            factor = Decimal("1000")
        elif re.search(r"\btriệu\b|\btrieu\b", norm_u):
            factor = Decimal("1")
        elif re.search(r"\bnghìn\b|\bnghin\b|\bngàn\b|\b1\.000\b", norm_u):
            factor = Decimal("0.001")
        elif re.search(r"\bvnd\b|\bvnđ\b|\bđồng\b|\bdong\b|\bđ\b", norm_u):
            factor = Decimal("0.000001")
        else:
            return None, resolved_unit, unit_evidence, f"Unrecognized currency unit '{resolved_unit}'."

        norm_val = amount * factor
        # Round to 2 decimal places in triệu VND
        rounded_val = norm_val.quantize(Decimal("0.01"))
        return rounded_val, resolved_unit, unit_evidence, None


# ==============================================================================
# 4. ACCOUNTING CORROBORATION & GROUNDING AUDITOR
# ==============================================================================

# Standard TT 200 Accounting Code & Semantic Corroboration Dictionary
ACCOUNTING_CORROBORATION_RULES: Dict[str, Dict[str, Any]] = {
    "net_revenue": {
        "expected_code": "10",
        "keywords": ["doanh thu thuần", "doanh thu thuần về bán hàng", "net revenue"],
    },
    "cogs": {
        "expected_code": "11",
        "keywords": ["giá vốn hàng bán", "giá vốn hàng bán và dịch vụ cung cấp", "giá vốn bán hàng", "cost of goods sold"],
    },
    "gross_profit": {
        "expected_code": "20",
        "keywords": ["lợi nhuận gộp", "lợi nhuận gộp về bán hàng", "gross profit"],
    },
    "financial_income": {
        "expected_code": "21",
        "keywords": ["doanh thu hoạt động tài chính", "doanh thu tài chính", "financial income"],
    },
    "financial_expenses": {
        "expected_code": "22",
        "keywords": ["chi phí tài chính", "financial expenses"],
    },
    "interest_expenses": {
        "expected_code": "23",
        "keywords": ["chi phí lãi vay", "trong đó: chi phí lãi vay", "interest expenses"],
    },
    "sga_expenses": {
        "expected_code": ["25", "26"],
        "keywords": ["chi phí bán hàng", "chi phí quản lý doanh nghiệp", "chi phí qldn", "chi phí bán hàng và qldn", "sga"],
    },
    "net_profit_before_tax": {
        "expected_code": "50",
        "keywords": ["lợi nhuận kế toán trước thuế", "lợi nhuận trước thuế", "profit before tax"],
    },
    "net_profit_after_tax": {
        "expected_code": "60",
        "keywords": ["lợi nhuận sau thuế", "lợi nhuận sau thuế tndn", "net profit after tax"],
    },
    "current_assets": {
        "expected_code": "100",
        "keywords": ["tài sản ngắn hạn", "current assets"],
    },
    "cash": {
        "expected_code": "110",
        "keywords": ["tiền và các khoản tương đương tiền", "tiền và tương đương tiền", "tiền mặt", "cash"],
    },
    "receivables": {
        "expected_code": "130",
        "keywords": ["các khoản phải thu ngắn hạn", "phải thu ngắn hạn", "accounts receivable"],
    },
    "inventories": {
        "expected_code": "140",
        "keywords": ["hàng tồn kho", "inventories"],
    },
    "total_assets": {
        "expected_code": "270",
        "keywords": ["tổng cộng tài sản", "tổng tài sản", "total assets"],
    },
    "total_liabilities": {
        "expected_code": "300",
        "keywords": ["nợ phải trả", "c. nợ phải trả", "total liabilities"],
    },
    "current_liabilities": {
        "expected_code": "310",
        "keywords": ["nợ ngắn hạn", "i. nợ ngắn hạn", "current liabilities"],
    },
    "short_term_debt": {
        "expected_code": "320",
        "keywords": ["vay và nợ thuê tài chính ngắn hạn", "vay ngắn hạn", "short-term debt"],
    },
    "equity": {
        "expected_code": ["400", "410"],
        "keywords": ["vốn chủ sở hữu", "equity", "owner's equity"],
    },
}


class FinancialGroundingAuditor:
    """Verifies that extracted financial facts are genuinely grounded in document text."""

    @staticmethod
    def audit_field(
        canonical_name: str,
        field_data: FinancialEvidenceField,
        page_tagged_text: str,
        page_count: int,
    ) -> List[str]:
        """Audit field against tagged text. Returns list of warning/error reasons."""
        errors: List[str] = []

        if field_data.value_raw is None:
            return errors

        # A. Declared page check
        if field_data.page is None:
            errors.append(f"{canonical_name}: Missing declared page number.")
            return errors
        if field_data.page < 1 or field_data.page > page_count:
            errors.append(f"{canonical_name}: Declared page {field_data.page} exceeds physical pages (1-{page_count}).")
            return errors

        # B. Evidence presence on declared page
        if not field_data.evidence or not field_data.evidence.strip():
            errors.append(f"{canonical_name}: Missing verbatim textual evidence.")
            return errors

        # Extract target page content from tagged text
        page_marker = f"[PAGE {field_data.page}]"
        next_marker = f"[PAGE {field_data.page + 1}]"
        if page_marker not in page_tagged_text:
            errors.append(f"{canonical_name}: Page marker {page_marker} not found in tagged text.")
            return errors

        start_idx = page_tagged_text.find(page_marker) + len(page_marker)
        end_idx = page_tagged_text.find(next_marker) if next_marker in page_tagged_text else len(page_tagged_text)
        page_text = page_tagged_text[start_idx:end_idx]

        norm_page = " ".join(unicodedata.normalize("NFC", page_text).lower().split())
        norm_ev = " ".join(unicodedata.normalize("NFC", field_data.evidence).lower().split())

        if norm_ev not in norm_page:
            errors.append(f"{canonical_name}: Evidence not found on declared Page {field_data.page}.")

        # C. Raw value appears inside evidence
        raw_val_clean = str(field_data.value_raw).replace("(", "").replace(")", "").strip()
        if raw_val_clean not in field_data.evidence:
            errors.append(f"{canonical_name}: Raw numeric value '{field_data.value_raw}' not in evidence text.")

        # D. Accounting code & semantic corroboration
        rule = ACCOUNTING_CORROBORATION_RULES.get(canonical_name)
        if rule:
            # Semantic label check
            if field_data.semantic_label:
                norm_label = unicodedata.normalize("NFC", field_data.semantic_label).lower()
                matches_keyword = any(kw in norm_label for kw in rule["keywords"])
                if not matches_keyword:
                    errors.append(
                        f"{canonical_name}: Semantic label '{field_data.semantic_label}' does not corroborate with expected concepts {rule['keywords'][:2]}."
                    )

            # Code corroboration
            if field_data.accounting_code:
                code_str = str(field_data.accounting_code).strip()
                expected_codes = rule["expected_code"] if isinstance(rule["expected_code"], list) else [rule["expected_code"]]
                if code_str not in expected_codes:
                    errors.append(
                        f"{canonical_name}: Accounting code '{code_str}' conflicts with expected code(s) {expected_codes}."
                    )

        return errors


# ==============================================================================
# 5. REAL GREENNODE FINANCIAL EXTRACTOR
# ==============================================================================

FINANCIAL_EXTRACTION_SYSTEM_PROMPT = """Bạn là Chuyên viên Trích xuất Báo cáo Tài chính (Financial Document Extractor) cho hệ thống Thẩm định Tín dụng MSB.
Nhiệm vụ: Trích xuất các sự thật tài chính THÔ (RAW SOURCE FACTS) từ Báo cáo tài chính (BCTC) đính kèm.

QUY TẮC CỐT LÕI (BẮT BUỘC TUÂN THỦ 100%):
1. NO EVIDENCE -> NO FACT: Chỉ trích xuất số liệu xuất hiện tường minh trên tài liệu kèm trích dẫn văn bản (evidence) và số trang (page). Không có chứng cứ -> để null.
2. CHỈ TRÍCH XUẤT SỰ THẬT NGUỒN TỪ BÁO CÁO CHÍNH THỨC:
   - Báo cáo Kết quả kinh doanh (P&L): net_revenue, cogs, gross_profit, financial_income, financial_expenses, interest_expenses, sga_expenses, net_profit_before_tax, net_profit_after_tax.
   - Bảng Cân đối kế toán (Balance Sheet): current_assets, cash, receivables, inventories, total_assets, total_liabilities, current_liabilities, short_term_debt, equity.
3. PHÂN BIỆT RÕ CHỈ TIÊU BÁO CÁO CHÍNH THỨC (STATEMENTS) VS THÀNH PHẦN THUYẾT MINH (NOTES):
   - Các trường trong schema đại diện cho CHỈ TIÊU TỔNG HỢP CHÍNH THỨC trên Báo cáo Kết quả Hoạt động Kinh doanh (Mẫu B02-DN) và Bảng Cân đối Kế toán (Mẫu B01-DN).
   - TUYỆT ĐỐI KHÔNG trích xuất các dòng thành phần, tiểu mục trong phần Thuyết minh (Notes) vào các trường chỉ tiêu chính thức:
     * cogs: Phải là chỉ tiêu chính thức "Giá vốn hàng bán" hoặc "Giá vốn hàng bán và dịch vụ cung cấp" (Mã số 11 trên P&L B02-DN). TUYỆT ĐỐI KHÔNG lấy dòng "Giá vốn hàng hóa" trong Thuyết minh "Chi phí sản xuất, kinh doanh theo yếu tố". Nếu phân đoạn chỉ có Thuyết minh chi phí theo yếu tố mà không có Báo cáo KQKD, BẮT BUỘC để cogs: null.
     * sga_expenses: Chỉ lấy dòng tổng "Chi phí bán hàng" (Mã 25) và "Chi phí quản lý doanh nghiệp" (Mã 26) trên P&L. KHÔNG lấy các thành phần chi tiết trong thuyết minh (nhân công, khấu hao, tiếp khách...).
     * short_term_debt: Chỉ lấy chỉ tiêu "Vay và nợ thuê tài chính ngắn hạn" (Mã 320) trên Bảng cân đối. KHÔNG lấy các khoản vay từng ngân hàng riêng lẻ trong thuyết minh.
     * cash: Chỉ lấy chỉ tiêu "Tiền và các khoản tương đương tiền" (Mã 110). KHÔNG lấy tiểu mục "Tiền mặt tại quỹ" hay chi tiết từng tài khoản trong thuyết minh.
     * receivables: Chỉ lấy chỉ tiêu "Các khoản phải thu ngắn hạn" (Mã 130). KHÔNG lấy chi tiết phải thu từng khách hàng riêng lẻ trong thuyết minh.
   - Nếu phân đoạn trang (chunk) CHỈ chứa Thuyết minh chi tiết mà không có bảng báo cáo tổng hợp chính thức, BẮT BUỘC để các trường đó là null.
4. TUYỆT ĐỐI CẤM TÍNH TOÁN HAY SUY ĐOÁN:
   - KHÔNG tính các chỉ số an toàn tài chính (current_ratio, quick_ratio, debt_to_equity, DSCR, ROS, ROE,...).
   - KHÔNG tính toán chu kỳ kinh doanh (CCC, MB09) hay lợi nhuận điều chỉnh rủi ro (RORWA).
   - Python sẽ tự động tính toán 100% các chỉ số này.
5. XÁC ĐỊNH ĐƠN VỊ TÍNH (UNIT) GẮN LIỀN VỚI TỪNG TRANG:
   - Tìm câu văn ghi đơn vị tính (ví dụ: 'Đơn vị tính: VND', 'Đơn vị tính: triệu đồng').
   - Ghi nhận unit_raw và unit_evidence.
   - QUY TẮC BẮT BUỘC VỀ TÍNH TOÀN VẸN CỦA BẢN GHI UNIT (page_units/document_unit):
     * Nếu một trang KHÔNG có câu văn ghi đơn vị tính tường minh (không có bằng chứng unit),
       BẮT BUỘC bỏ qua (OMIT) hẳn trang đó khỏi "page_units" -- KHÔNG được thêm entry với
       "unit_raw": null, "evidence": null cho trang đó.
     * TUYỆT ĐỐI KHÔNG xuất ra dạng {"unit_raw": null, "evidence": null, "page": <số trang>}
       trong "page_units" hay "document_unit".
     * Nếu KHÔNG tìm thấy đơn vị tính cấp tài liệu (document-level), trả về
       "document_unit": null (không tạo object nửa vời).
     * Nếu trả về một object unit (cho "document_unit" hoặc bất kỳ entry nào trong
       "page_units"), object đó BẮT BUỘC phải có đủ CẢ BA trường unit_raw, evidence,
       và page đều khác null -- không được để một phần null.
6. PHÂN TÁCH RÕ RÀNG TỪNG NĂM / KỲ KẾ TOÁN (PERIOD):
   - Xác định rõ cột số liệu thuộc năm nào (ví dụ: '2025', '2024'). Không được tráo đổi thứ tự cột.
7. TRANG OCR KHÔNG ĐỌC ĐƯỢC (ĐÁNH DẤU {OCR_UNREADABLE_MARKER}):
   - Một số trang có thể được đánh dấu nội dung đúng bằng chuỗi tất định
     "{OCR_UNREADABLE_MARKER}" thay vì văn bản thật -- điều này có nghĩa là hệ thống OCR
     KHÔNG đọc được trang đó sau khi đã thử lại nhiều lần (không phải trang trắng, không
     phải lỗi của bạn).
   - Một trang có đánh dấu "{OCR_UNREADABLE_MARKER}" HOÀN TOÀN KHÔNG chứa bằng chứng
     (evidence) sử dụng được. TUYỆT ĐỐI KHÔNG được:
     * Suy đoán, ước lượng, hay "điền vào chỗ trống" bất kỳ số liệu nào cho trang đó.
     * Sao chép/kế thừa đơn vị tính (unit) hoặc evidence từ trang khác sang cho trang đó.
     * Giả định trang đó là trang trắng hoặc không quan trọng.
     * Trích dẫn số trang đó (page) làm bằng chứng cho bất kỳ chỉ tiêu hay unit nào.
   - Quy tắc "NO EVIDENCE -> NO FACT" ở mục 1 áp dụng NGHIÊM NGẶT cho các trang này.
8. ĐỊNH DẠNG ĐẦU RA:
   - BẮT BUỘC trả về định dạng JSON thuần túy (strict JSON), KHÔNG dùng Markdown fence (không viết ```json), KHÔNG có lời giải thích bên ngoài.

CẤU TRÚC JSON MẪU:
{
  "document_title": "Báo cáo tài chính năm 2025",
  "document_unit": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1},
  "page_units": {
    "1": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1},
    "2": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 2}
  },
  "periods": [
    {
      "period": "2025",
      "net_revenue": {"value_raw": "120.000.000.000", "semantic_label": "Doanh thu thuần về bán hàng và cung cấp dịch vụ", "accounting_code": "10", "evidence": "Doanh thu thuần về bán hàng và cung cấp dịch vụ | 10 | 120.000.000.000", "page": 1},
      "cogs": {"value_raw": "96.000.000.000", "semantic_label": "Giá vốn hàng bán", "accounting_code": "11", "evidence": "Giá vốn hàng bán | 11 | 96.000.000.000", "page": 1},
      "gross_profit": {"value_raw": "24.000.000.000", "semantic_label": "Lợi nhuận gộp", "accounting_code": "20", "evidence": "Lợi nhuận gộp | 20 | 24.000.000.000", "page": 1},
      "financial_income": {"value_raw": "2.500.000.000", "semantic_label": "Doanh thu hoạt động tài chính", "accounting_code": "21", "evidence": "Doanh thu hoạt động tài chính | 21 | 2.500.000.000", "page": 1},
      "financial_expenses": {"value_raw": "3.200.000.000", "semantic_label": "Chi phí tài chính", "accounting_code": "22", "evidence": "Chi phí tài chính | 22 | 3.200.000.000", "page": 1},
      "interest_expenses": {"value_raw": "2.800.000.000", "semantic_label": "Chi phí lãi vay", "accounting_code": "23", "evidence": "Chi phí lãi vay | 23 | 2.800.000.000", "page": 1},
      "sga_expenses": {"value_raw": "10.500.000.000", "semantic_label": "Chi phí bán hàng và chi phí quản lý", "accounting_code": "25", "evidence": "Chi phí bán hàng | 25 | 6.000.000.000 và Quản lý | 26 | 4.500.000.000", "page": 1},
      "net_profit_before_tax": {"value_raw": "12.800.000.000", "semantic_label": "Tổng lợi nhuận kế toán trước thuế", "accounting_code": "50", "evidence": "Tổng lợi nhuận kế toán trước thuế | 50 | 12.800.000.000", "page": 1},
      "net_profit_after_tax": {"value_raw": "10.240.000.000", "semantic_label": "Lợi nhuận sau thuế thu nhập doanh nghiệp", "accounting_code": "60", "evidence": "Lợi nhuận sau thuế | 60 | 10.240.000.000", "page": 1},
      "current_assets": {"value_raw": "65.000.000.000", "semantic_label": "TÀI SẢN NGẮN HẠN", "accounting_code": "100", "evidence": "A. TÀI SẢN NGẮN HẠN | 100 | 65.000.000.000", "page": 2},
      "cash": {"value_raw": "8.500.000.000", "semantic_label": "Tiền và các khoản tương đương tiền", "accounting_code": "110", "evidence": "Tiền và các khoản tương đương tiền | 110 | 8.500.000.000", "page": 2},
      "receivables": {"value_raw": "26.500.000.000", "semantic_label": "Các khoản phải thu ngắn hạn", "accounting_code": "130", "evidence": "Các khoản phải thu ngắn hạn | 130 | 26.500.000.000", "page": 2},
      "inventories": {"value_raw": "28.000.000.000", "semantic_label": "Hàng tồn kho", "accounting_code": "140", "evidence": "Hàng tồn kho | 140 | 28.000.000.000", "page": 2},
      "total_assets": {"value_raw": "90.000.000.000", "semantic_label": "TỔNG CỘNG TÀI SẢN", "accounting_code": "270", "evidence": "TỔNG CỘNG TÀI SẢN | 270 | 90.000.000.000", "page": 2},
      "total_liabilities": {"value_raw": "45.000.000.000", "semantic_label": "NỢ PHẢI TRẢ", "accounting_code": "300", "evidence": "C. NỢ PHẢI TRẢ | 300 | 45.000.000.000", "page": 2},
      "current_liabilities": {"value_raw": "35.000.000.000", "semantic_label": "Nợ ngắn hạn", "accounting_code": "310", "evidence": "I. Nợ ngắn hạn | 310 | 35.000.000.000", "page": 2},
      "short_term_debt": {"value_raw": "20.000.000.000", "semantic_label": "Vay và nợ thuê tài chính ngắn hạn", "accounting_code": "320", "evidence": "Vay và nợ thuê tài chính ngắn hạn | 320 | 20.000.000.000", "page": 2},
      "equity": {"value_raw": "45.000.000.000", "semantic_label": "VỐN CHỦ SỞ HỮU", "accounting_code": "400", "evidence": "D. VỐN CHỦ SỞ HỮU | 400 | 45.000.000.000", "page": 2}
    }
  ]
}
"""

# Substitutes the OCR_UNREADABLE marker's single source of truth
# (pdf_ocr.OCR_UNREADABLE_PAGE_MARKER) into the prompt via a plain placeholder
# token/str.replace() rather than str.format(), since the prompt's JSON example
# already contains many literal '{'/'}' characters that would otherwise need
# escaping.
FINANCIAL_EXTRACTION_SYSTEM_PROMPT = FINANCIAL_EXTRACTION_SYSTEM_PROMPT.replace(
    "{OCR_UNREADABLE_MARKER}", OCR_UNREADABLE_PAGE_MARKER
)


# ==============================================================================
# 5. FINANCIAL EXTRACTION EXCEPTION HIERARCHY & CONFIGURATION
# ==============================================================================

class FinancialExtractionError(ValueError):
    """Lỗi cơ sở cho toàn bộ quy trình trích xuất báo cáo tài chính."""
    pass


class FinancialPageMarkerError(FinancialExtractionError):
    """Lỗi khi cấu trúc thẻ trang [PAGE X] không hợp lệ, thiếu, hoặc trùng lặp."""
    pass


class FinancialChunkExtractionError(FinancialExtractionError):
    """Lỗi khi trích xuất một phân đoạn tài liệu (JSON hỏng, cắt cụt, hoặc lỗi mạng)."""
    pass


class FinancialMergeConflictError(FinancialExtractionError):
    """Lỗi khi hợp nhất các phân đoạn phát hiện dữ liệu xung đột không thể giải quyết tất định."""
    pass


FINANCIAL_SOURCE_FACT_FIELDS: List[str] = [
    "net_revenue",
    "cogs",
    "gross_profit",
    "financial_income",
    "financial_expenses",
    "interest_expenses",
    "sga_expenses",
    "net_profit_before_tax",
    "net_profit_after_tax",
    "current_assets",
    "cash",
    "receivables",
    "inventories",
    "total_assets",
    "total_liabilities",
    "current_liabilities",
    "short_term_debt",
    "equity",
]


def is_note_disclosure_cogs(cogs_val: Any) -> bool:
    """Kiểm tra xem dữ liệu cogs có phải là một thành phần trong Thuyết minh (Notes)
    như 'Chi phí sản xuất, kinh doanh theo yếu tố' hay 'Giá vốn hàng hóa' thay vì
    chỉ tiêu Giá vốn hàng bán chính thức trên Báo cáo Kết quả Kinh doanh (Mẫu B02-DN).

    Quy tắc phân định tất định:
    1. Nếu có accounting_code == '11' (mã chuẩn P&L TT 200), đây là chỉ tiêu chính thức -> KHÔNG phải note.
    2. Nếu nhãn hoặc bằng chứng thể hiện Thuyết minh chi phí theo yếu tố (expense by nature)
       hoặc nhãn là 'Giá vốn hàng hóa' (thương phẩm) mà không có mã 11 -> ĐÂY LÀ NOTE COMPONENT.
    """
    if not isinstance(cogs_val, dict):
        return False

    code = str(cogs_val.get("accounting_code") or "").strip()
    if code == "11":
        return False

    label = unicodedata.normalize("NFC", str(cogs_val.get("semantic_label") or "")).strip().lower()
    evidence = unicodedata.normalize("NFC", str(cogs_val.get("evidence") or "")).strip().lower()

    # Thuyết minh chi phí sản xuất kinh doanh theo yếu tố
    expense_by_nature_markers = [
        "chi phí sản xuất, kinh doanh theo yếu tố",
        "chi phí sản xuất kinh doanh theo yếu tố",
        "chi phí theo yếu tố",
        "chi phí sản xuất theo yếu tố",
        "expense by nature",
        "expenses by nature",
    ]
    if any(m in evidence for m in expense_by_nature_markers) or any(m in label for m in expense_by_nature_markers):
        return True

    # Nhãn 'giá vốn hàng hóa' khi không có mã 11
    if label in ("giá vốn hàng hóa", "gia von hang hoa") or label.startswith("giá vốn hàng hóa"):
        return True

    return False


def normalize_financial_extraction_raw_dict(raw_dict: Any) -> Any:
    """Chuẩn hóa dictionary thô nhận được từ LLM trước khi gọi model_validate.

    Quy tắc:
    - Loại bỏ thành phần thuyết minh chi tiết bị gán nhầm vào chỉ tiêu chính thức:
      Ví dụ: cogs thuộc Thuyết minh chi phí theo yếu tố ('Giá vốn hàng hóa') không có mã 11
      sẽ được loại bỏ (coi như vắng mặt fact chính thức trong phân đoạn này).
    - CHỈ loại bỏ các khóa thuộc FINANCIAL_SOURCE_FACT_FIELDS trong mỗi period dictionary
      nếu giá trị của khóa đó là None (null từ JSON).
    - Không loại bỏ hoặc can thiệp vào 'period', 'document_title', 'document_unit', 'page_units'.
    - Không sửa chữa ngầm các giá trị non-null không hợp lệ (ví dụ: chuỗi thay vì object).
    - Khi một trường bị loại bỏ, Pydantic sẽ sử dụng default_factory mặc định (vắng mặt sự thật).
    """
    if not isinstance(raw_dict, dict):
        return raw_dict

    def _clean_period_dict(period_obj: Dict[str, Any]) -> None:
        # Lọc bỏ thành phần thuyết minh cogs bị gán nhầm
        if "cogs" in period_obj and is_note_disclosure_cogs(period_obj["cogs"]):
            del period_obj["cogs"]

        for field_name in FINANCIAL_SOURCE_FACT_FIELDS:
            if field_name in period_obj and period_obj[field_name] is None:
                del period_obj[field_name]

    # Trường hợp 1: raw_dict là tài liệu chứa danh sách periods
    periods = raw_dict.get("periods")
    if isinstance(periods, list):
        for period_obj in periods:
            if isinstance(period_obj, dict):
                _clean_period_dict(period_obj)

    # Trường hợp 2: raw_dict chính là một period dictionary đơn lẻ
    if "period" in raw_dict:
        _clean_period_dict(raw_dict)

    return raw_dict


DEFAULT_FINANCIAL_PAGES_PER_CHUNK = 5
MIN_FINANCIAL_PAGES_PER_CHUNK = 2
MAX_FINANCIAL_PAGES_PER_CHUNK = 10

DEFAULT_FINANCIAL_EXTRACTION_MAX_WORKERS = 2
MIN_FINANCIAL_EXTRACTION_MAX_WORKERS = 1
MAX_FINANCIAL_EXTRACTION_MAX_WORKERS = 4


def get_financial_pages_per_chunk(configured: Optional[Union[int, str]] = None) -> int:
    """Xác định số trang trên mỗi phân đoạn trích xuất tài chính.

    Quy tắc:
    - Nếu truyền configured: dùng giá trị đó sau khi kiểm tra / clamp.
    - Nếu không: đọc biến môi trường FINANCIAL_PAGES_PER_CHUNK.
    - Nếu không có biến MT hoặc rỗng: mặc định DEFAULT_FINANCIAL_PAGES_PER_CHUNK (5).
    - Nếu giá trị không parse được thành số nguyên: an toàn trả về mặc định 5.
    - Nếu < 2: an toàn trả về mặc định 5.
    - Nếu > 10: kẹp (clamp) về tối đa 10.
    - Nếu trong khoảng [2, 10]: trả về giá trị đó.
    """
    raw_val = configured
    if raw_val is None:
        raw_env = os.getenv("FINANCIAL_PAGES_PER_CHUNK")
        if raw_env is not None and str(raw_env).strip():
            try:
                raw_val = int(str(raw_env).strip())
            except ValueError:
                return DEFAULT_FINANCIAL_PAGES_PER_CHUNK
        else:
            return DEFAULT_FINANCIAL_PAGES_PER_CHUNK

    try:
        val = int(raw_val)
    except (ValueError, TypeError):
        return DEFAULT_FINANCIAL_PAGES_PER_CHUNK

    if val < MIN_FINANCIAL_PAGES_PER_CHUNK:
        return DEFAULT_FINANCIAL_PAGES_PER_CHUNK
    if val > MAX_FINANCIAL_PAGES_PER_CHUNK:
        return MAX_FINANCIAL_PAGES_PER_CHUNK
    return val


def get_financial_extraction_max_workers(configured: Optional[Union[int, str]] = None) -> int:
    """Xác định số lượng worker chạy trích xuất chunk song song có giới hạn an toàn.

    Quy tắc:
    - Nếu truyền configured: dùng giá trị đó sau khi kiểm tra / clamp.
    - Nếu không: đọc biến môi trường FINANCIAL_EXTRACTION_MAX_WORKERS.
    - Nếu không có biến MT hoặc rỗng: mặc định DEFAULT_FINANCIAL_EXTRACTION_MAX_WORKERS (2).
    - Nếu giá trị không parse được thành số nguyên: an toàn trả về mặc định 2.
    - Nếu < 1: an toàn trả về mặc định 2.
    - Nếu > 4: kẹp (clamp) về tối đa 4.
    - Nếu trong khoảng [1, 4]: trả về giá trị đó.
    """
    raw_val = configured
    if raw_val is None:
        raw_env = os.getenv("FINANCIAL_EXTRACTION_MAX_WORKERS")
        if raw_env is not None and str(raw_env).strip():
            try:
                raw_val = int(str(raw_env).strip())
            except ValueError:
                return DEFAULT_FINANCIAL_EXTRACTION_MAX_WORKERS
        else:
            return DEFAULT_FINANCIAL_EXTRACTION_MAX_WORKERS

    try:
        val = int(raw_val)
    except (ValueError, TypeError):
        return DEFAULT_FINANCIAL_EXTRACTION_MAX_WORKERS

    if val < MIN_FINANCIAL_EXTRACTION_MAX_WORKERS:
        return DEFAULT_FINANCIAL_EXTRACTION_MAX_WORKERS
    if val > MAX_FINANCIAL_EXTRACTION_MAX_WORKERS:
        return MAX_FINANCIAL_EXTRACTION_MAX_WORKERS
    return val


# Deterministic page-level degraded-handling threshold for FINANCIAL PDF OCR only
# (legal/business/CIC ingestion never reads this -- they keep the pre-existing
# "any OCR failure aborts the whole document" behavior unconditionally).
DEFAULT_FINANCIAL_OCR_MAX_FAILED_PAGES = 2
MIN_FINANCIAL_OCR_MAX_FAILED_PAGES = 0


def get_financial_ocr_max_failed_pages(configured: Optional[Union[int, str]] = None) -> int:
    """Xác định ngưỡng tối đa số trang OCR được phép dung thứ (tolerate) là không đọc
    được (sau khi đã hết mọi lần thử lại nội dung rỗng) trước khi toàn bộ quá trình
    nhập liệu BCTC bị coi là thất bại.

    Quy tắc:
    - Nếu truyền configured: dùng giá trị đó sau khi kiểm tra.
    - Nếu không: đọc biến môi trường FINANCIAL_OCR_MAX_FAILED_PAGES.
    - Nếu không có biến MT hoặc rỗng: mặc định DEFAULT_FINANCIAL_OCR_MAX_FAILED_PAGES (2).
    - Nếu giá trị không parse được thành số nguyên, hoặc < 0: an toàn trả về mặc định 2.
    - Giá trị >= 0 hợp lệ: trả về nguyên giá trị đó (0 nghĩa là KHÔNG dung thứ bất kỳ
      trang lỗi nào -- tương đương thất bại ngay khi có 1 trang không đọc được).
    """
    raw_val = configured
    if raw_val is None:
        raw_env = os.getenv("FINANCIAL_OCR_MAX_FAILED_PAGES")
        if raw_env is not None and str(raw_env).strip():
            try:
                raw_val = int(str(raw_env).strip())
            except ValueError:
                return DEFAULT_FINANCIAL_OCR_MAX_FAILED_PAGES
        else:
            return DEFAULT_FINANCIAL_OCR_MAX_FAILED_PAGES

    try:
        val = int(raw_val)
    except (ValueError, TypeError):
        return DEFAULT_FINANCIAL_OCR_MAX_FAILED_PAGES

    if val < MIN_FINANCIAL_OCR_MAX_FAILED_PAGES:
        return DEFAULT_FINANCIAL_OCR_MAX_FAILED_PAGES
    return val


# ==============================================================================
# 6. DETERMINISTIC PAGE PARSER & CHUNKER
# ==============================================================================

@dataclass(frozen=True)
class FinancialPageChunk:
    """Đại diện cho một phân đoạn trang vật lý của Báo cáo tài chính."""
    chunk_index: int
    start_page: int
    end_page: int
    page_nums: List[int]
    tagged_text: str


def parse_tagged_pages(
    tagged_text: str,
    page_count: Optional[int] = None,
) -> List[Tuple[int, str]]:
    """Phân tách văn bản gắn thẻ [PAGE X] thành danh sách các trang vật lý (page_num, page_content).

    Bất biến bắt buộc:
    - Đầu vào phải là chuỗi (string).
    - Chỉ cho phép ký tự khoảng trắng trước thẻ [PAGE X] đầu tiên.
    - Bắt buộc phải có ít nhất một thẻ [PAGE X].
    - Số trang phải là số nguyên > 0.
    - Chuỗi trang vật lý phải bắt đầu từ trang 1 và liên tục tăng dần nghiêm ngặt (1, 2, ..., N),
      không ngắt quãng (gaps), không đảo thứ tự (reordering), không trùng lặp (duplicates).
    - Nếu có tham số page_count: số trang thực tế và số trang lớn nhất phải khớp chính xác với page_count.
    - Giữ nguyên số trang vật lý gốc, tuyệt đối không đánh lại số trang.
    """
    if not isinstance(tagged_text, str):
        raise FinancialPageMarkerError("Văn bản nguồn phải là kiểu chuỗi (string).")

    pattern = re.compile(r"\[PAGE\s+(-?\d+)\]")
    matches = list(pattern.finditer(tagged_text))

    if not matches:
        raise FinancialPageMarkerError("Văn bản nguồn không chứa bất kỳ thẻ trang [PAGE X] hợp lệ nào.")

    first_match = matches[0]
    preamble = tagged_text[:first_match.start()]
    if preamble.strip() != "":
        raise FinancialPageMarkerError(
            f"Văn bản nguồn chứa nội dung không phải khoảng trắng trước thẻ trang đầu tiên: '{preamble.strip()[:100]}'"
        )

    seen_pages = set()
    pages: List[Tuple[int, str]] = []

    for i, match in enumerate(matches):
        page_num_str = match.group(1)
        try:
            page_num = int(page_num_str)
        except ValueError:
            raise FinancialPageMarkerError(f"Số trang không hợp lệ: '{page_num_str}'")

        if page_num <= 0:
            raise FinancialPageMarkerError(f"Số trang trong thẻ [PAGE {page_num}] phải > 0.")

        if page_num in seen_pages:
            raise FinancialPageMarkerError(f"Phát hiện trùng lặp thẻ trang: [PAGE {page_num}].")
        seen_pages.add(page_num)

        expected_page = i + 1
        if i == 0 and page_num != 1:
            raise FinancialPageMarkerError(
                f"Chuỗi trang vật lý phải bắt đầu từ trang 1, nhưng bắt đầu từ [PAGE {page_num}]."
            )
        if page_num != expected_page:
            raise FinancialPageMarkerError(
                f"Phát hiện gián đoạn hoặc sai thứ tự trang vật lý: kỳ vọng [PAGE {expected_page}], nhưng gặp [PAGE {page_num}]."
            )

        start_pos = match.end()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(tagged_text)
        page_content = tagged_text[start_pos:end_pos]
        pages.append((page_num, page_content))

    if page_count is not None:
        try:
            expected_count = int(page_count)
        except (ValueError, TypeError):
            raise FinancialPageMarkerError(f"Số lượng trang kỳ vọng (page_count={page_count}) không hợp lệ.")

        if expected_count <= 0:
            raise FinancialPageMarkerError(f"Số lượng trang kỳ vọng (page_count={expected_count}) phải > 0.")

        actual_count = len(pages)
        max_page = pages[-1][0] if pages else 0
        if actual_count != expected_count or max_page != expected_count:
            raise FinancialPageMarkerError(
                f"Bất đồng số lượng trang: tài liệu thực tế có {actual_count} trang (1..{max_page}) "
                f"nhưng tham số page_count yêu cầu {expected_count} trang."
            )

    return pages


def chunk_pages(
    pages: List[Tuple[int, str]],
    pages_per_chunk: int = DEFAULT_FINANCIAL_PAGES_PER_CHUNK,
) -> List[FinancialPageChunk]:
    """Phân tách danh sách các trang thành các chunk theo ranh giới trang vật lý."""
    if not pages:
        return []

    chunks: List[FinancialPageChunk] = []
    chunk_idx = 1
    for i in range(0, len(pages), pages_per_chunk):
        slice_pages = pages[i : i + pages_per_chunk]
        page_nums = [p_num for p_num, _ in slice_pages]
        start_page = min(page_nums)
        end_page = max(page_nums)

        chunk_blocks: List[str] = []
        for p_num, content in slice_pages:
            body = content if content.startswith("\n") else f"\n{content}"
            chunk_blocks.append(f"[PAGE {p_num}]{body.rstrip()}")
        chunk_text = "\n\n".join(chunk_blocks)

        chunks.append(
            FinancialPageChunk(
                chunk_index=chunk_idx,
                start_page=start_page,
                end_page=end_page,
                page_nums=page_nums,
                tagged_text=chunk_text,
            )
        )
        chunk_idx += 1

    return chunks


# ==============================================================================
# 7. DETERMINISTIC PYTHON MERGE
# ==============================================================================

def are_evidence_fields_identical(f1: FinancialEvidenceField, f2: FinancialEvidenceField) -> bool:
    """Kiểm tra xem hai FinancialEvidenceField có biểu diễn cùng một giá trị tài chính tương đương và đơn vị tương thích hay không.

    Lưu ý: Số trang khác nhau (ví dụ: số liệu xuất hiện ở Báo cáo tài chính trang 8 và Thuyết minh trang 21)
    KHÔNG phải là xung đột nếu giá trị số và đơn vị tính tương thích.
    """
    raw1 = str(f1.value_raw).strip() if f1.value_raw is not None else ""
    raw2 = str(f2.value_raw).strip() if f2.value_raw is not None else ""

    if not raw1 and not raw2:
        return True
    if not raw1 or not raw2:
        return False

    # 1. Kiểm tra tính tương thích của đơn vị tính nếu cả hai đều khai báo tường minh
    if f1.unit_raw and f2.unit_raw:
        u1 = unicodedata.normalize("NFC", str(f1.unit_raw)).strip().lower()
        u2 = unicodedata.normalize("NFC", str(f2.unit_raw)).strip().lower()
        if u1 != u2:
            return False

    # 2. Nếu chuỗi thô giống hệt nhau
    if raw1 == raw2:
        return True

    # 3. Đối chiếu giá trị số sau chuẩn hóa tiền tệ / kế toán (Decimal equivalence)
    tok1, err1 = LexicalFinancialNumberParser.parse_token(raw1)
    tok2, err2 = LexicalFinancialNumberParser.parse_token(raw2)
    if tok1 is not None and tok2 is not None and not err1 and not err2:
        val1, v_err1 = AccountingSemanticInterpreter.interpret(tok1)
        val2, v_err2 = AccountingSemanticInterpreter.interpret(tok2)
        if val1 is not None and val2 is not None and val1 == val2:
            return True

    return False


def _merge_evidence_field(
    period_key: str,
    field_name: str,
    f1: FinancialEvidenceField,
    f2: FinancialEvidenceField,
) -> FinancialEvidenceField:
    """Hợp nhất hai trường bằng chứng tài chính theo quy tắc không ghi đè ngầm và bắt lỗi xung đột."""
    f1_has_val = f1.value_raw is not None and str(f1.value_raw).strip() != ""
    f2_has_val = f2.value_raw is not None and str(f2.value_raw).strip() != ""

    if not f1_has_val and not f2_has_val:
        return f1

    if not f1_has_val and f2_has_val:
        return f2

    if f1_has_val and not f2_has_val:
        return f1

    # Cả hai đều có giá trị -> Kiểm tra xung đột đơn vị tính trước
    if f1.unit_raw and f2.unit_raw:
        u1 = unicodedata.normalize("NFC", str(f1.unit_raw)).strip().lower()
        u2 = unicodedata.normalize("NFC", str(f2.unit_raw)).strip().lower()
        if u1 != u2:
            raise FinancialMergeConflictError(
                f"Xung đột đơn vị tính tại kỳ '{period_key}', chỉ tiêu '{field_name}': "
                f"'{f1.unit_raw}' (trang {f1.page}) vs '{f2.unit_raw}' (trang {f2.page})."
            )

    # Kiểm tra giá trị trùng lặp / tương đương
    if are_evidence_fields_identical(f1, f2):
        # Lựa chọn đại diện tất định: ưu tiên trang vật lý nhỏ hơn; nếu một bên có trang, một bên không thì ưu tiên bên có trang.
        prefer_f1 = True
        if f1.page is not None and f2.page is not None:
            prefer_f1 = f1.page <= f2.page
        elif f1.page is None and f2.page is not None:
            prefer_f1 = False
        elif f1.page is not None and f2.page is None:
            prefer_f1 = True

        rep = f1 if prefer_f1 else f2
        other = f2 if prefer_f1 else f1

        unit_raw = rep.unit_raw if rep.unit_raw is not None else other.unit_raw
        unit_evidence = rep.unit_evidence if rep.unit_raw is not None else other.unit_evidence
        accounting_code = rep.accounting_code or other.accounting_code
        semantic_label = rep.semantic_label or other.semantic_label

        return FinancialEvidenceField(
            value_raw=rep.value_raw,
            semantic_label=semantic_label,
            accounting_code=accounting_code,
            unit_raw=unit_raw,
            unit_evidence=unit_evidence,
            evidence=rep.evidence,
            page=rep.page,
        )

    raise FinancialMergeConflictError(
        f"Xung đột dữ liệu không thể hợp nhất cho kỳ '{period_key}', chỉ tiêu '{field_name}': "
        f"giá trị '{f1.value_raw}' (trang {f1.page}) và '{f2.value_raw}' (trang {f2.page})."
    )


def merge_financial_extractions(
    extractions: List[FinancialDocumentExtraction],
) -> FinancialDocumentExtraction:
    """Hợp nhất tất định danh sách các kết quả trích xuất chunk thành một FinancialDocumentExtraction duy nhất.

    Quy tắc:
    A. PAGE UNITS: Hợp nhất theo số trang vật lý gốc. Trùng lặp cùng đơn vị -> gộp tất định. Xung đột đơn vị -> báo lỗi.
    B. PERIODS: Nhận diện kỳ theo chuỗi kỳ chuẩn hóa. Ghép trường theo từng field_name.
    C. DUPLICATE IDENTICAL FACT: Cùng kỳ, cùng trường, cùng giá trị/trang -> gộp tất định.
    D. CONFLICTING FACT: Khác giá trị non-null -> ném ngoại lệ FinancialMergeConflictError, cấm last-write-wins.
    """
    if not extractions:
        return FinancialDocumentExtraction()

    if len(extractions) == 1:
        return extractions[0]

    # 1. Hợp nhất document_title: Tiêu đề phi rỗng đầu tiên theo thứ tự chunk được chọn làm đại diện
    merged_title: Optional[str] = None
    for ext in extractions:
        if ext.document_title and ext.document_title.strip():
            t = ext.document_title.strip()
            if merged_title is None:
                merged_title = t

    # 2. Hợp nhất document_unit
    merged_doc_unit: Optional[FinancialUnitInfo] = None
    for ext in extractions:
        if ext.document_unit is not None:
            if merged_doc_unit is None:
                merged_doc_unit = ext.document_unit
            else:
                norm_u1 = unicodedata.normalize("NFC", merged_doc_unit.unit_raw).strip().lower()
                norm_u2 = unicodedata.normalize("NFC", ext.document_unit.unit_raw).strip().lower()
                if norm_u1 != norm_u2:
                    raise FinancialMergeConflictError(
                        f"Xung đột đơn vị tính tài liệu (document_unit): '{merged_doc_unit.unit_raw}' "
                        f"(trang {merged_doc_unit.page}) và '{ext.document_unit.unit_raw}' (trang {ext.document_unit.page})."
                    )

    # 3. Hợp nhất page_units
    merged_page_units: Dict[int, FinancialUnitInfo] = {}
    for ext in extractions:
        for page_num_raw, unit_info in ext.page_units.items():
            p_num = int(page_num_raw)
            if p_num not in merged_page_units:
                merged_page_units[p_num] = unit_info
            else:
                existing_unit = merged_page_units[p_num]
                norm_u1 = unicodedata.normalize("NFC", existing_unit.unit_raw).strip().lower()
                norm_u2 = unicodedata.normalize("NFC", unit_info.unit_raw).strip().lower()
                if norm_u1 != norm_u2:
                    raise FinancialMergeConflictError(
                        f"Xung đột đơn vị tính tại trang {p_num} (page_units): "
                        f"'{existing_unit.unit_raw}' vs '{unit_info.unit_raw}'."
                    )

    # 4. Hợp nhất periods theo từng kỳ và từng trường
    merged_periods_map: Dict[str, FinancialPeriodExtraction] = {}
    period_order: List[str] = []

    for ext in extractions:
        for p in ext.periods:
            pkey = unicodedata.normalize("NFC", p.period).strip()
            if pkey not in merged_periods_map:
                merged_periods_map[pkey] = FinancialPeriodExtraction(period=pkey)
                period_order.append(pkey)

            target_period = merged_periods_map[pkey]
            for field_name in FINANCIAL_SOURCE_FACT_FIELDS:
                existing_field = getattr(target_period, field_name)
                incoming_field = getattr(p, field_name)

                merged_field = _merge_evidence_field(
                    period_key=pkey,
                    field_name=field_name,
                    f1=existing_field,
                    f2=incoming_field,
                )
                setattr(target_period, field_name, merged_field)

    merged_periods = [merged_periods_map[pkey] for pkey in period_order]

    return FinancialDocumentExtraction(
        document_title=merged_title,
        periods=merged_periods,
        page_units=merged_page_units,
        document_unit=merged_doc_unit,
    )


# ==============================================================================
# 8. FINANCIAL DOCUMENT EXTRACTOR (PAGE CHUNKING ORCHESTRATOR)
# ==============================================================================

class FinancialDocumentExtractor:
    """Orchestrates GreenNode financial document extraction with page chunking and grounding audit."""

    def __init__(
        self,
        ai_client: Optional[Any] = None,
        pages_per_chunk: Optional[int] = None,
        max_workers: Optional[int] = None,
    ):
        self.ai_client = ai_client
        self.pages_per_chunk = pages_per_chunk
        self.max_workers = max_workers

    def _extract_chunk(
        self,
        chunk: FinancialPageChunk,
        api_key: Optional[str] = None,
    ) -> FinancialDocumentExtraction:
        """Thực hiện trích xuất cho đúng 1 phân đoạn trang độc lập."""
        user_prompt = f"""Bạn đang xử lý một phần của Báo cáo tài chính, bao gồm các trang vật lý từ [PAGE {chunk.start_page}] đến [PAGE {chunk.end_page}]:

{chunk.tagged_text}

HƯỚNG DẪN XỬ LÝ PHÂN ĐOẠN:
1. Đây CHỈ LÀ MỘT PHẦN (subset) của toàn bộ BCTC.
2. CHỈ trích xuất các sự thật tài chính (facts) và đơn vị tính (unit) xuất hiện TƯỜNG MINH trong các trang vật lý này.
3. CHỈ TIÊU CHÍNH THỨC TRÊN BÁO CÁO VS THÀNH PHẦN THUYẾT MINH:
   - Các trường tài chính đại diện cho chỉ tiêu tổng hợp chính thức trên Báo cáo Kết quả Kinh doanh (P&L Mẫu B02-DN) và Bảng Cân đối Kế toán (Mẫu B01-DN).
   - TUYỆT ĐỐI KHÔNG gán các dòng chi tiết trong Thuyết minh (Notes) vào chỉ tiêu chính:
     * cogs: Phải là chỉ tiêu chính "Giá vốn hàng bán" (Mã số 11) trên P&L. TUYỆT ĐỐI KHÔNG lấy dòng "Giá vốn hàng hóa" trong Thuyết minh "Chi phí sản xuất, kinh doanh theo yếu tố".
     * Nếu phân đoạn này chỉ có Thuyết minh chi tiết theo yếu tố mà không có chỉ tiêu P&L chính thức, BẮT BUỘC để cogs: null hoặc bỏ qua.
     * Tương tự với sga_expenses, cash, receivables, short_term_debt: không lấy thành phần thuyết minh chi tiết thay cho chỉ tiêu chính thức.
4. BẮT BUỘC giữ nguyên số trang vật lý gốc trong trường "page" (ví dụ: nếu số liệu nằm ở [PAGE {chunk.start_page}], "page" phải là {chunk.start_page}). TUYỆT ĐỐI KHÔNG đánh lại số trang từ 1.
5. NO EVIDENCE -> NO FACT: Trường nào không có số liệu/bằng chứng trong các trang này thì để null hoặc bỏ qua, TUYỆT ĐỐI KHÔNG tự suy đoán số liệu từ các năm khác hay phân đoạn khác.
6. KHÔNG tính toán bất kỳ chỉ số tài chính nào.
7. Bắt buộc trả về đúng định dạng JSON thuần túy (strict JSON)."""

        operation = f"financial_extraction_pages_{chunk.start_page}_{chunk.end_page}"

        try:
            if self.ai_client and hasattr(self.ai_client, "generate_text"):
                resp_text = self.ai_client.generate_text(
                    prompt=user_prompt,
                    system_prompt=FINANCIAL_EXTRACTION_SYSTEM_PROMPT,
                    operation=operation,
                )
            elif self.ai_client and hasattr(self.ai_client, "chat"):
                resp_text = self.ai_client.chat(
                    system_prompt=FINANCIAL_EXTRACTION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=0.0,
                    max_tokens=4096,
                    api_key=api_key,
                    operation=operation,
                )
            else:
                resp_text = AIAssistantClient.chat(
                    system_prompt=FINANCIAL_EXTRACTION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=0.0,
                    max_tokens=4096,
                    api_key=api_key,
                    operation=operation,
                )
        except Exception as e:
            raise FinancialChunkExtractionError(
                f"Lỗi khi gọi GreenNode cho phân đoạn trang {chunk.start_page}-{chunk.end_page}: {str(e)}"
            ) from e

        if resp_text is None:
            raise FinancialChunkExtractionError(
                f"GreenNode trả về phản hồi rỗng (None) cho phân đoạn trang {chunk.start_page}-{chunk.end_page}."
            )

        cleaned_json = resp_text.strip()
        if cleaned_json.startswith("```"):
            cleaned_json = re.sub(r"^```(?:json)?\s*", "", cleaned_json, flags=re.IGNORECASE)
            cleaned_json = re.sub(r"\s*```$", "", cleaned_json)
        cleaned_json = cleaned_json.strip()

        try:
            raw_dict = json.loads(cleaned_json)
        except json.JSONDecodeError as e:
            snippet = cleaned_json[:200] if len(cleaned_json) > 200 else cleaned_json
            raise FinancialChunkExtractionError(
                f"GreenNode returned invalid JSON for financial chunk pages {chunk.start_page}-{chunk.end_page}: {str(e)}\nSnippet: {snippet}"
            ) from e

        if not isinstance(raw_dict, dict):
            raise FinancialChunkExtractionError(
                f"GreenNode trả về định dạng không phải JSON Object cho phân đoạn trang {chunk.start_page}-{chunk.end_page}."
            )

        raw_dict = normalize_financial_extraction_raw_dict(raw_dict)

        try:
            extraction = FinancialDocumentExtraction.model_validate(raw_dict)
            return extraction
        except Exception as e:
            raise FinancialChunkExtractionError(
                f"Lỗi kiểm thực Pydantic cho phân đoạn trang {chunk.start_page}-{chunk.end_page}: {str(e)}"
            ) from e

    def extract(
        self,
        tagged_text: str,
        page_count: Optional[int] = None,
        api_key: Optional[str] = None,
        pages_per_chunk: Optional[int] = None,
        max_workers: Optional[int] = None,
    ) -> FinancialDocumentExtraction:
        """Trích xuất dữ liệu tài chính qua cơ chế phân đoạn trang (chunking) và hợp nhất tất định."""
        parsed_pages = parse_tagged_pages(tagged_text, page_count=page_count)
        if not parsed_pages:
            return FinancialDocumentExtraction()

        effective_ppc = get_financial_pages_per_chunk(pages_per_chunk or self.pages_per_chunk)
        effective_workers = get_financial_extraction_max_workers(max_workers or self.max_workers)

        chunks = chunk_pages(parsed_pages, pages_per_chunk=effective_ppc)
        if not chunks:
            return FinancialDocumentExtraction()

        # Nếu chỉ có 1 chunk hoặc worker = 1: chạy tuần tự an toàn
        if len(chunks) == 1 or effective_workers == 1:
            chunk_results: List[FinancialDocumentExtraction] = []
            for chunk in chunks:
                res = self._extract_chunk(chunk, api_key=api_key)
                chunk_results.append(res)
            return merge_financial_extractions(chunk_results)

        # Chạy song song có giới hạn bằng ThreadPoolExecutor
        workers_bound = min(effective_workers, len(chunks))
        chunk_results_dict: Dict[int, FinancialDocumentExtraction] = {}
        first_exc: Optional[Exception] = None

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers_bound) as executor:
            future_to_chunk = {
                executor.submit(self._extract_chunk, chunk, api_key=api_key): chunk
                for chunk in chunks
            }
            for future in concurrent.futures.as_completed(future_to_chunk):
                chunk = future_to_chunk[future]
                try:
                    res = future.result()
                    chunk_results_dict[chunk.chunk_index] = res
                except Exception as exc:
                    if first_exc is None:
                        first_exc = exc
                    for f in future_to_chunk:
                        f.cancel()

        if first_exc is not None:
            raise first_exc

        ordered_results = [chunk_results_dict[idx] for idx in sorted(chunk_results_dict.keys())]
        return merge_financial_extractions(ordered_results)
