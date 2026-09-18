# -*- coding: utf-8 -*-
"""Deterministic mapper from CICDocumentExtraction into canonical section_e.

Module: msb_eb_copilot.src.mapping.cic_mapper
Strict Boundary:
- Non-mutating input behavior (deepcopy).
- Section E isolation: ONLY section_e is modified.
- ONE BUSINESS FACT -> ONE CANONICAL AUTHORITY:
  - total_debt_million is DERIVED_PYTHON.
  - total_debt_other_banks_excluding_msb is DERIVED_PYTHON.
  - msb_outstanding is DERIVED_PYTHON.
- Facility -> Institution aggregation precedence:
  1. Institution summary wins.
  2. Facility details preserved in staging/provenance.
  3. Reconcile facility sum vs summary (warning if mismatch).
  4. Fallback to additive facility sum only if verified additive.
  5. Ambiguity -> limit = None + warning.
- Scoped debt_group: scoped strictly to institution row.
- Currency-safe USD debt: VND-equivalent required for total inclusion.
- MSB alias resolver: single authority across all MSB calculations.
"""

from __future__ import annotations
import copy
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

from msb_eb_copilot.src.extraction.cic_extraction import (
    CICDocumentExtraction,
    CICInstitutionItem,
    CICFacilityItem,
    CICEvidenceField,
    CICNormalizer,
    CICGroundingAuditor,
    GroundingAuditResult,
)
from msb_eb_copilot.src.section_e.models import is_msb_institution
from msb_eb_copilot.src.mapping.models import (
    CanonicalMappingResult,
    MappingConflict,
    MappingProvenance,
    MappingSourceMetadata,
    MappingWarning,
)


