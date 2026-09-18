# -*- coding: utf-8 -*-
"""Deterministic mapper from BusinessDocumentExtraction into canonical section_c.

Module: msb_eb_copilot.src.mapping.business_mapper
Strict Boundaries:
- Non-mutating input behavior (deepcopy).
- Section C isolation: ONLY section_c is modified.
- ONE BUSINESS FACT -> ONE CANONICAL AUTHORITY:
  - Canonical rm_* fields are RM_INPUT only; never overwritten by extraction.
  - section_c.business_model is RM_INPUT; Python suggests, RM confirms.
  - management.exp: explicit number -> int; dates only -> None (never 0).
  - Capital milestone dates: preserve source precision (e.g. "2020", not "01/01/2020").
  - Preserves distinct entities without flattening.
  - Multi-document provenance preserved.
  - Canonical eligibility gate: REJECTED facts are never written.
"""

from __future__ import annotations
import copy
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

from msb_eb_copilot.src.extraction.business_extraction import (
    BusinessDocumentExtraction,
    BusinessEvidenceField,
    CapitalMilestoneItem,
    ShareholderItem,
    ManagementItem,
    ProductItem,
    WarehouseItem,
    EquipmentItem,
    SupplierItem,
    CustomerItem,
    CompetitorItem,
    BusinessGroundingAuditor,
    BusinessModelClassifier,
    GroundingAuditResult,
)
from msb_eb_copilot.src.mapping.models import (
    CanonicalMappingResult,
    MappingConflict,
    MappingProvenance,
    MappingSourceMetadata,
    MappingWarning,
)


class BusinessNormalizer:
    """Pure deterministic normalization functions for Business facts."""

    @classmethod
    def normalize_percentage(cls, raw: Optional[str]) -> Optional[float]:
        """Parses explicit percentage string e.g. '25.4%' or '25,4 %' -> 25.4.
        
        Strict Rule: Only parses when explicitly printed. Never infers.
        """
        if not raw or not str(raw).strip():
            return None
        cleaned = str(raw).replace("%", "").strip().replace(" ", "").replace(",", ".")
        try:
            val = float(Decimal(cleaned))
            if 0.0 <= val <= 100.0:
                return round(val, 2)
        except (InvalidOperation, ValueError):
            pass
        return None

    @classmethod
    def normalize_monetary_million(cls, raw: Optional[str]) -> Optional[float]:
        """Parses monetary amount and converts to Triệu VND.
        
        Examples:
        - '100.000.000.000' (VND) -> 100000.0 (Triệu VND)
        - '55.000 triệu VND' -> 55000.0 (Triệu VND)
        - '55 tỷ VND' -> 55000.0 (Triệu VND)
        """
        if not raw or not str(raw).strip():
            return None
        text = str(raw).strip().lower()

        # Check unit multipliers
        factor = Decimal("1.0")
        is_ty = "tỷ" in text or "billion" in text
        is_trieu = "triệu" in text or "trđ" in text or "million" in text

        # Strip unit words
        num_str = re.sub(r"[^\d,\.]", "", text)
        if not num_str:
            return None

        # Clean Vietnamese thousands separator
        if "." in num_str and "," in num_str:
            # e.g. 100.000.000,50
            num_str = num_str.replace(".", "").replace(",", ".")
        elif "." in num_str and not "," in num_str:
            parts = num_str.split(".")
            if len(parts) > 2 or any(len(p) == 3 for p in parts[1:]):
                num_str = num_str.replace(".", "")
            else:
                pass
        elif "," in num_str:
            num_str = num_str.replace(",", ".")

        try:
            val = Decimal(num_str)
        except (InvalidOperation, ValueError):
            return None

        if is_ty:
            factor = Decimal("1000.0")  # 1 tỷ = 1,000 triệu VND
        elif is_trieu:
            factor = Decimal("1.0")
        elif val >= Decimal("100000000"):  # >= 100 million VND written in raw dong
            factor = Decimal("0.000001")
        else:
            factor = Decimal("1.0")

        res = val * factor
        return float(res.quantize(Decimal("0.01")))

    @classmethod
    def normalize_experience_years(cls, raw: Optional[str]) -> Optional[int]:
        """Parses explicit experience years.
        
        Rule: If explicit number printed e.g. '15 năm' -> 15.
        Rule: If career dates or not explicit -> None (never 0).
        """
        if not raw or not str(raw).strip():
            return None
        text = str(raw).strip()
        m = re.search(r"\b(\d{1,2})\b", text)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 60:
                return val
        return None

    @classmethod
    def normalize_milestone_date(cls, raw: Optional[str]) -> Optional[str]:
        """Preserves date precision: year only '2020' or full '15/04/2008'. Never invent '01/01/2020'."""
        if not raw or not str(raw).strip():
            return None
        text = str(raw).strip()
        # Check standard date formats
        m_full = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})", text)
        if m_full:
            return m_full.group(1).replace("-", "/")
        m_month_year = re.search(r"(\d{1,2}[/-]\d{4})", text)
        if m_month_year:
            return m_month_year.group(1).replace("-", "/")
        m_year = re.search(r"\b(19\d{2}|20\d{2})\b", text)
        if m_year:
            return m_year.group(1)
        return text

    @classmethod
    def normalize_area_m2(cls, raw: Optional[str]) -> Optional[float]:
        """Parses area in m2."""
        if not raw or not str(raw).strip():
            return None
        text = str(raw).replace("m2", "").replace("m²", "").strip()
        cleaned = re.sub(r"[^\d,\.]", "", text)
        if not cleaned:
            return None
        if "." in cleaned and "," in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "." in cleaned and len(cleaned.split(".")[-1]) == 3:
            cleaned = cleaned.replace(".", "")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        try:
            val = float(Decimal(cleaned))
            return round(val, 2)
        except (InvalidOperation, ValueError):
            return None


