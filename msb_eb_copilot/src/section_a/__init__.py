"""Canonical Section A domain models.

This package is intentionally limited to Phase 1 and Phase 2 foundations:
field definitions plus fact/evidence state. It does not perform extraction,
readiness evaluation, UI workflow, or document rendering.
"""

from .enums import (
    CandidateStatus,
    ConflictState,
    DataBehavior,
    FactValueType,
    ConditionalRequirementKind,
    ReadinessState,
    RequirementMode,
    RMConfirmationMode,
    SourceCategory,
)
from .evidence import EvidenceCandidate, Provenance
from .binding_map import BindingType, FieldBinding, SECTION_A_BINDING_MAP
from .docx_mutator import SectionADocxMutator
from .field_definitions import SECTION_A_FIELD_REGISTRY, SectionAFieldDefinition
from .models import CanonicalFact, CanonicalValue
from .renderer import SectionARenderResult, SectionARenderer, SectionARenderingError

__all__ = [
    "BindingType",
    "CandidateStatus",
    "ConflictState",
    "CanonicalFact",
    "CanonicalValue",
    "ConditionalRequirementKind",
    "DataBehavior",
    "EvidenceCandidate",
    "FactValueType",
    "FieldBinding",
    "Provenance",
    "ReadinessState",
    "RequirementMode",
    "RMConfirmationMode",
    "SECTION_A_BINDING_MAP",
    "SECTION_A_FIELD_REGISTRY",
    "SectionADocxMutator",
    "SectionAFieldDefinition",
    "SectionARenderResult",
    "SectionARenderer",
    "SectionARenderingError",
    "SourceCategory",
]
