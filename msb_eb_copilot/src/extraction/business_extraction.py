# -*- coding: utf-8 -*-
"""Real GreenNode Business Document Extractor for Section C Facts.

Module: msb_eb_copilot.src.extraction.business_extraction
Strict Boundaries:
- GreenNode populates SOURCE_FACT and SOURCE_CLAIM fields only.
- GreenNode is FORBIDDEN from choosing canonical RM_INPUT enums or calculating experience/shares.
- Strict Pydantic models with ConfigDict(extra="forbid").
- Verbatim evidence-backed provenance (value_raw, semantic_label, evidence, page).
- Per-item repeated entity preservation (shareholders, management, products, warehouses, equipments, suppliers, customers, competitors, milestones).
- Customer identity extraction is IDENTITY_CHECK_ONLY; never written to customer identity.
- Management experience duration: explicit number -> int; dates only -> None (never 0).
- Capital milestone dates: preserve source precision (e.g. "2020", not "01/01/2020").
"""

from __future__ import annotations
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field, model_validator

from msb_eb_copilot.src.ai_client import AIAssistantClient


# ==============================================================================
# 1. STAGING DATA MODELS (Strict Pydantic, extra="forbid")
# ==============================================================================

class BusinessEvidenceField(BaseModel):
    """Evidence-backed extraction for one business fact or claim."""
    model_config = ConfigDict(extra="forbid")

    value_raw: Optional[str] = Field(None, description="Raw literal string from document")
    semantic_label: Optional[str] = Field(None, description="Exact field label or header")
    evidence: Optional[str] = Field(None, description="Verbatim text snippet containing the fact")
    page: Optional[int] = Field(None, description="Physical 1-indexed page number")


class CapitalMilestoneItem(BaseModel):
    """Lịch sử các mốc thay đổi / tăng vốn điều lệ."""
    model_config = ConfigDict(extra="forbid")

    effective_date: Optional[BusinessEvidenceField] = None
    charter_capital_raw: Optional[BusinessEvidenceField] = None
    event_description: Optional[BusinessEvidenceField] = None
    page: Optional[int] = None


class ShareholderItem(BaseModel):
    """Thông tin Cổ đông lớn / Thành viên góp vốn."""
    model_config = ConfigDict(extra="forbid")

    shareholder_name: Optional[BusinessEvidenceField] = None
    id_tax_code: Optional[BusinessEvidenceField] = None
    ownership_percentage_raw: Optional[BusinessEvidenceField] = None
    contributed_capital_raw: Optional[BusinessEvidenceField] = None
    shareholder_type: Optional[BusinessEvidenceField] = None
    page: Optional[int] = None


class ManagementItem(BaseModel):
    """Thành viên Ban lãnh đạo / Ban điều hành."""
    model_config = ConfigDict(extra="forbid")

    full_name: Optional[BusinessEvidenceField] = None
    position: Optional[BusinessEvidenceField] = None
    career_history_raw: Optional[BusinessEvidenceField] = None
    explicit_experience_years_raw: Optional[BusinessEvidenceField] = None
    profile_summary: Optional[BusinessEvidenceField] = None
    page: Optional[int] = None


class ProductItem(BaseModel):
    """Sản phẩm / Dịch vụ kinh doanh chính."""
    model_config = ConfigDict(extra="forbid")

    product_name: Optional[BusinessEvidenceField] = None
    brand_or_spec: Optional[BusinessEvidenceField] = None
    revenue_share_percentage_raw: Optional[BusinessEvidenceField] = None
    page: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if "specification_brand" in d and "brand_or_spec" not in d:
                d["brand_or_spec"] = d.pop("specification_brand")
            if "revenue_percentage_raw" in d and "revenue_share_percentage_raw" not in d:
                d["revenue_share_percentage_raw"] = d.pop("revenue_percentage_raw")
            return d
        return data


class WarehouseItem(BaseModel):
    """Cơ sở vật chất: Hệ thống nhà xưởng, kho bãi (Bảng 01 MB07)."""
    model_config = ConfigDict(extra="forbid")

    facility_type: Optional[BusinessEvidenceField] = None
    address: Optional[BusinessEvidenceField] = None
    area_raw: Optional[BusinessEvidenceField] = None
    ownership_type: Optional[BusinessEvidenceField] = None
    capacity_description: Optional[BusinessEvidenceField] = None
    page: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if "area_m2_raw" in d and "area_raw" not in d:
                d["area_raw"] = d.pop("area_m2_raw")
            if "capacity_raw" in d and "capacity_description" not in d:
                d["capacity_description"] = d.pop("capacity_raw")
            return d
        return data