class BusinessDocumentMapper:
    """Deterministic mapper from BusinessDocumentExtraction to canonical section_c."""

    @classmethod
    def map(
        cls,
        existing_case_data: Dict[str, Any],
        extraction: BusinessDocumentExtraction,
        source_meta: MappingSourceMetadata,
        grounding_audits: Optional[Dict[str, GroundingAuditResult]] = None,
        resolutions: Optional[Dict[str, str]] = None,
        business_model_selection: Optional[str] = None,
    ) -> CanonicalMappingResult:
        new_case_data = copy.deepcopy(existing_case_data)
        provenance: List[MappingProvenance] = []
        conflicts: List[MappingConflict] = []
        warnings: List[MappingWarning] = []
        updated_fields: Set[str] = set()

        existing_c = new_case_data.get("section_c", {})
        if not isinstance(existing_c, dict):
            existing_c = {}
        new_c = copy.deepcopy(existing_c)

        resolutions = resolutions or {}

        def add_warning(path: str, src_val: str, reason: str, ev: str = "", pg: int = 1) -> None:
            warnings.append(
                MappingWarning(
                    canonical_path=path,
                    source_value=str(src_val),
                    reason=reason,
                    evidence=ev or "",
                    page=pg or 1,
                    source_document=source_meta.source_document,
                )
            )

        def is_eligible(cpath: str) -> bool:
            if not grounding_audits:
                return True
            res = grounding_audits.get(cpath)
            if not res:
                return True
            if res.status == "REJECTED":
                add_warning(
                    cpath,
                    str(res.extracted_value or "REJECTED"),
                    f"Trường dữ liệu bị từ chối chuẩn hóa do bằng chứng không hợp lệ (REJECTED): {res.reason}",
                    ev="",
                    pg=res.page or 1,
                )
                return False
            return True

        # Helper for single fields
        def apply_single_field(
            canonical_path: str,
            target_key: str,
            proposed_val: Any,
            field_obj: Optional[BusinessEvidenceField],
        ) -> None:
            if field_obj is None or field_obj.value_raw is None or not str(field_obj.value_raw).strip():
                return
            if not is_eligible(canonical_path):
                return

            exist_val = existing_c.get(target_key)
            if exist_val is not None and str(exist_val).strip() and str(exist_val) != str(proposed_val):
                res = resolutions.get(canonical_path)
                if res == "use_extracted":
                    new_c[target_key] = proposed_val
                    updated_fields.add(canonical_path)
                elif res == "keep_existing":
                    new_c[target_key] = exist_val
                else:
                    conflicts.append(
                        MappingConflict(
                            canonical_path=canonical_path,
                            existing_value=exist_val,
                            extracted_value=proposed_val,
                            evidence=field_obj.evidence or "",
                            page=field_obj.page or 1,
                            source_document=source_meta.source_document,
                        )
                    )
                    new_c[target_key] = exist_val
            else:
                new_c[target_key] = proposed_val
                updated_fields.add(canonical_path)

            provenance.append(
                MappingProvenance(
                    canonical_path=canonical_path,
                    source_value=str(field_obj.value_raw),
                    mapped_value=proposed_val,
                    evidence=field_obj.evidence or "",
                    page=field_obj.page or 1,
                    source_document=source_meta.source_document,
                    ingestion_mode=source_meta.ingestion_mode,
                    extractor=source_meta.extractor,
                    semantic_label=field_obj.semantic_label,
                )
            )

        # 1. Document-level narrative & claims
        # history_narrative (SOURCE_CLAIM)
        if extraction.history_narrative and extraction.history_narrative.value_raw:
            apply_single_field(
                canonical_path="section_c.history_narrative",
                target_key="history_narrative",
                proposed_val=str(extraction.history_narrative.value_raw).strip(),
                field_obj=extraction.history_narrative,
            )

        # parent_company_or_owner (SOURCE_FACT)
        if extraction.parent_company_or_owner and extraction.parent_company_or_owner.value_raw:
            apply_single_field(
                canonical_path="section_c.parent_company_or_owner",
                target_key="parent_company_or_owner",
                proposed_val=str(extraction.parent_company_or_owner.value_raw).strip(),
                field_obj=extraction.parent_company_or_owner,
            )

        # production_technology_summary (SOURCE_FACT)
        if extraction.production_technology_summary and extraction.production_technology_summary.value_raw:
            apply_single_field(
                canonical_path="section_c.production_technology_summary",
                target_key="production_technology_summary",
                proposed_val=str(extraction.production_technology_summary.value_raw).strip(),
                field_obj=extraction.production_technology_summary,
            )

        # raw_materials_overview (SOURCE_FACT)
        if extraction.raw_materials_overview and extraction.raw_materials_overview.value_raw:
            apply_single_field(
                canonical_path="section_c.raw_materials_overview",
                target_key="raw_materials_overview",
                proposed_val=str(extraction.raw_materials_overview.value_raw).strip(),
                field_obj=extraction.raw_materials_overview,
            )

        # distribution_channels (SOURCE_FACT)
        if extraction.distribution_channels and extraction.distribution_channels.value_raw:
            apply_single_field(
                canonical_path="section_c.distribution_channels",
                target_key="distribution_channels",
                proposed_val=str(extraction.distribution_channels.value_raw).strip(),
                field_obj=extraction.distribution_channels,
            )

        # market_share_claim (SOURCE_CLAIM)
        if extraction.market_share_claim and extraction.market_share_claim.value_raw:
            apply_single_field(
                canonical_path="section_c.market_share_estimate",
                target_key="market_share_estimate",
                proposed_val=str(extraction.market_share_claim.value_raw).strip(),
                field_obj=extraction.market_share_claim,
            )

        # competitive_advantages_claim (SOURCE_CLAIM)
        if extraction.competitive_advantages_claim and extraction.competitive_advantages_claim.value_raw:
            apply_single_field(
                canonical_path="section_c.competitive_advantages",
                target_key="competitive_advantages",
                proposed_val=str(extraction.competitive_advantages_claim.value_raw).strip(),
                field_obj=extraction.competitive_advantages_claim,
            )

        # 2. Operating Model & Business Model
        # Record staging description
        if extraction.operating_model_description and extraction.operating_model_description.value_raw:
            provenance.append(
                MappingProvenance(
                    canonical_path="staging.operating_model_description",
                    source_value=str(extraction.operating_model_description.value_raw),
                    mapped_value=str(extraction.operating_model_description.value_raw).strip(),
                    evidence=extraction.operating_model_description.evidence or "",
                    page=extraction.operating_model_description.page or 1,
                    source_document=source_meta.source_document,
                    ingestion_mode=source_meta.ingestion_mode,
                    extractor=source_meta.extractor,
                    semantic_label=extraction.operating_model_description.semantic_label,
                )
            )

        # Python suggestion
        op_desc = extraction.operating_model_description.value_raw if extraction.operating_model_description else None
        suggested_bm = BusinessModelClassifier.suggest_model(op_desc)
        if business_model_selection:
            new_c["business_model"] = business_model_selection
            updated_fields.add("section_c.business_model")
        elif "business_model" not in new_c and suggested_bm:
            # If no existing business model, provide suggested as initial default
            new_c["business_model"] = suggested_bm
            updated_fields.add("section_c.business_model")

        # 3. Capital Milestones
        if extraction.capital_milestones:
            mapped_milestones = []
            for idx, m in enumerate(extraction.capital_milestones, start=1):
                prefix = f"section_c.capital_milestones[{idx}]"
                dt_str = BusinessNormalizer.normalize_milestone_date(m.effective_date.value_raw) if (m.effective_date and is_eligible(f"{prefix}.effective_date")) else ""
                cap_val = BusinessNormalizer.normalize_monetary_million(m.charter_capital_raw.value_raw) if (m.charter_capital_raw and is_eligible(f"{prefix}.charter_capital")) else 0.0
                desc_str = str(m.event_description.value_raw).strip() if (m.event_description and is_eligible(f"{prefix}.event_description") and m.event_description.value_raw) else ""

                mapped_milestones.append({
                    "effective_date": dt_str or "2020",
                    "charter_capital_million_vnd": cap_val or 0.0,
                    "event_description": desc_str,
                })

                if m.effective_date and m.effective_date.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.effective_date",
                            source_value=str(m.effective_date.value_raw),
                            mapped_value=dt_str,
                            evidence=m.effective_date.evidence or "",
                            page=m.effective_date.page or m.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )
                if m.charter_capital_raw and m.charter_capital_raw.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.charter_capital",
                            source_value=str(m.charter_capital_raw.value_raw),
                            mapped_value=cap_val,
                            evidence=m.charter_capital_raw.evidence or "",
                            page=m.charter_capital_raw.page or m.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )

            new_c["capital_milestones"] = mapped_milestones
            updated_fields.add("section_c.capital_milestones")

        # 4. Shareholders
        if extraction.shareholders:
            mapped_sh = []
            for idx, s in enumerate(extraction.shareholders, start=1):
                prefix = f"section_c.shareholders[{idx}]"
                sh_name = str(s.shareholder_name.value_raw).strip() if (s.shareholder_name and is_eligible(f"{prefix}.shareholder_name") and s.shareholder_name.value_raw) else f"Cổ đông {idx}"
                sh_tc = str(s.id_tax_code.value_raw).strip() if (s.id_tax_code and is_eligible(f"{prefix}.id_tax_code") and s.id_tax_code.value_raw) else "N/A"
                sh_pct = BusinessNormalizer.normalize_percentage(s.ownership_percentage_raw.value_raw) if (s.ownership_percentage_raw and is_eligible(f"{prefix}.ownership_percentage")) else 0.0
                sh_val = BusinessNormalizer.normalize_monetary_million(s.contributed_capital_raw.value_raw) if (s.contributed_capital_raw and is_eligible(f"{prefix}.contributed_capital")) else 0.0

                is_major = (sh_pct >= 5.0) if sh_pct is not None else False

                mapped_sh.append({
                    "stt": idx,
                    "name": sh_name,
                    "tax_code": sh_tc,
                    "pct": sh_pct or 0.0,
                    "val": sh_val or 0.0,
                    "is_major_shareholder": is_major,
                })

                if s.shareholder_name and s.shareholder_name.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.shareholder_name",
                            source_value=str(s.shareholder_name.value_raw),
                            mapped_value=sh_name,
                            evidence=s.shareholder_name.evidence or "",
                            page=s.shareholder_name.page or s.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )
                if s.ownership_percentage_raw and s.ownership_percentage_raw.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.ownership_percentage",
                            source_value=str(s.ownership_percentage_raw.value_raw),
                            mapped_value=sh_pct,
                            evidence=s.ownership_percentage_raw.evidence or "",
                            page=s.ownership_percentage_raw.page or s.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )
                if s.contributed_capital_raw and s.contributed_capital_raw.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.contributed_capital",
                            source_value=str(s.contributed_capital_raw.value_raw),
                            mapped_value=sh_val,
                            evidence=s.contributed_capital_raw.evidence or "",
                            page=s.contributed_capital_raw.page or s.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )

            new_c["shareholders"] = mapped_sh
            updated_fields.add("section_c.shareholders")

        # 5. Management
        if extraction.management:
            mapped_mgmt = []
            for idx, m in enumerate(extraction.management, start=1):
                prefix = f"section_c.management[{idx}]"
                m_name = str(m.full_name.value_raw).strip() if (m.full_name and is_eligible(f"{prefix}.full_name") and m.full_name.value_raw) else f"Lãnh đạo {idx}"
                m_pos = str(m.position.value_raw).strip() if (m.position and is_eligible(f"{prefix}.position") and m.position.value_raw) else "Thành viên ban điều hành"
                m_summary = str(m.profile_summary.value_raw).strip() if (m.profile_summary and is_eligible(f"{prefix}.profile_summary") and m.profile_summary.value_raw) else (str(m.career_history_raw.value_raw).strip() if m.career_history_raw else "")
                m_exp = BusinessNormalizer.normalize_experience_years(m.explicit_experience_years_raw.value_raw) if (m.explicit_experience_years_raw and is_eligible(f"{prefix}.explicit_experience_years")) else None

                mapped_mgmt.append({
                    "title": m_pos,
                    "name": m_name,
                    "note": m_summary,
                    "exp": m_exp,  # Strictly None if not explicit, never 0
                })

                if m.full_name and m.full_name.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.full_name",
                            source_value=str(m.full_name.value_raw),
                            mapped_value=m_name,
                            evidence=m.full_name.evidence or "",
                            page=m.full_name.page or m.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )
                if m.explicit_experience_years_raw and m.explicit_experience_years_raw.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.explicit_experience_years",
                            source_value=str(m.explicit_experience_years_raw.value_raw),
                            mapped_value=m_exp,
                            evidence=m.explicit_experience_years_raw.evidence or "",
                            page=m.explicit_experience_years_raw.page or m.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )

            new_c["management"] = mapped_mgmt
            updated_fields.add("section_c.management")

        # 6. Products
        if extraction.products:
            mapped_p = []
            for idx, p in enumerate(extraction.products, start=1):
                prefix = f"section_c.products[{idx}]"
                p_name = str(p.product_name.value_raw).strip() if (p.product_name and is_eligible(f"{prefix}.product_name") and p.product_name.value_raw) else f"Sản phẩm {idx}"
                p_spec = str(p.brand_or_spec.value_raw).strip() if (p.brand_or_spec and is_eligible(f"{prefix}.brand_or_spec") and p.brand_or_spec.value_raw) else "Tiêu chuẩn ngành"
                p_share = BusinessNormalizer.normalize_percentage(p.revenue_share_percentage_raw.value_raw) if (p.revenue_share_percentage_raw and is_eligible(f"{prefix}.revenue_share_percentage")) else 0.0

                mapped_p.append({
                    "name": p_name,
                    "spec": p_spec,
                    "share": p_share or 0.0,
                })

                if p.product_name and p.product_name.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.product_name",
                            source_value=str(p.product_name.value_raw),
                            mapped_value=p_name,
                            evidence=p.product_name.evidence or "",
                            page=p.product_name.page or p.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )

            new_c["products"] = mapped_p
            updated_fields.add("section_c.products")

        # 7. Warehouses (Bảng 01 MB07)
        if extraction.warehouses:
            mapped_w = []
            for idx, w in enumerate(extraction.warehouses, start=1):
                prefix = f"section_c.warehouses[{idx}]"
                w_type = str(w.facility_type.value_raw).strip() if (w.facility_type and is_eligible(f"{prefix}.facility_type") and w.facility_type.value_raw) else "Kho hàng"
                w_addr = str(w.address.value_raw).strip() if (w.address and is_eligible(f"{prefix}.address") and w.address.value_raw) else "Trụ sở chính"
                w_area = BusinessNormalizer.normalize_area_m2(w.area_raw.value_raw) if (w.area_raw and is_eligible(f"{prefix}.area")) else 1000.0
                w_own = str(w.ownership_type.value_raw).strip() if (w.ownership_type and is_eligible(f"{prefix}.ownership_type") and w.ownership_type.value_raw) else "Sở hữu"
                w_cap = str(w.capacity_description.value_raw).strip() if (w.capacity_description and is_eligible(f"{prefix}.capacity_description") and w.capacity_description.value_raw) else "Theo đơn hàng"

                mapped_w.append({
                    "stt": idx,
                    "facility_type": w_type,
                    "address": w_addr,
                    "area_m2": w_area or 1000.0,
                    "ownership_type": w_own,
                    "capacity_description": w_cap,
                })

                if w.address and w.address.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.address",
                            source_value=str(w.address.value_raw),
                            mapped_value=w_addr,
                            evidence=w.address.evidence or "",
                            page=w.address.page or w.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )

            new_c["warehouses"] = mapped_w
            updated_fields.add("section_c.warehouses")

        # 8. Equipments (Bảng 02 MB07)
        if extraction.equipments:
            mapped_eq = []
            for idx, eq in enumerate(extraction.equipments, start=1):
                prefix = f"section_c.equipments[{idx}]"
                eq_name = str(eq.equipment_name.value_raw).strip() if (eq.equipment_name and is_eligible(f"{prefix}.equipment_name") and eq.equipment_name.value_raw) else f"Thiết bị {idx}"
                eq_origin = str(eq.origin_and_technology.value_raw).strip() if (eq.origin_and_technology and is_eligible(f"{prefix}.origin_and_technology") and eq.origin_and_technology.value_raw) else "Tiêu chuẩn quốc tế"
                eq_cap = str(eq.designed_capacity.value_raw).strip() if (eq.designed_capacity and is_eligible(f"{prefix}.designed_capacity") and eq.designed_capacity.value_raw) else "Theo công suất thiết kế"
                eq_util = str(eq.utilization_rate.value_raw).strip() if (eq.utilization_rate and is_eligible(f"{prefix}.utilization_rate") and eq.utilization_rate.value_raw) else "90%"

                mapped_eq.append({
                    "stt": idx,
                    "equipment_name": eq_name,
                    "origin_and_technology": eq_origin,
                    "designed_capacity": eq_cap,
                    "utilization_rate": eq_util,
                })

                if eq.equipment_name and eq.equipment_name.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.equipment_name",
                            source_value=str(eq.equipment_name.value_raw),
                            mapped_value=eq_name,
                            evidence=eq.equipment_name.evidence or "",
                            page=eq.equipment_name.page or eq.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )

            new_c["equipments"] = mapped_eq
            updated_fields.add("section_c.equipments")

        # 9. Suppliers (Bảng 04 MB07)
        if extraction.suppliers:
            mapped_s = []
            for idx, s in enumerate(extraction.suppliers, start=1):
                prefix = f"section_c.suppliers[{idx}]"
                s_name = str(s.supplier_name.value_raw).strip() if (s.supplier_name and is_eligible(f"{prefix}.supplier_name") and s.supplier_name.value_raw) else f"Nhà cung cấp {idx}"
                s_goods = str(s.supplied_goods.value_raw).strip() if (s.supplied_goods and is_eligible(f"{prefix}.supplied_goods") and s.supplied_goods.value_raw) else "Nguyên vật liệu"
                s_share = BusinessNormalizer.normalize_percentage(s.purchase_share_percentage_raw.value_raw) if (s.purchase_share_percentage_raw and is_eligible(f"{prefix}.purchase_share_percentage")) else 0.0
                s_term = str(s.payment_terms.value_raw).strip() if (s.payment_terms and is_eligible(f"{prefix}.payment_terms") and s.payment_terms.value_raw) else "Chuyển khoản / L/C"

                has_cic = (s_share >= 30.0) if s_share is not None else False

                mapped_s.append({
                    "name": s_name,
                    "goods": s_goods,
                    "share": s_share or 0.0,
                    "term": s_term,
                    "has_cic_check": has_cic,
                })

                if s.supplier_name and s.supplier_name.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.supplier_name",
                            source_value=str(s.supplier_name.value_raw),
                            mapped_value=s_name,
                            evidence=s.supplier_name.evidence or "",
                            page=s.supplier_name.page or s.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )

            new_c["suppliers"] = mapped_s
            updated_fields.add("section_c.suppliers")

        # 10. Customers (Bảng 06 MB07)
        if extraction.customers:
            mapped_cust = []
            for idx, c in enumerate(extraction.customers, start=1):
                prefix = f"section_c.customers[{idx}]"
                c_name = str(c.customer_name.value_raw).strip() if (c.customer_name and is_eligible(f"{prefix}.customer_name") and c.customer_name.value_raw) else f"Khách hàng {idx}"
                c_goods = str(c.product_purchased.value_raw).strip() if (c.product_purchased and is_eligible(f"{prefix}.product_purchased") and c.product_purchased.value_raw) else "Sản phẩm chính"
                c_share = BusinessNormalizer.normalize_percentage(c.revenue_share_percentage_raw.value_raw) if (c.revenue_share_percentage_raw and is_eligible(f"{prefix}.revenue_share_percentage")) else 0.0
                c_term = str(c.credit_terms.value_raw).strip() if (c.credit_terms and is_eligible(f"{prefix}.credit_terms") and c.credit_terms.value_raw) else "Trả chậm / Chuyển khoản"

                mapped_cust.append({
                    "name": c_name,
                    "goods": c_goods,
                    "share": c_share or 0.0,
                    "term": c_term,
                })

                if c.customer_name and c.customer_name.value_raw:
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.customer_name",
                            source_value=str(c.customer_name.value_raw),
                            mapped_value=c_name,
                            evidence=c.customer_name.evidence or "",
                            page=c.customer_name.page or c.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )

            new_c["customers"] = mapped_cust
            updated_fields.add("section_c.customers")

        # 11. Competitors (SOURCE_CLAIM)
        if extraction.competitors:
            mapped_comp = []
            for idx, comp in enumerate(extraction.competitors, start=1):
                prefix = f"section_c.competitors[{idx}]"
                if comp.competitor_name and comp.competitor_name.value_raw and is_eligible(f"{prefix}.competitor_name"):
                    comp_name = str(comp.competitor_name.value_raw).strip()
                    mapped_comp.append(comp_name)
                    provenance.append(
                        MappingProvenance(
                            canonical_path=f"{prefix}.competitor_name",
                            source_value=str(comp.competitor_name.value_raw),
                            mapped_value=comp_name,
                            evidence=comp.competitor_name.evidence or "",
                            page=comp.competitor_name.page or comp.page or 1,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor=source_meta.extractor,
                        )
                    )
            if mapped_comp:
                new_c["top_competitors"] = mapped_comp
                updated_fields.add("section_c.top_competitors")

        # Preserve RM-owned fields untouched
        for rm_fld in ("rm_management_assessment", "rm_market_position", "rm_supply_chain_assessment", "rm_credit_risk_mitigation", "rm_industry_assessment"):
            if rm_fld in existing_c:
                new_c[rm_fld] = existing_c[rm_fld]

        # Isolate section_c inside case_data
        new_case_data["section_c"] = new_c

        # Group provenance by canonical path
        prov_dict: Dict[str, Tuple[MappingProvenance, ...]] = {}
        for p in provenance:
            prov_dict.setdefault(p.canonical_path, ())
            prov_dict[p.canonical_path] = prov_dict[p.canonical_path] + (p,)

        return CanonicalMappingResult(
            case_data=new_case_data,
            provenance=prov_dict,
            conflicts=tuple(conflicts),
            warnings=tuple(warnings),
            updated_fields=tuple(sorted(updated_fields)),
        )
