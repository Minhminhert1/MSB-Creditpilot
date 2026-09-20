# -*- coding: utf-8 -*-
"""Module: document_formatter.py
Description: Fidelity-Safe Document Formatter and Polisher for MSB MB07 Credit Proposals.

Adheres strictly to the Template Fidelity Contract:
1. Preserves authoritative template styles, geometries, alignments, and spacing.
2. Does NOT perform global style normalization (no blanket font, size, alignment, or spacing overrides).
3. Does NOT rebuild paragraphs (no p.text = ... or cell.text = ...).
4. Safely strips yellow highlights and background shading when keep_highlights=False.
5. Safely cleans known placeholder dot patterns strictly at the run level without rebuilding unrelated runs.
6. Preserves all template drawings, images, logos, headers, footers, and section properties.
"""

from __future__ import annotations
import os
import re
from typing import Optional
import docx
from docx.oxml.ns import qn


YELLOW_SHADING_HEX = {
    "FFFFCC", "FFFFD0", "FFFF99", "FFFF00", "FFF2CC", "FFE599",
    "FFF9C4", "FFF59D", "FFEE58", "FDD835", "FBC02D"
}

# Known isolated placeholder dot/ellipsis markers
ISOLATED_PLACEHOLDER_MARKERS = {
    "…", "….", "...", "....", "…..", "……", "…………", "………", "…...",
    "………………………………….", "…………………………………", "………………………………",
    "................................"
}


class DocumentFormatter:
    """Fidelity-safe document formatter for MSB MB07 credit proposals."""

    @staticmethod
    def strip_highlights_and_shading(doc: docx.Document) -> None:
        """Safely strip all yellow highlights and shading without altering runs, text, or styles."""
        # 1. Remove w:highlight XML elements from document body
        for h_elem in doc._body._element.xpath(".//w:highlight"):
            try:
                parent = h_elem.getparent()
                if parent is not None:
                    parent.remove(h_elem)
            except Exception:
                pass

        # 2. Remove w:highlight from headers and footers across all sections
        for section in doc.sections:
            for hf in [section.header, section.footer, section.first_page_header, section.first_page_footer]:
                if hf is not None and hf._element is not None:
                    for h_elem in hf._element.xpath(".//w:highlight"):
                        try:
                            parent = h_elem.getparent()
                            if parent is not None:
                                parent.remove(h_elem)
                        except Exception:
                            pass

        # 3. Clear run.font.highlight_color in paragraphs
        for p in doc.paragraphs:
            for r in p.runs:
                if r.font.highlight_color is not None:
                    r.font.highlight_color = None

        # 4. Clear run.font.highlight_color and yellow cell shading in tables
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for r in p.runs:
                            if r.font.highlight_color is not None:
                                r.font.highlight_color = None
                    tcPr = cell._tc.get_or_add_tcPr()
                    for shd in tcPr.xpath(".//w:shd"):
                        fill_val = shd.get(qn("w:fill"), "").upper()
                        if fill_val in YELLOW_SHADING_HEX:
                            try:
                                tcPr.remove(shd)
                            except Exception:
                                pass

    @staticmethod
    def clean_known_placeholders_in_runs(doc: docx.Document) -> None:
        """Safely clean explicitly known placeholder dot lines strictly at the run level.

        Preserves:
        - All run elements and their formatting (font, size, bold, italic, color).
        - Paragraph structure, alignment, spacing, and properties (pPr).
        - Table structure and cell geometry.
        - NEVER uses p.text = ... or cell.text = ...
        """
        def _clean_run(r: docx.text.run.Run) -> None:
            if not r.text:
                return
            txt = r.text
            # 1. Exact isolated placeholder dots in a run -> replace with empty string
            stripped = txt.strip()
            if stripped in ISOLATED_PLACEHOLDER_MARKERS:
                r.text = txt.replace(stripped, "")
                return

            # 2. Trailing repeating dots/ellipsis (3 or more) within a run (e.g. 'Khác…..' -> 'Khác')
            if re.search(r'[\.]{3,}|…{2,}', txt):
                cleaned = re.sub(r'[\.]{3,}|…{2,}', '', txt)
                if cleaned != txt:
                    r.text = cleaned

        # Apply to body paragraphs
        for p in doc.paragraphs:
            for r in p.runs:
                _clean_run(r)

        # Apply to table cell paragraphs
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for r in p.runs:
                            _clean_run(r)

    @staticmethod
    def clean_template_prompts_and_dots(doc: docx.Document, keep_highlights: bool = False) -> None:
        """Backward-compatible entry point for prompt and dot cleaning.

        Now executed fidelity-safely without global style overrides or run destruction.
        """
        DocumentFormatter.clean_known_placeholders_in_runs(doc)
        if not keep_highlights:
            DocumentFormatter.strip_highlights_and_shading(doc)

    @staticmethod
    def polish(doc_path: str, output_path: Optional[str] = None, keep_highlights: bool = False) -> str:
        """Perform fidelity-safe polish on the proposal document.

        Strict invariants:
        - Preserves authoritative template font sizes, font names, styles, alignments, and spacing.
        - Preserves all drawings, images, logo relationships, headers, footers, and section geometries.
        - Strips yellow highlights and shading if keep_highlights=False.
        - Cleans explicitly known placeholder dot lines strictly at the run level.
        - Does NOT perform global style normalization or rebuild paragraphs.
        """
        if output_path is None:
            output_path = doc_path

        doc = docx.Document(doc_path)

        # 1. Safe placeholder cleanup strictly within runs
        DocumentFormatter.clean_known_placeholders_in_runs(doc)

        # 2. Safe highlight and shading removal when keep_highlights is False
        if not keep_highlights:
            DocumentFormatter.strip_highlights_and_shading(doc)

        # 3. Save without structural alteration
        doc.save(output_path)
        return output_path
