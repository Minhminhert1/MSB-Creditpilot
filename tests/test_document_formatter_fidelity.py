# -*- coding: utf-8 -*-
"""Regression tests for Fidelity-Safe DocumentFormatter.

Proves:
1. Template logo/drawing relationships survive polish().
2. Headers and footers survive across all sections.
3. Section count and section geometries survive.
4. Existing run font sizes and font names are not globally overwritten.
5. Existing paragraph alignments and spacings are strictly preserved.
6. Highlight removal works when keep_highlights=False.
7. Highlights and shading are preserved when keep_highlights=True.
8. StructureGuard verification passes on the polished document.
9. No p.text = ... or cell.text = ... run collapses occur.
10. Known placeholder dot lines are cleaned strictly at the run level.
"""

from __future__ import annotations
import os
import shutil
import tempfile
import unittest
import docx
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from msb_eb_copilot.src.document_formatter import DocumentFormatter
from msb_eb_copilot.src.template_rendering.structure_guard import StructureGuard


class TestDocumentFormatterFidelity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.template_path = os.path.join(
            base_dir, "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - thực hiện rà soát - tái cấp.docx"
        )
        if not os.path.exists(cls.template_path):
            cls.template_path = os.path.join(
                base_dir, "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - bản tham khảo.docx"
            )
        assert os.path.exists(cls.template_path), f"MB07 template not found at {cls.template_path}"

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_docx = os.path.join(self.temp_dir, "test_doc.docx")
        shutil.copyfile(self.template_path, self.test_docx)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_section_count_and_geometry_survive(self):
        """1. Section count, page dimensions, margins, and orientation must survive polish()."""
        doc_before = docx.Document(self.test_docx)
        orig_sections = len(doc_before.sections)
        orig_geometries = [
            (
                s.page_width,
                s.page_height,
                s.top_margin,
                s.bottom_margin,
                s.left_margin,
                s.right_margin,
                s.orientation,
            )
            for s in doc_before.sections
        ]

        output_path = os.path.join(self.temp_dir, "polished.docx")
        DocumentFormatter.polish(self.test_docx, output_path, keep_highlights=False)

        doc_after = docx.Document(output_path)
        self.assertEqual(len(doc_after.sections), orig_sections)

        after_geometries = [
            (
                s.page_width,
                s.page_height,
                s.top_margin,
                s.bottom_margin,
                s.left_margin,
                s.right_margin,
                s.orientation,
            )
            for s in doc_after.sections
        ]
        self.assertEqual(orig_geometries, after_geometries)

    def test_02_headers_and_footers_survive(self):
        """2. Headers and footers across all sections must be preserved without loss."""
        doc_before = docx.Document(self.test_docx)
        orig_hf_data = []
        for s in doc_before.sections:
            orig_hf_data.append({
                "header_paras": len(s.header.paragraphs),
                "footer_paras": len(s.footer.paragraphs),
                "header_text": [p.text for p in s.header.paragraphs],
                "footer_text": [p.text for p in s.footer.paragraphs],
            })

        output_path = os.path.join(self.temp_dir, "polished.docx")
        DocumentFormatter.polish(self.test_docx, output_path, keep_highlights=False)

        doc_after = docx.Document(output_path)
        after_hf_data = []
        for s in doc_after.sections:
            after_hf_data.append({
                "header_paras": len(s.header.paragraphs),
                "footer_paras": len(s.footer.paragraphs),
                "header_text": [p.text for p in s.header.paragraphs],
                "footer_text": [p.text for p in s.footer.paragraphs],
            })

        self.assertEqual(orig_hf_data, after_hf_data)

    def test_03_drawings_and_logo_relationships_survive(self):
        """3. Template drawings, picts, and logo image relationships must survive intact."""
        doc_before = docx.Document(self.test_docx)
        orig_drawings = len(doc_before._body._element.xpath(".//w:drawing"))
        orig_picts = len(doc_before._body._element.xpath(".//w:pict"))
        orig_img_rels = {
            rId: rel.target_ref
            for rId, rel in doc_before.part.rels.items()
            if "image" in rel.reltype
        }
        self.assertGreater(len(orig_img_rels), 0, "Template must have at least one image (logo)")

        output_path = os.path.join(self.temp_dir, "polished.docx")
        DocumentFormatter.polish(self.test_docx, output_path, keep_highlights=False)

        doc_after = docx.Document(output_path)
        after_drawings = len(doc_after._body._element.xpath(".//w:drawing"))
        after_picts = len(doc_after._body._element.xpath(".//w:pict"))
        after_img_rels = {
            rId: rel.target_ref
            for rId, rel in doc_after.part.rels.items()
            if "image" in rel.reltype
        }

        self.assertEqual(after_drawings, orig_drawings)
        self.assertEqual(after_picts, orig_picts)
        self.assertEqual(after_img_rels, orig_img_rels)

    def test_04_run_font_sizes_not_globally_overwritten(self):
        """4. Existing run font sizes and font names must NOT be globally overwritten."""
        doc_before = docx.Document(self.test_docx)
        orig_run_fonts = []
        for p_idx, p in enumerate(doc_before.paragraphs):
            for r_idx, r in enumerate(p.runs):
                if r.font.size is not None or r.font.name is not None:
                    orig_run_fonts.append((p_idx, r_idx, r.font.size, r.font.name))

        output_path = os.path.join(self.temp_dir, "polished.docx")
        DocumentFormatter.polish(self.test_docx, output_path, keep_highlights=False)

        doc_after = docx.Document(output_path)
        after_run_fonts = []
        for p_idx, p in enumerate(doc_after.paragraphs):
            for r_idx, r in enumerate(p.runs):
                if r.font.size is not None or r.font.name is not None:
                    after_run_fonts.append((p_idx, r_idx, r.font.size, r.font.name))

        self.assertEqual(orig_run_fonts, after_run_fonts)

    def test_05_paragraph_alignment_and_spacing_preserved(self):
        """5. Existing paragraph alignment, spacing before/after, and line spacing must be preserved."""
        doc_before = docx.Document(self.test_docx)
        orig_p_formats = [
            (
                p.alignment,
                p.paragraph_format.space_before,
                p.paragraph_format.space_after,
                p.paragraph_format.line_spacing,
            )
            for p in doc_before.paragraphs
        ]

        output_path = os.path.join(self.temp_dir, "polished.docx")
        DocumentFormatter.polish(self.test_docx, output_path, keep_highlights=False)

        doc_after = docx.Document(output_path)
        after_p_formats = [
            (
                p.alignment,
                p.paragraph_format.space_before,
                p.paragraph_format.space_after,
                p.paragraph_format.line_spacing,
            )
            for p in doc_after.paragraphs
        ]

        self.assertEqual(orig_p_formats, after_p_formats)

    def test_06_highlight_removal_when_keep_highlights_false(self):
        """6. Highlight removal works when keep_highlights=False, clearing XML and run properties."""
        # Inject test highlights and shading into test_docx
        doc = docx.Document(self.test_docx)
        p = doc.paragraphs[0]
        r = p.add_run("Highlighted test text")
        r.font.highlight_color = WD_COLOR_INDEX.YELLOW

        # Add yellow shading to a table cell
        if doc.tables:
            cell = doc.tables[0].rows[0].cells[0]
            tcPr = cell._tc.get_or_add_tcPr()
            tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="FFFF00"/>'))

        doc.save(self.test_docx)

        output_path = os.path.join(self.temp_dir, "polished_nohighlight.docx")
        DocumentFormatter.polish(self.test_docx, output_path, keep_highlights=False)

        doc_after = docx.Document(output_path)
        # Check XML highlights
        hl_elements = doc_after._body._element.xpath(".//w:highlight")
        self.assertEqual(len(hl_elements), 0)

        # Check run highlight properties
        for p in doc_after.paragraphs:
            for r in p.runs:
                self.assertIsNone(r.font.highlight_color)

        # Check table cell yellow shading
        for tbl in doc_after.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for shd in cell._tc.xpath(".//w:shd"):
                        fill = shd.get(docx.oxml.ns.qn("w:fill"), "").upper()
                        self.assertNotIn(fill, {"FFFF00", "FFFFCC", "FFFF99", "FFF2CC"})

    def test_07_highlight_preserved_when_keep_highlights_true(self):
        """7. Highlights and shading are preserved when keep_highlights=True."""
        doc = docx.Document(self.test_docx)
        p = doc.paragraphs[0]
        r = p.add_run("Highlighted test text")
        r.font.highlight_color = WD_COLOR_INDEX.YELLOW
        doc.save(self.test_docx)

        output_path = os.path.join(self.temp_dir, "polished_keep.docx")
        DocumentFormatter.polish(self.test_docx, output_path, keep_highlights=True)

        doc_after = docx.Document(output_path)
        # Verify highlight is still present
        has_highlight = any(
            r.font.highlight_color is not None
            for p in doc_after.paragraphs
            for r in p.runs
        )
        self.assertTrue(has_highlight)

    def test_08_structure_guard_verification_passes_after_polish(self):
        """8. StructureGuard verification must pass with exact match after polish()."""
        output_path = os.path.join(self.temp_dir, "polished_guard.docx")
        DocumentFormatter.polish(self.test_docx, output_path, keep_highlights=False)

        guard = StructureGuard(self.template_path, allow_table_expansion=False, allow_row_growth=False)
        result = guard.verify(output_path, raise_on_violation=True)
        self.assertTrue(result.is_structurally_sound)
        self.assertTrue(result.is_exact_match)
        self.assertEqual(len(result.all_violations), 0)

    def test_09_no_run_collapse_from_p_text_or_cell_text(self):
        """9. Multiple runs in a paragraph or cell must NOT be collapsed by p.text = ... or cell.text = ..."""
        doc = docx.Document(self.test_docx)
        # Find a paragraph with multiple runs
        multi_run_paras = [p for p in doc.paragraphs if len(p.runs) >= 2]
        self.assertGreater(len(multi_run_paras), 0)
        orig_run_counts = [len(p.runs) for p in multi_run_paras]

        output_path = os.path.join(self.temp_dir, "polished_runs.docx")
        DocumentFormatter.polish(self.test_docx, output_path, keep_highlights=False)

        doc_after = docx.Document(output_path)
        # Verify paragraph count is identical
        self.assertEqual(len(doc_after.paragraphs), len(doc.paragraphs))
        # Verify multi-run paragraphs still have their runs
        for idx, orig_p in enumerate(doc.paragraphs):
            if len(orig_p.runs) >= 2:
                after_p = doc_after.paragraphs[idx]
                self.assertEqual(
                    len(after_p.runs),
                    len(orig_p.runs),
                    f"Paragraph {idx} runs were collapsed from {len(orig_p.runs)} to {len(after_p.runs)}"
                )

    def test_10_known_placeholder_dots_cleaned_at_run_level(self):
        """10. Known placeholder dot lines are cleaned without destroying run properties or surrounding runs."""
        doc = docx.Document(self.test_docx)
        # Add a paragraph with two runs: one label and one placeholder dots
        p = doc.add_paragraph()
        r1 = p.add_run("Nhãn mục tiêu: ")
        r1.bold = True
        r1.font.name = "Arial"
        r1.font.size = Pt(13)

        r2 = p.add_run("………………………………….")
        r2.italic = True
        r2.font.name = "Courier New"
        r2.font.size = Pt(10)

        doc.save(self.test_docx)

        output_path = os.path.join(self.temp_dir, "polished_dots.docx")
        DocumentFormatter.polish(self.test_docx, output_path, keep_highlights=False)

        doc_after = docx.Document(output_path)
        after_p = doc_after.paragraphs[-1]
        self.assertEqual(len(after_p.runs), 2)
        # r1 unchanged
        self.assertEqual(after_p.runs[0].text, "Nhãn mục tiêu: ")
        self.assertTrue(after_p.runs[0].bold)
        self.assertEqual(after_p.runs[0].font.name, "Arial")
        self.assertEqual(after_p.runs[0].font.size, Pt(13))
        # r2 placeholder dots removed, run properties preserved
        self.assertEqual(after_p.runs[1].text, "")
        self.assertTrue(after_p.runs[1].italic)
        self.assertEqual(after_p.runs[1].font.name, "Courier New")
        self.assertEqual(after_p.runs[1].font.size, Pt(10))


if __name__ == "__main__":
    unittest.main()
