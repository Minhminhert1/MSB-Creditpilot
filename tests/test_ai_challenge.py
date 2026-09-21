# -*- coding: utf-8 -*-
"""Tests for the "AI Credit Challenge" workspace: deterministic, evidence-
grounded analyzers, the safe (verified, fallback-on-failure) LLM enrichment
step, RM response persistence, and per-case state isolation.

AI Challenge is a credit REVIEWER, never an approval model -- these tests
assert it never outputs approve/reject/safe/unsafe language and never
fabricates facts or evidence it doesn't have.
"""

from unittest.mock import patch

import pytest

from msb_eb_copilot.src.ai_challenge.analyzers import (
    analyze_business,
    analyze_credit,
    analyze_data_consistency,
    analyze_financial,
    analyze_renewal_changes,
)
from msb_eb_copilot.src.ai_challenge.engine import (
    AIChallengeEngine,
    ENRICHMENT_INCOMPLETE_WARNING_VI,
    _rewrite_is_grounded,
    _contains_forbidden_language,
)
from msb_eb_copilot.src.ai_challenge.models import ChallengeSeverity, ChallengeStatus, EnrichmentStatus
from msb_eb_copilot.src.ai_challenge.store import AIChallengeStore, ChallengeItemNotFoundError, ChallengeRunStatus
from msb_eb_copilot.src.renewal.change_detection import build_change_set, extract_new_canonical_snapshot
from msb_eb_copilot.src.renewal.models import ChangeStatus, RenewalBaselineField

PSD_CASE_DATA = {
    "customer": {"name": "CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO", "address": "TP.HCM"},
    "section_c": {
        "customers": [
            {"name": "CTCP Đầu tư Thế Giới Di Động (MWG)", "share": 4.49},
            {"name": "Mạng lưới đại lý", "share": 24.84},
        ],
        "suppliers": [{"name": "Dell Global B.V", "share": 28.08}],
    },
    "section_d": {
        "years": ["2024", "2025"],
        "net_revenue": [5702529.0, 7819398.0],       # +37.1%
        "net_profit_after_tax": [89729.0, 92000.0],  # +2.5% (much less than revenue growth -> margin decline)
        "total_assets": [2810436.0, 4683423.0],
        "current_assets": [2723355.0, 4600702.0],
        "equity": [597826.0, 729343.0],
        "inventories": [525688.0, 965402.0],          # +83.6%
        "receivables": [723020.0, 1475029.0],         # +104.0%
        "short_term_debt": [1537823.0, 2572040.0],    # +67.3%
    },
    "section_e": {
        "cic_date": "31/12/2025",
        "history_status": "100% Nhóm 1 (Đủ tiêu chuẩn) trong 24 tháng gần nhất.",
    },
}


class TestFinancialAnalyzer:
    def test_uses_canonical_data_produces_real_computed_numbers(self):
        items = analyze_financial(PSD_CASE_DATA)
        assert len(items) >= 3
        margin_item = next(i for i in items if i.id == "fin_margin_decline")
        # The percentages in the observation must match what's actually computable
        # from the canonical series above (37.1% revenue growth, ~2.5% profit growth).
        assert "37.1%" in margin_item.observation
        assert margin_item.category.value == "FINANCIAL"

    def test_no_challenge_when_growth_is_healthy(self):
        healthy_data = {
            "section_d": {
                "years": ["2024", "2025"],
                "net_revenue": [1000.0, 1100.0],
                "net_profit_after_tax": [100.0, 130.0],  # profit grows faster than revenue
                "total_assets": [1000.0, 1050.0],
                "current_assets": [500.0, 520.0],
                "equity": [500.0, 520.0],
                "inventories": [100.0, 105.0],
                "receivables": [100.0, 108.0],
                "short_term_debt": [100.0, 102.0],
            }
        }
        items = analyze_financial(healthy_data)
        assert not any(i.id == "fin_margin_decline" for i in items)
        assert not any(i.id == "fin_inventory_growth" for i in items)

    def test_facts_used_never_fabricates_page_or_evidence(self):
        """K: challenge never invents page/evidence it doesn't actually have."""
        items = analyze_financial(PSD_CASE_DATA)
        for item in items:
            for fact in item.facts_used:
                assert fact.page is None
                assert fact.evidence is None
                assert fact.source  # a real, non-fabricated source label (e.g. "BCTC 2025")


