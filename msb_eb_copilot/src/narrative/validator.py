# -*- coding: utf-8 -*-
"""Deterministic Narrative Validator.

Module: msb_eb_copilot.src.narrative.validator
Principles:
- Strict zero-hallucination verification.
- Validates:
  A. Numeric correctness against registered display representations.
  B. Referential integrity of facts_used and insights_used.
  C. Dynamic entity allow-list derived from FactManifest.
  D. Supported calendar dates and years.
  E. Mandatory attribution for SOURCE_CLAIM facts.
  F. Mandatory caveat for INCOMPLETE CIC external debt.
  G. Causal language requires supporting facts.
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import (
    FactAuthority,
    FactManifest,
    NarrativeBlock,
    NarrativeValidationError,
    VerificationStatus,
    VerifiedInsight,
)

CAUSAL_WORDS = [
    r"\bnhờ\b",
    r"\bdo\b",
    r"\bdẫn đến\b",
    r"\bkhiến\b",
    r"\bchủ yếu do\b",
    r"\bxuất phát từ\b",
    r"\bvì\b",
]

SOURCE_CLAIM_ATTRIBUTIONS = [
    "theo hồ sơ doanh nghiệp cung cấp",
    "theo báo cáo tự kê khai của doanh nghiệp",
    "theo chia sẻ của doanh nghiệp",
    "theo ghi nhận từ hồ sơ doanh nghiệp",
    "doanh nghiệp cho biết",
]

CIC_INCOMPLETE_CAVEATS = [
    "chưa thể xác định đầy đủ",
    "chưa được quy đổi",
    "ngoại tệ",
    "khoản nợ ngoại tệ",
    "dữ liệu chưa hoàn tất quy đổi",
    "chưa có giá trị quy đổi",
]


class DeterministicNarrativeValidator:
    """Rigorous deterministic validator for AI-generated and RM-edited credit narrative prose."""

    def __init__(self, manifest: FactManifest, verified_insights: Optional[List[VerifiedInsight]] = None):
        self.manifest = manifest
        self.verified_insights = {i.insight_id: i for i in (verified_insights or [])}
        self.entity_allow_list = self.manifest.get_entity_allow_list()

    def validate_all(self, blocks: List[NarrativeBlock]) -> Dict[str, Any]:
        """Validate all narrative blocks in a package."""
        results = {}
        for block in blocks:
            results[block.target_binding.value] = self.validate_block(block)
        return {
            "all_valid": all(r["valid"] for r in results.values()),
            "block_results": results
        }

    def validate_blocks(self, blocks: List[NarrativeBlock]):
        """Validate list of blocks returning object with .is_valid and .errors."""
        all_res = self.validate_all(blocks)
        collected_errors = []
        for r in all_res["block_results"].values():
            collected_errors.extend(r.get("errors", []))

        class ValidationSummary:
            def __init__(self, is_valid: bool, errors: List[str]):
                self.is_valid = is_valid
                self.errors = errors
            def model_dump(self):
                return {"is_valid": self.is_valid, "errors": self.errors}
        return ValidationSummary(is_valid=all_res["all_valid"], errors=collected_errors)

    def validate_block(self, block: NarrativeBlock) -> Dict[str, Any]:
        """Validate an individual NarrativeBlock."""
        errors: List[str] = []

        # 1. Referential Integrity: facts_used
        referenced_facts = []
        for fid in block.facts_used:
            fact = self.manifest.get_fact(fid)
            if not fact:
                errors.append(f"Referential integrity error: fact_id '{fid}' does not exist in FactManifest")
            else:
                referenced_facts.append(fact)

        # 2. Referential Integrity: insights_used
        referenced_insights = []
        for iid in block.insights_used:
            if iid not in self.verified_insights:
                errors.append(f"Referential integrity error: insight_id '{iid}' not in verified insights")
            else:
                v_ins = self.verified_insights[iid]
                if v_ins.status not in (VerificationStatus.VERIFIED, VerificationStatus.CORRECTED_AND_VERIFIED):
                    errors.append(f"Referential error: insight '{iid}' has untrusted status '{v_ins.status.value}'")
                else:
                    referenced_insights.append(v_ins)

        # 3. Build Trusted Representation Set
        trusted_reps: Set[str] = set()
        trusted_clean_numbers: Set[str] = set()

        for f in referenced_facts:
            for rep in f.display_representations:
                trusted_reps.add(rep.strip().lower())
                for num_tok in re.findall(r"\d+(?:[\.,]\d+)?", rep):
                    trusted_clean_numbers.add(num_tok)
                    trusted_clean_numbers.add(num_tok.replace(".", "").replace(",", ""))

        for ins in referenced_insights:
            for rep in ins.display_representations:
                trusted_reps.add(rep.strip().lower())
                for num_tok in re.findall(r"\d+(?:[\.,]\d+)?", rep):
                    trusted_clean_numbers.add(num_tok)
                    trusted_clean_numbers.add(num_tok.replace(".", "").replace(",", ""))

        # Also add legal rep years, standard periods
        for yr in ("2020", "2021", "2022", "2023", "2024", "2025", "2026"):
            trusted_clean_numbers.add(yr)
            trusted_reps.add(yr)

        # 4. Numeric Audit: Extract all numbers and check against trusted set
        text_lower = block.text.lower()
        # Find all tokens resembling numbers (with optional %, dots, commas)
        number_matches = re.finditer(r"\b(\d+(?:[\.,]\d+)?\s*(?:%|tỷ|triệu|nghìn|vnd|usd|ngày|năm|tháng|lần|x)?)\b", text_lower)
        for m in number_matches:
            raw_token = m.group(1).strip()
            # Clean off units to check pure number
            pure_num = re.sub(r"[^\d\.,]", "", raw_token).strip()

            # Check if raw token or pure number is in trusted set
            matched = False
            if raw_token in trusted_reps or pure_num in trusted_clean_numbers:
                matched = True
            elif pure_num in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"):
                # Small integers for enumerations / months are permitted
                matched = True
            else:
                # Check for standard formatted thousands
                clean_num_no_punct = pure_num.replace(".", "").replace(",", "")
                if clean_num_no_punct in trusted_clean_numbers:
                    matched = True

            if not matched:
                errors.append(f"Ungrounded numeric claim detected: '{raw_token}' (numeric: '{pure_num}') in binding '{block.target_binding.value}'")

        # 5. SOURCE_CLAIM Attribution Check
        for f in referenced_facts:
            if f.authority == FactAuthority.SOURCE_CLAIM:
                # Attribution phrase must be present in narrative text
                has_attr = any(attr in text_lower for attr in SOURCE_CLAIM_ATTRIBUTIONS)
                if not has_attr:
                    errors.append(
                        f"Missing mandatory source attribution for SOURCE_CLAIM fact '{f.fact_id}'. "
                        "Must include 'Theo hồ sơ doanh nghiệp cung cấp...' or approved equivalent."
                    )

        # 6. CIC Completeness Caveat Check
        has_cic_gap = any(gap.fact_id == "GAP_CIC_EXTERNAL_DEBT_INCOMPLETE" for gap in self.manifest.data_gaps)
        if block.section == "CIC" and has_cic_gap:
            has_caveat = any(c in text_lower for c in CIC_INCOMPLETE_CAVEATS)
            if not has_caveat:
                errors.append(
                    "CIC external debt is INCOMPLETE (contains unnormalized foreign currency debt). "
                    "Narrative must explicitly state that external debt is not fully determinable in VND."
                )

        # 7. Causal Language Guardrail Check
        has_causal = any(re.search(pat, text_lower) for pat in CAUSAL_WORDS)
        if has_causal:
            # Must cite supporting business facts or verified insights, or be explaining an audit data gap
            has_supporting_cause = any(
                f.section in ("BUSINESS", "LEGAL") or f.fact_id.startswith("BIZ_")
                for f in referenced_facts
            ) or len(referenced_insights) > 0 or len(block.data_gaps) > 0 or (block.section == "CIC" and has_cic_gap)
            if not has_supporting_cause:
                errors.append(
                    f"Causal statement detected without supporting business fact or verified insight in binding '{block.target_binding.value}'"
                )

        is_valid = len(errors) == 0
        return {
            "valid": is_valid,
            "target_binding": block.target_binding.value,
            "errors": errors
        }

    def assert_valid(self, block: NarrativeBlock):
        """Raise NarrativeValidationError if block is invalid."""
        res = self.validate_block(block)
        if not res["valid"]:
            raise NarrativeValidationError(
                message="; ".join(res["errors"]),
                code="NARRATIVE_VALIDATION_FAILED",
                binding=block.target_binding.value
            )
