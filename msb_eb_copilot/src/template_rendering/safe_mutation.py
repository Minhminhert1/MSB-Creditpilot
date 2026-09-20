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


def _sdt_text_nodes(paragraph_element: Any) -> List[Any]:
    """Returns <w:t> nodes nested inside any content control (w:sdt) within this paragraph.

    python-docx's Paragraph.runs / Cell.paragraphs only ever see direct <w:r> children of
    <w:p>. Authoritative MB07 dropdown/placeholder fields (e.g. the "Chọn kết quả" /
    "Chọn sản phẩm" defaults) live inside <w:sdt><w:sdtContent><w:r><w:t>, which is
    completely invisible to run-based mutation. Without this check, a mutator that finds
    "no runs" in such a paragraph will happily append a brand-new sibling run next to the
    untouched placeholder, producing a silent concatenation defect such as
    "Chọn kết quảTái cấp và ..." in the rendered document.
    """
    return paragraph_element.xpath(".//w:sdt//w:t")


def _set_sdt_placeholder_text(
    t_nodes: List[Any],
    text: str,
    bold: Optional[bool] = None,
    color: Optional[RGBColor] = None,
    highlight: bool = False,
    font_name: Optional[str] = None,
    font_size_pt: Optional[float] = None,
) -> None:
    """Replaces a content control's placeholder text in-place (never adds a sibling run).

    Mirrors SectionADocxMutator.set_sdt_dropdown_text: writes the final value into the
    control's own text node(s) and strips the template's placeholder styling (red color /
    italics), which is the standard MB07 convention for turning a red instructional
    placeholder into normal final black content.
    """
    if not t_nodes:
        return

    t_nodes[0].text = text
    for extra_t in t_nodes[1:]:
        extra_t.text = ""

    # Apply any requested formatting overrides on the run that owns the surviving text node.
    owning_run_elem = t_nodes[0].getparent()
    if owning_run_elem is not None and etree.QName(owning_run_elem).localname == "r":
        owning_run = Run(owning_run_elem, None)
        if bold is not None:
            owning_run.bold = bold
        if color:
            owning_run.font.color.rgb = color
        if highlight:
            owning_run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        if font_name:
            owning_run.font.name = font_name
        if font_size_pt:
            owning_run.font.size = Pt(font_size_pt)

    # Strip the template's red/italic placeholder styling within the control's content.
    sdt_content = t_nodes[0]
    while sdt_content is not None and etree.QName(sdt_content).localname != "sdtContent":
        sdt_content = sdt_content.getparent()
    if sdt_content is not None:
        for color_elem in sdt_content.findall(".//" + qn("w:color")):
            parent = color_elem.getparent()
            if parent is not None:
                parent.remove(color_elem)
        for italic_elem in sdt_content.findall(".//" + qn("w:i")):
            parent = italic_elem.getparent()
            if parent is not None:
                parent.remove(italic_elem)


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
        text_runs = [r for r in runs if not _is_visual_run(r)]
        non_blank_text_runs = [r for r in text_runs if (r.text or "").strip()]

        # A template content control (w:sdt) placeholder such as "Chọn kết quả" lives
        # outside of p.runs entirely. If the only "content" in this paragraph is such a
        # placeholder (optionally alongside blank/whitespace-only cosmetic runs), the final
        # value MUST be written into the placeholder itself -- never appended as a new
        # sibling run, which would silently leave the old placeholder text concatenated in
        # front of/behind the new value.
        sdt_t_nodes = _sdt_text_nodes(p._p)
        if sdt_t_nodes and not non_blank_text_runs:
            _set_sdt_placeholder_text(
                sdt_t_nodes, text_str,
                bold=bold, color=color, highlight=highlight,
                font_name=font_name, font_size_pt=font_size_pt,
            )
            for blank_run in text_runs:
                blank_run.text = ""
            return

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
        text_runs = [r for r in runs if not _is_visual_run(r)]
        non_blank_text_runs = [r for r in text_runs if (r.text or "").strip()]

        # Same content-control placeholder guard as SafeCellMutator.set_cell_text (see there
        # for full rationale): never append a sibling run next to an untouched w:sdt
        # placeholder such as "Chọn kết quả".
        sdt_t_nodes = _sdt_text_nodes(paragraph._p)
        if sdt_t_nodes and not non_blank_text_runs:
            _set_sdt_placeholder_text(
                sdt_t_nodes, text_str,
                bold=bold, color=color, highlight=highlight,
            )
            for blank_run in text_runs:
                blank_run.text = ""
            return

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
