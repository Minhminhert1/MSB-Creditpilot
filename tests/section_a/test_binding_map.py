"""Tests for authoritative MB07 template binding map for Section A (Phase 11)."""

import unittest

from msb_eb_copilot.src.section_a.binding_map import (
    SECTION_A_BINDING_MAP,
    BindingType,
    FieldBinding,
)
from msb_eb_copilot.src.section_a.field_definitions import SECTION_A_FIELD_REGISTRY


class SectionABindingMapTests(unittest.TestCase):
    """Test suite for Phase 11 binding map integrity."""

    def test_all_canonical_fields_are_mapped(self):
        """Every canonical field in the registry must have an entry in the binding map."""
        registry_keys = set(SECTION_A_FIELD_REGISTRY.keys())
        binding_keys = set(SECTION_A_BINDING_MAP.keys())

        # Exact match of keys
        self.assertEqual(
            registry_keys,
            binding_keys,
            f"Difference between registry and bindings: {registry_keys.symmetric_difference(binding_keys)}",
        )
        self.assertEqual(len(binding_keys), 43)

    def test_unresolved_bindings_have_explicit_reasons(self):
        """Unresolved bindings must be clearly justified and marked."""
        unresolved_bindings = [
            b for b in SECTION_A_BINDING_MAP.values() if b.binding_type == BindingType.UNRESOLVED
        ]
        self.assertEqual(len(unresolved_bindings), 2)

        unresolved_keys = {b.canonical_key for b in unresolved_bindings}
        expected_unresolved = {
            "relationship.segment_other_description",
            "financial.latest_revenue_year",
        }
        self.assertEqual(unresolved_keys, expected_unresolved)

        for b in unresolved_bindings:
            self.assertIsNotNone(b.unresolved_reason)
            self.assertTrue(len(b.unresolved_reason.strip()) > 10)

    def test_resolved_bindings_have_valid_row_indices(self):
        """Table 1 in MB07 has 30 rows (index 0 to 29). All resolved bindings must fall within this range."""
        for key, binding in SECTION_A_BINDING_MAP.items():
            if binding.binding_type != BindingType.UNRESOLVED:
                self.assertIsNotNone(
                    binding.row_index,
                    f"Resolved binding {key} must have row_index",
                )
                self.assertTrue(
                    0 <= binding.row_index <= 29,
                    f"Binding {key} row_index {binding.row_index} out of bounds [0, 29]",
                )

    def test_checkbox_group_bindings_have_valid_options(self):
        """Form checkbox groups must map allowed selection values to non-negative checkbox indices."""
        checkbox_bindings = [
            b for b in SECTION_A_BINDING_MAP.values() if b.binding_type == BindingType.FORM_CHECKBOX_GROUP
        ]
        self.assertGreater(len(checkbox_bindings), 0)

        for binding in checkbox_bindings:
            self.assertGreater(len(binding.checkbox_options), 0, f"No options for {binding.canonical_key}")
            for opt, idx in binding.checkbox_options.items():
                self.assertIsInstance(opt, str)
                self.assertIsInstance(idx, int)
                self.assertGreaterEqual(idx, 0)

    def test_prefixed_text_bindings_have_prefix_or_suffix(self):
        """PREFIXED_TEXT bindings must provide either prefix or suffix."""
        prefixed_bindings = [
            b for b in SECTION_A_BINDING_MAP.values() if b.binding_type == BindingType.PREFIXED_TEXT
        ]
        self.assertGreater(len(prefixed_bindings), 0)

        for binding in prefixed_bindings:
            has_prefix = bool(binding.prefix and binding.prefix.strip())
            has_suffix = bool(binding.suffix and binding.suffix.strip())
            self.assertTrue(
                has_prefix or has_suffix,
                f"Prefixed binding {binding.canonical_key} must have prefix or suffix",
            )


if __name__ == "__main__":
    unittest.main()
