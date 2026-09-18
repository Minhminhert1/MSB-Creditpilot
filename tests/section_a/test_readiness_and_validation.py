"""Tests for Section A readiness states and deterministic validation (Phases 7 & 8)."""

from decimal import Decimal
import unittest

from msb_eb_copilot.src.section_a import (
    CandidateStatus,
    CanonicalFact,
    CanonicalValue,
    ConflictState,
    FactValueType,
    ReadinessState,
    SourceCategory,
)
from msb_eb_copilot.src.section_a.readiness import SectionAReadinessEvaluator
from msb_eb_copilot.src.section_a.review_session import SectionAReviewSession
from msb_eb_copilot.src.section_a.validator import SectionAValidator


class SectionAReadinessAndValidationTests(unittest.TestCase):
    """Test suite for Section A readiness evaluation and deterministic validation."""

    def setUp(self) -> None:
        self.evaluator = SectionAReadinessEvaluator()
        self.validator = SectionAValidator(self.evaluator)

    def test_required_empty_field_evaluates_to_missing_rm_input(self):
        fact = CanonicalFact("company.legal_name")
        state = self.evaluator.evaluate_fact_readiness(fact, {fact.canonical_key: fact})
        self.assertEqual(state, ReadinessState.MISSING_RM_INPUT)

    def test_optional_empty_field_evaluates_to_optional_empty(self):
        fact = CanonicalFact("company.short_name")
        state = self.evaluator.evaluate_fact_readiness(fact, {fact.canonical_key: fact})
        self.assertEqual(state, ReadinessState.OPTIONAL_EMPTY)

    def test_field_with_canonical_value_evaluates_to_ready(self):
        fact = CanonicalFact(
            "company.legal_name",
            value=CanonicalValue("Example Co", FactValueType.TEXT, source_category=SourceCategory.DOCUMENT_EXTRACTED),
        )
        state = self.evaluator.evaluate_fact_readiness(fact, {fact.canonical_key: fact})
        self.assertEqual(state, ReadinessState.READY)

    def test_unresolved_conflict_evaluates_to_needs_rm_confirmation(self):
        fact = CanonicalFact("financial.latest_net_revenue", conflict_state=ConflictState.UNRESOLVED)
        state = self.evaluator.evaluate_fact_readiness(fact, {fact.canonical_key: fact})
        self.assertEqual(state, ReadinessState.NEEDS_RM_CONFIRMATION)

    def test_rm_confirmation_required_mode_evaluates_to_needs_rm_confirmation(self):
        # company.group_name strictly requires RM confirmation
        fact = CanonicalFact(
            "company.group_name",
            value=CanonicalValue("Group A", FactValueType.TEXT, source_category=SourceCategory.DOCUMENT_EXTRACTED),
        )
        state = self.evaluator.evaluate_fact_readiness(fact, {fact.canonical_key: fact})
        self.assertEqual(state, ReadinessState.NEEDS_RM_CONFIRMATION)

        # After RM confirms, it evaluates to READY
        confirmed = fact.confirm_with_rm(fact.value)
        state_after = self.evaluator.evaluate_fact_readiness(confirmed, {confirmed.canonical_key: confirmed})
        self.assertEqual(state_after, ReadinessState.READY)

    def test_pending_section_dependency_evaluates_to_pending_dependency(self):
        fact = CanonicalFact.pending_dependency("credit_relation.loan_outstanding_at_msb")
        state = self.evaluator.evaluate_fact_readiness(fact, {fact.canonical_key: fact})
        self.assertEqual(state, ReadinessState.PENDING_SECTION_DEPENDENCY)

    def test_conditional_cif_readiness(self):
        # If KH_MOI -> CIF is OPTIONAL_EMPTY when blank
        status_moi = CanonicalFact(
            "relationship.customer_status",
            value=CanonicalValue("KH_MOI", FactValueType.SELECTION, source_category=SourceCategory.RM_SELECTED),
        )
        cif_fact = CanonicalFact("relationship.cif")
        all_facts_moi = {"relationship.customer_status": status_moi, "relationship.cif": cif_fact}
        self.assertEqual(
            self.evaluator.evaluate_fact_readiness(cif_fact, all_facts_moi),
            ReadinessState.OPTIONAL_EMPTY,
        )

        # If KH_HIEN_HUU -> CIF is MISSING_RM_INPUT when blank
        status_hh = CanonicalFact(
            "relationship.customer_status",
            value=CanonicalValue("KH_HIEN_HUU", FactValueType.SELECTION, source_category=SourceCategory.RM_SELECTED),
        )
        all_facts_hh = {"relationship.customer_status": status_hh, "relationship.cif": cif_fact}
        self.assertEqual(
            self.evaluator.evaluate_fact_readiness(cif_fact, all_facts_hh),
            ReadinessState.MISSING_RM_INPUT,
        )

    def test_validator_blocks_when_required_facts_missing(self):
        session = SectionAReviewSession("case-001")
        # Session initialized without values
        res = self.validator.validate(session.facts)
        self.assertFalse(res.is_valid)
        self.assertGreater(res.blocking_field_count, 0)
        self.assertTrue(any("Missing required RM input" in e for e in res.errors))
        self.assertTrue(any("pending dependency from Section E" in e for e in res.errors))

    def test_validator_enforces_cif_rule(self):
        session = SectionAReviewSession("case-001")
        session.set_rm_selected("relationship.customer_status", "KH_HIEN_HUU")
        res = self.validator.validate(session.facts)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("CIF code is mandatory" in e for e in res.errors))

    def test_validator_enforces_segment_other_description_rule(self):
        session = SectionAReviewSession("case-001")
        session.set_rm_selected("relationship.segment", "KHAC")
        res = self.validator.validate(session.facts)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Segment description is mandatory" in e for e in res.errors))

    def test_validator_enforces_revenue_year_rule(self):
        session = SectionAReviewSession("case-001")
        session.confirm_fact_with_rm("financial.latest_net_revenue", Decimal("1000000"), unit="triệu đồng")
        res = self.validator.validate(session.facts)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Latest revenue year is required" in e for e in res.errors))


if __name__ == "__main__":
    unittest.main()