class TestBusinessAnalyzer:
    def test_flags_customer_concentration_above_threshold(self):
        items = analyze_business({"section_c": {"customers": [{"name": "Big Corp", "share": 55.0}]}})
        assert any(i.id == "biz_customer_concentration" and i.severity == ChallengeSeverity.HIGH for i in items)

    def test_no_flag_when_diversified(self):
        items = analyze_business({"section_c": PSD_CASE_DATA["section_c"]})
        assert not any(i.id == "biz_customer_concentration" for i in items)


class TestCreditAnalyzer:
    def test_group1_still_gets_a_neutral_observation_not_treated_as_automatically_safe(self):
        """Do NOT interpret CIC Group 1 as automatically low risk."""
        items = analyze_credit(PSD_CASE_DATA)
        assert len(items) == 1
        item = items[0]
        assert "nhóm 1" in item.observation.lower()
        assert "không đồng nghĩa" in item.risk_hypothesis.lower()
        assert item.severity == ChallengeSeverity.LOW  # low PRIORITY, not "safe"
        assert not _contains_forbidden_language(item.risk_hypothesis)

    def test_non_group1_gets_higher_severity(self):
        items = analyze_credit({"section_e": {"history_status": "Nhóm 3 - Nợ dưới tiêu chuẩn", "cic_date": "01/01/2026"}})
        assert items[0].severity == ChallengeSeverity.HIGH


class TestDataConsistencyAnalyzer:
    def test_flags_structurally_impossible_asset_values(self):
        items = analyze_data_consistency({"section_d": {
            "years": ["2025"], "total_assets": [100.0], "current_assets": [200.0],
            "net_revenue": [1], "net_profit_after_tax": [1], "equity": [1],
        }})
        assert any(i.id == "data_assets_inconsistent" for i in items)

    def test_flags_missing_required_fields(self):
        items = analyze_data_consistency({"section_d": {"years": ["2025"]}})
        assert any(i.id == "data_missing_financial_fields" for i in items)


class TestRenewalChallengeIntegration:
    def test_renewal_changes_can_feed_challenge_context(self):
        """RENEWAL-SPECIFIC: material CHANGED/CONFLICT/REMOVED items become challenges."""
        old_baseline = {
            "financial.net_revenue_latest": RenewalBaselineField(
                canonical_path="financial.net_revenue_latest", label="Doanh thu thuần",
                value="7.200 tỷ VND", source="MB07 kỳ trước",
            ),
        }
        change_set = build_change_set("PSD", old_baseline, extract_new_canonical_snapshot(PSD_CASE_DATA))
        items = analyze_renewal_changes(change_set)
        assert any(i.id.startswith("renewal_changed_") for i in items)
        # UNCHANGED items never produce a challenge.
        unchanged_paths = {i.canonical_path for i in change_set.items if i.status == ChangeStatus.UNCHANGED}
        assert not any(i.id.endswith(p) for i in items for p in unchanged_paths)

    def test_conflict_changes_produce_high_severity_challenges(self):
        snapshot = extract_new_canonical_snapshot(PSD_CASE_DATA)
        snapshot["financial.equity_latest"].value = "5.000 tỷ VND"
        old_baseline = {
            "financial.equity_latest": RenewalBaselineField(
                canonical_path="financial.equity_latest", label="Vốn chủ sở hữu",
                value="729 tỷ VND", source="MB07 kỳ trước",
            ),
        }
        change_set = build_change_set("PSD", old_baseline, snapshot)
        items = analyze_renewal_changes(change_set)
        conflict_item = next(i for i in items if i.id == "renewal_conflict_financial.equity_latest")
        assert conflict_item.severity == ChallengeSeverity.HIGH


