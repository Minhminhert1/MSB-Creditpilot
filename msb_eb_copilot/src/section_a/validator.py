"""Deterministic business rules validator for Section A."""

from dataclasses import dataclass, field
from typing import Sequence

from .enums import ReadinessState
from .models import CanonicalFact
from .readiness import SectionAReadinessEvaluator


@dataclass(frozen=True)
class SectionAValidationResult:
    """Outcome of validating Section A facts for credit proposal assembly.

    Attributes:
        is_valid: True if all required facts are READY or OPTIONAL_EMPTY and rules pass.
        errors: List of blocking validation error messages.
        warnings: List of non-blocking warning messages.
        readiness_map: Dictionary mapping canonical keys to their ReadinessState.
    """

    is_valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    readiness_map: dict[str, ReadinessState] = field(default_factory=dict)

    @property
    def blocking_field_count(self) -> int:
        return len(self.errors)


class SectionAValidator:
    """Validates Section A facts against banking regulations and consistency rules."""

    def __init__(self, evaluator: SectionAReadinessEvaluator | None = None) -> None:
        self.evaluator = evaluator or SectionAReadinessEvaluator()

    def validate(self, facts: dict[str, CanonicalFact]) -> SectionAValidationResult:
        """Perform deterministic validation on a full set of Section A facts."""
        errors: list[str] = []
        warnings: list[str] = []

        readiness_map = self.evaluator.evaluate_all(facts)

        for key, state in readiness_map.items():
            if state == ReadinessState.MISSING_RM_INPUT:
                errors.append(f"Missing required RM input for field '{key}'.")
            elif state == ReadinessState.NEEDS_RM_CONFIRMATION:
                errors.append(f"Field '{key}' requires RM confirmation or conflict resolution.")
            elif state == ReadinessState.PENDING_SECTION_DEPENDENCY:
                errors.append(f"Field '{key}' is pending dependency from Section E.")

        # Business Rule 1: Customer Status vs CIF
        status_fact = facts.get("relationship.customer_status")
        cif_fact = facts.get("relationship.cif")
        if status_fact and status_fact.has_value and str(status_fact.value.value) == "KH_HIEN_HUU":
            if not cif_fact or not cif_fact.has_value:
                errors.append("CIF code is mandatory when customer status is 'KH_HIEN_HUU'.")

        # Business Rule 2: Segment vs Other Description
        segment_fact = facts.get("relationship.segment")
        desc_fact = facts.get("relationship.segment_other_description")
        if segment_fact and segment_fact.has_value and str(segment_fact.value.value) == "KHAC":
            if not desc_fact or not desc_fact.has_value:
                errors.append("Segment description is mandatory when segment is 'KHAC'.")

        # Business Rule 3: Revenue Year present when Net Revenue present
        rev_fact = facts.get("financial.latest_net_revenue")
        year_fact = facts.get("financial.latest_revenue_year")
        if rev_fact and rev_fact.has_value:
            if not year_fact or not year_fact.has_value:
                errors.append("Latest revenue year is required when latest net revenue is specified.")

        # Business Rule 4: Paid-in Capital As-Of date present when Paid-in Capital present
        paid_cap_fact = facts.get("capital.paid_in_capital")
        as_of_fact = facts.get("capital.paid_in_capital_as_of")
        if paid_cap_fact and paid_cap_fact.has_value:
            if not as_of_fact or not as_of_fact.has_value:
                errors.append("Paid-in capital as-of date is required when paid-in capital is specified.")

        is_valid = len(errors) == 0
        return SectionAValidationResult(
            is_valid=is_valid,
            errors=tuple(errors),
            warnings=tuple(warnings),
            readiness_map=readiness_map,
        )
