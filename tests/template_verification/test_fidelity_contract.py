"""Module: test_fidelity_contract.py
Description: Exhaustive test suite for MB07 Template Fidelity Contract.
Tests all invariant protections: table count, row growth, section margins,
fail-closed version validation, and StructureGuard enforcement.
"""

import os
import unittest
import tempfile
import docx
from docx.shared import Inches, Pt

from msb_eb_copilot.src.template_verification.structure_fingerprint import (
    DocumentStructureSnapshot,
    DynamicTableRule,
    StructureComparisonResult,
    compare_template_structure,
    snapshot_template_structure,
)
from msb_eb_copilot.src.template_rendering.structure_guard import (
    StructureGuard,
    MB07FidelityError,
    UnsupportedTemplateVersionError,
    validate_template_compatibility,
)
from msb_eb_copilot.src.template_rendering.safe_mutation import (
    SafeCellMutator,
    DynamicRowCloner,
)


class TestTemplateFidelityContract(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.template_path = os.path.join(self.temp_dir.name, "sample_template.docx")
        self.output_path = os.path.join(self.temp_dir.name, "sample_output.docx")

        # Build a synthetic 25-table template
        doc = docx.Document()
        for idx in range(25):
            p = doc.add_paragraph(f"Heading {idx}: ")
            if idx == 0:
                p.text = "Đơn vị trình"
            elif idx == 1:
                p.text = "Tên khách hàng - Mã số thuế"
            elif idx == 5:
                p.text = "NỘI DUNG ĐỀ XUẤT CẤP TÍN DỤNG"
            elif idx == 10:
                p.text = "HOẠT ĐỘNG KINH DOANH CỦA KHÁCH HÀNG"
            elif idx == 15:
                p.text = "TÌNH HÌNH TÀI CHÍNH DOANH NGHIỆP"
            elif idx == 20:
                p.text = "THÔNG TIN QUAN HỆ TÍN DỤNG CỦA KHÁCH HÀNG"

            tbl = doc.add_table(rows=3, cols=3)
            for r_i, r in enumerate(tbl.rows):
                for c_i, c in enumerate(r.cells):
                    c.text = f"Cell_{idx}_{r_i}_{c_i}"

        doc.save(self.template_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_validate_template_compatibility_valid(self):
        is_valid = validate_template_compatibility(self.template_path)
        self.assertTrue(is_valid)

    def test_validate_template_compatibility_incompatible_raises(self):
        # Create a blank 2-table doc
        bad_doc_path = os.path.join(self.temp_dir.name, "bad.docx")
        doc = docx.Document()
        doc.add_table(rows=1, cols=1)
        doc.save(bad_doc_path)

        with self.assertRaises(UnsupportedTemplateVersionError):
            validate_template_compatibility(bad_doc_path)

    def test_exact_structure_comparison_pass(self):
        # Copy template directly to output
        doc = docx.Document(self.template_path)
        doc.save(self.output_path)

        t_snap = snapshot_template_structure(self.template_path)
        o_snap = snapshot_template_structure(self.output_path)

        res = compare_template_structure(t_snap, o_snap)
        self.assertTrue(res.is_structurally_sound)
        self.assertTrue(res.is_exact_match)
        self.assertEqual(len(res.all_violations), 0)

    def test_table_count_shift_detected_as_violation(self):
        doc = docx.Document(self.template_path)
        # Add an extra unapproved table
        doc.add_table(rows=2, cols=2)
        doc.save(self.output_path)

        t_snap = snapshot_template_structure(self.template_path)
        o_snap = snapshot_template_structure(self.output_path)

        res = compare_template_structure(t_snap, o_snap, allow_table_expansion=False)
        self.assertFalse(res.is_structurally_sound)
        self.assertTrue(any("Table count altered" in v for v in res.all_violations))

    def test_static_table_row_growth_rejected_by_default(self):
        doc = docx.Document(self.template_path)
        # Grow rows on Table 0 without explicit permission
        t0 = doc.tables[0]
        DynamicRowCloner.clone_row(t0)
        doc.save(self.output_path)

        t_snap = snapshot_template_structure(self.template_path)
        o_snap = snapshot_template_structure(self.output_path)

        res = compare_template_structure(t_snap, o_snap, allow_row_growth=False)
        self.assertFalse(res.is_structurally_sound)
        self.assertTrue(any("row count altered without permission" in v for v in res.all_violations))

    def test_allowlisted_dynamic_row_growth_accepted(self):
        doc = docx.Document(self.template_path)
        # Grow rows on Table 20 (CIC relations)
        t20 = doc.tables[20]
        DynamicRowCloner.clone_row(t20)
        doc.save(self.output_path)

        t_snap = snapshot_template_structure(self.template_path)
        o_snap = snapshot_template_structure(self.output_path)

        rule = DynamicTableRule(table_index=20, binding_id="cic_credit_relations", allow_row_growth=True, max_growth=20)
        res = compare_template_structure(t_snap, o_snap, dynamic_table_rules=[rule])
        self.assertTrue(res.is_structurally_sound)
        self.assertEqual(len(res.all_violations), 0)
        self.assertTrue(any("grew" in msg for msg in res.allowed_mutations_observed))

    def test_margin_alteration_detected_as_violation(self):
        doc = docx.Document(self.template_path)
        # Alter section margins
        doc.sections[0].left_margin = Inches(0.2)
        doc.save(self.output_path)

        t_snap = snapshot_template_structure(self.template_path)
        o_snap = snapshot_template_structure(self.output_path)

        res = compare_template_structure(t_snap, o_snap)
        self.assertFalse(res.is_structurally_sound)
        self.assertTrue(any("left_margin_dxa altered" in v for v in res.all_violations))

    def test_structure_guard_verifies_successfully_on_safe_mutations(self):
        guard = StructureGuard(
            template_path=self.template_path,
            dynamic_table_rules=[
                DynamicTableRule(table_index=20, binding_id="cic_relations", allow_row_growth=True)
            ]
        )

        doc = docx.Document(self.template_path)
        # Mutate values safely in Table 0
        SafeCellMutator.set_cell_text(doc.tables[0].rows[0].cells[1], "NEW VALUE 1")
        SafeCellMutator.set_cell_text(doc.tables[0].rows[1].cells[1], "NEW VALUE 2")

        # Dynamically clone row in Table 20
        DynamicRowCloner.clone_row(doc.tables[20])

        doc.save(self.output_path)

        result = guard.verify(self.output_path, raise_on_violation=True)
        self.assertTrue(result.is_structurally_sound)


if __name__ == "__main__":
    unittest.main()
