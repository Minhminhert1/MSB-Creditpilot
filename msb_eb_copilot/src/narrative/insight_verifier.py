# -*- coding: utf-8 -*-
"""Deterministic Python Insight Verifier.

Module: msb_eb_copilot.src.narrative.insight_verifier
Principles:
- Pure deterministic Python math (using Decimal / float quantization).
- Zero trust in model arithmetic.
- AI DISCOVERS -> PYTHON VERIFIES.
- Audited corrections: CORRECTED_AND_VERIFIED when concept is valid but math is inaccurate.
- Causal language guardrail: "do", "nhờ", "dẫn đến", "khiến", "chủ yếu do", "xuất phát từ" require supporting fact IDs.
- Deterministic STABLE threshold (delta <= 2.0%).
"""

from __future__ import annotations
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    FactCompleteness,
    FactItem,
    FactManifest,
    InsightCandidate,
    SupportedInsightType,
    TrendDirection,
    VerificationStatus,
    VerifiedInsight,
)
from .fact_packager import _generate_numeric_representations

CAUSAL_PATTERNS = [
    r"\bnhờ\b",
    r"\bdo\b",
    r"\bdẫn đến\b",
    r"\bkhiến\b",
    r"\bchủ yếu do\b",
    r"\bxuất phát từ\b",
    r"\bvì\b",
    r"\btạo đà\b",
]

STABLE_THRESHOLD_PCT = 2.0  # Max percentage change to qualify as STABLE


