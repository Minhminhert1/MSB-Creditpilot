"""Module: safe_mutation.py
Description: Run-preserving and OOXML-safe mutation primitives for MB07 DOCX templates.
Safely mutates table cells, paragraphs, form fields, and dynamic rows while strictly
preserving styles, fonts, sizes, alignments, borders, shading, and non-text elements.
"""

from __future__ import annotations
import copy
from typing import Any, List, Optional, Union
import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt, RGBColor
from docx.table import Table, _Cell, _Row
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from lxml import etree


def _is_visual_run(run: Run) -> bool:
    """Returns True if the run contains visual/graphic elements (drawings, shapes, pictures)."""
    xml = run._r.xml
    return (
        "w:drawing" in xml
        or "AlternateContent" in xml
        or "v:shape" in xml
        or "v:imagedata" in xml
        or "w:object" in xml
        or "w:pict" in xml
    )


class SafeCellMutator:
    """Safe, run-preserving in-place mutation for table cells."""

    @staticmethod
    def set_cell_text(
        cell: _Cell,
        text: Any,
        bold: Optional[bool] = None,
        color: Optional[RGBColor] = None,
        highlight: bool = False,
        align: Optional[WD_ALIGN_PARAGRAPH] = None,
        font_name: Optional[str] = None,
        font_size_pt: Optional[float] = None,
    ) -> None:
        """Update the text of a cell while preserving paragraph and run formatting and visuals."""
        text_str = "" if text is None else str(text)

        # Ensure cell has at least one paragraph
        if not cell.paragraphs:
            p = cell.add_paragraph()
        else:
            p = cell.paragraphs[0]

        if align is not None:
            p.alignment = align

        # Handle runs inside the first paragraph
        runs = p.runs
        if not runs:
            # Create a run and apply standard MB07 font defaults if needed
            r = p.add_run(text_str)
            r.font.name = font_name or "Times New Roman"
            r.font.size = Pt(font_size_pt) if font_size_pt else Pt(10)
            if bold is not None:
                r.bold = bold
            if color:
                r.font.color.rgb = color
            if highlight:
                r.font.highlight_color = WD_COLOR_INDEX.YELLOW
            return

        text_runs = [r for r in runs if not _is_visual_run(r)]
        if not text_runs:
            donor_run = p.add_run(text_str)
            donor_run.font.name = font_name or "Times New Roman"
            donor_run.font.size = Pt(font_size_pt) if font_size_pt else Pt(10)
            if bold is not None:
                donor_run.bold = bold
            if color:
                donor_run.font.color.rgb = color
            if highlight:
                donor_run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            return

        donor_run = text_runs[0]

        # Check if donor run has formatting properties
        if bold is not None:
            donor_run.bold = bold
        if color:
            donor_run.font.color.rgb = color
        if highlight:
            donor_run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        if font_name:
            donor_run.font.name = font_name
        if font_size_pt:
            donor_run.font.size = Pt(font_size_pt)

        # Set text on the donor run
        donor_run.text = text_str

        # Clear remaining non-visual text runs in the first paragraph
        for extra_r in text_runs[1:]:
            extra_r.text = ""

        # Remove extra paragraphs in the cell if this was a single value mutation
        if len(cell.paragraphs) > 1:
            for extra_p in list(cell.paragraphs[1:]):
                p_elem = extra_p._p
                parent = p_elem.getparent()
                if parent is not None:
                    parent.remove(p_elem)

    @staticmethod
    def set_multiline_text(
        cell: _Cell,
        lines: List[str],
        bold: Optional[bool] = None,
        align: Optional[WD_ALIGN_PARAGRAPH] = None,
    ) -> None:
        """Insert multiple lines of narrative into a cell, cloning donor paragraph properties."""
        if not lines:
            SafeCellMutator.set_cell_text(cell, "", bold=bold, align=align)
            return

        # First line goes to first paragraph
        SafeCellMutator.set_cell_text(cell, lines[0], bold=bold, align=align)
        donor_p = cell.paragraphs[0]
        donor_r = donor_p.runs[0] if donor_p.runs else None

        # Clean any extra paragraphs after paragraph 0 before adding new lines
        for extra_p in list(cell.paragraphs[1:]):
            p_elem = extra_p._p
            parent = p_elem.getparent()
            if parent is not None:
                parent.remove(p_elem)

        # Add remaining lines as cloned paragraphs
        for line in lines[1:]:
            new_p = cell.add_paragraph()
            # Copy paragraph properties if present
            if donor_p._p.pPr is not None:
                new_p._p.append(copy.deepcopy(donor_p._p.pPr))
            if align is not None:
                new_p.alignment = align
            elif donor_p.alignment is not None:
                new_p.alignment = donor_p.alignment

            new_r = new_p.add_run(line)
            if donor_r is not None:
                if donor_r._r.rPr is not None:
                    new_r._r.append(copy.deepcopy(donor_r._r.rPr))
                if donor_r.font.name:
                    new_r.font.name = donor_r.font.name
                if donor_r.font.size:
                    new_r.font.size = donor_r.font.size
            if bold is not None:
                new_r.bold = bold