class EquipmentItem(BaseModel):
    """Hệ thống Máy móc thiết bị (MMTB) (Bảng 02 MB07)."""
    model_config = ConfigDict(extra="forbid")

    equipment_name: Optional[BusinessEvidenceField] = None
    origin_and_technology: Optional[BusinessEvidenceField] = None
    designed_capacity: Optional[BusinessEvidenceField] = None
    utilization_rate: Optional[BusinessEvidenceField] = None
    page: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if "origin_technology" in d and "origin_and_technology" not in d:
                d["origin_and_technology"] = d.pop("origin_technology")
            if "design_capacity_raw" in d and "designed_capacity" not in d:
                d["designed_capacity"] = d.pop("design_capacity_raw")
            if "operational_performance_raw" in d and "utilization_rate" not in d:
                d["utilization_rate"] = d.pop("operational_performance_raw")
            return d
        return data


class SupplierItem(BaseModel):
    """Thị trường Đầu vào & Top Nhà cung cấp chính (Bảng 04 MB07)."""
    model_config = ConfigDict(extra="forbid")

    supplier_name: Optional[BusinessEvidenceField] = None
    supplied_goods: Optional[BusinessEvidenceField] = None
    purchase_share_percentage_raw: Optional[BusinessEvidenceField] = None
    payment_terms: Optional[BusinessEvidenceField] = None
    page: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if "materials_supplied" in d and "supplied_goods" not in d:
                d["supplied_goods"] = d.pop("materials_supplied")
            if "purchase_percentage_raw" in d and "purchase_share_percentage_raw" not in d:
                d["purchase_share_percentage_raw"] = d.pop("purchase_percentage_raw")
            return d
        return data


class CustomerItem(BaseModel):
    """Thị trường Đầu ra & Top Khách hàng chính (Bảng 06 MB07)."""
    model_config = ConfigDict(extra="forbid")

    customer_name: Optional[BusinessEvidenceField] = None
    product_purchased: Optional[BusinessEvidenceField] = None
    revenue_share_percentage_raw: Optional[BusinessEvidenceField] = None
    credit_terms: Optional[BusinessEvidenceField] = None
    page: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if "products_supplied" in d and "product_purchased" not in d:
                d["product_purchased"] = d.pop("products_supplied")
            if "revenue_percentage_raw" in d and "revenue_share_percentage_raw" not in d:
                d["revenue_share_percentage_raw"] = d.pop("revenue_percentage_raw")
            if "receivables_policy" in d and "credit_terms" not in d:
                d["credit_terms"] = d.pop("receivables_policy")
            return d
        return data


class CompetitorItem(BaseModel):
    """Đối thủ cạnh tranh chính trên thị trường."""
    model_config = ConfigDict(extra="forbid")

    competitor_name: Optional[BusinessEvidenceField] = None
    noted_strengths_or_share: Optional[BusinessEvidenceField] = None
    page: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if "strengths" in d and "noted_strengths_or_share" not in d:
                d["noted_strengths_or_share"] = d.pop("strengths")
            return d
        return data


class BusinessDocumentExtraction(BaseModel):
    """Root extraction staging schema for Business & Operational documents."""
    model_config = ConfigDict(extra="forbid")

    # Identity check only (never written to customer identity)
    company_name: Optional[BusinessEvidenceField] = None
    tax_code: Optional[BusinessEvidenceField] = None

    # Company History & Milestones
    established_year: Optional[BusinessEvidenceField] = None
    history_narrative: Optional[BusinessEvidenceField] = None  # SOURCE_CLAIM
    capital_milestones: List[CapitalMilestoneItem] = Field(default_factory=list)

    # Ownership & Governance
    parent_company_or_owner: Optional[BusinessEvidenceField] = None
    shareholders: List[ShareholderItem] = Field(default_factory=list)

    # Management
    management: List[ManagementItem] = Field(default_factory=list)

    # Operations & Products
    operating_model_description: Optional[BusinessEvidenceField] = None  # Staging description only
    products: List[ProductItem] = Field(default_factory=list)
    production_technology_summary: Optional[BusinessEvidenceField] = None
    warehouses: List[WarehouseItem] = Field(default_factory=list)
    equipments: List[EquipmentItem] = Field(default_factory=list)

    # Supply Chain
    raw_materials_overview: Optional[BusinessEvidenceField] = None
    suppliers: List[SupplierItem] = Field(default_factory=list)
    distribution_channels: Optional[BusinessEvidenceField] = None
    customers: List[CustomerItem] = Field(default_factory=list)

    # Market Claims
    market_share_claim: Optional[BusinessEvidenceField] = None  # SOURCE_CLAIM
    competitors: List[CompetitorItem] = Field(default_factory=list)  # SOURCE_CLAIM
    competitive_advantages_claim: Optional[BusinessEvidenceField] = None  # SOURCE_CLAIM


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