class CICDocumentMapper:
    """Deterministic mapper from CICDocumentExtraction to canonical section_e."""

    @classmethod
    def map(
        cls,
        existing_case_data: Dict[str, Any],
        extraction: CICDocumentExtraction,
        source_meta: MappingSourceMetadata,
        grounding_audits: Optional[Dict[str, GroundingAuditResult]] = None,
    ) -> CanonicalMappingResult:
        """Deterministically map extracted CIC facts into section_e.
        
        Principle: NO EVIDENCE -> NO FACT.
        Canonical Eligibility:
        - VERIFIED: eligible for canonical mapping.
        - WARNING: eligible if documented.
        - REJECTED: never canonical (set to None, emit warning).
        - MISSING: null.
        """
        new_case_data = copy.deepcopy(existing_case_data)
        provenance: List[MappingProvenance] = []
        conflicts: List[MappingConflict] = []
        warnings: List[MappingWarning] = []
        updated_fields: Set[str] = set()

        existing_e = new_case_data.get("section_e", {})
        new_e = copy.deepcopy(existing_e)

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

        # 1. Document-level facts
        # a) cic_date
        if extraction.cic_report_date and extraction.cic_report_date.value_raw:
            if is_eligible("section_e.cic_date"):
                raw_d = extraction.cic_report_date.value_raw.strip()
                cls._apply_field(
                    canonical_path="section_e.cic_date",
                    target_dict=new_e,
                    key="cic_date",
                    proposed_value=raw_d,
                    raw_field=extraction.cic_report_date,
                    existing_dict=existing_e,
                    source_meta=source_meta,
                    provenance=provenance,
                    conflicts=conflicts,
                    updated_fields=updated_fields,
                )
            else:
                new_e["cic_date"] = None
        else:
            new_e["cic_date"] = None

        # b) history_status
        if extraction.history_status and extraction.history_status.value_raw:
            if is_eligible("section_e.history_status"):
                raw_hist = extraction.history_status.value_raw.strip()
                cls._apply_field(
                    canonical_path="section_e.history_status",
                    target_dict=new_e,
                    key="history_status",
                    proposed_value=raw_hist,
                    raw_field=extraction.history_status,
                    existing_dict=existing_e,
                    source_meta=source_meta,
                    provenance=provenance,
                    conflicts=conflicts,
                    updated_fields=updated_fields,
                )
            else:
                new_e["history_status"] = None
        else:
            new_e["history_status"] = None

        # c) is_overdue_12m (Tri-state: True, False, None)
        raw_ov = extraction.is_overdue_12m.value_raw if extraction.is_overdue_12m else None
        ev_ov = extraction.is_overdue_12m.evidence if extraction.is_overdue_12m else None
        if is_eligible("section_e.is_overdue_12m"):
            parsed_overdue = CICNormalizer.parse_tri_state_overdue(raw_ov, ev_ov)
        else:
            parsed_overdue = None

        if parsed_overdue is not None:
            cls._apply_field(
                canonical_path="section_e.is_overdue_12m",
                target_dict=new_e,
                key="is_overdue_12m",
                proposed_value=parsed_overdue,
                raw_field=extraction.is_overdue_12m,
                existing_dict=existing_e,
                source_meta=source_meta,
                provenance=provenance,
                conflicts=conflicts,
                updated_fields=updated_fields,
            )
        else:
            new_e["is_overdue_12m"] = None
            if not extraction.is_overdue_12m or not extraction.is_overdue_12m.value_raw:
                add_warning(
                    "section_e.is_overdue_12m",
                    "null",
                    "Báo cáo CIC không nêu rõ trạng thái nợ quá hạn 12 tháng; gán null để RM xác nhận.",
                    ev="",
                    pg=1,
                )

        # d) derivative_transactions_info (None if absent or REJECTED)
        if extraction.derivative_transactions_info and extraction.derivative_transactions_info.value_raw and is_eligible("section_e.derivative_transactions_info"):
            raw_deriv = extraction.derivative_transactions_info.value_raw.strip()
            cls._apply_field(
                canonical_path="section_e.derivative_transactions_info",
                target_dict=new_e,
                key="derivative_transactions_info",
                proposed_value=raw_deriv,
                raw_field=extraction.derivative_transactions_info,
                existing_dict=existing_e,
                source_meta=source_meta,
                provenance=provenance,
                conflicts=conflicts,
                updated_fields=updated_fields,
            )
        else:
            new_e["derivative_transactions_info"] = None

        # 2. Multi-Bank Institution Relations & Facility Aggregation Precedence
        # Group facilities by bank name
        facilities_by_bank: Dict[str, List[CICFacilityItem]] = {}
        for fac in extraction.facilities:
            b_name = fac.bank_name.value_raw.strip() if fac.bank_name and fac.bank_name.value_raw else "TCTD_UNKNOWN"
            facilities_by_bank.setdefault(b_name, []).append(fac)

        mapped_relations: List[Dict[str, Any]] = []
        all_insts = list(extraction.institutions)

        # If institutions list is empty but facilities exist, create virtual institution headers
        if not all_insts and facilities_by_bank:
            for b_name, f_list in facilities_by_bank.items():
                v_inst = CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw=b_name, evidence=f_list[0].bank_name.evidence, page=f_list[0].page),
                    facilities=f_list,
                    page=f_list[0].page,
                )
                all_insts.append(v_inst)

        for idx, inst in enumerate(all_insts, start=1):
            inst_prefix = f"section_e.relations[{idx}]"
            if not is_eligible(f"{inst_prefix}.bank_name"):
                continue

            b_name = inst.bank_name.value_raw.strip() if inst.bank_name and inst.bank_name.value_raw else f"TCTD_{idx}"
            inst_page = inst.page or (inst.bank_name.page if inst.bank_name else 1) or 1

            # Match associated facility rows
            inst_facilities = inst.facilities or facilities_by_bank.get(b_name, [])

            # --- Precedence 1: Explicit Institution Summary ---
            summary_limit = None
            if is_eligible(f"{inst_prefix}.short_term_limit"):
                summary_limit, _ = CICNormalizer.parse_monetary(inst.short_term_limit_raw.value_raw if inst.short_term_limit_raw else None)

            summary_st_vnd = None
            if is_eligible(f"{inst_prefix}.short_term_debt_vnd"):
                summary_st_vnd, _ = CICNormalizer.parse_monetary(inst.short_term_debt_vnd_raw.value_raw if inst.short_term_debt_vnd_raw else None)

            summary_st_usd_equiv = None
            if is_eligible(f"{inst_prefix}.short_term_debt_usd_equiv"):
                summary_st_usd_equiv, _ = CICNormalizer.parse_monetary(inst.short_term_debt_usd_vnd_equiv_raw.value_raw if inst.short_term_debt_usd_vnd_equiv_raw else None)

            summary_med_long = None
            if is_eligible(f"{inst_prefix}.medium_long_term_debt"):
                summary_med_long, _ = CICNormalizer.parse_monetary(inst.medium_long_term_debt_raw.value_raw if inst.medium_long_term_debt_raw else None)

            raw_usd_str = None
            if is_eligible(f"{inst_prefix}.raw_usd_amount"):
                raw_usd_str = inst.raw_usd_amount_raw.value_raw if inst.raw_usd_amount_raw else None

            # Check facility sum for reconciliation
            fac_sum_vnd = 0.0
            fac_sum_limit = 0.0
            for f in inst_facilities:
                f_vnd, _ = CICNormalizer.parse_monetary(f.outstanding_vnd_raw.value_raw if f.outstanding_vnd_raw else None)
                f_lim, _ = CICNormalizer.parse_monetary(f.credit_limit_raw.value_raw if f.credit_limit_raw else None)
                if f_vnd:
                    fac_sum_vnd += f_vnd
                if f_lim:
                    fac_sum_limit += f_lim

            # Precedence decision for limits:
            resolved_limit = summary_limit
            if resolved_limit is None and fac_sum_limit > 0:
                # Precedence 4: Additive summation fallback
                resolved_limit = fac_sum_limit

            # Precedence decision for VND debt:
            resolved_st_vnd = summary_st_vnd
            if resolved_st_vnd is None and fac_sum_vnd > 0:
                resolved_st_vnd = fac_sum_vnd

            # Precedence 3: Reconciliation check
            if summary_st_vnd is not None and fac_sum_vnd > 0:
                if abs(summary_st_vnd - fac_sum_vnd) > 1.0:
                    add_warning(
                        f"section_e.relations[{idx}].short_term_debt_vnd_million",
                        f"summary: {summary_st_vnd}, facilities: {fac_sum_vnd}",
                        f"Chênh lệch số liệu giữa bảng tổng hợp TCTD ({summary_st_vnd:,.1f}) và tổng các hợp đồng ({fac_sum_vnd:,.1f}) tại '{b_name}'.",
                        ev=inst.bank_name.evidence or "",
                        pg=inst_page,
                    )

            # --- Currency-Safe USD Handling ---
            raw_usd_val = None
            resolved_st_usd_equiv = summary_st_usd_equiv
            if raw_usd_str:
                # Raw USD was explicitly provided
                try:
                    num_only = re.sub(r"(?i)[^\d.,-]", "", raw_usd_str).strip()
                    if "." in num_only and "," in num_only:
                        if num_only.rfind(",") > num_only.rfind("."):
                            num_only = num_only.replace(".", "").replace(",", ".")
                        else:
                            num_only = num_only.replace(",", "")
                    elif "." in num_only:
                        parts = num_only.split(".")
                        if all(len(p) == 3 for p in parts[1:]):
                            num_only = "".join(parts)
                    elif "," in num_only:
                        parts = num_only.split(",")
                        if all(len(p) == 3 for p in parts[1:]):
                            num_only = "".join(parts)
                    raw_usd_val = float(num_only) if num_only else None
                except ValueError:
                    raw_usd_val = None

                if resolved_st_usd_equiv is None:
                    add_warning(
                        f"section_e.relations[{idx}].short_term_debt_usd_million",
                        f"{raw_usd_val} USD",
                        f"Tại '{b_name}' có khoản nợ ngoại tệ {raw_usd_val} USD nhưng không có giá trị quy đổi VND trên CIC; không tự động quy đổi hoặc cộng gộp vào tổng dư nợ VND.",
                        ev=raw_usd_str,
                        pg=inst_page,
                    )

            # --- Total Debt Completeness (Python Owned) ---
            # Rule: If raw USD exists without VND equivalent, total_debt_million is None
            if raw_usd_val is not None and resolved_st_usd_equiv is None:
                resolved_total_debt = None
                add_warning(
                    f"section_e.relations[{idx}].total_debt_million",
                    "None (Incomplete)",
                    f"Tổng dư nợ tại '{b_name}' không thể tính toán hoàn chỉnh do thiếu giá trị quy đổi VND của khoản nợ {raw_usd_val} USD.",
                    ev=raw_usd_str or "",
                    pg=inst_page,
                )
            else:
                c_vnd = resolved_st_vnd or 0.0
                c_usd = resolved_st_usd_equiv or 0.0
                c_tdh = summary_med_long or 0.0
                resolved_total_debt = round(c_vnd + c_usd + c_tdh, 2)

            # Reconcile with printed total debt if available
            printed_tot = None
            if is_eligible(f"{inst_prefix}.total_debt_printed"):
                printed_tot, _ = CICNormalizer.parse_monetary(inst.total_debt_printed.value_raw if inst.total_debt_printed else None)
            if printed_tot is not None and resolved_total_debt is not None:
                if abs(resolved_total_debt - printed_tot) > 1.0:
                    add_warning(
                        f"section_e.relations[{idx}].total_debt_million",
                        f"calc: {resolved_total_debt}, printed: {printed_tot}",
                        f"Chênh lệch giữa tổng dư nợ tính toán ({resolved_total_debt:,.1f}) và tổng dư nợ in trên CIC ({printed_tot:,.1f}) tại '{b_name}'.",
                        ev=inst.total_debt_printed.evidence if inst.total_debt_printed else "",
                        pg=inst_page,
                    )

            # --- Scoped Debt Group ---
            # Strictly scoped to this institution row
            inst_debt_group = None
            if is_eligible(f"{inst_prefix}.debt_group"):
                inst_debt_group = CICNormalizer.parse_debt_group(inst.debt_group.value_raw if inst.debt_group else None)

            # --- Collateral Description ---
            collateral_txt = ""
            if is_eligible(f"{inst_prefix}.collateral_description"):
                collateral_txt = inst.collateral_description.value_raw.strip() if inst.collateral_description and inst.collateral_description.value_raw else ""
            if not collateral_txt and inst_facilities:
                # Merge unique collateral notes from facilities
                fac_colls = [f.collateral.value_raw.strip() for f in inst_facilities if f.collateral and f.collateral.value_raw]
                if fac_colls:
                    collateral_txt = "; ".join(dict.fromkeys(fac_colls))

            rel_dict: Dict[str, Any] = {
                "stt": idx,
                "bank_name": b_name,
                "short_term_limit_million_vnd": resolved_limit,
                "short_term_debt_vnd_million": resolved_st_vnd,
                "short_term_debt_usd_million": resolved_st_usd_equiv,
                "medium_long_term_debt_million": summary_med_long,
                "total_debt_million": resolved_total_debt,
                "collateral_description": collateral_txt if collateral_txt else None,
                "debt_group": inst_debt_group,
                "raw_usd_amount": raw_usd_val,
                "raw_usd_currency": "USD" if raw_usd_val else None,
            }
            mapped_relations.append(rel_dict)

            # Record provenance for each institution fact
            prov_fields = [
                (f"{inst_prefix}.bank_name", b_name, inst.bank_name),
                (f"{inst_prefix}.short_term_limit_million_vnd", resolved_limit, inst.short_term_limit_raw),
                (f"{inst_prefix}.short_term_debt_vnd_million", resolved_st_vnd, inst.short_term_debt_vnd_raw),
                (f"{inst_prefix}.short_term_debt_usd_million", resolved_st_usd_equiv, inst.short_term_debt_usd_vnd_equiv_raw),
                (f"{inst_prefix}.medium_long_term_debt_million", summary_med_long, inst.medium_long_term_debt_raw),
                (f"{inst_prefix}.raw_usd_amount", raw_usd_val, inst.raw_usd_amount_raw),
                (f"{inst_prefix}.total_debt_million", resolved_total_debt, inst.total_debt_printed or inst.bank_name),
                (f"{inst_prefix}.debt_group", inst_debt_group, inst.debt_group),
                (f"{inst_prefix}.collateral_description", collateral_txt if collateral_txt else None, inst.collateral_description),
            ]
            for p_path, p_val, raw_fld in prov_fields:
                if p_val is not None and raw_fld and getattr(raw_fld, "evidence", None):
                    provenance.append(
                        MappingProvenance(
                            canonical_path=p_path,
                            source_value=str(p_val),
                            mapped_value=p_val,
                            evidence=raw_fld.evidence,
                            page=raw_fld.page or inst_page,
                            source_document=source_meta.source_document,
                            ingestion_mode=source_meta.ingestion_mode,
                            extractor="CICDocumentExtractor",
                        )
                    )

        # Apply relations list
        existing_relations = existing_e.get("relations", [])
        if existing_relations and existing_relations != mapped_relations:
            conflicts.append(
                MappingConflict(
                    canonical_path="section_e.relations",
                    existing_value=existing_relations,
                    extracted_value=mapped_relations,
                    evidence=f"Cập nhật danh sách quan hệ tín dụng {len(mapped_relations)} TCTD từ CIC",
                    page=1,
                    source_document=source_meta.source_document,
                )
            )
            # Retain existing until confirmed
            new_e["relations"] = existing_relations
        else:
            new_e["relations"] = mapped_relations
            updated_fields.add("section_e.relations")

        # 3. Derived Cross-Section Calculations (Python Owned via is_msb_institution)
        active_rels = new_e["relations"]

        # a) total_debt_other_banks_excluding_msb
        other_rels = [r for r in active_rels if not is_msb_institution(r.get("bank_name"))]
        has_incomplete_other = any(r.get("total_debt_million") is None for r in other_rels)
        if has_incomplete_other:
            new_e["total_debt_other_banks_excluding_msb"] = None
            add_warning(
                "section_e.total_debt_other_banks_excluding_msb",
                "None (Incomplete)",
                "Dữ liệu tổng dư nợ TCTD khác chưa hoàn chỉnh (có tổ chức tín dụng thiếu quy đổi VND chuẩn); không cung cấp số liệu cục bộ cho MB09.",
                ev="Dữ liệu TCTD khác chưa hoàn chỉnh",
                pg=1,
            )
        else:
            tot_other_debt = sum(
                (r.get("total_debt_million") or 0.0) for r in other_rels
            )
            new_e["total_debt_other_banks_excluding_msb"] = round(tot_other_debt, 2)
        updated_fields.add("section_e.total_debt_other_banks_excluding_msb")

        # b) msb_outstanding
        msb_rels = [r for r in active_rels if is_msb_institution(r.get("bank_name"))]
        has_incomplete_msb = any(r.get("total_debt_million") is None for r in msb_rels)
        if has_incomplete_msb:
            new_e["msb_outstanding"] = None
            new_e["loan_outstanding_at_msb_million"] = None
            add_warning(
                "section_e.loan_outstanding_at_msb_million",
                "None (Incomplete)",
                "Dữ liệu dư nợ tại MSB chưa hoàn chỉnh do thiếu giá trị quy đổi VND chuẩn.",
                ev="Dữ liệu MSB chưa hoàn chỉnh",
                pg=1,
            )
        else:
            msb_out = sum(
                (r.get("total_debt_million") or 0.0) for r in msb_rels
            )
            new_e["msb_outstanding"] = round(msb_out, 2)
            new_e["loan_outstanding_at_msb_million"] = round(msb_out, 2)
        updated_fields.add("section_e.msb_outstanding")
        updated_fields.add("section_e.loan_outstanding_at_msb_million")

        # c) total_credit_exposure_at_msb_million
        if has_incomplete_msb:
            new_e["total_credit_exposure_at_msb_million"] = None
        else:
            msb_exp = sum(
                max(r.get("short_term_limit_million_vnd") or 0.0, r.get("total_debt_million") or 0.0)
                for r in msb_rels
            )
            new_e["total_credit_exposure_at_msb_million"] = round(msb_exp, 2)
        updated_fields.add("section_e.total_credit_exposure_at_msb_million")

        new_case_data["section_e"] = new_e

        prov_map: Dict[str, Tuple[MappingProvenance, ...]] = {}
        for p in provenance:
            prov_map.setdefault(p.canonical_path, ())
            prov_map[p.canonical_path] = prov_map[p.canonical_path] + (p,)

        return CanonicalMappingResult(
            case_data=new_case_data,
            provenance=prov_map,
            conflicts=tuple(conflicts),
            warnings=tuple(warnings),
            updated_fields=tuple(sorted(updated_fields)),
        )

    @classmethod
    def _apply_field(
        cls,
        canonical_path: str,
        target_dict: Dict[str, Any],
        key: str,
        proposed_value: Any,
        raw_field: CICEvidenceField,
        existing_dict: Dict[str, Any],
        source_meta: MappingSourceMetadata,
        provenance: List[MappingProvenance],
        conflicts: List[MappingConflict],
        updated_fields: Set[str],
    ):
        page = raw_field.page or 1
        evidence = raw_field.evidence or f"Trích xuất {canonical_path}"
        existing_val = existing_dict.get(key)

        provenance.append(
            MappingProvenance(
                canonical_path=canonical_path,
                source_value=str(raw_field.value_raw),
                mapped_value=proposed_value,
                evidence=evidence,
                page=page,
                source_document=source_meta.source_document,
                ingestion_mode=source_meta.ingestion_mode,
                extractor="CICDocumentExtractor",
            )
        )

        if existing_val is not None and existing_val != proposed_value:
            conflicts.append(
                MappingConflict(
                    canonical_path=canonical_path,
                    existing_value=existing_val,
                    extracted_value=proposed_value,
                    evidence=evidence,
                    page=page,
                    source_document=source_meta.source_document,
                )
            )
            # Do not overwrite on conflict; retain existing until confirmed
            target_dict[key] = existing_val
        else:
            target_dict[key] = proposed_value
            updated_fields.add(canonical_path)
