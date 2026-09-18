from decimal import Decimal
import json
import unittest

from msb_eb_copilot.src.section_a import (
    CandidateStatus,
    CanonicalFact,
    CanonicalValue,
    ConflictState,
    ConditionalRequirementKind,
    DataBehavior,
    EvidenceCandidate,
    FactValueType,
    Provenance,
    ReadinessState,
    RequirementMode,
    RMConfirmationMode,
    SECTION_A_FIELD_REGISTRY,
    SourceCategory,
)


APPROVED_KEYS = {
    "company.legal_name",
    "company.short_name",
    "company.legal_type",
    "relationship.customer_status",
    "relationship.cif",
    "relationship.segment",
    "relationship.segment_other_description",
    "company.group_name",
    "company.registered_address",
    "company.registration_no",
    "company.registration_issue_date",
    "company.registration_issue_place",
    "company.operation_start_date_or_year",
    "company.legal_representative.name",
    "company.legal_representative.title",
    "proposal.credit_request_representative.name",
    "proposal.credit_request_representative.title",
    "compliance.restricted_credit_subject",
    "compliance.esg_assessment_required",
    "financial.latest_net_revenue",
    "financial.latest_revenue_year",
    "business.primary_industry.code_level_5",
    "business.primary_industry.name",
    "business.primary_industry.revenue_share_pct",
    "business.main_products",
    "capital.registered_capital",
    "capital.paid_in_capital",
    "capital.paid_in_capital_as_of",
    "internal_rating.case_id",
    "internal_rating.grade",
    "internal_rating.score",
    "credit_relation.loan_outstanding_at_msb",
    "credit_relation.total_credit_exposure_at_msb",
    "credit_relation.regulatory_limit_status",
    "approval.existing_limit.total",
    "approval.existing_limit.unsecured",
    "approval.proposed_limit.total",
    "approval.proposed_limit.unsecured",
    "approval.aggregate_limit.total",
    "approval.aggregate_limit.unsecured",
    "approval.authority",
    "approval.previous_approval_period",
    "proposal.request_type",
}


