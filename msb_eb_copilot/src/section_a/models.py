"""Canonical fact and value models for Section A."""

from dataclasses import dataclass, replace
from typing import Any

from .enums import CandidateStatus, ConflictState, FactValueType, ReadinessState, SourceCategory
from .evidence import EvidenceCandidate, FactValuePayload, _deserialize_payload, _serialize_value, _validate_payload


@dataclass(frozen=True)
class CanonicalValue:
    """Typed canonical value payload.

    Identifiers such as business registration numbers should use a string
    payload with ``FactValueType.TEXT_IDENTIFIER`` so leading zeros are kept.
    """

    value: FactValuePayload
    value_type: FactValueType
    unit: str | None = None
    source_category: SourceCategory | None = None

    def __post_init__(self) -> None:
        _validate_payload(self.value)
        if self.value_type == FactValueType.TEXT_IDENTIFIER and not isinstance(self.value, str):
            raise TypeError("TEXT_IDENTIFIER values must be stored as strings.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": _serialize_value(self.value),
            "value_type": self.value_type.value,
            "unit": self.unit,
            "source_category": self.source_category.value if self.source_category else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CanonicalValue":
        source = data.get("source_category")
        return cls(
            value=_deserialize_payload(data["value"]),
            value_type=FactValueType(data["value_type"]),
            unit=data.get("unit"),
            source_category=SourceCategory(source) if source else None,
        )


@dataclass(frozen=True)
class CanonicalFact:
    """Current state for one Section A canonical business fact.

    The model can hold no canonical value, one or more candidates, RM-provided
    or RM-selected values, RM-confirmed values, cross-section linked values, and
    pending dependency states. Evidence is append-only from the perspective of
    these helpers so confirmation does not erase extraction history.
    """

    canonical_key: str
    value: CanonicalValue | None = None
    readiness_state: ReadinessState | None = None
    conflict_state: ConflictState = ConflictState.NONE
    candidates: tuple[EvidenceCandidate, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.readiness_state == ReadinessState.PENDING_SECTION_DEPENDENCY and self.value is not None:
            raise ValueError("A pending section dependency cannot have a canonical value.")

    @property
    def has_value(self) -> bool:
        return self.value is not None

    @property
    def has_multiple_candidates(self) -> bool:
        return len(self.candidates) > 1

    @property
    def unresolved_conflict(self) -> bool:
        return self.conflict_state == ConflictState.UNRESOLVED

    @property
    def pending_section_dependency(self) -> bool:
        return self.readiness_state == ReadinessState.PENDING_SECTION_DEPENDENCY

    @property
    def confirmed_by_rm(self) -> bool:
        return self.value is not None and self.value.source_category == SourceCategory.RM_CONFIRMED

    @classmethod
    def pending_dependency(cls, canonical_key: str) -> "CanonicalFact":
        return cls(
            canonical_key=canonical_key,
            readiness_state=ReadinessState.PENDING_SECTION_DEPENDENCY,
        )

    def with_candidate(self, candidate: EvidenceCandidate) -> "CanonicalFact":
        if candidate.canonical_key != self.canonical_key:
            raise ValueError("Candidate canonical key does not match fact canonical key.")
        candidates = self.candidates + (candidate,)
        conflict_state = self.conflict_state
        if candidate.status == CandidateStatus.CONFLICTING:
            conflict_state = ConflictState.UNRESOLVED
        return replace(
            self,
            candidates=candidates,
            conflict_state=conflict_state,
            readiness_state=None,
        )

    def mark_conflict_unresolved(self) -> "CanonicalFact":
        return replace(self, conflict_state=ConflictState.UNRESOLVED, readiness_state=None)

    def with_rm_value(self, value: CanonicalValue) -> "CanonicalFact":
        if value.source_category not in {
            SourceCategory.RM_PROVIDED,
            SourceCategory.RM_SELECTED,
        }:
            raise ValueError("with_rm_value requires an RM_PROVIDED or RM_SELECTED source category.")
        return replace(self, value=value, readiness_state=None)

    def confirm_with_rm(self, value: CanonicalValue) -> "CanonicalFact":
        confirmed_value = replace(value, source_category=SourceCategory.RM_CONFIRMED)
        return replace(self, value=confirmed_value, readiness_state=None)

    def resolve_conflict_with_rm(self, value: CanonicalValue) -> "CanonicalFact":
        if self.conflict_state != ConflictState.UNRESOLVED:
            raise ValueError("Conflict resolution requires an unresolved conflict.")
        confirmed_value = replace(value, source_category=SourceCategory.RM_CONFIRMED)
        return replace(
            self,
            value=confirmed_value,
            conflict_state=ConflictState.RESOLVED,
            readiness_state=None,
        )

    def with_cross_section_value(self, value: CanonicalValue) -> "CanonicalFact":
        linked_value = replace(value, source_category=SourceCategory.CROSS_SECTION_LINKED)
        return replace(self, value=linked_value, readiness_state=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_key": self.canonical_key,
            "value": self.value.to_dict() if self.value else None,
            "readiness_state": self.readiness_state.value if self.readiness_state else None,
            "conflict_state": self.conflict_state.value,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CanonicalFact":
        value = data.get("value")
        state = data.get("readiness_state")
        return cls(
            canonical_key=data["canonical_key"],
            value=CanonicalValue.from_dict(value) if value else None,
            readiness_state=ReadinessState(state) if state else None,
            conflict_state=ConflictState(data.get("conflict_state", ConflictState.NONE.value)),
            candidates=tuple(EvidenceCandidate.from_dict(item) for item in data.get("candidates", [])),
            notes=data.get("notes"),
        )
