"""Authoritative Section A Document Renderer (Phase 14).

Orchestrates deterministic rendering of canonical Section A facts into Table 1
of an immutable working copy of the authoritative MSB MB07 template.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Mapping, Sequence

from ..template_verification.verifier import (
    AUTHORITATIVE_MB07_SHA256,
    MB07TemplateVerifier,
    TemplateVerificationError,
)
from .binding_map import BindingType, FieldBinding, SECTION_A_BINDING_MAP
from .docx_mutator import SectionADocxMutator
from .models import CanonicalFact
from .validator import SectionAValidationResult, SectionAValidator


class SectionARenderingError(Exception):
    """Raised when Section A rendering fails validation, verification, or formatting."""


@dataclass(frozen=True)
class SectionARenderResult:
    """Outcome of rendering Section A into an MB07 Word document.

    Attributes:
        output_path: Absolute path to the generated working copy DOCX.
        is_success: True if the document was successfully validated and rendered.
        fields_rendered: Canonical keys written to Table 1.
        fields_skipped: Canonical keys with no value or intentionally omitted.
        unresolved_fields: Canonical keys marked as UNRESOLVED in the binding map.
    """

    output_path: str
    is_success: bool
    fields_rendered: tuple[str, ...]
    fields_skipped: tuple[str, ...]
    unresolved_fields: tuple[str, ...]


def _format_value_for_binding(value: Any, binding: FieldBinding) -> str:
    """Format a canonical fact value for rendering into DOCX."""
    if isinstance(value, (list, tuple)):
        formatted = ", ".join(str(item).strip() for item in value if item is not None)
    elif isinstance(value, float):
        if value.is_integer():
            formatted = f"{int(value):,}"
        else:
            formatted = f"{value:,.2f}".rstrip("0").rstrip(".")
    elif isinstance(value, int):
        formatted = f"{value:,}"
    else:
        formatted = str(value).strip()

    # Strip existing suffix or prefix if already in value to prevent duplicate labels
    if binding.suffix and formatted.endswith(binding.suffix):
        formatted = formatted[: -len(binding.suffix)].strip()
    if binding.prefix and formatted.startswith(binding.prefix):
        formatted = formatted[len(binding.prefix) :].strip()

    return formatted


class SectionARenderer:
    """Renders canonical Section A facts into an authoritative MB07 template copy."""

    def __init__(
        self,
        verifier: MB07TemplateVerifier | None = None,
        validator: SectionAValidator | None = None,
        binding_map: dict[str, FieldBinding] | None = None,
    ) -> None:
        self.verifier = verifier or MB07TemplateVerifier()
        self.validator = validator or SectionAValidator()
        self.binding_map = binding_map or SECTION_A_BINDING_MAP

    def render(
        self,
        facts: Mapping[str, CanonicalFact],
        template_path: str,
        output_path: str,
        skip_validation: bool = False,
    ) -> SectionARenderResult:
        """Render Section A facts into an immutable working copy of the template.

        Args:
            facts: Dictionary mapping canonical keys to CanonicalFact instances.
            template_path: Path to the authoritative MB07 template.
            output_path: Path where the mutated working copy will be written.
            skip_validation: If False, blocks rendering if validation produces errors.

        Returns:
            SectionARenderResult with details of rendered and unresolved fields.

        Raises:
            SectionARenderingError: If validation fails or the template is invalid.
        """
        # 1. Validation check
        if not skip_validation:
            facts_dict = dict(facts)
            validation: SectionAValidationResult = self.validator.validate(facts_dict)
            if not validation.is_valid:
                errors_str = "; ".join(validation.errors)
                raise SectionARenderingError(
                    f"Validation failed with {len(validation.errors)} error(s): {errors_str}"
                )

        # 2. Verify authoritative template and create isolated working copy
        try:
            self.verifier.create_working_copy(template_path, output_path)
        except (TemplateVerificationError, FileNotFoundError, Exception) as exc:
            raise SectionARenderingError(
                f"Failed to verify template and create working copy: {exc}"
            ) from exc

        # 3. Instantiate mutator and clear stale placeholders
        mutator = SectionADocxMutator(output_path)
        mutator.clear_sample_placeholders()

        fields_rendered: list[str] = []
        fields_skipped: list[str] = []
        unresolved_fields: list[str] = []
        row_offset = mutator.row_offset

        # 4. Apply each canonical field
        for key, binding in self.binding_map.items():
            if binding.binding_type == BindingType.UNRESOLVED:
                unresolved_fields.append(key)
                continue

            fact = facts.get(key)
            if fact is None or not fact.has_value or fact.value is None or fact.value.value is None:
                fields_skipped.append(key)
                continue

            raw_val = fact.value.value
            formatted_val = _format_value_for_binding(raw_val, binding)
            target_row = (binding.row_index + row_offset) if binding.row_index is not None else None

            try:
                if binding.binding_type == BindingType.SIMPLE_CELL:
                    if target_row is not None and binding.cell_index is not None:
                        # Append suffix if specified in binding
                        if binding.suffix and not formatted_val.endswith(binding.suffix):
                            display_val = f"{formatted_val}{binding.suffix}" if binding.suffix == "%" else f"{formatted_val} {binding.suffix}"
                        else:
                            display_val = formatted_val
                        mutator.set_cell_text(target_row, binding.cell_index, display_val)
                        fields_rendered.append(key)

                elif binding.binding_type == BindingType.PREFIXED_TEXT:
                    if target_row is not None and binding.cell_index is not None:
                        mutator.set_prefixed_text(
                            row_index=target_row,
                            cell_index=binding.cell_index,
                            prefix=binding.prefix,
                            value=formatted_val,
                            suffix=binding.suffix,
                        )
                        fields_rendered.append(key)

                elif binding.binding_type == BindingType.FORM_CHECKBOX_GROUP:
                    if target_row is not None:
                        val_str = str(raw_val).strip()
                        selected_idx = binding.checkbox_options.get(val_str)
                        mutator.set_checkbox(target_row, selected_idx, selected_value=val_str)
                        fields_rendered.append(key)

                elif binding.binding_type == BindingType.CONTENT_CONTROL_DROPDOWN:
                    if target_row is not None:
                        mutator.set_sdt_dropdown_text(target_row, formatted_val)
                        fields_rendered.append(key)

            except Exception as exc:
                raise SectionARenderingError(
                    f"Error rendering canonical field '{key}' into row {target_row}: {exc}"
                ) from exc

        # 5. Save final document
        mutator.save(output_path)

        return SectionARenderResult(
            output_path=os.path.abspath(output_path),
            is_success=True,
            fields_rendered=tuple(fields_rendered),
            fields_skipped=tuple(fields_skipped),
            unresolved_fields=tuple(unresolved_fields),
        )
