"""Enums for the Section A canonical data foundation."""

from enum import Enum


class DataBehavior(str, Enum):
    """Approved Section A field behavior."""

    DOCUMENT_EXTRACTED = "DOCUMENT_EXTRACTED"
    RM_PROVIDED = "RM_PROVIDED"
    RM_SELECTED = "RM_SELECTED"
    RM_CONFIRMED = "RM_CONFIRMED"
    CROSS_SECTION_LINKED = "CROSS_SECTION_LINKED"


class ReadinessState(str, Enum):
    """Approved Section A readiness states.

    The evaluation engine for these states is deliberately out of scope for
    this phase; the enum exists so later workflow code can use stable values.
    """

    READY = "READY"
    MISSING_RM_INPUT = "MISSING_RM_INPUT"
    NEEDS_RM_CONFIRMATION = "NEEDS_RM_CONFIRMATION"
    PENDING_SECTION_DEPENDENCY = "PENDING_SECTION_DEPENDENCY"
    OPTIONAL_EMPTY = "OPTIONAL_EMPTY"


class FactValueType(str, Enum):
    """Generic value types needed by approved Section A fields."""

    TEXT = "TEXT"
    TEXT_IDENTIFIER = "TEXT_IDENTIFIER"
    DATE = "DATE"
    YEAR = "YEAR"
    DATE_OR_YEAR_OR_TEXT = "DATE_OR_YEAR_OR_TEXT"
    MONETARY_AMOUNT = "MONETARY_AMOUNT"
    PERCENTAGE = "PERCENTAGE"
    NUMBER = "NUMBER"
    SELECTION = "SELECTION"
    REPEATABLE_TEXT_LIST = "REPEATABLE_TEXT_LIST"
    TEXT_OR_DATE_PERIOD = "TEXT_OR_DATE_PERIOD"


class RequirementMode(str, Enum):
    """Approved requiredness semantics for Section A field definitions."""

    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    CONDITIONAL = "CONDITIONAL"
    REQUIRED_WHEN_EVIDENCE_AVAILABLE = "REQUIRED_WHEN_EVIDENCE_AVAILABLE"


class ConditionalRequirementKind(str, Enum):
    """Machine-readable conditional requirement types."""

    FIELD_EQUALS = "FIELD_EQUALS"
    FIELD_PRESENT = "FIELD_PRESENT"
    BUSINESS_CONDITION = "BUSINESS_CONDITION"


class RMConfirmationMode(str, Enum):
    """Whether a field requires RM confirmation before final Section A use."""

    NONE = "NONE"
    REQUIRED = "REQUIRED"
    WHEN_EVIDENCE_NOT_EXPLICIT = "WHEN_EVIDENCE_NOT_EXPLICIT"


class SourceCategory(str, Enum):
    """Source categories shared with the broader case-data architecture."""

    DOCUMENT_EXTRACTED = "DOCUMENT_EXTRACTED"
    RM_PROVIDED = "RM_PROVIDED"
    RM_SELECTED = "RM_SELECTED"
    RM_CONFIRMED = "RM_CONFIRMED"
    DETERMINISTIC_CALCULATION = "DETERMINISTIC_CALCULATION"
    CROSS_SECTION_LINKED = "CROSS_SECTION_LINKED"


class CandidateStatus(str, Enum):
    """Status for a candidate value before or after canonical selection."""

    CANDIDATE = "CANDIDATE"
    CONFLICTING = "CONFLICTING"
    NEEDS_RM_CONFIRMATION = "NEEDS_RM_CONFIRMATION"
    SELECTED_CANONICAL = "SELECTED_CANONICAL"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ConflictState(str, Enum):
    """Fact-level conflict state.

    Multiple candidates alone do not imply conflict; this state changes only
    through explicit candidate status or explicit workflow operations.
    """

    NONE = "NONE"
    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"
