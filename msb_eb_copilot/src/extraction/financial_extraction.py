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
import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

from msb_eb_copilot.src.ai_client import AIAssistantClient


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
    """Grounded unit information at page or document level."""
    unit_raw: str = Field(..., description="Raw unit text, e.g. 'VND', 'triệu đồng'")
    evidence: str = Field(..., description="Verbatim snippet where unit appears")
    page: int = Field(..., description="Page number where unit evidence was found")


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
        "keywords": ["giá vốn", "giá vốn hàng bán", "cost of goods sold"],
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
2. CHỈ TRÍCH XUẤT SỰ THẬT NGUỒN:
   - Báo cáo Kết quả kinh doanh (P&L): net_revenue, cogs, gross_profit, financial_income, financial_expenses, interest_expenses, sga_expenses, net_profit_before_tax, net_profit_after_tax.
   - Bảng Cân đối kế toán (Balance Sheet): current_assets, cash, receivables, inventories, total_assets, total_liabilities, current_liabilities, short_term_debt, equity.
3. TUYỆT ĐỐI CẤM TÍNH TOÁN HAY SUY ĐOÁN:
   - KHÔNG tính các chỉ số an toàn tài chính (current_ratio, quick_ratio, debt_to_equity, DSCR, ROS, ROE,...).
   - KHÔNG tính toán chu kỳ kinh doanh (CCC, MB09) hay lợi nhuận điều chỉnh rủi ro (RORWA).
   - Python sẽ tự động tính toán 100% các chỉ số này.
4. XÁC ĐỊNH ĐƠN VỊ TÍNH (UNIT) GẮN LIỀN VỚI TỪNG TRANG:
   - Tìm câu văn ghi đơn vị tính (ví dụ: 'Đơn vị tính: VND', 'Đơn vị tính: triệu đồng').
   - Ghi nhận unit_raw và unit_evidence.
5. PHÂN TÁCH RÕ RÀNG TỪNG NĂM / KỲ KẾ TOÁN (PERIOD):
   - Xác định rõ cột số liệu thuộc năm nào (ví dụ: '2025', '2024'). Không được tráo đổi thứ tự cột.
6. ĐỊNH DẠNG ĐẦU RA:
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


class FinancialDocumentExtractor:
    """Orchestrates GreenNode financial document extraction with grounding audit."""

    def __init__(self, ai_client: Optional[Any] = None):
        self.ai_client = ai_client

    def extract(self, tagged_text: str, page_count: int, api_key: Optional[str] = None) -> FinancialDocumentExtraction:
        """Call GreenNode MaaS text model to extract structured financial staging data."""
        user_prompt = f"""Hãy đọc kỹ toàn bộ văn bản Báo cáo tài chính dưới đây (đã phân chia theo thẻ [PAGE X]):

{tagged_text}

Trích xuất toàn bộ các sự thật tài chính nguồn theo đúng hướng dẫn hệ thống. Bắt buộc trả về JSON hợp lệ."""

        if self.ai_client and hasattr(self.ai_client, "generate_text"):
            resp_text = self.ai_client.generate_text(
                prompt=user_prompt,
                system_prompt=FINANCIAL_EXTRACTION_SYSTEM_PROMPT,
                operation="financial_extraction",
            )
        elif self.ai_client and hasattr(self.ai_client, "chat"):
            resp_text = self.ai_client.chat(
                system_prompt=FINANCIAL_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=4096,
                api_key=api_key,
                operation="financial_extraction",
            )
        else:
            resp_text = AIAssistantClient.chat(
                system_prompt=FINANCIAL_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=4096,
                api_key=api_key,
                operation="financial_extraction",
            )

        # Parse JSON
        cleaned_json = resp_text.strip()
        if cleaned_json.startswith("```"):
            cleaned_json = re.sub(r"^```(?:json)?\s*", "", cleaned_json)
            cleaned_json = re.sub(r"\s*```$", "", cleaned_json)

        try:
            raw_dict = json.loads(cleaned_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"GreenNode returned invalid JSON for financial extraction: {e}\nRaw: {resp_text[:300]}")

        # Construct Pydantic model
        extraction = FinancialDocumentExtraction.model_validate(raw_dict)
        return extraction