class BusinessGroundingAuditor:
    """Verifies that extracted facts appear verbatim on the physical page text."""

    @classmethod
    def extract_pages(cls, tagged_text: str) -> Tuple[Dict[int, str], int]:
        pages: Dict[int, str] = {}
        pattern = r"\[PAGE\s+(\d+)\](.*?)(?=\[PAGE\s+\d+\]|\Z)"
        matches = re.findall(pattern, tagged_text, flags=re.DOTALL)
        for p_str, content in matches:
            pages[int(p_str)] = content.strip()
        max_p = max(pages.keys()) if pages else 1
        return pages, max_p

    @classmethod
    def _norm(cls, text: str) -> str:
        if not text:
            return ""
        norm = unicodedata.normalize("NFKC", text)
        return " ".join(norm.lower().split())

    @classmethod
    def audit_field(
        cls,
        field: Optional[BusinessEvidenceField],
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

        # 2. Whitespace-collapsed match
        clean_page = re.sub(r"\s+", " ", norm_page)
        clean_ev = re.sub(r"\s+", " ", norm_ev)
        if clean_ev in clean_page:
            return GroundingAuditResult("VERIFIED", field_name, "Evidence verified on source page.", field.value_raw, field.page)

        punc_page = re.sub(r"[^\w\s]", "", clean_page)
        punc_ev = re.sub(r"[^\w\s]", "", clean_ev)
        if punc_ev in punc_page:
            return GroundingAuditResult("VERIFIED", field_name, "Evidence verified on source page.", field.value_raw, field.page)

        # 3. Table / Cell / Token grounding
        clean_val = re.sub(r"\s+", " ", norm_val)
        punc_val = re.sub(r"[^\w\s]", "", clean_val).strip()

        val_found = (
            clean_val in clean_page
            or (punc_val and punc_val in punc_page)
            or any(part in clean_page for part in clean_val.split() if len(part) >= 4)
        )

        if not val_found:
            return GroundingAuditResult(
                "REJECTED",
                field_name,
                f"Value '{field.value_raw}' not found on page {field.page}.",
                field.value_raw,
                field.page,
            )

        # Token overlap verification on evidence snippet
        ev_tokens = [w for w in re.findall(r"\w+", clean_ev) if len(w) > 1 and not w.isdigit()]
        if ev_tokens:
            matched_tokens = sum(1 for tok in ev_tokens if tok in clean_page)
            if matched_tokens / len(ev_tokens) < 0.5:
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
        extraction: BusinessDocumentExtraction,
        pages_text: Dict[int, str],
        page_count: int,
    ) -> Dict[str, GroundingAuditResult]:
        """Audits every individual non-null fact extracted across document and entities."""
        results: Dict[str, GroundingAuditResult] = {}

        # 1. Document-level fields
        doc_fields = [
            ("identity.company_name", extraction.company_name),
            ("identity.tax_code", extraction.tax_code),
            ("section_c.established_year", extraction.established_year),
            ("section_c.history_narrative", extraction.history_narrative),
            ("section_c.parent_company_or_owner", extraction.parent_company_or_owner),
            ("section_c.operating_model_description", extraction.operating_model_description),
            ("section_c.production_technology_summary", extraction.production_technology_summary),
            ("section_c.raw_materials_overview", extraction.raw_materials_overview),
            ("section_c.distribution_channels", extraction.distribution_channels),
            ("section_c.market_share_claim", extraction.market_share_claim),
            ("section_c.competitive_advantages_claim", extraction.competitive_advantages_claim),
        ]
        for cpath, fld in doc_fields:
            if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                results[cpath] = cls.audit_field(fld, cpath, pages_text, page_count)

        # 2. Capital Milestones
        for idx, m in enumerate(extraction.capital_milestones, start=1):
            prefix = f"section_c.capital_milestones[{idx}]"
            items = [
                (f"{prefix}.effective_date", m.effective_date),
                (f"{prefix}.charter_capital", m.charter_capital_raw),
                (f"{prefix}.event_description", m.event_description),
            ]
            for fpath, fld in items:
                if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                    results[fpath] = cls.audit_field(fld, fpath, pages_text, page_count)

        # 3. Shareholders
        for idx, s in enumerate(extraction.shareholders, start=1):
            prefix = f"section_c.shareholders[{idx}]"
            items = [
                (f"{prefix}.shareholder_name", s.shareholder_name),
                (f"{prefix}.id_tax_code", s.id_tax_code),
                (f"{prefix}.ownership_percentage", s.ownership_percentage_raw),
                (f"{prefix}.contributed_capital", s.contributed_capital_raw),
                (f"{prefix}.shareholder_type", s.shareholder_type),
            ]
            for fpath, fld in items:
                if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                    results[fpath] = cls.audit_field(fld, fpath, pages_text, page_count)

        # 4. Management
        for idx, m in enumerate(extraction.management, start=1):
            prefix = f"section_c.management[{idx}]"
            items = [
                (f"{prefix}.full_name", m.full_name),
                (f"{prefix}.position", m.position),
                (f"{prefix}.career_history", m.career_history_raw),
                (f"{prefix}.explicit_experience_years", m.explicit_experience_years_raw),
                (f"{prefix}.profile_summary", m.profile_summary),
            ]
            for fpath, fld in items:
                if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                    results[fpath] = cls.audit_field(fld, fpath, pages_text, page_count)

        # 5. Products
        for idx, p in enumerate(extraction.products, start=1):
            prefix = f"section_c.products[{idx}]"
            items = [
                (f"{prefix}.product_name", p.product_name),
                (f"{prefix}.brand_or_spec", p.brand_or_spec),
                (f"{prefix}.revenue_share_percentage", p.revenue_share_percentage_raw),
            ]
            for fpath, fld in items:
                if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                    results[fpath] = cls.audit_field(fld, fpath, pages_text, page_count)

        # 6. Warehouses
        for idx, w in enumerate(extraction.warehouses, start=1):
            prefix = f"section_c.warehouses[{idx}]"
            items = [
                (f"{prefix}.facility_type", w.facility_type),
                (f"{prefix}.address", w.address),
                (f"{prefix}.area", w.area_raw),
                (f"{prefix}.ownership_type", w.ownership_type),
                (f"{prefix}.capacity_description", w.capacity_description),
            ]
            for fpath, fld in items:
                if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                    results[fpath] = cls.audit_field(fld, fpath, pages_text, page_count)

        # 7. Equipments
        for idx, eq in enumerate(extraction.equipments, start=1):
            prefix = f"section_c.equipments[{idx}]"
            items = [
                (f"{prefix}.equipment_name", eq.equipment_name),
                (f"{prefix}.origin_and_technology", eq.origin_and_technology),
                (f"{prefix}.designed_capacity", eq.designed_capacity),
                (f"{prefix}.utilization_rate", eq.utilization_rate),
            ]
            for fpath, fld in items:
                if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                    results[fpath] = cls.audit_field(fld, fpath, pages_text, page_count)

        # 8. Suppliers
        for idx, s in enumerate(extraction.suppliers, start=1):
            prefix = f"section_c.suppliers[{idx}]"
            items = [
                (f"{prefix}.supplier_name", s.supplier_name),
                (f"{prefix}.supplied_goods", s.supplied_goods),
                (f"{prefix}.purchase_share_percentage", s.purchase_share_percentage_raw),
                (f"{prefix}.payment_terms", s.payment_terms),
            ]
            for fpath, fld in items:
                if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                    results[fpath] = cls.audit_field(fld, fpath, pages_text, page_count)

        # 9. Customers
        for idx, c in enumerate(extraction.customers, start=1):
            prefix = f"section_c.customers[{idx}]"
            items = [
                (f"{prefix}.customer_name", c.customer_name),
                (f"{prefix}.product_purchased", c.product_purchased),
                (f"{prefix}.revenue_share_percentage", c.revenue_share_percentage_raw),
                (f"{prefix}.credit_terms", c.credit_terms),
            ]
            for fpath, fld in items:
                if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                    results[fpath] = cls.audit_field(fld, fpath, pages_text, page_count)

        # 10. Competitors
        for idx, comp in enumerate(extraction.competitors, start=1):
            prefix = f"section_c.competitors[{idx}]"
            items = [
                (f"{prefix}.competitor_name", comp.competitor_name),
                (f"{prefix}.noted_strengths_or_share", comp.noted_strengths_or_share),
            ]
            for fpath, fld in items:
                if fld and fld.value_raw is not None and str(fld.value_raw).strip():
                    results[fpath] = cls.audit_field(fld, fpath, pages_text, page_count)

        return results


