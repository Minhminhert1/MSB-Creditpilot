# -*- coding: utf-8 -*-
"""Deterministic legal mapper from LegalDocumentExtraction to canonical case_data."""

import copy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any, Optional
import unicodedata

from ..extraction.legal_extraction import EvidenceField, LegalDocumentExtraction
from ..section_a.normalizers import normalize_monetary_to_million_vnd
from .models import (
    CanonicalMappingResult,
    MappingConflict,
    MappingProvenance,
    MappingSchemaError,
    MappingSourceMetadata,
    MappingWarning,
)


@dataclass(frozen=True)
class MonetarySourceToken:
    """Deterministic token representing an extracted numeric amount and its bound unit."""
    numeric_text: str
    explicit_unit: str
    source_fragment: str


def _normalize_text_for_comparison(val: Any) -> str:
    """Normalize text for conservative case-sensitive comparison (NFC + collapsed whitespace)."""
    if val is None:
        return ""
    nfc_str = unicodedata.normalize("NFC", str(val)).strip()
    return " ".join(nfc_str.split())


def _normalize_tax_code_for_comparison(val: Any) -> str:
    """Normalize tax code for comparison by stripping whitespace and delimiters while preserving string zeros."""
    if val is None:
        return ""
    raw = str(val).strip()
    return re.sub(r"[\s.\-_]", "", raw)


def _parse_monetary_source_token(raw_text: str) -> tuple[Optional[MonetarySourceToken], Optional[str]]:
    """Parse local numeric amount and explicitly bound currency unit.
    
    Returns:
        (MonetarySourceToken, None) on success.
        (None, error_reason) on failure or ambiguous format.
    """
    if not raw_text or not isinstance(raw_text, str):
        return None, "Empty or non-string monetary input"

    # 1. Normalize NFC
    text = unicodedata.normalize("NFC", raw_text).strip()

    # 2. Reject approximations
    if re.search(r"(?i)\b(khoảng|ước tính|tầm|khoang|about)\b", text):
        return None, f"Approximation expression detected in '{raw_text}'"

    # 3. Reject ranges
    if re.search(r"\d+\s*[-–—/]\s*\d+", text):
        return None, f"Range expression detected in '{raw_text}'"

    # 4. Strip explicit descriptive 'Bằng chữ' clauses
    cleaned = re.sub(r"\s*\([^)]*(?:bằng chữ|bang chu)[^)]*\)", "", text, flags=re.IGNORECASE).strip()
    cleaned = re.split(r"(?i)[,;]?\s*(?:bằng chữ|bang chu)\s*:", cleaned)[0].strip()

    # 5. Check if numeric digits exist
    if not re.search(r"\d", cleaned):
        return None, f"No numeric digits found in '{raw_text}'"

    # 6. Pattern: <numeric token> + <unit token>
    # Punctuation before number is allowed (e.g. 'Vốn điều lệ:50 tỷ đồng', '50.000.000.000đ')
    pattern = re.compile(
        r"(?:^|[^\w.,-])"                                     # Start of string or non-word delimiter (allows : or whitespace)
        r"(?P<number>-?\d+(?:[.,]\d+)*)"                      # Numeric amount
        r"\s*"                                                # Optional whitespace between number and unit
        r"(?P<unit>"
        r"tỷ\s*(?:đồng|vnđ|vnd)?|ty\s*(?:dong|vnd)?|"
        r"triệu\s*(?:đồng|vnđ|vnd)?|trieu\s*(?:dong|vnd)?|"
        r"đồng|dong|vnđ|vnd|đ"
        r")"
        r"(?!\w)",                                            # End of unit (not part of longer word)
        re.IGNORECASE
    )

    matches = list(pattern.finditer(cleaned))
    if not matches:
        return None, f"No explicit recognized currency unit bound to numeric amount in '{raw_text}'"
    if len(matches) > 1:
        return None, f"Multiple numeric monetary tokens found in '{raw_text}'"

    m = matches[0]
    num_str = m.group("number").strip()
    raw_unit = m.group("unit").strip().lower()

    # 7. Reject negative numbers
    if num_str.startswith("-"):
        return None, f"Negative monetary amount not allowed: '{num_str}'"

    # 8. Map to canonical source unit for normalizer
    if re.search(r"^(?:tỷ|ty)", raw_unit):
        canonical_unit = "tỷ đồng"
    elif re.search(r"^(?:triệu|trieu)", raw_unit):
        canonical_unit = "triệu đồng"
    elif re.search(r"^(?:đồng|dong|vnđ|vnd|đ)$", raw_unit):
        canonical_unit = "VND"
    else:
        return None, f"Unrecognized currency unit '{raw_unit}'"

    return MonetarySourceToken(numeric_text=num_str, explicit_unit=canonical_unit, source_fragment=m.group(0).strip()), None