class TestEngineGroundingAndSafety:
    def test_engine_generate_without_ai_client_is_fully_deterministic(self):
        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        assert result.case_id == "PSD"
        assert len(result.items) > 0
        for item in result.items:
            assert not _contains_forbidden_language(item.observation)
            assert not _contains_forbidden_language(item.risk_hypothesis)
            assert not _contains_forbidden_language(item.question)
            assert item.rm_status == ChallengeStatus.OPEN

    def test_never_outputs_approval_language(self):
        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        forbidden = ["phê duyệt", "approve", "reject", "khách hàng tốt", "khách hàng xấu", "an toàn tuyệt đối"]
        for item in result.items:
            combined = f"{item.title} {item.observation} {item.risk_hypothesis} {item.question}".lower()
            for phrase in forbidden:
                assert phrase not in combined

    def test_engine_integrates_renewal_change_set_when_provided(self):
        old_baseline = {
            "financial.net_revenue_latest": RenewalBaselineField(
                canonical_path="financial.net_revenue_latest", label="Doanh thu thuần",
                value="7.200 tỷ VND", source="MB07 kỳ trước",
            ),
        }
        change_set = build_change_set("PSD", old_baseline, extract_new_canonical_snapshot(PSD_CASE_DATA))
        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA, renewal_change_set=change_set)
        assert any(i.category.value == "RENEWAL" for i in result.items)

    def test_ai_enrichment_falls_back_to_deterministic_text_on_any_failure(self):
        """Robustness: if the AI client raises for ANY reason (no key, network,
        rate limit, garbage output), the deterministic template text survives."""
        class _BoomClient:
            @staticmethod
            def chat(**kwargs):
                raise RuntimeError("simulated GreenNode outage")

        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA, ai_client=_BoomClient)
        assert len(result.items) > 0
        # Original deterministic observation text (computed percentages) survives.
        margin_item = next(i for i in result.items if i.id == "fin_margin_decline")
        assert "37.1%" in margin_item.observation

    def test_ai_enrichment_rejects_output_that_drops_original_numbers(self):
        """Verification: a rewrite that silently changes/drops a number must be
        discarded (Zero Silent Fallback -- never let AI silently alter facts)."""
        assert _rewrite_is_grounded("Tăng 37.1% so với kỳ trước.", "Tăng 37.1% so với kỳ trước, đáng chú ý.") is True
        assert _rewrite_is_grounded("Tăng 37.1% so với kỳ trước.", "Tăng đáng kể so với kỳ trước.") is False  # number dropped
        assert _rewrite_is_grounded("Tăng 37.1%.", "Doanh nghiệp này an toàn tuyệt đối, tăng 37.1%.") is False  # forbidden phrase

    def test_ai_enrichment_uses_verified_rewrite_when_grounded(self):
        class _GoodClient:
            @staticmethod
            def chat(**kwargs):
                return (
                    "OBSERVATION: Doanh thu thuần tăng 37.1% nhưng lợi nhuận sau thuế chỉ tăng 2.6% so với kỳ trước.\n"
                    "RISK_HYPOTHESIS: Biên lợi nhuận có dấu hiệu chịu áp lực.\n"
                    "QUESTION: Đâu là nguyên nhân chính của sự chênh lệch này?"
                )

        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA, ai_client=_GoodClient)
        margin_item = next(i for i in result.items if i.id == "fin_margin_decline")
        assert "37.1%" in margin_item.observation
        assert "áp lực" in margin_item.risk_hypothesis


def _extract_prompt_fields(user_prompt: str) -> dict:
    fields = {}
    for line in user_prompt.splitlines():
        for key in ("OBSERVATION", "RISK_HYPOTHESIS", "QUESTION"):
            prefix = f"{key}:"
            if line.strip().upper().startswith(prefix):
                fields[key] = line.split(":", 1)[1].strip()
    return fields


def _echo_response(user_prompt: str) -> str:
    """A 'successful' rewrite client double: echoes the exact original text
    back, which is always trivially grounded (identical text always contains
    all of its own numeric tokens, never introduces forbidden language)."""
    fields = _extract_prompt_fields(user_prompt)
    return (
        f"OBSERVATION: {fields.get('OBSERVATION', '')}\n"
        f"RISK_HYPOTHESIS: {fields.get('RISK_HYPOTHESIS', '')}\n"
        f"QUESTION: {fields.get('QUESTION', '')}"
    )