# ==============================================================================
# 3. IDENTITY RECONCILIATION
# ==============================================================================

class BusinessIdentityReconciler:
    """Verifies that business document belongs to the active case customer.
    
    Hard Rule: Never writes to customer canonical identity fields.
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

        if norm_case_tc and norm_ext_tc:
            if norm_ext_tc != norm_case_tc:
                return (
                    "MISMATCH",
                    f"CẢNH BÁO XUNG ĐỘT DANH TÍNH: Mã số thuế trên tài liệu ({norm_ext_tc}) KHÔNG TRÙNG KHỚP với hồ sơ khách hàng ({norm_case_tc})!",
                )
            # If tax code matches identically, verify name is not completely contradictory
            norm_ext_n = cls._norm_name(extracted_name or "")
            norm_case_n = cls._norm_name(case_name or "")
            if norm_case_n and norm_ext_n:
                ext_words = [w for w in norm_ext_n.split() if len(w) > 1]
                case_words = [w for w in norm_case_n.split() if len(w) > 1]
                common = set(ext_words).intersection(set(case_words))
                if not common and len(ext_words) > 0 and len(case_words) > 0:
                    return (
                        "WARNING",
                        f"Mã số thuế trùng khớp nhưng tên doanh nghiệp trên tài liệu ('{extracted_name}') có sự khác biệt lớn so với hồ sơ ('{case_name}').",
                    )
            return "MATCH", "Mã số thuế và tên doanh nghiệp trùng khớp với hồ sơ khách hàng."

        norm_ext_n = cls._norm_name(extracted_name or "")
        norm_case_n = cls._norm_name(case_name or "")

        if not norm_ext_tc and not norm_ext_n:
            return "WARNING", "Tài liệu không có Mã số thuế hoặc Tên công ty rõ ràng để đối soát danh tính."

        if norm_case_n and norm_ext_n:
            ext_words = [w for w in norm_ext_n.split() if len(w) > 1]
            case_words = [w for w in norm_case_n.split() if len(w) > 1]
            common = set(ext_words).intersection(set(case_words))
            if not common or len(common) / max(len(ext_words), 1) < 0.3:
                return (
                    "WARNING",
                    f"Tên doanh nghiệp trên tài liệu ('{extracted_name}') có sự khác biệt so với hồ sơ ('{case_name}').",
                )

        return "MATCH", "Định danh doanh nghiệp trên tài liệu trùng khớp với hồ sơ khách hàng."

    @staticmethod
    def _norm_name(name: str) -> str:
        norm = unicodedata.normalize("NFD", name)
        norm = "".join(c for c in norm if unicodedata.category(c) != "Mn").lower()
        norm = re.sub(r"\b(cong ty|co phan|ctcp|tnhh|cp|cty)\b", " ", norm)
        norm = re.sub(r"[^a-z0-9\s]", " ", norm)
        return " ".join(norm.split())


# ==============================================================================
# 4. BUSINESS MODEL CLASSIFIER (Python deterministic rule engine)
# ==============================================================================

class BusinessModelClassifier:
    """Proposes a BusinessModelType suggestion based on explicit extracted operating description.
    
    Rule: GLM must NOT choose the enum.
    Rule: Uses ONLY existing enum members: SAN_XUAT, THUONG_MAI, DICH_VU, HON_HOP.
    Rule: Ambiguous description -> None (requires RM selection).
    """

    @classmethod
    def suggest_model(cls, operating_description: Optional[str]) -> Optional[str]:
        if not operating_description or not operating_description.strip():
            return None

        desc = operating_description.lower()

        # Keywords
        mfg_keywords = ["sản xuất", "chế tạo", "nhà máy", "gia công", "lắp ráp", "chế biến"]
        trade_keywords = ["thương mại", "phân phối", "bán buôn", "bán lẻ", "nhập khẩu", "đại lý"]
        service_keywords = ["dịch vụ", "kho vận", "logistics", "vận tải", "tư vấn", "cho thuê"]

        has_mfg = any(k in desc for k in mfg_keywords)
        has_trade = any(k in desc for k in trade_keywords)
        has_service = any(k in desc for k in service_keywords)

        if has_mfg and (has_trade or has_service):
            return "HON_HOP"
        if has_mfg:
            return "SAN_XUAT"
        if has_trade:
            return "THUONG_MAI"
        if has_service:
            return "DICH_VU"

        return None


# ==============================================================================
# 5. GREENNODE DOCUMENT EXTRACTOR ORCHESTRATOR
# ==============================================================================

BUSINESS_EXTRACTION_SYSTEM_PROMPT = """Bạn là Chuyên viên Phân tích Dữ liệu Hồ sơ Doanh nghiệp (Business & Operations Specialist) của Khối Khách hàng Doanh nghiệp MSB.
Nhiệm vụ của bạn là đọc hiểu và trích xuất CÁC SỰ THẬT NGUỒN (SOURCE_FACT) và TUYÊN BỐ CỦA DOANH NGHIỆP (SOURCE_CLAIM) từ các tài liệu doanh nghiệp (Hồ sơ năng lực, Điều lệ, Báo cáo thường niên, Danh sách cổ đông/ban lãnh đạo, Danh mục nhà cung cấp, khách hàng...).

