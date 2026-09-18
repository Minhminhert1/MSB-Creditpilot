"""Deterministic readiness evaluator for Section A canonical facts."""

from typing import Any

from .enums import (
    ConditionalRequirementKind,
    ConflictState,
    DataBehavior,
    ReadinessState,
    RequirementMode,
    RMConfirmationMode,
    SourceCategory,
)
from .field_definitions import SECTION_A_FIELD_REGISTRY, SectionAFieldDefinition
from .models import CanonicalFact


class SectionAReadinessEvaluator:
    """Evaluates the readiness state for each Section A canonical fact deterministically."""

    def evaluate_fact_readiness(
        self,
        fact: CanonicalFact,
        all_facts: dict[str, CanonicalFact],
    ) -> ReadinessState:
        """Calculate the readiness state for a single canonical fact in context."""
        key = fact.canonical_key
        field_def = SECTION_A_FIELD_REGISTRY.get(key)
        if field_def is None:
            raise KeyError(f"Unknown Section A canonical key: '{key}'.")

        # 1. Check pending cross-section dependency
        if fact.pending_section_dependency:
            return ReadinessState.PENDING_SECTION_DEPENDENCY

        # 2. Check unresolved conflicts
        if fact.conflict_state == ConflictState.UNRESOLVED or fact.unresolved_conflict:
            return ReadinessState.NEEDS_RM_CONFIRMATION

        # 3. Check RM confirmation requirement
        if fact.has_value:
            val = fact.value
            # If field strictly requires RM confirmation and hasn't been confirmed
            if (
                field_def.rm_confirmation_mode == RMConfirmationMode.REQUIRED
                and val.source_category != SourceCategory.RM_CONFIRMED
                and val.source_category != SourceCategory.RM_PROVIDED
            ):
                return ReadinessState.NEEDS_RM_CONFIRMATION
            return ReadinessState.READY

        # 4. If fact has NO value, evaluate requirement mode
        if field_def.requirement_mode == RequirementMode.REQUIRED:
            return ReadinessState.MISSING_RM_INPUT

        if field_def.requirement_mode == RequirementMode.OPTIONAL:
            return ReadinessState.OPTIONAL_EMPTY

        if field_def.requirement_mode == RequirementMode.REQUIRED_WHEN_EVIDENCE_AVAILABLE:
            # If candidates exist but none selected/confirmed, needs confirmation/input
            if fact.candidates:
                return ReadinessState.NEEDS_RM_CONFIRMATION
            return ReadinessState.OPTIONAL_EMPTY

        if field_def.requirement_mode == RequirementMode.CONDITIONAL:
            cond = field_def.conditional_requiredness
            if cond is None:
                return ReadinessState.OPTIONAL_EMPTY

            is_triggered = self._is_condition_triggered(cond, all_facts)
            if is_triggered:
                return ReadinessState.MISSING_RM_INPUT
            return ReadinessState.OPTIONAL_EMPTY

        return ReadinessState.OPTIONAL_EMPTY

    def evaluate_all(
        self,
        facts: dict[str, CanonicalFact],
    ) -> dict[str, ReadinessState]:
        """Evaluate readiness for all Section A facts in a case."""
        result: dict[str, ReadinessState] = {}
        for key, fact in facts.items():
            result[key] = self.evaluate_fact_readiness(fact, facts)
        return result

    def _is_condition_triggered(
        self,
        condition: Any,
        all_facts: dict[str, CanonicalFact],
    ) -> bool:
        if condition.kind == ConditionalRequirementKind.FIELD_EQUALS:
            target_fact = all_facts.get(condition.field_key)
            if target_fact and target_fact.has_value:
                return str(target_fact.value.value) == str(condition.equals)
            return False

        if condition.kind == ConditionalRequirementKind.FIELD_PRESENT:
            target_fact = all_facts.get(condition.field_key)
            return target_fact is not None and target_fact.has_value

        if condition.kind == ConditionalRequirementKind.BUSINESS_CONDITION:
            # Business condition defaults to not triggered unless explicit context indicates
            return False

        return False