class SafeParagraphMutator:
    """Safe, run-preserving in-place mutation for standalone paragraphs."""

    @staticmethod
    def set_paragraph_text(
        paragraph: Paragraph,
        text: Any,
        bold: Optional[bool] = None,
        color: Optional[RGBColor] = None,
        highlight: bool = False,
        align: Optional[WD_ALIGN_PARAGRAPH] = None,
    ) -> None:
        """Update paragraph text preserving existing pPr, rPr properties and visual drawings."""
        text_str = "" if text is None else str(text)

        if align is not None:
            paragraph.alignment = align

        runs = paragraph.runs
        if not runs:
            r = paragraph.add_run(text_str)
            r.font.name = "Times New Roman"
            r.font.size = Pt(11)
            if bold is not None:
                r.bold = bold
            if color:
                r.font.color.rgb = color
            if highlight:
                r.font.highlight_color = WD_COLOR_INDEX.YELLOW
            return

        text_runs = [r for r in runs if not _is_visual_run(r)]
        if not text_runs:
            donor_run = paragraph.add_run(text_str)
            donor_run.font.name = "Times New Roman"
            donor_run.font.size = Pt(11)
            if bold is not None:
                donor_run.bold = bold
            if color:
                donor_run.font.color.rgb = color
            if highlight:
                donor_run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            return

        donor_run = text_runs[0]
        if bold is not None:
            donor_run.bold = bold
        if color:
            donor_run.font.color.rgb = color
        if highlight:
            donor_run.font.highlight_color = WD_COLOR_INDEX.YELLOW

        donor_run.text = text_str

        # Clear remaining non-visual text runs (preserving all visual drawings)
        for extra_r in text_runs[1:]:
            extra_r.text = ""


class DynamicRowCloner:
    """Safely duplicates template table rows for allowlisted repeatable dynamic entries."""

    @staticmethod
    def clone_row(
        table: Table,
        source_row_index: int = -1,
    ) -> _Row:
        """Deep-clones a template row, preserving all trPr, tcPr, borders, shading, widths,
        and styles while resetting cell contents to blank strings.
        """
        if not table.rows:
            raise ValueError("Cannot clone row from an empty table.")

        if source_row_index < 0:
            source_row_index = len(table.rows) + source_row_index

        if source_row_index < 0 or source_row_index >= len(table.rows):
            raise IndexError(f"Source row index {source_row_index} out of range [0, {len(table.rows)-1}].")

        source_tr = table.rows[source_row_index]._tr
        cloned_tr = copy.deepcopy(source_tr)

        # Append cloned row XML to table element
        table._tbl.append(cloned_tr)
        new_row = table.rows[len(table.rows) - 1]

        # Clear text contents in all cells of the new cloned row while keeping formatting
        for cell in new_row.cells:
            for p in cell.paragraphs:
                for r in p.runs:
                    r.text = ""

        return new_row