BẮT BUỘC TUÂN THỦ CÁC QUY TẮC NGHIỆP VỤ SAU:
1. NGUYÊN TẮC BẢO ĐẢM NGUỒN (NO EVIDENCE -> NO FACT):
   - Mọi trường dữ liệu không-null BẮT BUỘC phải kèm theo:
     * `value_raw`: Chuỗi ký tự nguyên bản trong tài liệu.
     * `semantic_label`: Nhãn/tiêu đề cột của trường thông tin.
     * `evidence`: Câu văn hoặc cụm từ ngắn gọn (tối đa 120 ký tự) chứa sự thật trong tài liệu. KHÔNG trích sao chép toàn bộ đoạn văn dài.
     * `page`: Số trang vật lý (1-indexed) nơi xuất hiện dữ liệu.
   - Nếu tài liệu không đề cập trường nào: BẮT BUỘC trả về null hoặc mảng rỗng `[]`. TUYỆT ĐỐI KHÔNG BỊA ĐẶT.

2. CƠ CẤU THỰC THỂ (ENTITY GRANULARITY):
   - Trích xuất từng phần tử độc lập:
     * `capital_milestones`: Từng mốc thời gian tăng vốn. Giữ nguyên độ chính xác thời gian (nếu chỉ ghi "2020", ghi "2020", không tự điền "01/01/2020").
     * `shareholders`: Từng cổ đông/thành viên góp vốn. Trích xuất độc lập tên, MST/CCCD, tỷ lệ sở hữu %, giá trị vốn góp (nếu có ghi).
     * `management`: Từng thành viên ban lãnh đạo. Trích xuất tên, chức vụ, tóm tắt lý lịch/kinh nghiệm.
       LƯU Ý: Chỉ trích xuất số năm kinh nghiệm vào `explicit_experience_years_raw` khi văn bản GHI RÕ BẰNG CHỮ/SỐ (vd: "15 năm kinh nghiệm"). Nếu chỉ ghi các mốc năm công tác (vd: 2012-2018...), để `explicit_experience_years_raw: null`, trích xuất lịch sử vào `career_history_raw`. KHÔNG ĐƯỢC TỰ TÍNH TOÁN SỐ NĂM.
     * `products`: Từng sản phẩm/nhóm sản phẩm chính kèm quy cách/thương hiệu và tỷ trọng doanh thu (nếu có ghi).
     * `warehouses`: Từng kho bãi, nhà xưởng (loại cơ sở, địa chỉ, diện tích m2, hình thức sở hữu, công suất).
     * `equipments`: Từng máy móc thiết bị chính (tên, xuất xứ/công nghệ, công suất thiết kế, hiệu suất).
     * `suppliers`: Từng nhà cung cấp chính (tên, mặt hàng, tỷ trọng mua %, điều khoản thanh toán).
     * `customers`: Từng khách hàng đầu ra chính (tên, sản phẩm cung cấp, tỷ trọng doanh thu %, chính sách công nợ).
     * `competitors`: Từng đối thủ cạnh tranh chính.