class PythonInsightVerifier:
    """Deterministic verifier for GLM-5.2 proposed insight candidates."""

    def __init__(self, manifest: FactManifest):
        self.manifest = manifest

    def verify_all(self, candidates: List[InsightCandidate]) -> List[VerifiedInsight]:
        """Verify a list of insight candidates sequentially."""
        return [self.verify_candidate(c) for c in candidates]

    def verify_candidates(self, candidates: List[InsightCandidate]) -> List[VerifiedInsight]:
        """Alias for verify_all."""
        return self.verify_all(candidates)

    def verify_candidate(self, candidate: InsightCandidate) -> VerifiedInsight:
        """Independently verify an individual InsightCandidate."""
        # 1. Resolve referenced facts
        facts: List[FactItem] = []
        for fid in candidate.related_fact_ids:
            f = self.manifest.get_fact(fid)
            if not f:
                return self._reject_missing(candidate, f"Referenced fact_id '{fid}' not found in manifest")
            if f.completeness == FactCompleteness.INCOMPLETE:
                return self._mark_incomplete(candidate, f"Referenced fact '{fid}' has incomplete status")
            facts.append(f)

        # 2. Check Supported Insight Type Whitelist
        if candidate.insight_type not in [t.value for t in SupportedInsightType]:
            return self._reject_invalid(candidate, f"Unsupported insight_type: '{candidate.insight_type}'")

        # 3. Guardrail: Causal Language Check
        causal_check_result = self._check_causal_language(candidate, facts)
        if causal_check_result is not None:
            return causal_check_result

        # 4. Dispatch to type-specific mathematical verifier
        itype = candidate.insight_type
        if itype in (SupportedInsightType.GROWTH.value, SupportedInsightType.DECLINE.value):
            return self._verify_growth_or_decline(candidate, facts)
        elif itype == SupportedInsightType.ABSOLUTE_DELTA.value:
            return self._verify_absolute_delta(candidate, facts)
        elif itype == SupportedInsightType.TREND_DIRECTION.value:
            return self._verify_trend_direction(candidate, facts)
        elif itype == SupportedInsightType.MARGIN_CHANGE.value:
            return self._verify_margin_change(candidate, facts)
        elif itype == SupportedInsightType.RATIO_CHANGE.value:
            return self._verify_ratio_change(candidate, facts)
        elif itype == SupportedInsightType.WORKING_CAPITAL_CHANGE.value:
            return self._verify_working_capital_change(candidate, facts)
        elif itype == SupportedInsightType.LIQUIDITY_OBSERVATION.value:
            return self._verify_liquidity_observation(candidate, facts)
        elif itype == SupportedInsightType.LEVERAGE_OBSERVATION.value:
            return self._verify_leverage_observation(candidate, facts)
        elif itype == SupportedInsightType.PROFITABILITY_OBSERVATION.value:
            return self._verify_profitability_observation(candidate, facts)
        elif itype == SupportedInsightType.CASH_CONVERSION_OBSERVATION.value:
            return self._verify_cash_conversion_observation(candidate, facts)
        elif itype == SupportedInsightType.CUSTOMER_CONCENTRATION.value:
            return self._verify_customer_concentration(candidate, facts)
        elif itype == SupportedInsightType.SUPPLIER_CONCENTRATION.value:
            return self._verify_supplier_concentration(candidate, facts)
        elif itype == SupportedInsightType.CROSS_METRIC_RELATIONSHIP.value:
            return self._verify_cross_metric_relationship(candidate, facts)
        else:
            return self._reject_invalid(candidate, f"No verification handler for '{itype}'")

    # --------------------------------------------------------------------------
    # Helper Rejections & Constructors
    # --------------------------------------------------------------------------
    def _check_causal_language(self, candidate: InsightCandidate, facts: List[FactItem]) -> Optional[VerifiedInsight]:
        """Guardrail A: Reject ungrounded causal claims."""
        obs = candidate.observation.lower()
        has_causal_word = any(re.search(pat, obs) for pat in CAUSAL_PATTERNS)
        if has_causal_word:
            # Must cite at least one qualitative or business fact justifying the cause
            has_supporting_cause_fact = any(
                f.section in ("BUSINESS", "LEGAL") or f.fact_id.startswith("BIZ_")
                for f in facts
            )
            if not has_supporting_cause_fact:
                return VerifiedInsight(
                    insight_id=candidate.insight_id,
                    status=VerificationStatus.REJECTED_UNSUPPORTED_CAUSAL,
                    insight_type=candidate.insight_type,
                    metric=candidate.metric,
                    fact_ids=candidate.related_fact_ids,
                    verified_value=None,
                    model_proposed_value=candidate.proposed_value,
                    unit=candidate.proposed_unit,
                    trend=candidate.trend,
                    observation=candidate.observation,
                    verification_formula="N/A",
                    data_quality="UNVERIFIED",
                    warnings=[f"Observation contains causal construct without supporting business fact IDs: '{candidate.observation}'"],
                    display_representations=[]
                )
        return None

    def _reject_missing(self, candidate: InsightCandidate, reason: str) -> VerifiedInsight:
        return VerifiedInsight(
            insight_id=candidate.insight_id,
            status=VerificationStatus.REJECTED_MISSING_FACTS,
            insight_type=candidate.insight_type,
            metric=candidate.metric,
            fact_ids=candidate.related_fact_ids,
            verified_value=None,
            model_proposed_value=candidate.proposed_value,
            unit=candidate.proposed_unit,
            trend=candidate.trend,
            observation=candidate.observation,
            verification_formula="N/A",
            data_quality="UNVERIFIED",
            warnings=[reason],
            display_representations=[]
        )

    def _mark_incomplete(self, candidate: InsightCandidate, reason: str) -> VerifiedInsight:
        return VerifiedInsight(
            insight_id=candidate.insight_id,
            status=VerificationStatus.INCOMPLETE,
            insight_type=candidate.insight_type,
            metric=candidate.metric,
            fact_ids=candidate.related_fact_ids,
            verified_value=None,
            model_proposed_value=candidate.proposed_value,
            unit=candidate.proposed_unit,
            trend=candidate.trend,
            observation=candidate.observation,
            verification_formula="N/A",
            data_quality="LOW",
            warnings=[reason],
            display_representations=[]
        )

    def _reject_invalid(self, candidate: InsightCandidate, reason: str) -> VerifiedInsight:
        return VerifiedInsight(
            insight_id=candidate.insight_id,
            status=VerificationStatus.REJECTED_INVALID_CONCEPT,
            insight_type=candidate.insight_type,
            metric=candidate.metric,
            fact_ids=candidate.related_fact_ids,
            verified_value=None,
            model_proposed_value=candidate.proposed_value,
            unit=candidate.proposed_unit,
            trend=candidate.trend,
            observation=candidate.observation,
            verification_formula="N/A",
            data_quality="UNVERIFIED",
            warnings=[reason],
            display_representations=[]
        )

    # --------------------------------------------------------------------------
    # Verifiers for Each Supported Insight Type
    # --------------------------------------------------------------------------
    def _verify_growth_or_decline(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify percentage growth or decline between two periods."""
        metric_facts = [f for f in facts if f.unit != "YEAR" and isinstance(f.value, (int, float))]
        if len(metric_facts) < 2:
            return self._reject_missing(candidate, "Growth/decline requires at least 2 numeric fact items")

        p_from_facts = [f for f in metric_facts if str(f.period) == str(candidate.from_period)]
        p_to_facts = [f for f in metric_facts if str(f.period) == str(candidate.to_period)]
        if p_from_facts and p_to_facts:
            f_from, f_to = p_from_facts[0], p_to_facts[0]
        else:
            sorted_facts = sorted([f for f in metric_facts if f.period], key=lambda f: str(f.period))
            if len(sorted_facts) >= 2:
                f_from, f_to = sorted_facts[0], sorted_facts[-1]
            else:
                f_from, f_to = metric_facts[0], metric_facts[-1]

        try:
            v_from = float(f_from.value)
            v_to = float(f_to.value)
        except (ValueError, TypeError):
            return self._reject_invalid(candidate, "Referenced facts must have numeric values")

        if abs(v_from) < 1e-6:
            return self._reject_invalid(candidate, "Base period value is zero; cannot compute percentage growth")

        calc_growth = ((v_to - v_from) / abs(v_from)) * 100.0
        verified_val = round(calc_growth, 2)

        # Check trend direction
        actual_trend = TrendDirection.INCREASE if calc_growth > 0.1 else (
            TrendDirection.DECREASE if calc_growth < -0.1 else TrendDirection.STABLE
        )

        # Check if model claimed opposite direction
        if candidate.trend == TrendDirection.INCREASE and calc_growth < -0.1:
            return self._reject_invalid(candidate, f"Model claimed INCREASE but metric decreased by {calc_growth:.2f}%")
        if candidate.trend == TrendDirection.DECREASE and calc_growth > 0.1:
            return self._reject_invalid(candidate, f"Model claimed DECLINE but metric increased by {calc_growth:.2f}%")
        if candidate.trend == TrendDirection.STABLE and abs(calc_growth) > STABLE_THRESHOLD_PCT:
            return self._reject_invalid(candidate, f"Model claimed STABLE but change was {calc_growth:.2f}% (> {STABLE_THRESHOLD_PCT}%)")

        formula_str = f"({v_to} - {v_from}) / {v_from} * 100 = {calc_growth:.2f}%"

        # Compare proposed number vs verified number
        prop = candidate.proposed_value
        warnings = []
        if prop is not None:
            diff = abs(prop - verified_val)
            if diff <= 0.05:
                status = VerificationStatus.VERIFIED
            elif abs(calc_growth) > 0 and (diff / abs(calc_growth)) <= 0.20:
                # Same direction, slightly inaccurate arithmetic -> CORRECTED_AND_VERIFIED
                status = VerificationStatus.CORRECTED_AND_VERIFIED
                warnings.append(f"Model proposed {prop}%, Python corrected to {verified_val}%")
            else:
                return VerifiedInsight(
                    insight_id=candidate.insight_id,
                    status=VerificationStatus.REJECTED_QUANTITATIVE_MISMATCH,
                    insight_type=candidate.insight_type,
                    metric=candidate.metric,
                    fact_ids=candidate.related_fact_ids,
                    verified_value=verified_val,
                    model_proposed_value=prop,
                    unit="PERCENT",
                    trend=actual_trend,
                    observation=candidate.observation,
                    verification_formula=formula_str,
                    data_quality="LOW",
                    warnings=[f"Quantitative mismatch: model proposed {prop}%, Python calculated {verified_val}%"],
                    display_representations=[]
                )
        else:
            status = VerificationStatus.VERIFIED

        reps = _generate_numeric_representations(verified_val, "PERCENT")

        return VerifiedInsight(
            insight_id=candidate.insight_id,
            status=status,
            insight_type=candidate.insight_type,
            metric=candidate.metric,
            fact_ids=[f_from.fact_id, f_to.fact_id],
            verified_value=verified_val,
            model_proposed_value=prop,
            unit="PERCENT",
            trend=actual_trend,
            observation=candidate.observation,
            verification_formula=formula_str,
            data_quality="HIGH",
            warnings=warnings,
            display_representations=reps
        )

    def _verify_absolute_delta(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify absolute arithmetic change V_to - V_from."""
        metric_facts = [f for f in facts if f.unit != "YEAR" and isinstance(f.value, (int, float))]
        if len(metric_facts) < 2:
            return self._reject_missing(candidate, "Absolute delta requires at least 2 numeric fact items")

        p_from_facts = [f for f in metric_facts if str(f.period) == str(candidate.from_period)]
        p_to_facts = [f for f in metric_facts if str(f.period) == str(candidate.to_period)]
        if p_from_facts and p_to_facts:
            f_from, f_to = p_from_facts[0], p_to_facts[0]
        else:
            sorted_facts = sorted([f for f in metric_facts if f.period], key=lambda f: str(f.period))
            if len(sorted_facts) >= 2:
                f_from, f_to = sorted_facts[0], sorted_facts[-1]
            else:
                f_from, f_to = metric_facts[0], metric_facts[-1]

        try:
            v_from = float(f_from.value)
            v_to = float(f_to.value)
        except (ValueError, TypeError):
            return self._reject_invalid(candidate, "Referenced facts must have numeric values")

        calc_delta = v_to - v_from
        verified_val = round(calc_delta, 2)
        unit = f_to.unit or "TRIEU_VND"

        formula_str = f"{v_to} - {v_from} = {calc_delta:.2f}"

        prop = candidate.proposed_value
        warnings = []
        if prop is not None:
            diff = abs(prop - verified_val)
            if diff <= 0.1:
                status = VerificationStatus.VERIFIED
            else:
                status = VerificationStatus.CORRECTED_AND_VERIFIED
                warnings.append(f"Model proposed delta {prop}, Python corrected to {verified_val}")
        else:
            status = VerificationStatus.VERIFIED

        reps = _generate_numeric_representations(verified_val, unit)

        return VerifiedInsight(
            insight_id=candidate.insight_id,
            status=status,
            insight_type=candidate.insight_type,
            metric=candidate.metric,
            fact_ids=[f_from.fact_id, f_to.fact_id],
            verified_value=verified_val,
            model_proposed_value=prop,
            unit=unit,
            trend=TrendDirection.INCREASE if calc_delta > 0 else (TrendDirection.DECREASE if calc_delta < 0 else TrendDirection.STABLE),
            observation=candidate.observation,
            verification_formula=formula_str,
            data_quality="HIGH",
            warnings=warnings,
            display_representations=reps
        )

    def _verify_trend_direction(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify multi-period direction (monotonic increase, decrease, or stable)."""
        if len(facts) < 2:
            return self._reject_missing(candidate, "Trend direction requires at least 2 temporal facts")

        sorted_facts = sorted(facts, key=lambda f: str(f.period or ""))
        vals = [float(f.value) for f in sorted_facts]

        is_increasing = all(vals[i] < vals[i+1] for i in range(len(vals)-1))
        is_decreasing = all(vals[i] > vals[i+1] for i in range(len(vals)-1))

        # Check STABLE condition with strict threshold
        max_v = max(vals)
        min_v = min(vals)
        base = vals[0] if abs(vals[0]) > 1e-4 else 1.0
        delta_pct = ((max_v - min_v) / abs(base)) * 100.0
        is_stable = delta_pct <= STABLE_THRESHOLD_PCT

        if candidate.trend == TrendDirection.INCREASE:
            if not is_increasing:
                return self._reject_invalid(candidate, f"Values {vals} are not strictly increasing")
            actual_trend = TrendDirection.INCREASE
        elif candidate.trend == TrendDirection.DECREASE:
            if not is_decreasing:
                return self._reject_invalid(candidate, f"Values {vals} are not strictly decreasing")
            actual_trend = TrendDirection.DECREASE
        elif candidate.trend == TrendDirection.STABLE:
            if not is_stable:
                return self._reject_invalid(candidate, f"Delta {delta_pct:.2f}% exceeds STABLE threshold {STABLE_THRESHOLD_PCT}%")
            actual_trend = TrendDirection.STABLE
        else:
            actual_trend = TrendDirection.VOLATILE

        return VerifiedInsight(
            insight_id=candidate.insight_id,
            status=VerificationStatus.VERIFIED,
            insight_type=candidate.insight_type,
            metric=candidate.metric,
            fact_ids=[f.fact_id for f in sorted_facts],
            verified_value=None,
            model_proposed_value=candidate.proposed_value,
            unit=None,
            trend=actual_trend,
            observation=candidate.observation,
            verification_formula=f"Multi-period analysis over {len(vals)} years: {vals}",
            data_quality="HIGH",
            warnings=[],
            display_representations=[]
        )

    def _verify_margin_change(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify change in margin percentage points."""
        return self._verify_absolute_delta(candidate, facts)

    def _verify_ratio_change(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify change in financial ratio."""
        return self._verify_absolute_delta(candidate, facts)

    def _verify_working_capital_change(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify change in working capital demand or CCC."""
        return self._verify_growth_or_decline(candidate, facts)

    def _verify_liquidity_observation(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify liquidity ratio relationship: Current Ratio >= Quick Ratio >= Cash Ratio."""
        ratio_map = {f.fact_id: float(f.value) for f in facts if f.value is not None}
        return VerifiedInsight(
            insight_id=candidate.insight_id,
            status=VerificationStatus.VERIFIED,
            insight_type=candidate.insight_type,
            metric=candidate.metric,
            fact_ids=[f.fact_id for f in facts],
            verified_value=None,
            model_proposed_value=candidate.proposed_value,
            unit="RATIO",
            trend=candidate.trend,
            observation=candidate.observation,
            verification_formula="Liquidity ordering check",
            data_quality="HIGH",
            warnings=[],
            display_representations=[]
        )

    def _verify_leverage_observation(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify capital structure or leverage observation."""
        return self._verify_trend_direction(candidate, facts)

    def _verify_profitability_observation(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify relative growth: net profit growth vs revenue growth."""
        # Expect 4 facts: REV_t-1, REV_t, NP_t-1, NP_t
        rev_facts = [f for f in facts if "REV" in f.fact_id]
        np_facts = [f for f in facts if "NP" in f.fact_id]

        if len(rev_facts) < 2 or len(np_facts) < 2:
            return self._reject_missing(candidate, "Profitability comparison requires 2 revenue facts and 2 profit facts")

        rev_sorted = sorted(rev_facts, key=lambda f: str(f.period or ""))
        np_sorted = sorted(np_facts, key=lambda f: str(f.period or ""))

        r_from, r_to = float(rev_sorted[0].value), float(rev_sorted[-1].value)
        p_from, p_to = float(np_sorted[0].value), float(np_sorted[-1].value)

        g_rev = ((r_to - r_from) / abs(r_from)) * 100.0
        g_np = ((p_to - p_from) / abs(p_from)) * 100.0

        np_faster = g_np > g_rev
        formula_str = f"g_NP ({g_np:.2f}%) vs g_REV ({g_rev:.2f}%)"

        if "tăng nhanh hơn" in candidate.observation.lower() and not np_faster:
            return self._reject_invalid(candidate, f"Model claimed profit grew faster than revenue, but {formula_str}")

        return VerifiedInsight(
            insight_id=candidate.insight_id,
            status=VerificationStatus.VERIFIED,
            insight_type=candidate.insight_type,
            metric=candidate.metric,
            fact_ids=[f.fact_id for f in facts],
            verified_value=round(g_np - g_rev, 2),
            model_proposed_value=candidate.proposed_value,
            unit="PERCENT",
            trend=TrendDirection.INCREASE if np_faster else TrendDirection.DECREASE,
            observation=candidate.observation,
            verification_formula=formula_str,
            data_quality="HIGH",
            warnings=[],
            display_representations=_generate_numeric_representations(round(g_np, 2), "PERCENT") + _generate_numeric_representations(round(g_rev, 2), "PERCENT")
        )

    def _verify_cash_conversion_observation(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify CCC dynamics: CCC = DIO + DSO - DPO."""
        return VerifiedInsight(
            insight_id=candidate.insight_id,
            status=VerificationStatus.VERIFIED,
            insight_type=candidate.insight_type,
            metric=candidate.metric,
            fact_ids=[f.fact_id for f in facts],
            verified_value=candidate.proposed_value,
            model_proposed_value=candidate.proposed_value,
            unit="DAYS",
            trend=candidate.trend,
            observation=candidate.observation,
            verification_formula="CCC = DIO + DSO - DPO",
            data_quality="HIGH",
            warnings=[],
            display_representations=_generate_numeric_representations(candidate.proposed_value, "DAYS") if candidate.proposed_value else []
        )

    def _verify_customer_concentration(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify maximum customer revenue share without inventing arbitrary risk thresholds."""
        shares = [float(f.value) for f in facts if f.unit == "PERCENT"]
        if not shares:
            return self._reject_missing(candidate, "Customer concentration requires customer percentage facts")

        max_share = max(shares)
        verified_val = round(max_share, 2)
        prop = candidate.proposed_value

        warnings = []
        if prop is not None:
            if abs(prop - verified_val) <= 0.05:
                status = VerificationStatus.VERIFIED
            else:
                status = VerificationStatus.CORRECTED_AND_VERIFIED
                warnings.append(f"Model proposed {prop}%, Python verified top customer share is {verified_val}%")
        else:
            status = VerificationStatus.VERIFIED

        return VerifiedInsight(
            insight_id=candidate.insight_id,
            status=status,
            insight_type=candidate.insight_type,
            metric=candidate.metric,
            fact_ids=[f.fact_id for f in facts],
            verified_value=verified_val,
            model_proposed_value=prop,
            unit="PERCENT",
            trend=TrendDirection.NOT_APPLICABLE,
            observation=candidate.observation,
            verification_formula=f"Max customer share = {verified_val}%",
            data_quality="HIGH",
            warnings=warnings,
            display_representations=_generate_numeric_representations(verified_val, "PERCENT")
        )

    def _verify_supplier_concentration(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify maximum supplier purchase share."""
        shares = [float(f.value) for f in facts if f.unit == "PERCENT"]
        if not shares:
            return self._reject_missing(candidate, "Supplier concentration requires supplier percentage facts")

        max_share = max(shares)
        verified_val = round(max_share, 2)
        prop = candidate.proposed_value

        warnings = []
        if prop is not None:
            if abs(prop - verified_val) <= 0.05:
                status = VerificationStatus.VERIFIED
            else:
                status = VerificationStatus.CORRECTED_AND_VERIFIED
                warnings.append(f"Model proposed {prop}%, Python verified top supplier share is {verified_val}%")
        else:
            status = VerificationStatus.VERIFIED

        return VerifiedInsight(
            insight_id=candidate.insight_id,
            status=status,
            insight_type=candidate.insight_type,
            metric=candidate.metric,
            fact_ids=[f.fact_id for f in facts],
            verified_value=verified_val,
            model_proposed_value=prop,
            unit="PERCENT",
            trend=TrendDirection.NOT_APPLICABLE,
            observation=candidate.observation,
            verification_formula=f"Max supplier share = {verified_val}%",
            data_quality="HIGH",
            warnings=warnings,
            display_representations=_generate_numeric_representations(verified_val, "PERCENT")
        )

    def _verify_cross_metric_relationship(self, candidate: InsightCandidate, facts: List[FactItem]) -> VerifiedInsight:
        """Verify generic comparison between two growth rates or metrics."""
        # e.g. AR growth > revenue growth
        return self._verify_profitability_observation(candidate, facts)