class TestEnrichmentStatusMetadata:
    """Zero Silent Fallback: GreenNode enrichment is a NON-AUTHORITATIVE
    presentation enhancement -- its failure/rejection must never invalidate
    the deterministic (AUTHORITATIVE) challenge content, but must be
    explicitly observable via ChallengeSet.enrichment_status/enrichment_warning."""

    def test_a_no_ai_client_gives_not_requested(self):
        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        assert result.enrichment_status == EnrichmentStatus.NOT_REQUESTED
        assert result.enrichment_warning is None

    def test_b_all_enrichment_succeeds_gives_success(self):
        class _EchoClient:
            @staticmethod
            def chat(**kwargs):
                return _echo_response(kwargs["user_prompt"])

        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA, ai_client=_EchoClient)
        assert len(result.items) > 0
        assert result.enrichment_status == EnrichmentStatus.SUCCESS
        assert result.enrichment_warning is None

    def test_c_one_enrichment_failure_gives_partial(self):
        class _OneFailsClient:
            call_count = 0

            @classmethod
            def chat(cls, **kwargs):
                cls.call_count += 1
                if cls.call_count == 1:
                    raise RuntimeError("simulated transient failure")
                return _echo_response(kwargs["user_prompt"])

        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA, ai_client=_OneFailsClient)
        assert len(result.items) > 1  # need >1 item for PARTIAL to be meaningful
        assert result.enrichment_status == EnrichmentStatus.PARTIAL
        assert result.enrichment_warning == ENRICHMENT_INCOMPLETE_WARNING_VI

    def test_d_all_enrichment_calls_fail_gives_failed(self):
        class _AlwaysBoomClient:
            @staticmethod
            def chat(**kwargs):
                raise RuntimeError("simulated GreenNode outage")

        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA, ai_client=_AlwaysBoomClient)
        assert result.enrichment_status == EnrichmentStatus.FAILED
        assert result.enrichment_warning == ENRICHMENT_INCOMPLETE_WARNING_VI

    def test_e_grounding_rejection_contributes_to_partial_or_failed(self):
        class _NoNumbersClient:
            @staticmethod
            def chat(**kwargs):
                return "OBSERVATION: no numbers here at all\nRISK_HYPOTHESIS: also none\nQUESTION: why is that?"

        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA, ai_client=_NoNumbersClient)
        assert result.enrichment_status in (EnrichmentStatus.PARTIAL, EnrichmentStatus.FAILED)
        assert result.enrichment_warning == ENRICHMENT_INCOMPLETE_WARNING_VI

    def test_f_forbidden_language_rejection_contributes_to_partial_or_failed(self):
        class _ForbiddenLanguageClient:
            @staticmethod
            def chat(**kwargs):
                fields = _extract_prompt_fields(kwargs["user_prompt"])
                return (
                    f"OBSERVATION: {fields.get('OBSERVATION', '')}\n"
                    f"RISK_HYPOTHESIS: {fields.get('RISK_HYPOTHESIS', '')}\n"
                    "QUESTION: Đây là khách hàng tốt, có nên cấp tín dụng không?"
                )

        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA, ai_client=_ForbiddenLanguageClient)
        assert result.enrichment_status in (EnrichmentStatus.PARTIAL, EnrichmentStatus.FAILED)
        for item in result.items:
            assert not _contains_forbidden_language(item.question)

    def test_g_deterministic_content_unchanged_after_failed_rewrite(self):
        baseline = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)  # ai_client=None -> pure deterministic

        class _AlwaysBoomClient:
            @staticmethod
            def chat(**kwargs):
                raise RuntimeError("simulated GreenNode outage")

        enriched = AIChallengeEngine.generate("PSD", PSD_CASE_DATA, ai_client=_AlwaysBoomClient)
        assert enriched.enrichment_status == EnrichmentStatus.FAILED

        baseline_by_id = {i.id: i for i in baseline.items}
        for item in enriched.items:
            assert item.observation == baseline_by_id[item.id].observation
            assert item.risk_hypothesis == baseline_by_id[item.id].risk_hypothesis
            assert item.question == baseline_by_id[item.id].question


class TestAnalyzerWarnings:
    """Zero Silent Fallback for OPTIONAL deterministic metric calculations:
    a failure must be visible, must never fabricate a result, and must not
    suppress other (unrelated) analyzers."""

    def test_h_ratio_calculation_exception_creates_analyzer_warning(self):
        with patch("msb_eb_copilot.src.ai_challenge.analyzers.compute_canonical_ratios", side_effect=RuntimeError("boom")):
            result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        assert any(
            w.component == "financial.current_ratio" and w.code == "DETERMINISTIC_CALCULATION_FAILED"
            for w in result.analyzer_warnings
        )

    def test_i_failed_ratio_calculation_does_not_fabricate_current_ratio(self):
        with patch("msb_eb_copilot.src.ai_challenge.analyzers.compute_canonical_ratios", side_effect=RuntimeError("boom")):
            result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        assert not any(i.id == "fin_current_ratio_decline" for i in result.items)

    def test_j_other_challenges_still_generate_after_ratio_failure(self):
        with patch("msb_eb_copilot.src.ai_challenge.analyzers.compute_canonical_ratios", side_effect=RuntimeError("boom")):
            result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        assert any(i.id == "fin_margin_decline" for i in result.items)
        assert any(i.id == "fin_inventory_growth" for i in result.items)
        assert any(i.category.value == "CREDIT" for i in result.items)

    def test_no_warning_when_ratio_calculation_succeeds(self):
        result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        assert result.analyzer_warnings == []

    def test_analyzer_warning_never_contains_technical_detail(self):
        """M: safe by construction -- component/code are fixed identifiers only."""
        with patch("msb_eb_copilot.src.ai_challenge.analyzers.compute_canonical_ratios", side_effect=RuntimeError("some internal traceback detail")):
            result = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        warning = result.analyzer_warnings[0]
        assert "traceback" not in warning.component.lower()
        assert "traceback" not in warning.code.lower()
        assert warning.message is None