3. TUYÊN BỐ NGUỒN (SOURCE CLAIM) VÀ MÔ HÌNH HOẠT ĐỘNG:
   - `operating_model_description`: Trích xuất đoạn văn mô tả mô hình hoạt động kinh doanh, vận hành sản xuất/thương mại của doanh nghiệp. KHÔNG ĐƯỢC TỰ CHỌN ENUM.
   - `market_share_claim`: Trích xuất nguyên văn tuyên bố về thị phần của doanh nghiệp nếu có (vd: "Chiếm 25% thị phần phân phối...").
   - `competitive_advantages_claim`: Trích xuất nguyên văn tuyên bố về lợi thế cạnh tranh của doanh nghiệp nếu có.

4. ĐỊNH DẠNG ĐẦU RA:
   - Trả về DUY NHẤT một khối JSON hợp lệ tuân thủ schema dưới đây.
   - KHÔNG bọc thêm lời giải thích hay markdown thừa ngoài ```json ... ```.

Schema mẫu:
```json
{
  "company_name": {"value_raw": "CÔNG TY CP...", "semantic_label": "Tên công ty", "evidence": "Tên công ty: CÔNG TY...", "page": 1},
  "tax_code": {"value_raw": "0108889999", "semantic_label": "Mã số thuế", "evidence": "Mã số thuế: 0108889999", "page": 1},
  "established_year": {"value_raw": "2010", "semantic_label": "Năm thành lập", "evidence": "Thành lập năm 2010...", "page": 1},
  "history_narrative": {"value_raw": "Thành lập năm 2010 tiền thân là...", "semantic_label": "Quá trình hình thành", "evidence": "Thành lập năm 2010 tiền thân là...", "page": 1},
  "capital_milestones": [
    {
      "effective_date": {"value_raw": "2020", "semantic_label": "Thời điểm", "evidence": "Năm 2020 tăng vốn...", "page": 1},
      "charter_capital_raw": {"value_raw": "100.000.000.000", "semantic_label": "Vốn điều lệ", "evidence": "đạt 100 tỷ đồng", "page": 1},
      "event_description": {"value_raw": "Phát hành cho cổ đông hiện hữu", "semantic_label": "Sự kiện", "evidence": "phát hành cho cổ đông...", "page": 1},
      "page": 1
    }
  ],
  "parent_company_or_owner": {"value_raw": "Tập đoàn ABC", "semantic_label": "Công ty mẹ", "evidence": "thuộc Tập đoàn ABC", "page": 1},
  "shareholders": [
    {
      "shareholder_name": {"value_raw": "Nguyễn Văn A", "semantic_label": "Tên cổ đông", "evidence": "Nguyễn Văn A sở hữu 55%", "page": 1},
      "id_tax_code": {"value_raw": "001085012345", "semantic_label": "CCCD", "evidence": "CCCD: 001085012345", "page": 1},
      "ownership_percentage_raw": {"value_raw": "55%", "semantic_label": "Tỷ lệ", "evidence": "sở hữu 55%", "page": 1},
      "contributed_capital_raw": {"value_raw": "55.000.000.000", "semantic_label": "Vốn góp", "evidence": "vốn góp 55 tỷ VND", "page": 1},
      "shareholder_type": {"value_raw": "Cá nhân", "semantic_label": "Loại cổ đông", "evidence": "Cổ đông cá nhân", "page": 1},
      "page": 1
    }
  ],
  "management": [
    {
      "full_name": {"value_raw": "Trần Văn B", "semantic_label": "Họ và tên", "evidence": "Tổng Giám đốc: Trần Văn B", "page": 2},
      "position": {"value_raw": "Tổng Giám đốc", "semantic_label": "Chức vụ", "evidence": "Tổng Giám đốc", "page": 2},
      "career_history_raw": {"value_raw": "2015-2020: Giám đốc Kinh doanh", "semantic_label": "Lịch sử công tác", "evidence": "2015-2020: Giám đốc Kinh doanh", "page": 2},
      "explicit_experience_years_raw": {"value_raw": "15", "semantic_label": "Số năm kinh nghiệm", "evidence": "Hơn 15 năm kinh nghiệm trong ngành", "page": 2},
      "profile_summary": {"value_raw": "Kỹ sư CNTT, hơn 15 năm kinh nghiệm", "semantic_label": "Tóm tắt lý lịch", "evidence": "Kỹ sư CNTT, hơn 15 năm...", "page": 2},
      "page": 2
    }
  ],
  "operating_model_description": {"value_raw": "Doanh nghiệp hoạt động theo mô hình sản xuất và phân phối thiết bị công nghệ...", "semantic_label": "Mô hình vận hành", "evidence": "hoạt động theo mô hình...", "page": 2},
  "products": [
    {
      "product_name": {"value_raw": "Gateway IoT", "semantic_label": "Sản phẩm", "evidence": "Gateway IoT", "page": 1},
      "brand_or_spec": {"value_raw": "Chuẩn IP67", "semantic_label": "Quy cách", "evidence": "Chuẩn IP67", "page": 1},
      "revenue_share_percentage_raw": {"value_raw": "45.0%", "semantic_label": "Tỷ trọng doanh thu", "evidence": "Tỷ trọng doanh thu: 45.0%", "page": 1},
      "page": 1
    }
  ],
  "production_technology_summary": {"value_raw": "Dây chuyền gắn chip SMT tự động", "semantic_label": "Công nghệ", "evidence": "Dây chuyền...", "page": 1},
  "warehouses": [
    {
      "facility_type": {"value_raw": "Nhà máy", "semantic_label": "Loại cơ sở", "evidence": "Nhà máy", "page": 1},
      "address": {"value_raw": "KCN Cao Hòa Lạc", "semantic_label": "Địa chỉ", "evidence": "KCN Cao Hòa Lạc", "page": 1},
      "area_raw": {"value_raw": "3.500", "semantic_label": "Diện tích", "evidence": "3.500 m2", "page": 1},
      "ownership_type": {"value_raw": "Thuê dài hạn", "semantic_label": "Hình thức", "evidence": "Thuê dài hạn", "page": 1},
      "capacity_description": {"value_raw": "50.000 sp/năm", "semantic_label": "Công suất", "evidence": "50.000 sp/năm", "page": 1},
      "page": 1
    }
  ],
  "equipments": [
    {
      "equipment_name": {"value_raw": "Dây chuyền SMT", "semantic_label": "Thiết bị", "evidence": "Dây chuyền SMT", "page": 1},
      "origin_and_technology": {"value_raw": "Nhật Bản - Yamaha", "semantic_label": "Xuất xứ", "evidence": "Yamaha", "page": 1},
      "designed_capacity": {"value_raw": "50.000 sp/năm", "semantic_label": "Công suất", "evidence": "50.000 sp/năm", "page": 1},
      "utilization_rate": {"value_raw": "92%", "semantic_label": "Hiệu suất", "evidence": "92%", "page": 1},
      "page": 1
    }
  ],
  "raw_materials_overview": {"value_raw": "Linh kiện điện tử, vi mạch...", "semantic_label": "Nguyên vật liệu", "evidence": "Linh kiện...", "page": 1},
  "suppliers": [
    {
      "supplier_name": {"value_raw": "Qualcomm", "semantic_label": "Tên NCC", "evidence": "Qualcomm", "page": 1},
      "supplied_goods": {"value_raw": "Chipset 4G", "semantic_label": "Mặt hàng", "evidence": "Chipset 4G", "page": 1},
      "purchase_share_percentage_raw": {"value_raw": "32.0%", "semantic_label": "Tỷ trọng", "evidence": "32.0%", "page": 1},
      "payment_terms": {"value_raw": "L/C 60 ngày", "semantic_label": "Điều khoản", "evidence": "L/C 60 ngày", "page": 1},
      "page": 1
    }
  ],
  "distribution_channels": {"value_raw": "Phân phối trực tiếp...", "semantic_label": "Kênh phân phối", "evidence": "Trực tiếp...", "page": 1},
  "customers": [
    {
      "customer_name": {"value_raw": "Tập đoàn Viettel", "semantic_label": "Khách hàng", "evidence": "Viettel", "page": 1},
      "product_purchased": {"value_raw": "Thiết bị Gateway IoT", "semantic_label": "Sản phẩm", "evidence": "Gateway IoT", "page": 1},
      "revenue_share_percentage_raw": {"value_raw": "34.5%", "semantic_label": "Tỷ trọng", "evidence": "34.5%", "page": 1},
      "credit_terms": {"value_raw": "Bảo lãnh 45 ngày", "semantic_label": "Công nợ", "evidence": "Bảo lãnh 45 ngày", "page": 1},
      "page": 1
    }
  ],
  "market_share_claim": {"value_raw": "Chiếm 25% thị phần", "semantic_label": "Thị phần", "evidence": "Chiếm 25% thị phần", "page": 1},
  "competitors": [
    {
      "competitor_name": {"value_raw": "Công ty X", "semantic_label": "Đối thủ", "evidence": "Công ty X", "page": 1},
      "noted_strengths_or_share": {"value_raw": "Mạnh về giá", "semantic_label": "Thế mạnh", "evidence": "Mạnh về giá", "page": 1},
      "page": 1
    }
  ],
  "competitive_advantages_claim": {"value_raw": "Sở hữu bản quyền công nghệ lõi", "semantic_label": "Lợi thế", "evidence": "Bản quyền công nghệ lõi", "page": 1}
}
```
"""


class BusinessDocumentExtractor:
    """Orchestrates GreenNode Business document extraction with grounding verification."""

    def __init__(self, ai_client: Optional[Any] = None):
        self.ai_client = ai_client

    def extract(self, tagged_text: str, page_count: int, api_key: Optional[str] = None) -> BusinessDocumentExtraction:
        user_prompt = f"""Hãy đọc kỹ toàn bộ văn bản Hồ sơ Hoạt động Doanh nghiệp dưới đây (đã phân chia theo thẻ [PAGE X]):

