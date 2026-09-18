"""RM review and input workflow session for Section A canonical facts."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence

from .enums import (
    CandidateStatus,
    ConflictState,
    DataBehavior,
    FactValueType,
    RMConfirmationMode,
    SourceCategory,
)
from .evidence import EvidenceCandidate
from .field_definitions import SECTION_A_FIELD_REGISTRY
from .models import CanonicalFact, CanonicalValue


class SectionAReviewSession:
    """Manages the lifecycle, pre-filling, and RM interactions for Section A facts of a case."""

    def __init__(self, case_id: str) -> None:
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case_id must be a non-empty string.")
        self.case_id = case_id.strip()

        # Initialize all 43 approved Section A canonical facts
        self._facts: dict[str, CanonicalFact] = {}
        for key in SECTION_A_FIELD_REGISTRY:
            if key in (
                "credit_relation.loan_outstanding_at_msb",
                "credit_relation.total_credit_exposure_at_msb",
            ):
                self._facts[key] = CanonicalFact.pending_dependency(key)
            else:
                self._facts[key] = CanonicalFact(canonical_key=key)

    @property
    def facts(self) -> dict[str, CanonicalFact]:
        """Current mapping of canonical keys to CanonicalFact models."""
        return dict(self._facts)

    def get_fact(self, canonical_key: str) -> CanonicalFact:
        """Retrieve the canonical fact for a given key."""
        if canonical_key not in self._facts:
            raise KeyError(f"Unknown Section A canonical key: '{canonical_key}'.")
        return self._facts[canonical_key]

    def ingest_candidates(self, candidates: Sequence[EvidenceCandidate]) -> None:
        """Pre-fill facts by ingesting extracted evidence candidates from documents.

        Preserves multiple candidates and marks conflicts as UNRESOLVED when conflicting evidence coexists.
        """
        for cand in candidates:
            key = cand.canonical_key
            if key not in self._facts:
                continue

            current_fact = self._facts[key]
            updated_fact = current_fact.with_candidate(cand)

            # Auto-propose value only if:
            # 1. Fact currently has no value.
            # 2. No unresolved conflict.
            # 3. Field allows DOCUMENT_EXTRACTED behavior.
            # 4. Field does NOT strictly require prior RM confirmation before use.
            field_def = SECTION_A_FIELD_REGISTRY[key]
            if (
                updated_fact.value is None
                and not updated_fact.unresolved_conflict
                and DataBehavior.DOCUMENT_EXTRACTED in field_def.behaviors
                and field_def.rm_confirmation_mode != RMConfirmationMode.REQUIRED
                and cand.status != CandidateStatus.CONFLICTING
            ):
                val_payload = cand.candidate_value
                unit = cand.unit
                # Pre-fill proposed extracted value
                updated_fact = CanonicalFact(
                    canonical_key=key,
                    value=CanonicalValue(
                        value=val_payload,
                        value_type=field_def.value_type,
                        unit=unit,
                        source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    ),
                    readiness_state=None,
                    conflict_state=updated_fact.conflict_state,
                    candidates=updated_fact.candidates,
                )

            self._facts[key] = updated_fact

    def set_rm_selected(self, canonical_key: str, selection: str) -> CanonicalFact:
        """Record an RM selection for an RM_SELECTED field."""
        field_def = SECTION_A_FIELD_REGISTRY.get(canonical_key)
        if field_def is None:
            raise KeyError(f"Unknown Section A canonical key: '{canonical_key}'.")

        if DataBehavior.RM_SELECTED not in field_def.behaviors:
            raise ValueError(f"Field '{canonical_key}' does not accept RM_SELECTED behavior.")

        if selection not in field_def.allowed_values:
            raise ValueError(
                f"Invalid selection '{selection}' for '{canonical_key}'. "
                f"Allowed values: {field_def.allowed_values}."
            )

        val = CanonicalValue(
            value=selection,
            value_type=FactValueType.SELECTION,
            source_category=SourceCategory.RM_SELECTED,
        )
        updated = self._facts[canonical_key].with_rm_value(val)
        self._facts[canonical_key] = updated
        return updated

    def set_rm_provided(
        self,
        canonical_key: str,
        value: Any,
        unit: str | None = None,
    ) -> CanonicalFact:
        """Record an RM provided value for an RM_PROVIDED field."""
        field_def = SECTION_A_FIELD_REGISTRY.get(canonical_key)
        if field_def is None:
            raise KeyError(f"Unknown Section A canonical key: '{canonical_key}'.")

        if DataBehavior.RM_PROVIDED not in field_def.behaviors:
            raise ValueError(f"Field '{canonical_key}' does not accept RM_PROVIDED behavior.")

        val = CanonicalValue(
            value=value,
            value_type=field_def.value_type,
            unit=unit,
            source_category=SourceCategory.RM_PROVIDED,
        )
        updated = self._facts[canonical_key].with_rm_value(val)
        self._facts[canonical_key] = updated
        return updated

    def confirm_fact_with_rm(
        self,
        canonical_key: str,
        confirmed_value: Any,
        unit: str | None = None,
    ) -> CanonicalFact:
        """Explicitly confirm a fact with the RM, preserving candidate history."""
        field_def = SECTION_A_FIELD_REGISTRY.get(canonical_key)
        if field_def is None:
            raise KeyError(f"Unknown Section A canonical key: '{canonical_key}'.")

        val = CanonicalValue(
            value=confirmed_value,
            value_type=field_def.value_type,
            unit=unit,
        )
        updated = self._facts[canonical_key].confirm_with_rm(val)
        self._facts[canonical_key] = updated
        return updated

    def resolve_conflict_with_rm(
        self,
        canonical_key: str,
        chosen_value: Any,
        unit: str | None = None,
    ) -> CanonicalFact:
        """Resolve an UNRESOLVED conflict explicitly by RM choice, preserving candidates."""
        field_def = SECTION_A_FIELD_REGISTRY.get(canonical_key)
        if field_def is None:
            raise KeyError(f"Unknown Section A canonical key: '{canonical_key}'.")

        val = CanonicalValue(
            value=chosen_value,
            value_type=field_def.value_type,
            unit=unit,
        )
        updated = self._facts[canonical_key].resolve_conflict_with_rm(val)
        self._facts[canonical_key] = updated
        return updated

    def link_cross_section_fact(
        self,
        canonical_key: str,
        value: Any,
        unit: str | None = None,
    ) -> CanonicalFact:
        """Link a value owned by another proposal section (e.g. Section E)."""
        field_def = SECTION_A_FIELD_REGISTRY.get(canonical_key)
        if field_def is None:
            raise KeyError(f"Unknown Section A canonical key: '{canonical_key}'.")

        if DataBehavior.CROSS_SECTION_LINKED not in field_def.behaviors:
            raise ValueError(f"Field '{canonical_key}' does not accept CROSS_SECTION_LINKED behavior.")

        val = CanonicalValue(
            value=value,
            value_type=field_def.value_type,
            unit=unit,
        )
        updated = self._facts[canonical_key].with_cross_section_value(val)
        self._facts[canonical_key] = updated
        return updated

    def to_dict(self) -> dict[str, Any]:
        """Serialize review session state to a dictionary."""
        return {
            "case_id": self.case_id,
            "facts": {k: f.to_dict() for k, f in self._facts.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SectionAReviewSession":
        """Reconstruct review session state from serialized dictionary."""
        session = cls(case_id=data["case_id"])
        facts_dict = data.get("facts", {})
        for key, fact_data in facts_dict.items():
            if key in session._facts:
                session._facts[key] = CanonicalFact.from_dict(fact_data)
        return session