class LegalDocumentMapper:
    """Stateless deterministic mapping engine from LegalDocumentExtraction to canonical case_data."""

    @classmethod
    def map(
        cls,
        existing_case_data: dict[str, Any],
        extraction: LegalDocumentExtraction,
        source_meta: MappingSourceMetadata,
        existing_provenance: Optional[dict[str, tuple[MappingProvenance, ...]]] = None,
        existing_conflicts: tuple[MappingConflict, ...] = (),
        existing_warnings: tuple[MappingWarning, ...] = (),
    ) -> CanonicalMappingResult:
        """Map extracted legal document fields to canonical case_data deterministically.
        
        Args:
            existing_case_data: Caller-supplied case data dictionary. Never mutated in place.
            extraction: Verified LegalDocumentExtraction staging instance.
            source_meta: Metadata identifying source document and ingestion mode.
            existing_provenance: Prior provenance dictionary mapping path to tuple of records.
            existing_conflicts: Prior tuple of conflicts.
            existing_warnings: Prior tuple of warnings.
            
        Returns:
            CanonicalMappingResult with updated case_data, provenance, conflicts, warnings, and updated_fields.
        """
        # 1. Non-mutation guarantee
        working_case_data = copy.deepcopy(existing_case_data)

        # 2. Canonical shape validation
        if "customer" not in working_case_data:
            working_case_data["customer"] = {}
        elif not isinstance(working_case_data["customer"], dict):
            raise MappingSchemaError(
                f"Malformed case_data: 'customer' must be a dict, got {type(working_case_data['customer']).__name__}."
            )

        customer_dict = working_case_data["customer"]

        # 3. Initialize stateful containers
        provenance_map: dict[str, list[MappingProvenance]] = {}
        if existing_provenance:
            for k, records in existing_provenance.items():
                provenance_map[k] = list(records)

        conflicts_list: list[MappingConflict] = list(existing_conflicts)
        warnings_list: list[MappingWarning] = list(existing_warnings)
        updated_fields_list: list[str] = []

        # Helpers for deduplication
        existing_conflict_keys = {c.identity_key for c in conflicts_list}
        existing_warning_keys = {w.identity_key for w in warnings_list}

        def add_provenance(path: str, src_val: str, mapped_val: Any, ev: str, pg: int) -> None:
            prov = MappingProvenance(
                canonical_path=path,
                source_value=src_val,
                mapped_value=mapped_val,
                evidence=ev,
                page=pg,
                source_document=source_meta.source_document,
                ingestion_mode=source_meta.ingestion_mode,
                extractor=source_meta.extractor,
            )
            records = provenance_map.setdefault(path, [])
            if prov.identity_key not in {r.identity_key for r in records}:
                records.append(prov)

        def add_conflict(path: str, exist_val: Any, ext_val: Any, ev: str, pg: int) -> None:
            conflict = MappingConflict(
                canonical_path=path,
                existing_value=exist_val,
                extracted_value=ext_val,
                evidence=ev,
                page=pg,
                source_document=source_meta.source_document,
            )
            if conflict.identity_key not in existing_conflict_keys:
                conflicts_list.append(conflict)
                existing_conflict_keys.add(conflict.identity_key)

        def add_warning(path: str, src_val: str, reason: str, ev: str, pg: int) -> None:
            warning = MappingWarning(
                canonical_path=path,
                source_value=src_val,
                reason=reason,
                evidence=ev,
                page=pg,
                source_document=source_meta.source_document,
            )
            if warning.identity_key not in existing_warning_keys:
                warnings_list.append(warning)
                existing_warning_keys.add(warning.identity_key)

        # 4. Define field mapping dispatch
        text_field_mappings = [
            ("company_name", "customer.name", "name"),
            ("short_name", "customer.short_name", "short_name"),
            ("address", "customer.address", "address"),
            ("legal_rep_name", "customer.legal_rep_name", "legal_rep_name"),
            ("legal_rep_title", "customer.legal_rep_title", "legal_rep_title"),
        ]

        # 5. Process standard text fields
        for staging_attr, canonical_path, dict_key in text_field_mappings:
            field_obj: EvidenceField = getattr(extraction, staging_attr)
            if field_obj.value is None:
                # Null policy: skip write, do not overwrite existing, do not write sentinel
                continue

            extracted_val = unicodedata.normalize("NFC", str(field_obj.value)).strip()
            existing_val = customer_dict.get(dict_key)

            # Preserve provenance for this observation
            add_provenance(
                path=canonical_path,
                src_val=str(field_obj.value),
                mapped_val=extracted_val,
                ev=field_obj.evidence or "",
                pg=field_obj.page or 1,
            )

            if existing_val is None or str(existing_val).strip() == "":
                # Field currently empty: write new value
                customer_dict[dict_key] = extracted_val
                updated_fields_list.append(canonical_path)
            else:
                # Field has existing non-empty value: compare conservatively
                norm_existing = _normalize_text_for_comparison(existing_val)
                norm_extracted = _normalize_text_for_comparison(extracted_val)
                if norm_existing != norm_extracted:
                    # Conflict: do not overwrite, emit conflict
                    add_conflict(
                        path=canonical_path,
                        exist_val=existing_val,
                        ext_val=extracted_val,
                        ev=field_obj.evidence or "",
                        pg=field_obj.page or 1,
                    )
                else:
                    # Identical fact: no conflict; value already present
                    pass

        # 6. Process tax code (strictly string, leading zero preserved)
        tax_obj: EvidenceField = extraction.tax_code
        if tax_obj.value is not None:
            extracted_tax = unicodedata.normalize("NFC", str(tax_obj.value)).strip()
            existing_tax = customer_dict.get("tax_code")

            add_provenance(
                path="customer.tax_code",
                src_val=str(tax_obj.value),
                mapped_val=extracted_tax,
                ev=tax_obj.evidence or "",
                pg=tax_obj.page or 1,
            )

            if existing_tax is None or str(existing_tax).strip() == "":
                customer_dict["tax_code"] = extracted_tax
                updated_fields_list.append("customer.tax_code")
            else:
                norm_existing_tax = _normalize_tax_code_for_comparison(existing_tax)
                norm_extracted_tax = _normalize_tax_code_for_comparison(extracted_tax)
                if norm_existing_tax != norm_extracted_tax:
                    add_conflict(
                        path="customer.tax_code",
                        exist_val=existing_tax,
                        ext_val=extracted_tax,
                        ev=tax_obj.evidence or "",
                        pg=tax_obj.page or 1,
                    )

        # 7. Process charter capital (triệu đồng, deterministic token parser)
        cap_obj: EvidenceField = extraction.charter_capital_raw
        if cap_obj.value is not None:
            token, parse_err = _parse_monetary_source_token(cap_obj.value)
            if parse_err:
                # Unparseable / ambiguous / unsupported format: warning and provenance with mapped_value=None
                add_provenance(
                    path="customer.charter_capital",
                    src_val=str(cap_obj.value),
                    mapped_val=None,
                    ev=cap_obj.evidence or "",
                    pg=cap_obj.page or 1,
                )
                add_warning(
                    path="customer.charter_capital",
                    src_val=str(cap_obj.value),
                    reason=parse_err,
                    ev=cap_obj.evidence or "",
                    pg=cap_obj.page or 1,
                )
            else:
                try:
                    norm_dec = normalize_monetary_to_million_vnd(
                        token.numeric_text,
                        source_unit=token.explicit_unit,
                    )
                    # Output validation: finite, non-negative
                    if norm_dec.is_nan() or norm_dec.is_infinite():
                        raise ValueError(f"Charter capital must be finite, got {norm_dec}")
                    if norm_dec < Decimal("0"):
                        raise ValueError(f"Charter capital cannot be negative, got {norm_dec}")

                    final_numeric = int(norm_dec) if norm_dec == int(norm_dec) else float(norm_dec)

                    add_provenance(
                        path="customer.charter_capital",
                        src_val=str(cap_obj.value),
                        mapped_val=final_numeric,
                        ev=cap_obj.evidence or "",
                        pg=cap_obj.page or 1,
                    )

                    existing_cap = customer_dict.get("charter_capital")
                    if existing_cap is None or str(existing_cap).strip() == "":
                        customer_dict["charter_capital"] = final_numeric
                        updated_fields_list.append("customer.charter_capital")
                    else:
                        # Compare normalized million VND numeric values
                        try:
                            exist_dec = Decimal(str(existing_cap))
                            diff = abs(exist_dec - norm_dec)
                            if diff >= Decimal("0.000001"):
                                add_conflict(
                                    path="customer.charter_capital",
                                    exist_val=existing_cap,
                                    ext_val=final_numeric,
                                    ev=cap_obj.evidence or "",
                                    pg=cap_obj.page or 1,
                                )
                        except (InvalidOperation, ValueError):
                            # Existing value is not numeric -> conflict
                            add_conflict(
                                path="customer.charter_capital",
                                exist_val=existing_cap,
                                ext_val=final_numeric,
                                ev=cap_obj.evidence or "",
                                pg=cap_obj.page or 1,
                            )

                except Exception as ex:
                    add_provenance(
                        path="customer.charter_capital",
                        src_val=str(cap_obj.value),
                        mapped_val=None,
                        ev=cap_obj.evidence or "",
                        pg=cap_obj.page or 1,
                    )
                    add_warning(
                        path="customer.charter_capital",
                        src_val=str(cap_obj.value),
                        reason=f"Normalization failed: {ex}",
                        ev=cap_obj.evidence or "",
                        pg=cap_obj.page or 1,
                    )

        # 8. Package immutable result
        final_provenance = {k: tuple(v) for k, v in provenance_map.items()}
        return CanonicalMappingResult(
            case_data=working_case_data,
            provenance=final_provenance,
            conflicts=tuple(conflicts_list),
            warnings=tuple(warnings_list),
            updated_fields=tuple(updated_fields_list),
        )