{tagged_text}

Trích xuất toàn bộ các sự thật nguồn về lịch sử, mốc vốn, chủ sở hữu, cổ đông, ban điều hành, mô hình vận hành, sản phẩm, kho bãi, máy móc, nhà cung cấp, khách hàng, kênh phân phối, đối thủ và các tuyên bố về thị phần/lợi thế cạnh tranh theo đúng hướng dẫn hệ thống. Bắt buộc trả về JSON hợp lệ."""

        if self.ai_client and hasattr(self.ai_client, "chat"):
            resp_text = self.ai_client.chat(
                system_prompt=BUSINESS_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=8192,
                api_key=api_key,
                operation="business_extraction",
            )
        else:
            resp_text = AIAssistantClient.chat(
                system_prompt=BUSINESS_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=8192,
                api_key=api_key,
                operation="business_extraction",
            )

        cleaned_json = resp_text.strip()
        json_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", cleaned_json)
        if json_match:
            cleaned_json = json_match.group(1).strip()
        elif cleaned_json.startswith("```"):
            cleaned_json = re.sub(r"^```(?:json)?\s*", "", cleaned_json)
            cleaned_json = re.sub(r"\s*```$", "", cleaned_json)

        try:
            raw_dict = json.loads(cleaned_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"GreenNode returned invalid JSON for Business extraction: {e}\nRaw: {resp_text[:300]}")

        return BusinessDocumentExtraction.model_validate(raw_dict)
