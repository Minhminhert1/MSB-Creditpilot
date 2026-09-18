"""Tests for Section A RM review session and workflow state (Phase 6)."""

from decimal import Decimal
import unittest

from msb_eb_copilot.src.section_a import (
    CandidateStatus,
    ConflictState,
    EvidenceCandidate,
    Provenance,
    ReadinessState,
    SECTION_A_FIELD_REGISTRY,
    SourceCategory,
)
from msb_eb_copilot.src.section_a.review_session import SectionAReviewSession


class SectionAReviewSessionTests(unittest.TestCase):
    """Test suite for SectionAReviewSession."""

    def setUp(self) -> None:
        self.session = SectionAReviewSession(case_id="case-2026-001")

    def test_initialization_contains_all_43_fields(self):
        self.assertEqual(len(self.session.facts), 43)
        self.assertEqual(set(self.session.facts.keys()), set(SECTION_A_FIELD_REGISTRY.keys()))

        # Section E dependent fields start as pending dependency
        loan_fact = self.session.get_fact("credit_relation.loan_outstanding_at_msb")
        self.assertTrue(loan_fact.pending_section_dependency)
        self.assertIsNone(loan_fact.value)

    def test_ingest_candidates_prefills_eligible_facts(self):
        cand = EvidenceCandidate(
            canonical_key="company.legal_name",
            candidate_value="CÔNG TY TNHH MTV THÉP MIỀN NAM - VNSTEEL",
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            confidence=0.95,
        )
        self.session.ingest_candidates([cand])
        fact = self.session.get_fact("company.legal_name")
        self.assertIsNotNone(fact.value)
        self.assertEqual(fact.value.value, "CÔNG TY TNHH MTV THÉP MIỀN NAM - VNSTEEL")
        self.assertEqual(fact.value.source_category, SourceCategory.DOCUMENT_EXTRACTED)

    def test_ingest_conflicting_candidates_sets_unresolved_without_value(self):
        cand_hn = EvidenceCandidate(
            canonical_key="financial.latest_net_revenue",
            candidate_value=Decimal("6162331.83414"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
            status=CandidateStatus.CONFLICTING,
        )
        cand_rl = EvidenceCandidate(
            canonical_key="financial.latest_net_revenue",
            candidate_value=Decimal("5518843.929542"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
            status=CandidateStatus.CONFLICTING,
        )
        self.session.ingest_candidates([cand_hn, cand_rl])
        fact = self.session.get_fact("financial.latest_net_revenue")
        self.assertEqual(fact.conflict_state, ConflictState.UNRESOLVED)
        self.assertTrue(fact.unresolved_conflict)
        self.assertIsNone(fact.value)  # No winner auto-chosen!

    def test_set_rm_selected(self):
        # Valid selection
        updated = self.session.set_rm_selected("relationship.customer_status", "KH_HIEN_HUU")
        self.assertEqual(updated.value.value, "KH_HIEN_HUU")
        self.assertEqual(updated.value.source_category, SourceCategory.RM_SELECTED)

        # Invalid selection value rejected
        with self.assertRaises(ValueError):
            self.session.set_rm_selected("relationship.customer_status", "INVALID_STATUS")

        # Calling set_rm_selected on non-RM_SELECTED field rejected
        with self.assertRaises(ValueError):
            self.session.set_rm_selected("company.legal_name", "Some Name")

    def test_set_rm_provided(self):
        updated = self.session.set_rm_provided("approval.proposed_limit.total", Decimal("1500000"), unit="triệu đồng")
        self.assertEqual(updated.value.value, Decimal("1500000"))
        self.assertEqual(updated.value.source_category, SourceCategory.RM_PROVIDED)

    def test_confirm_fact_with_rm_preserves_candidates(self):
        cand = EvidenceCandidate(
            canonical_key="capital.paid_in_capital",
            candidate_value=Decimal("500000"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
        )
        self.session.ingest_candidates([cand])
        confirmed = self.session.confirm_fact_with_rm("capital.paid_in_capital", Decimal("500000"), unit="triệu đồng")
        self.assertEqual(confirmed.value.source_category, SourceCategory.RM_CONFIRMED)
        self.assertEqual(len(confirmed.candidates), 1)

    def test_resolve_conflict_with_rm(self):
        cand_hn = EvidenceCandidate(
            canonical_key="financial.latest_net_revenue",
            candidate_value=Decimal("6162331.83414"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
            status=CandidateStatus.CONFLICTING,
        )
        cand_rl = EvidenceCandidate(
            canonical_key="financial.latest_net_revenue",
            candidate_value=Decimal("5518843.929542"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
            status=CandidateStatus.CONFLICTING,
        )
        self.session.ingest_candidates([cand_hn, cand_rl])

        # RM resolves conflict by choosing the audited consolidated revenue
        resolved = self.session.resolve_conflict_with_rm(
            "financial.latest_net_revenue",
            Decimal("6162331.83414"),
            unit="triệu đồng",
        )
        self.assertEqual(resolved.conflict_state, ConflictState.RESOLVED)
        self.assertFalse(resolved.unresolved_conflict)
        self.assertEqual(resolved.value.source_category, SourceCategory.RM_CONFIRMED)
        self.assertEqual(len(resolved.candidates), 2)  # All candidates preserved in audit trail

    def test_link_cross_section_fact(self):
        fact_before = self.session.get_fact("credit_relation.loan_outstanding_at_msb")
        self.assertTrue(fact_before.pending_section_dependency)

        linked = self.session.link_cross_section_fact(
            "credit_relation.loan_outstanding_at_msb",
            Decimal("1200000"),
            unit="triệu đồng",
        )
        self.assertEqual(linked.value.source_category, SourceCategory.CROSS_SECTION_LINKED)
        self.assertFalse(linked.pending_section_dependency)

    def test_serialization_round_trip(self):
        self.session.set_rm_selected("relationship.customer_status", "KH_MOI")
        serialized = self.session.to_dict()
        reconstructed = SectionAReviewSession.from_dict(serialized)
        self.assertEqual(reconstructed.case_id, self.session.case_id)
        self.assertEqual(
            reconstructed.get_fact("relationship.customer_status").value.value,
            "KH_MOI",
        )


if __name__ == "__main__":
    unittest.main()