class SectionAFoundationTests(unittest.TestCase):
    def test_every_approved_key_exists_exactly_once(self):
        self.assertEqual(set(SECTION_A_FIELD_REGISTRY), APPROVED_KEYS)
        self.assertEqual(len(SECTION_A_FIELD_REGISTRY), 43)
        self.assertEqual(len(SECTION_A_FIELD_REGISTRY), len(APPROVED_KEYS))

    def test_no_duplicate_canonical_key_exists(self):
        keys = list(SECTION_A_FIELD_REGISTRY)
        self.assertEqual(len(keys), len(set(keys)))

    def test_rm_selected_allowed_values_match_spec(self):
        expected = {
            "relationship.customer_status": ("KH_MOI", "KH_HIEN_HUU"),
            "relationship.segment": ("LC", "LMC", "KHAC"),
            "compliance.restricted_credit_subject": ("CO", "KHONG"),
            "compliance.esg_assessment_required": ("BAT_BUOC_DANH_GIA", "KHONG_BAT_BUOC_DANH_GIA"),
            "credit_relation.regulatory_limit_status": ("VUOT_GIOI_HAN", "TRONG_GIOI_HAN"),
            "approval.authority": ("HĐTD&ĐT", "HĐQT", "HĐTDCC"),
            "proposal.request_type": ("TAI_CAP", "CAP_MOI"),
        }
        for key, allowed_values in expected.items():
            field = SECTION_A_FIELD_REGISTRY[key]
            self.assertIn(DataBehavior.RM_SELECTED, field.behaviors)
            self.assertEqual(field.allowed_values, allowed_values)

    def test_rm_selected_fields_have_no_automatic_default(self):
        for field in SECTION_A_FIELD_REGISTRY.values():
            if DataBehavior.RM_SELECTED in field.behaviors:
                self.assertFalse(hasattr(field, "default_value"))
                self.assertFalse(hasattr(field, "derived_value"))
                self.assertFalse(hasattr(field, "automatic_derivation_rule"))
                self.assertEqual(field.value_type, FactValueType.SELECTION)
                self.assertTrue(field.allowed_values)

    def test_requiredness_modes_distinguish_spec_semantics(self):
        self.assertEqual(SECTION_A_FIELD_REGISTRY["company.legal_name"].requirement_mode, RequirementMode.REQUIRED)
        self.assertEqual(SECTION_A_FIELD_REGISTRY["company.short_name"].requirement_mode, RequirementMode.OPTIONAL)
        self.assertEqual(SECTION_A_FIELD_REGISTRY["relationship.cif"].requirement_mode, RequirementMode.CONDITIONAL)
        self.assertEqual(
            SECTION_A_FIELD_REGISTRY["company.legal_type"].requirement_mode,
            RequirementMode.REQUIRED_WHEN_EVIDENCE_AVAILABLE,
        )

    def test_evidence_available_fields_are_not_unconditional_required(self):
        for key in (
            "company.legal_type",
            "company.registered_address",
            "company.registration_issue_date",
            "company.registration_issue_place",
            "financial.latest_net_revenue",
            "capital.registered_capital",
        ):
            field = SECTION_A_FIELD_REGISTRY[key]
            self.assertEqual(field.requirement_mode, RequirementMode.REQUIRED_WHEN_EVIDENCE_AVAILABLE)
            self.assertFalse(field.is_unconditionally_required)

    def test_financial_revenue_year_condition_is_structured(self):
        field = SECTION_A_FIELD_REGISTRY["financial.latest_revenue_year"]
        condition = field.conditional_requiredness
        self.assertEqual(field.requirement_mode, RequirementMode.CONDITIONAL)
        self.assertEqual(condition.kind, ConditionalRequirementKind.FIELD_PRESENT)
        self.assertEqual(condition.field_key, "financial.latest_net_revenue")

    def test_field_equals_conditions_are_structured(self):
        cif_condition = SECTION_A_FIELD_REGISTRY["relationship.cif"].conditional_requiredness
        self.assertEqual(cif_condition.kind, ConditionalRequirementKind.FIELD_EQUALS)
        self.assertEqual(cif_condition.field_key, "relationship.customer_status")
        self.assertEqual(cif_condition.equals, "KH_HIEN_HUU")

        segment_condition = SECTION_A_FIELD_REGISTRY["relationship.segment_other_description"].conditional_requiredness
        self.assertEqual(segment_condition.kind, ConditionalRequirementKind.FIELD_EQUALS)
        self.assertEqual(segment_condition.field_key, "relationship.segment")
        self.assertEqual(segment_condition.equals, "KHAC")

    def test_paid_in_capital_as_of_condition_is_structured(self):
        field = SECTION_A_FIELD_REGISTRY["capital.paid_in_capital_as_of"]
        condition = field.conditional_requiredness
        self.assertEqual(field.requirement_mode, RequirementMode.CONDITIONAL)
        self.assertEqual(condition.kind, ConditionalRequirementKind.FIELD_PRESENT)
        self.assertEqual(condition.field_key, "capital.paid_in_capital")

    def test_existing_limits_use_business_condition_code(self):
        for key in ("approval.existing_limit.total", "approval.existing_limit.unsecured"):
            field = SECTION_A_FIELD_REGISTRY[key]
            condition = field.conditional_requiredness
            self.assertEqual(field.requirement_mode, RequirementMode.CONDITIONAL)
            self.assertEqual(condition.kind, ConditionalRequirementKind.BUSINESS_CONDITION)
            self.assertEqual(condition.condition_code, "EXISTING_APPROVED_LIMIT_APPLIES")
            self.assertIsNone(condition.field_key)

    def test_rm_confirmation_policy_is_explicit(self):
        self.assertEqual(SECTION_A_FIELD_REGISTRY["company.group_name"].rm_confirmation_mode, RMConfirmationMode.REQUIRED)
        self.assertEqual(
            SECTION_A_FIELD_REGISTRY["company.operation_start_date_or_year"].rm_confirmation_mode,
            RMConfirmationMode.WHEN_EVIDENCE_NOT_EXPLICIT,
        )
        self.assertEqual(SECTION_A_FIELD_REGISTRY["capital.paid_in_capital"].rm_confirmation_mode, RMConfirmationMode.REQUIRED)
        self.assertEqual(SECTION_A_FIELD_REGISTRY["capital.paid_in_capital_as_of"].rm_confirmation_mode, RMConfirmationMode.REQUIRED)
        self.assertEqual(SECTION_A_FIELD_REGISTRY["company.legal_representative.name"].rm_confirmation_mode, RMConfirmationMode.NONE)
        self.assertEqual(SECTION_A_FIELD_REGISTRY["company.legal_representative.title"].rm_confirmation_mode, RMConfirmationMode.NONE)

    def test_business_registration_number_preserves_leading_zero(self):
        value = CanonicalValue("0305097236", FactValueType.TEXT_IDENTIFIER)
        self.assertEqual(value.to_dict()["value"], {"kind": "str", "value": "0305097236"})

    def test_monetary_value_preserves_explicit_unit_metadata(self):
        value = CanonicalValue(Decimal("123.45"), FactValueType.MONETARY_AMOUNT, unit="triệu đồng")
        self.assertEqual(value.unit, "triệu đồng")
        self.assertEqual(value.to_dict()["value"], {"kind": "decimal", "value": "123.45"})

    def test_multiple_evidence_candidates_can_coexist(self):
        fact = CanonicalFact("company.registration_issue_date")
        first = EvidenceCandidate(
            canonical_key="company.registration_issue_date",
            candidate_value="2007-07-25",
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            evidence_label="first registration date",
        )
        amendment = EvidenceCandidate(
            canonical_key="company.registration_issue_date",
            candidate_value="2025-10-30",
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            evidence_label="latest amendment date",
        )
        fact = fact.with_candidate(first).with_candidate(amendment)
        self.assertEqual(len(fact.candidates), 2)
        self.assertEqual(fact.conflict_state, ConflictState.NONE)
        self.assertFalse(fact.unresolved_conflict)
        self.assertIsNone(fact.value)

    def test_two_equal_value_candidates_can_coexist_without_conflict(self):
        candidate_a = EvidenceCandidate(
            canonical_key="capital.paid_in_capital",
            candidate_value=Decimal("500000"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
            provenance=Provenance(document_id="doc-a"),
        )
        candidate_b = EvidenceCandidate(
            canonical_key="capital.paid_in_capital",
            candidate_value=Decimal("500000"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
            provenance=Provenance(document_id="doc-b"),
        )
        fact = CanonicalFact("capital.paid_in_capital").with_candidate(candidate_a).with_candidate(candidate_b)
        self.assertEqual(len(fact.candidates), 2)
        self.assertEqual(fact.conflict_state, ConflictState.NONE)
        self.assertIsNone(fact.value)

    def test_explicit_conflicting_candidate_sets_unresolved_conflict(self):
        candidate = EvidenceCandidate(
            canonical_key="company.legal_representative.name",
            candidate_value="Candidate A",
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            status=CandidateStatus.CONFLICTING,
        )
        fact = CanonicalFact("company.legal_representative.name").with_candidate(candidate)
        self.assertEqual(fact.conflict_state, ConflictState.UNRESOLVED)
        self.assertTrue(fact.unresolved_conflict)

    def test_new_conflicting_candidate_reopens_resolved_conflict(self):
        candidate = EvidenceCandidate(
            canonical_key="company.legal_representative.name",
            candidate_value="Candidate B",
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            status=CandidateStatus.CONFLICTING,
        )
        fact = CanonicalFact(
            "company.legal_representative.name",
            conflict_state=ConflictState.RESOLVED,
        ).with_candidate(candidate)
        self.assertEqual(fact.conflict_state, ConflictState.UNRESOLVED)

    def test_conflict_can_be_marked_unresolved_explicitly(self):
        fact = CanonicalFact("company.registered_address").mark_conflict_unresolved()
        self.assertEqual(fact.conflict_state, ConflictState.UNRESOLVED)

    def test_conflicting_revenue_candidates_do_not_select_winner(self):
        hn_candidate = EvidenceCandidate(
            canonical_key="financial.latest_net_revenue",
            candidate_value=Decimal("6162331.83414"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
            period_context="HN 2025",
            status=CandidateStatus.CONFLICTING,
            provenance=Provenance(document_id="doc-hn", original_filename="fixture-hn.xlsx", sheet_name="Financial_Report"),
        )
        rl_candidate = EvidenceCandidate(
            canonical_key="financial.latest_net_revenue",
            candidate_value=Decimal("5518843.929542"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
            period_context="RL 2025",
            status=CandidateStatus.CONFLICTING,
            provenance=Provenance(document_id="doc-rl", original_filename="fixture-rl.xlsx", sheet_name="Financial_Report"),
        )
        fact = CanonicalFact("financial.latest_net_revenue").with_candidate(hn_candidate).with_candidate(rl_candidate)
        self.assertEqual(fact.conflict_state, ConflictState.UNRESOLVED)
        self.assertTrue(fact.unresolved_conflict)
        self.assertIsNone(fact.value)

    def test_rm_confirmation_preserves_original_evidence_history(self):
        candidate = EvidenceCandidate(
            canonical_key="capital.paid_in_capital",
            candidate_value=Decimal("500000"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
        )
        fact = CanonicalFact("capital.paid_in_capital").with_candidate(candidate)
        confirmed = fact.confirm_with_rm(
            CanonicalValue(Decimal("500000"), FactValueType.MONETARY_AMOUNT, unit="triệu đồng")
        )
        self.assertEqual(len(confirmed.candidates), 1)
        self.assertTrue(confirmed.confirmed_by_rm)
        self.assertEqual(confirmed.value.source_category, SourceCategory.RM_CONFIRMED)
        self.assertIsNone(confirmed.readiness_state)

    def test_normal_rm_confirmation_does_not_resolve_conflict(self):
        fact = CanonicalFact("financial.latest_net_revenue").mark_conflict_unresolved()
        confirmed = fact.confirm_with_rm(
            CanonicalValue(Decimal("5518843.929542"), FactValueType.MONETARY_AMOUNT, unit="triệu đồng")
        )
        self.assertEqual(confirmed.conflict_state, ConflictState.UNRESOLVED)
        self.assertTrue(confirmed.confirmed_by_rm)
        self.assertIsNone(confirmed.readiness_state)

    def test_explicit_conflict_resolution_with_rm_preserves_candidates(self):
        candidate_a = EvidenceCandidate(
            canonical_key="financial.latest_net_revenue",
            candidate_value=Decimal("6162331.83414"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
            status=CandidateStatus.CONFLICTING,
        )
        candidate_b = EvidenceCandidate(
            canonical_key="financial.latest_net_revenue",
            candidate_value=Decimal("5518843.929542"),
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            unit="triệu đồng",
            status=CandidateStatus.CONFLICTING,
        )
        fact = CanonicalFact("financial.latest_net_revenue").with_candidate(candidate_a).with_candidate(candidate_b)
        resolved = fact.resolve_conflict_with_rm(
            CanonicalValue(Decimal("5518843.929542"), FactValueType.MONETARY_AMOUNT, unit="triệu đồng")
        )
        self.assertEqual(len(resolved.candidates), 2)
        self.assertEqual(resolved.value.source_category, SourceCategory.RM_CONFIRMED)
        self.assertEqual(resolved.conflict_state, ConflictState.RESOLVED)
        self.assertIsNone(resolved.readiness_state)

    def test_conflict_resolution_requires_unresolved_conflict(self):
        value = CanonicalValue("RM choice", FactValueType.TEXT)
        for state in (ConflictState.NONE, ConflictState.RESOLVED):
            with self.subTest(state=state):
                with self.assertRaisesRegex(ValueError, "unresolved conflict"):
                    CanonicalFact("company.group_name", conflict_state=state).resolve_conflict_with_rm(value)

    def test_with_rm_value_accepts_only_provided_or_selected_sources(self):
        cases = (
            SourceCategory.RM_PROVIDED,
            SourceCategory.RM_SELECTED,
        )
        for source in cases:
            with self.subTest(source=source):
                fact = CanonicalFact("relationship.customer_status").with_rm_value(
                    CanonicalValue("KH_MOI", FactValueType.SELECTION, source_category=source)
                )
                self.assertEqual(fact.value.source_category, source)

        with self.assertRaisesRegex(ValueError, "RM_PROVIDED or RM_SELECTED"):
            CanonicalFact("company.group_name").with_rm_value(
                CanonicalValue("Group name", FactValueType.TEXT, source_category=SourceCategory.RM_CONFIRMED)
            )

    def test_confirm_with_rm_creates_confirmed_source(self):
        fact = CanonicalFact("company.group_name").confirm_with_rm(
            CanonicalValue("Group name", FactValueType.TEXT, source_category=SourceCategory.DOCUMENT_EXTRACTED)
        )
        self.assertEqual(fact.value.source_category, SourceCategory.RM_CONFIRMED)
        self.assertTrue(fact.confirmed_by_rm)

    def test_fact_mutations_clear_stale_readiness(self):
        ready = CanonicalFact("company.group_name", readiness_state=ReadinessState.READY)
        rm_value = CanonicalValue("Group name", FactValueType.TEXT, source_category=SourceCategory.RM_PROVIDED)

        self.assertIsNone(ready.with_rm_value(rm_value).readiness_state)
        self.assertIsNone(ready.confirm_with_rm(rm_value).readiness_state)
        self.assertIsNone(ready.mark_conflict_unresolved().readiness_state)

        unresolved = CanonicalFact(
            "company.group_name",
            readiness_state=ReadinessState.READY,
            conflict_state=ConflictState.UNRESOLVED,
        )
        self.assertIsNone(unresolved.resolve_conflict_with_rm(rm_value).readiness_state)

    def test_adding_candidate_clears_stale_readiness(self):
        candidate = EvidenceCandidate(
            canonical_key="company.legal_name",
            candidate_value="Example Co",
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
        )
        fact = CanonicalFact("company.legal_name", readiness_state=ReadinessState.READY).with_candidate(candidate)
        self.assertIsNone(fact.readiness_state)

    def test_with_rm_value_does_not_assign_ready(self):
        fact = CanonicalFact("relationship.customer_status").with_rm_value(
            CanonicalValue("KH_MOI", FactValueType.SELECTION, source_category=SourceCategory.RM_SELECTED)
        )
        self.assertIsNone(fact.readiness_state)

    def test_confirm_with_rm_does_not_assign_ready(self):
        fact = CanonicalFact("company.group_name").confirm_with_rm(
            CanonicalValue("Group name", FactValueType.TEXT)
        )
        self.assertIsNone(fact.readiness_state)

    def test_cross_section_linked_pending_dependency_needs_no_numeric_placeholder(self):
        fact = CanonicalFact.pending_dependency("credit_relation.loan_outstanding_at_msb")
        self.assertIsNone(fact.value)
        self.assertTrue(fact.pending_section_dependency)
        self.assertEqual(fact.readiness_state, ReadinessState.PENDING_SECTION_DEPENDENCY)
        self.assertFalse(hasattr(fact, "_pending_section_dependency"))

    def test_pending_section_dependency_is_derived_from_readiness_state(self):
        fact = CanonicalFact("credit_relation.loan_outstanding_at_msb", readiness_state=ReadinessState.PENDING_SECTION_DEPENDENCY)
        self.assertTrue(fact.pending_section_dependency)
        cleared = CanonicalFact("credit_relation.loan_outstanding_at_msb")
        self.assertFalse(cleared.pending_section_dependency)

    def test_pending_dependency_cannot_have_canonical_value(self):
        with self.assertRaisesRegex(ValueError, "pending section dependency"):
            CanonicalFact(
                "credit_relation.loan_outstanding_at_msb",
                value=CanonicalValue(Decimal("0"), FactValueType.MONETARY_AMOUNT, unit="triệu đồng"),
                readiness_state=ReadinessState.PENDING_SECTION_DEPENDENCY,
            )

    def test_confirmed_by_rm_is_derived_from_value_source(self):
        fact = CanonicalFact("company.group_name", value=CanonicalValue("Group name", FactValueType.TEXT, source_category=SourceCategory.RM_CONFIRMED))
        self.assertTrue(fact.confirmed_by_rm)
        unconfirmed = CanonicalFact("company.group_name", value=CanonicalValue("Group name", FactValueType.TEXT, source_category=SourceCategory.DOCUMENT_EXTRACTED))
        self.assertFalse(unconfirmed.confirmed_by_rm)

    def test_resolving_section_e_dependency_uses_cross_section_source_without_ready(self):
        fact = CanonicalFact.pending_dependency("credit_relation.total_credit_exposure_at_msb")
        resolved = fact.with_cross_section_value(
            CanonicalValue(Decimal("2500"), FactValueType.MONETARY_AMOUNT, unit="triệu đồng")
        )
        self.assertEqual(resolved.value.source_category, SourceCategory.CROSS_SECTION_LINKED)
        self.assertFalse(resolved.pending_section_dependency)
        self.assertIsNone(resolved.readiness_state)
        self.assertNotEqual(resolved.value.source_category, SourceCategory.RM_PROVIDED)

    def test_aggregate_hmtd_fields_have_no_automatic_calculation_behavior(self):
        for key in ("approval.aggregate_limit.total", "approval.aggregate_limit.unsecured"):
            field = SECTION_A_FIELD_REGISTRY[key]
            self.assertIn(DataBehavior.RM_PROVIDED, field.behaviors)
            self.assertNotIn(DataBehavior.DOCUMENT_EXTRACTED, field.behaviors)
            self.assertNotIn(SourceCategory.DETERMINISTIC_CALCULATION.value, [behavior.value for behavior in field.behaviors])
            self.assertFalse(hasattr(field, "default_value"))
            self.assertFalse(hasattr(field, "derived_value"))
            self.assertFalse(hasattr(field, "automatic_derivation_rule"))

    def test_gas_south_values_are_not_production_defaults(self):
        forbidden = {
            "GAS SOUTH",
            "CÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM",
            "AgriS Gia Lai",
            "0305097236",
            "6162331.83414",
            "5518843.929542",
        }
        registry_text = json.dumps(
            {key: field.__dict__ for key, field in SECTION_A_FIELD_REGISTRY.items()},
            ensure_ascii=False,
            default=str,
        )
        for value in forbidden:
            self.assertNotIn(value, registry_text)

    def test_serialization_round_trip_for_fact_with_candidate(self):
        candidate = EvidenceCandidate(
            canonical_key="approval.proposed_limit.total",
            candidate_value=Decimal("1000.25"),
            source_category=SourceCategory.RM_PROVIDED,
            unit="triệu đồng",
        )
        fact = CanonicalFact("approval.proposed_limit.total").with_candidate(candidate).with_rm_value(
            CanonicalValue(Decimal("1000.25"), FactValueType.MONETARY_AMOUNT, unit="triệu đồng", source_category=SourceCategory.RM_PROVIDED)
        )
        round_trip = CanonicalFact.from_dict(fact.to_dict())
        self.assertEqual(round_trip, fact)

    def test_normalized_value_none_round_trips_as_none(self):
        candidate = EvidenceCandidate(
            canonical_key="company.legal_name",
            candidate_value="Example Co",
            source_category=SourceCategory.DOCUMENT_EXTRACTED,
            normalized_value=None,
        )
        serialized = candidate.to_dict()
        self.assertIsNone(serialized["normalized_value"])
        self.assertIsNone(EvidenceCandidate.from_dict(serialized).normalized_value)

    def test_decimal_and_tuple_payloads_round_trip(self):
        decimal_candidate = EvidenceCandidate(
            canonical_key="approval.proposed_limit.total",
            candidate_value=Decimal("100.10"),
            source_category=SourceCategory.RM_PROVIDED,
        )
        tuple_candidate = EvidenceCandidate(
            canonical_key="business.main_products",
            candidate_value=("Product A", "Product B"),
            source_category=SourceCategory.RM_PROVIDED,
        )
        self.assertEqual(EvidenceCandidate.from_dict(decimal_candidate.to_dict()).candidate_value, Decimal("100.10"))
        self.assertEqual(EvidenceCandidate.from_dict(tuple_candidate.to_dict()).candidate_value, ("Product A", "Product B"))

    def test_scalar_payloads_round_trip(self):
        for payload in ("Example Co", 123, True):
            with self.subTest(payload=payload):
                candidate = EvidenceCandidate(
                    canonical_key="company.legal_name",
                    candidate_value=payload,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                )
                self.assertEqual(EvidenceCandidate.from_dict(candidate.to_dict()).candidate_value, payload)
                self.assertIs(type(EvidenceCandidate.from_dict(candidate.to_dict()).candidate_value), type(payload))

    def test_serialized_kind_payload_mismatches_are_rejected(self):
        invalid_payloads = (
            {"kind": "str", "value": 123},
            {"kind": "int", "value": "123"},
            {"kind": "int", "value": True},
            {"kind": "bool", "value": 1},
            {"kind": "decimal", "value": 123},
            {"kind": "decimal", "value": "not-a-decimal"},
            {"kind": "tuple", "value": ("A", "B")},
            {"kind": "tuple", "value": ["A", 2]},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                data = {
                    "canonical_key": "company.legal_name",
                    "candidate_value": payload,
                    "source_category": SourceCategory.DOCUMENT_EXTRACTED.value,
                }
                with self.assertRaises((TypeError, ValueError)):
                    EvidenceCandidate.from_dict(data)

    def test_invalid_confidence_values_are_rejected(self):
        for confidence in (-0.01, 1.01):
            with self.assertRaises(ValueError):
                EvidenceCandidate(
                    canonical_key="company.legal_name",
                    candidate_value="Example Co",
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=confidence,
                )
        for confidence in ("0.5", True):
            with self.assertRaises(TypeError):
                EvidenceCandidate(
                    canonical_key="company.legal_name",
                    candidate_value="Example Co",
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=confidence,
                )

    def test_valid_confidence_values_are_preserved(self):
        for confidence in (0.0, 0.5, 1.0):
            candidate = EvidenceCandidate(
                canonical_key="company.legal_name",
                candidate_value="Example Co",
                source_category=SourceCategory.DOCUMENT_EXTRACTED,
                confidence=confidence,
            )
            self.assertEqual(candidate.confidence, confidence)
            self.assertEqual(EvidenceCandidate.from_dict(candidate.to_dict()).confidence, confidence)

    def test_text_identifier_rejects_integer_payload(self):
        with self.assertRaises(TypeError):
            CanonicalValue(305097236, FactValueType.TEXT_IDENTIFIER)

    def test_field_registry_requiredness_and_conditional_metadata(self):
        self.assertEqual(SECTION_A_FIELD_REGISTRY["relationship.customer_status"].requirement_mode, RequirementMode.REQUIRED)
        self.assertEqual(
            SECTION_A_FIELD_REGISTRY["relationship.cif"].conditional_requiredness.field_key,
            "relationship.customer_status",
        )
        self.assertEqual(
            SECTION_A_FIELD_REGISTRY["relationship.segment_other_description"].conditional_requiredness.equals,
            "KHAC",
        )
        self.assertEqual(
            SECTION_A_FIELD_REGISTRY["capital.paid_in_capital_as_of"].conditional_requiredness.field_key,
            "capital.paid_in_capital",
        )


if __name__ == "__main__":
    unittest.main()