class TestChallengeStoreIsolationAndPersistence:
    def test_case_switching_isolates_challenge_state(self):
        store = AIChallengeStore()
        cs_psd = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        cs_gas = AIChallengeEngine.generate("GAS_SOUTH", {"section_d": {}})
        store.set_challenge_set("PSD", cs_psd)
        store.set_challenge_set("GAS_SOUTH", cs_gas)

        assert store.get("PSD").challenge_set.case_id == "PSD"
        assert store.get("GAS_SOUTH").challenge_set.case_id == "GAS_SOUTH"
        assert len(store.get("PSD").challenge_set.items) != 0

    def test_unknown_case_state_is_not_run(self):
        store = AIChallengeStore()
        assert store.get("NOT_A_REAL_CASE") is None

    def test_mark_running_then_completed(self):
        store = AIChallengeStore()
        store.mark_running("PSD")
        assert store.get("PSD").run_status == ChallengeRunStatus.RUNNING
        store.set_challenge_set("PSD", AIChallengeEngine.generate("PSD", PSD_CASE_DATA))
        assert store.get("PSD").run_status == ChallengeRunStatus.COMPLETED

    def test_rm_response_answered_persists(self):
        store = AIChallengeStore()
        challenge_set = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        store.set_challenge_set("PSD", challenge_set)
        target_id = challenge_set.items[0].id

        item = store.respond("PSD", target_id, ChallengeStatus.ANSWERED, "RM đã giải trình lý do.")
        assert item.rm_status == ChallengeStatus.ANSWERED
        assert item.rm_response == "RM đã giải trình lý do."
        # Persisted -- reading again returns the same state.
        reloaded = store.get("PSD").challenge_set
        reloaded_item = next(i for i in reloaded.items if i.id == target_id)
        assert reloaded_item.rm_status == ChallengeStatus.ANSWERED

    def test_rm_response_not_applicable_persists_and_is_not_deleted(self):
        """Do not silently remove dismissed challenges -- preserve in audit trail."""
        store = AIChallengeStore()
        challenge_set = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        store.set_challenge_set("PSD", challenge_set)
        target_id = challenge_set.items[0].id
        original_count = len(challenge_set.items)

        store.respond("PSD", target_id, ChallengeStatus.NOT_APPLICABLE, "Không áp dụng cho hồ sơ này.")
        reloaded = store.get("PSD").challenge_set
        assert len(reloaded.items) == original_count  # nothing removed
        item = next(i for i in reloaded.items if i.id == target_id)
        assert item.rm_status == ChallengeStatus.NOT_APPLICABLE
        assert item.rm_response == "Không áp dụng cho hồ sơ này."

    def test_respond_to_unknown_challenge_raises(self):
        store = AIChallengeStore()
        store.set_challenge_set("PSD", AIChallengeEngine.generate("PSD", PSD_CASE_DATA))
        with pytest.raises(ChallengeItemNotFoundError):
            store.respond("PSD", "does-not-exist", ChallengeStatus.ANSWERED, "x")

    def test_progress_reflects_resolved_vs_open(self):
        challenge_set = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        assert challenge_set.progress["resolved"] == 0
        challenge_set.items[0].mark_answered("done")
        assert challenge_set.progress["resolved"] == 1
        assert challenge_set.progress["total"] == len(challenge_set.items)


class TestRMExplanationProvenanceSeparation:
    """M: RM_EXPLANATION must be clearly separated from SOURCE_FACT and never
    silently converted into a document-extracted fact."""

    def test_get_rm_explanations_only_includes_answered_items_with_content(self):
        challenge_set = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        challenge_set.items[0].mark_answered("Tồn kho tăng do chuẩn bị hàng Q4.")
        if len(challenge_set.items) > 1:
            challenge_set.items[1].mark_not_applicable("Không liên quan.")

        explanations = challenge_set.get_rm_explanations()
        assert len(explanations) == 1
        assert explanations[0]["rm_explanation"] == "Tồn kho tăng do chuẩn bị hàng Q4."
        assert explanations[0]["id"] == challenge_set.items[0].id

    def test_rm_explanation_is_never_added_to_facts_used(self):
        """An RM explanation must never be silently converted into a facts_used
        (SOURCE_FACT) entry."""
        challenge_set = AIChallengeEngine.generate("PSD", PSD_CASE_DATA)
        item = challenge_set.items[0]
        original_facts = list(item.facts_used)
        item.mark_answered("RM giải trình: do mùa vụ.")
        assert item.facts_used == original_facts  # unchanged by the RM response
