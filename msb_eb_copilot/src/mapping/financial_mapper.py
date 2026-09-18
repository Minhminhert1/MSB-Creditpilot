# -*- coding: utf-8 -*-
"""Deterministic financial mapper from FinancialDocumentExtraction to canonical case_data.

Module: msb_eb_copilot.src.mapping.financial_mapper
Strict Rules:
- GreenNode populates SOURCE_FACT fields only.
- Python owns normalization, timeline alignment, validation, and DERIVED_PYTHON ratios.
- Non-mutation guarantee (copy.deepcopy).
- Provenance per-fact retains unit resolution and evidence.
"""

from __future__ import annotations
import copy
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from ..extraction.financial_extraction import (
    AccountingSemanticInterpreter,
    FinancialDocumentExtraction,
    FinancialEvidenceField,
    FinancialPeriodExtraction,
    FinancialUnitResolver,
    LexicalFinancialNumberParser,
)
from .models import (
    CanonicalMappingResult,
    MappingConflict,
    MappingProvenance,
    MappingSchemaError,
    MappingSourceMetadata,
    MappingWarning,
)


FINANCIAL_SOURCE_FACT_FIELDS = [
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


def compute_canonical_ratios(section_d: Dict[str, Any]) -> Dict[str, List[Optional[float]]]:
    """Deterministically compute financial ratios using Python formulas.
    
    Hard Rule: GreenNode MUST NEVER calculate ratios. Ratios are DERIVED_PYTHON.
    Authoritative MSB Definitions:
    - Current Ratio = current_assets / current_liabilities (fallback to short_term_debt)
    - Quick Ratio = (current_assets - inventories) / current_liabilities (fallback to short_term_debt)
    - Cash Ratio = cash / current_liabilities (fallback to short_term_debt)
    - Debt to Equity = total_liabilities / equity (fallback to total_assets - equity or short_term_debt)
    - ROS = net_profit_after_tax / net_revenue * 100
    - ROE = net_profit_after_tax / equity * 100
    - Gross Profit Margin = gross_profit / net_revenue * 100
    - Revenue Growth = (net_revenue[t] - net_revenue[t-1]) / net_revenue[t-1] * 100
    """
    years = section_d.get("years", [])
    n = len(years)
    if n == 0:
        return {}

    def get_arr(field_name: str) -> List[Optional[float]]:
        arr = section_d.get(field_name, [])
        res: List[Optional[float]] = []
        for i in range(n):
            if i < len(arr) and arr[i] is not None:
                try:
                    res.append(float(arr[i]))
                except (ValueError, TypeError):
                    res.append(None)
            else:
                res.append(None)
        return res

    rev = get_arr("net_revenue")
    gp = get_arr("gross_profit")
    np_after = get_arr("net_profit_after_tax")
    ca = get_arr("current_assets")
    cash = get_arr("cash")
    inv = get_arr("inventories")
    ta = get_arr("total_assets")
    tl = get_arr("total_liabilities")
    cl = get_arr("current_liabilities")
    st_debt = get_arr("short_term_debt")
    eq = get_arr("equity")

    current_ratio: List[Optional[float]] = []
    quick_ratio: List[Optional[float]] = []
    cash_ratio: List[Optional[float]] = []
    debt_to_equity: List[Optional[float]] = []
    total_debt_to_equity: List[Optional[float]] = []
    ros: List[Optional[float]] = []
    roe: List[Optional[float]] = []
    gross_margin: List[Optional[float]] = []
    rev_growth: List[Optional[float]] = []

    for i in range(n):
        # Determine authoritative liquidity denominator: current_liabilities primary, short_term_debt fallback
        cl_denom = cl[i] if (cl[i] is not None and cl[i] > 0) else (st_debt[i] if (st_debt[i] is not None and st_debt[i] > 0) else None)

        # Current Ratio = Current Assets / Current Liabilities (or ST Debt)
        if ca[i] is not None and cl_denom is not None and cl_denom > 0:
            current_ratio.append(round(ca[i] / cl_denom, 2))
        else:
            current_ratio.append(None)

        # Quick Ratio = (Current Assets - Inventories) / Current Liabilities (or ST Debt)
        if ca[i] is not None and inv[i] is not None and cl_denom is not None and cl_denom > 0:
            quick_ratio.append(round((ca[i] - inv[i]) / cl_denom, 2))
        else:
            quick_ratio.append(None)

        # Cash Ratio = Cash / Current Liabilities (or ST Debt)
        if cash[i] is not None and cl_denom is not None and cl_denom > 0:
            cash_ratio.append(round(cash[i] / cl_denom, 2))
        else:
            cash_ratio.append(None)

        # Debt to Equity = Total Liabilities / Equity (fallback to TA - Equity or ST Debt)
        tl_num = tl[i] if (tl[i] is not None and tl[i] > 0) else (
            (ta[i] - eq[i]) if (ta[i] is not None and eq[i] is not None and ta[i] >= eq[i]) else (
                st_debt[i] if (st_debt[i] is not None and st_debt[i] > 0) else None
            )
        )
        if tl_num is not None and eq[i] is not None and eq[i] > 0:
            debt_to_equity.append(round(tl_num / eq[i], 2))
        else:
            debt_to_equity.append(None)

        # Total Debt to Equity = Short-term debt / Equity (or Total Debt / Equity)
        if st_debt[i] is not None and eq[i] is not None and eq[i] > 0:
            total_debt_to_equity.append(round(st_debt[i] / eq[i], 2))
        else:
            total_debt_to_equity.append(None)

        # Return on Sales (ROS) = Net Profit / Revenue * 100
        if np_after[i] is not None and rev[i] is not None and rev[i] > 0:
            ros.append(round((np_after[i] / rev[i]) * 100, 4))
        else:
            ros.append(None)

        # Return on Equity (ROE) = Net Profit / Equity * 100
        if np_after[i] is not None and eq[i] is not None and eq[i] > 0:
            roe.append(round((np_after[i] / eq[i]) * 100, 4))
        else:
            roe.append(None)

        # Gross Profit Margin = Gross Profit / Revenue * 100
        if gp[i] is not None and rev[i] is not None and rev[i] > 0:
            gross_margin.append(round((gp[i] / rev[i]) * 100, 4))
        else:
            gross_margin.append(None)

        # Revenue Growth YoY = (Rev[t] - Rev[t-1]) / Rev[t-1] * 100
        if i > 0 and rev[i] is not None and rev[i - 1] is not None and rev[i - 1] > 0:
            rev_growth.append(round(((rev[i] - rev[i - 1]) / rev[i - 1]) * 100, 4))
        else:
            rev_growth.append(None)

    return {
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "cash_ratio": cash_ratio,
        "debt_to_equity": debt_to_equity,
        "total_debt_to_equity": total_debt_to_equity,
        "ros": ros,
        "roe": roe,
        "gross_profit_margin_pct": gross_margin,
        "revenue_growth": rev_growth,
    }


def get_canonical_value_by_year(section_d: Dict[str, Any], field_name: str, year: Any) -> Optional[float]:
    """Retrieve a canonical financial value aligned strictly by year label, avoiding blind indexing."""
    years = [str(y).strip() for y in section_d.get("years", [])]
    target = str(year).strip()
    if target not in years:
        return None
    idx = years.index(target)
    arr = section_d.get(field_name, [])
    if idx < len(arr) and arr[idx] is not None:
        try:
            return float(arr[idx])
        except (ValueError, TypeError):
            return None
    return None


class FinancialDocumentMapper:
    """Deterministic mapper from FinancialDocumentExtraction into canonical section_d."""

    @classmethod
    def map(
        cls,
        existing_case_data: Dict[str, Any],
        extraction: FinancialDocumentExtraction,
        source_meta: MappingSourceMetadata,
    ) -> CanonicalMappingResult:
        """Deterministically map extracted financial source facts into section_d.
        
        Guarantees:
        1. Non-mutation of existing_case_data.
        2. Non-destruction of non-targeted fields.
        3. Strict multi-period timeline alignment.
        4. Field-level provenance with grounded unit evidence.
        5. Non-silent conflict handling.
        """
        # 1. Structural schema validation
        if not isinstance(existing_case_data, dict):
            raise MappingSchemaError(f"Target case_data must be a dictionary, got {type(existing_case_data)}")

        working_case_data = copy.deepcopy(existing_case_data)

        if "section_d" not in working_case_data or not isinstance(working_case_data["section_d"], dict):
            working_case_data["section_d"] = {}

        section_d = working_case_data["section_d"]

        # Track sidecar results
        provenance_map: Dict[str, List[MappingProvenance]] = {}
        conflicts_list: List[MappingConflict] = []
        warnings_list: List[MappingWarning] = []
        updated_fields_list: List[str] = []

        def add_provenance(
            path: str,
            src_val: str,
            mapped_val: Any,
            ev: str,
            pg: int,
            resolved_unit: Optional[str] = None,
            unit_ev: Optional[str] = None,
            acc_code: Optional[str] = None,
            sem_label: Optional[str] = None,
        ) -> None:
            record = MappingProvenance(
                canonical_path=path,
                source_value=src_val,
                mapped_value=mapped_val,
                evidence=ev,
                page=pg,
                source_document=source_meta.source_document,
                ingestion_mode=source_meta.ingestion_mode,
                extractor="FinancialDocumentExtractor",
                resolved_unit=resolved_unit,
                unit_evidence=unit_ev,
                accounting_code=acc_code,
                semantic_label=sem_label,
            )
            provenance_map.setdefault(path, []).append(record)

        def add_conflict(path: str, exist_val: Any, ext_val: Any, ev: str, pg: int) -> None:
            conflict = MappingConflict(
                canonical_path=path,
                existing_value=exist_val,
                extracted_value=ext_val,
                evidence=ev,
                page=pg,
                source_document=source_meta.source_document,
            )
            conflicts_list.append(conflict)

        def add_warning(path: str, src_val: str, reason: str, ev: str, pg: int) -> None:
            warning = MappingWarning(
                canonical_path=path,
                source_value=src_val,
                reason=reason,
                evidence=ev,
                page=pg,
                source_document=source_meta.source_document,
            )
            warnings_list.append(warning)

        # 2. Timeline Alignment
        # Extract available years from document
        extracted_periods = [p.period.strip() for p in extraction.periods if p.period and p.period.strip()]
        if not extracted_periods:
            # Nothing to map
            return CanonicalMappingResult(
                case_data=working_case_data,
                provenance={},
                conflicts=(),
                warnings=(),
                updated_fields=(),
            )

        existing_years: List[str] = [str(y).strip() for y in section_d.get("years", [])]
        
        # Merge timeline preserving order and adding new years
        if not existing_years:
            target_years = sorted(list(set(extracted_periods)))
            section_d["years"] = target_years
            updated_fields_list.append("section_d.years")
        else:
            # Union of years, keeping chronological order
            all_years_set = set(existing_years).union(set(extracted_periods))
            target_years = sorted(list(all_years_set))
            if target_years != existing_years:
                # Re-index existing fields to match new expanded timeline
                for f_name in FINANCIAL_SOURCE_FACT_FIELDS:
                    if f_name in section_d and isinstance(section_d[f_name], list):
                        old_arr = section_d[f_name]
                        new_arr = [None] * len(target_years)
                        for old_idx, yr in enumerate(existing_years):
                            if old_idx < len(old_arr):
                                new_pos = target_years.index(yr)
                                new_arr[new_pos] = old_arr[old_idx]
                        section_d[f_name] = new_arr
                section_d["years"] = target_years
                updated_fields_list.append("section_d.years")

        year_to_idx = {yr: idx for idx, yr in enumerate(target_years)}

        # Ensure all canonical field arrays are initialized to length of target_years
        for f_name in FINANCIAL_SOURCE_FACT_FIELDS:
            if f_name not in section_d or not isinstance(section_d[f_name], list):
                section_d[f_name] = [None] * len(target_years)
            elif len(section_d[f_name]) < len(target_years):
                section_d[f_name].extend([None] * (len(target_years) - len(section_d[f_name])))

        # 3. Map Each Period
        for period_ext in extraction.periods:
            yr = period_ext.period.strip()
            if yr not in year_to_idx:
                continue
            yr_idx = year_to_idx[yr]

            for field_name in FINANCIAL_SOURCE_FACT_FIELDS:
                field_obj: FinancialEvidenceField = getattr(period_ext, field_name, None)
                if not field_obj or field_obj.value_raw is None or str(field_obj.value_raw).strip() == "":
                    continue

                raw_val = str(field_obj.value_raw).strip()
                pg = field_obj.page or 1
                ev = field_obj.evidence or ""
                canonical_path = f"section_d.{field_name}[{yr}]"

                # Stage A: Lexical Parsing
                lex_token, lex_err = LexicalFinancialNumberParser.parse_token(raw_val)
                if lex_err:
                    add_warning(canonical_path, raw_val, f"Lexical parse error: {lex_err}", ev, pg)
                    add_provenance(canonical_path, raw_val, None, ev, pg)
                    continue

                if lex_token.is_empty:
                    continue

                if lex_token.is_dash:
                    # Dash: Missing or 0, do not fabricate fact
                    add_warning(canonical_path, raw_val, "Dash token indicates zero/omitted value", ev, pg)
                    add_provenance(canonical_path, raw_val, None, ev, pg)
                    continue

                # Stage B: Accounting Semantic Interpretation
                sem_dec, sem_err = AccountingSemanticInterpreter.interpret(lex_token)
                if sem_err:
                    add_warning(canonical_path, raw_val, f"Accounting semantic error: {sem_err}", ev, pg)
                    add_provenance(canonical_path, raw_val, None, ev, pg)
                    continue

                if sem_dec is None:
                    continue

                # Stage C: Grounded Unit Resolution & Normalization
                page_unit_info = extraction.page_units.get(pg)
                norm_dec, resolved_unit, unit_ev, unit_err = FinancialUnitResolver.resolve_and_normalize(
                    amount=sem_dec,
                    field_unit=field_obj.unit_raw,
                    page_unit=page_unit_info,
                    doc_unit=extraction.document_unit,
                )

                if unit_err:
                    add_warning(canonical_path, raw_val, f"Unit resolution error: {unit_err}", ev, pg)
                    add_provenance(
                        canonical_path,
                        raw_val,
                        None,
                        ev,
                        pg,
                        resolved_unit=resolved_unit,
                        unit_ev=unit_ev,
                        acc_code=field_obj.accounting_code,
                        sem_label=field_obj.semantic_label,
                    )
                    continue

                final_numeric = float(norm_dec) if norm_dec is not None else None

                # Store Provenance
                add_provenance(
                    canonical_path,
                    raw_val,
                    final_numeric,
                    ev,
                    pg,
                    resolved_unit=resolved_unit,
                    unit_ev=unit_ev,
                    acc_code=field_obj.accounting_code,
                    sem_label=field_obj.semantic_label,
                )

                # Stage D: Canonical Binding & Conflict Check
                existing_val = section_d[field_name][yr_idx]
                if existing_val is None or str(existing_val).strip() == "":
                    # Empty -> populate
                    section_d[field_name][yr_idx] = final_numeric
                    updated_fields_list.append(canonical_path)
                else:
                    # Compare existing with extracted
                    try:
                        exist_dec = Decimal(str(existing_val))
                        diff = abs(exist_dec - norm_dec)
                        # Threshold for slight rounding tolerance in triệu VND (0.05 mil = 50,000 VND)
                        if diff > Decimal("0.05"):
                            add_conflict(
                                canonical_path,
                                existing_val,
                                final_numeric,
                                ev,
                                pg,
                            )
                        else:
                            # Values match, no conflict
                            pass
                    except (InvalidOperation, ValueError):
                        # Existing value is not a valid number -> conflict
                        add_conflict(
                            canonical_path,
                            existing_val,
                            final_numeric,
                            ev,
                            pg,
                        )

        # 4. Package Immutable Result
        final_provenance = {k: tuple(v) for k, v in provenance_map.items()}
        return CanonicalMappingResult(
            case_data=working_case_data,
            provenance=final_provenance,
            conflicts=tuple(conflicts_list),
            warnings=tuple(warnings_list),
            updated_fields=tuple(updated_fields_list),
        )
