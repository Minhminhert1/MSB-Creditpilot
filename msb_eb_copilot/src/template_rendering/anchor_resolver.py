"""Module: anchor_resolver.py
Description: Fail-closed semantic anchor resolution engine for MB07 DOCX templates.
Locates target cells, tables, and narrative paragraphs using explicit semantic anchors
and target relationships rather than brittle hardcoded table indices.
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple, Union
import docx
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from .bindings import MutationType, TargetRelationship, TemplateBinding


class AnchorError(Exception):
    """Base exception for all anchor resolution failures."""
    pass


class AnchorNotFoundError(AnchorError):
    """Raised when an expected semantic anchor cannot be located in the template."""
    pass


class AnchorAmbiguousError(AnchorError):
    """Raised when an anchor matches multiple elements and cannot be uniquely resolved."""
    pass


class TemplateStructureMismatchError(AnchorError):
    """Raised when the resolved anchor does not match the expected structural relationship."""
    pass


def _normalize_text(text: str) -> str:
    """Normalize text by stripping whitespace and collapsing internal runs of whitespace."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


class AnchorResolver:
    """Resolves semantic anchors to concrete python-docx DOM elements (Table, _Cell, Paragraph)."""

    @staticmethod
    def find_cell_by_anchor(
        doc: docx.Document,
        anchor_text: str,
        target_rel: TargetRelationship = TargetRelationship.NEIGHBOR_CELL_RIGHT,
        expected_table_idx: Optional[int] = None,
        case_sensitive: bool = False,
    ) -> _Cell:
        """Locate a specific cell relative to an anchor label cell.
        
        Fail-closed: Raises AnchorNotFoundError if not found, or AnchorAmbiguousError if multiple matches.
        """
        norm_anchor = anchor_text.strip() if case_sensitive else _normalize_text(anchor_text)
        candidates: List[Tuple[int, int, int, _Cell, _Cell]] = []

        tables_to_search = (
            [(expected_table_idx, doc.tables[expected_table_idx])]
            if expected_table_idx is not None and 0 <= expected_table_idx < len(doc.tables)
            else list(enumerate(doc.tables))
        )

        for t_idx, tbl in tables_to_search:
            for r_idx, row in enumerate(tbl.rows):
                unique_cells = list(dict.fromkeys(row.cells))
                for c_idx, cell in enumerate(unique_cells):
                    cell_text = cell.text.strip() if case_sensitive else _normalize_text(cell.text)
                    if norm_anchor in cell_text or cell_text == norm_anchor:
                        if target_rel == TargetRelationship.SELF:
                            candidates.append((t_idx, r_idx, c_idx, cell, cell))
                        elif target_rel == TargetRelationship.NEIGHBOR_CELL_RIGHT:
                            if c_idx + 1 < len(unique_cells):
                                target_cell = unique_cells[c_idx + 1]
                                candidates.append((t_idx, r_idx, c_idx, cell, target_cell))
                            else:
                                raise TemplateStructureMismatchError(
                                    f"Anchor '{anchor_text}' found at table {t_idx}, row {r_idx}, col {c_idx}, "
                                    f"but has no right neighbor cell."
                                )
                        elif target_rel == TargetRelationship.NEIGHBOR_CELL_BELOW:
                            if r_idx + 1 < len(tbl.rows):
                                next_row_cells = list(dict.fromkeys(tbl.rows[r_idx + 1].cells))
                                if c_idx < len(next_row_cells):
                                    target_cell = next_row_cells[c_idx]
                                    candidates.append((t_idx, r_idx, c_idx, cell, target_cell))
                                else:
                                    raise TemplateStructureMismatchError(
                                        f"Anchor '{anchor_text}' found at table {t_idx}, row {r_idx}, col {c_idx}, "
                                        f"but row below lacks matching column index."
                                    )
                            else:
                                raise TemplateStructureMismatchError(
                                    f"Anchor '{anchor_text}' found at last row of table {t_idx}, no row below exists."
                                )

        if not candidates:
            raise AnchorNotFoundError(
                f"Anchor '{anchor_text}' not found in {'table ' + str(expected_table_idx) if expected_table_idx is not None else 'any table'}."
            )

        if len(candidates) > 1:
            locs = [f"(Table {c[0]}, Row {c[1]}, Col {c[2]})" for c in candidates]
            raise AnchorAmbiguousError(
                f"Anchor '{anchor_text}' is ambiguous, matched {len(candidates)} locations: {', '.join(locs)}"
            )

        return candidates[0][4]

    @staticmethod
    def find_table_by_heading(
        doc: docx.Document,
        heading_text: str,
        expected_index: Optional[int] = None,
        case_sensitive: bool = False,
    ) -> Table:
        """Find the table immediately following a designated section heading."""
        norm_heading = heading_text.strip() if case_sensitive else _normalize_text(heading_text)
        matched_paragraphs: List[Tuple[int, Paragraph]] = []

        for p_idx, p in enumerate(doc.paragraphs):
            p_text = p.text.strip() if case_sensitive else _normalize_text(p.text)
            if norm_heading in p_text or p_text == norm_heading:
                matched_paragraphs.append((p_idx, p))

        if not matched_paragraphs:
            raise AnchorNotFoundError(f"Section heading anchor '{heading_text}' not found in document paragraphs.")

        if len(matched_paragraphs) > 1:
            if expected_index is not None and 0 <= expected_index < len(doc.tables):
                pass
            else:
                indices = [str(mp[0]) for mp in matched_paragraphs]
                raise AnchorAmbiguousError(
                    f"Heading anchor '{heading_text}' matched {len(matched_paragraphs)} paragraphs: {', '.join(indices)}"
                )

        target_p = matched_paragraphs[0][1]
        p_elem = target_p._p

        body_elem = doc._body._element
        found_p = False
        target_tbl_elem = None

        for child in body_elem:
            if child == p_elem:
                found_p = True
                continue
            if found_p:
                tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if tag == 'tbl':
                    target_tbl_elem = child
                    break

        if target_tbl_elem is None:
            if expected_index is not None and 0 <= expected_index < len(doc.tables):
                return doc.tables[expected_index]
            raise AnchorNotFoundError(f"No table found immediately following heading '{heading_text}'.")

        for tbl in doc.tables:
            if tbl._tbl == target_tbl_elem:
                return tbl

        if expected_index is not None and 0 <= expected_index < len(doc.tables):
            return doc.tables[expected_index]

        raise AnchorNotFoundError(f"Table element following heading '{heading_text}' could not be resolved.")

    @staticmethod
    def find_paragraph_by_anchor(
        doc: docx.Document,
        anchor_text: str,
        target_rel: TargetRelationship = TargetRelationship.SELF,
        case_sensitive: bool = False,
    ) -> Paragraph:
        """Locate a specific paragraph by its textual anchor."""
        norm_anchor = anchor_text.strip() if case_sensitive else _normalize_text(anchor_text)
        matched: List[Tuple[int, Paragraph]] = []

        for idx, p in enumerate(doc.paragraphs):
            p_text = p.text.strip() if case_sensitive else _normalize_text(p.text)
            if norm_anchor in p_text:
                matched.append((idx, p))

        if not matched:
            raise AnchorNotFoundError(f"Paragraph anchor '{anchor_text}' not found.")

        if len(matched) > 1:
            indices = [str(m[0]) for m in matched]
            raise AnchorAmbiguousError(f"Paragraph anchor '{anchor_text}' matched multiple paragraphs: {', '.join(indices)}")

        p_idx, p_elem = matched[0]
        if target_rel == TargetRelationship.SELF:
            return p_elem
        elif target_rel == TargetRelationship.NARRATIVE_PARAGRAPH:
            if p_idx + 1 < len(doc.paragraphs):
                return doc.paragraphs[p_idx + 1]
            raise TemplateStructureMismatchError(f"No narrative paragraph exists following anchor '{anchor_text}'.")

        return p_elem

    @classmethod
    def resolve_binding(
        cls,
        doc: docx.Document,
        binding: TemplateBinding,
    ) -> Union[Table, _Cell, Paragraph]:
        """Resolve a full TemplateBinding definition to its concrete DOCX target element."""
        if binding.target_rel == TargetRelationship.ASSOCIATED_TABLE or binding.mutation_type == MutationType.TABLE_ROWS:
            return cls.find_table_by_heading(
                doc,
                heading_text=binding.anchor_text,
                expected_index=binding.expected_table_index,
            )
        elif binding.target_rel in (TargetRelationship.SELF, TargetRelationship.NEIGHBOR_CELL_RIGHT, TargetRelationship.NEIGHBOR_CELL_BELOW):
            try:
                return cls.find_cell_by_anchor(
                    doc,
                    anchor_text=binding.anchor_text,
                    target_rel=binding.target_rel,
                    expected_table_idx=binding.expected_table_index,
                )
            except AnchorNotFoundError:
                if binding.target_rel == TargetRelationship.SELF:
                    return cls.find_paragraph_by_anchor(doc, binding.anchor_text, target_rel=binding.target_rel)
                raise
        elif binding.target_rel == TargetRelationship.NARRATIVE_PARAGRAPH:
            return cls.find_paragraph_by_anchor(doc, binding.anchor_text, target_rel=binding.target_rel)

        raise TemplateStructureMismatchError(f"Unsupported binding target relationship '{binding.target_rel}'.")
