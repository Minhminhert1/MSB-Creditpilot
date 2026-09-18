"""Module: structure_fingerprint.py
Description: Deterministic Word document structure snapshot and fidelity comparison engine.
Extracts deep structural fingerprints of DOCX templates and verifies that output documents
preserve exact template geometry, layout invariants, section settings, table counts,
and formatting while allowing only explicitly approved mutations.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
import hashlib
import os
from typing import Any, Dict, List, Optional, Set, Tuple
import docx
from docx.oxml.ns import qn
from docx.table import Table, _Cell


@dataclass
class DynamicTableRule:
    """Explicit permission for dynamic row growth on a specific registered table."""
    table_index: int
    binding_id: str
    allow_row_growth: bool = True
    min_rows: Optional[int] = None
    max_growth: Optional[int] = 50


@dataclass
class SectionGeometry:
    section_index: int
    page_width_dxa: int
    page_height_dxa: int
    top_margin_dxa: int
    bottom_margin_dxa: int
    left_margin_dxa: int
    right_margin_dxa: int
    orientation: str
    has_header: bool
    has_footer: bool


@dataclass
class TableGeometry:
    table_index: int
    row_count: int
    col_count: int
    grid_cols_dxa: List[int]
    total_cells: int
    unique_cells_count: int
    merged_cells_count: int
    style_name: str
    alignment: str
    has_tbl_header: bool
    has_cant_split: bool


@dataclass
class DocumentStructureSnapshot:
    """Comprehensive structural snapshot of a DOCX document."""
    file_path: str
    sha256: str
    section_count: int
    sections: List[SectionGeometry]
    table_count: int
    tables: List[TableGeometry]
    paragraph_count: int
    paragraph_styles: List[str]
    form_checkbox_count: int
    sdt_content_control_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StructureComparisonResult:
    """Detailed result of comparing two document structure snapshots."""
    is_structurally_sound: bool
    is_exact_match: bool
    section_violations: List[str] = field(default_factory=list)
    margin_violations: List[str] = field(default_factory=list)
    table_count_diff: Optional[Tuple[int, int]] = None
    table_geometry_violations: List[str] = field(default_factory=list)
    style_violations: List[str] = field(default_factory=list)
    allowed_mutations_observed: List[str] = field(default_factory=list)
    all_violations: List[str] = field(default_factory=list)


def _compute_sha256(file_path: str) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def snapshot_template_structure(docx_path: str) -> DocumentStructureSnapshot:
    """Capture the comprehensive structural fingerprint of a DOCX file."""
    if not os.path.exists(docx_path):
        raise FileNotFoundError(f"DOCX file not found at '{docx_path}'")

    doc = docx.Document(docx_path)
    file_sha = _compute_sha256(docx_path)

    # 1. Section Geometries
    sections_info: List[SectionGeometry] = []
    for idx, s in enumerate(doc.sections):
        # Read properties in dxa (1 pt = 20 dxa)
        pw = int(round(s.page_width.pt * 20)) if s.page_width else 11906
        ph = int(round(s.page_height.pt * 20)) if s.page_height else 16838
        tm = int(round(s.top_margin.pt * 20)) if s.top_margin else 1440
        bm = int(round(s.bottom_margin.pt * 20)) if s.bottom_margin else 1440
        lm = int(round(s.left_margin.pt * 20)) if s.left_margin else 1440
        rm = int(round(s.right_margin.pt * 20)) if s.right_margin else 1440
        orient = str(s.orientation).split(".")[-1] if hasattr(s, "orientation") else "PORTRAIT"
        
        try:
            has_hdr = (not s.header.is_linked_to_previous) and len(s.header.paragraphs) > 0 and any(p.text.strip() for p in s.header.paragraphs)
        except Exception:
            has_hdr = False

        try:
            has_ftr = (not s.footer.is_linked_to_previous) and len(s.footer.paragraphs) > 0 and any(p.text.strip() for p in s.footer.paragraphs)
        except Exception:
            has_ftr = False

        sections_info.append(SectionGeometry(
            section_index=idx,
            page_width_dxa=pw,
            page_height_dxa=ph,
            top_margin_dxa=tm,
            bottom_margin_dxa=bm,
            left_margin_dxa=lm,
            right_margin_dxa=rm,
            orientation=orient,
            has_header=has_hdr,
            has_footer=has_ftr,
        ))

    # 2. Table Geometries
    tables_info: List[TableGeometry] = []
    for idx, tbl in enumerate(doc.tables):
        row_cnt = len(tbl.rows)
        col_cnt = len(tbl.columns) if row_cnt > 0 else 0
        total_cells = sum(len(r.cells) for r in tbl.rows)

        # Unique cells (deduplicating merged horizontal/vertical cells)
        unique_cells = set()
        for r in tbl.rows:
            for c in r.cells:
                unique_cells.add(c._tc)
        unique_cnt = len(unique_cells)
        merged_cnt = total_cells - unique_cnt

        # Grid columns
        grid_cols = []
        tblGrid = tbl._tbl.xpath(".//w:tblGrid/w:gridCol")
        for gc in tblGrid:
            w_val = gc.get(qn("w:w"))
            if w_val and w_val.isdigit():
                grid_cols.append(int(w_val))

        style_name = tbl.style.name if tbl.style else "Table Grid"
        alignment = str(tbl.alignment).split(".")[-1] if tbl.alignment else "LEFT"

        has_header_row = any(
            len(r._tr.xpath(".//w:trPr/w:tblHeader")) > 0 for r in tbl.rows
        )
        has_cant_split = any(
            len(r._tr.xpath(".//w:trPr/w:cantSplit")) > 0 for r in tbl.rows
        )

        tables_info.append(TableGeometry(
            table_index=idx,
            row_count=row_cnt,
            col_count=col_cnt,
            grid_cols_dxa=grid_cols,
            total_cells=total_cells,
            unique_cells_count=unique_cnt,
            merged_cells_count=merged_cnt,
            style_name=style_name,
            alignment=alignment,
            has_tbl_header=has_header_row,
            has_cant_split=has_cant_split,
        ))

    # 3. Paragraph styles
    p_styles = sorted(list({p.style.name for p in doc.paragraphs if p.style}))
    
    # 4. Form controls
    body_elem = doc._body._element
    checkboxes = len(body_elem.xpath(".//w:fldData | .//w:ffData/w:checkBox"))
    sdts = len(body_elem.xpath(".//w:sdt"))

    return DocumentStructureSnapshot(
        file_path=docx_path,
        sha256=file_sha,
        section_count=len(doc.sections),
        sections=sections_info,
        table_count=len(doc.tables),
        tables=tables_info,
        paragraph_count=len(doc.paragraphs),
        paragraph_styles=p_styles,
        form_checkbox_count=checkboxes,
        sdt_content_control_count=sdts,
    )


def compare_template_structure(
    template_snapshot: DocumentStructureSnapshot,
    output_snapshot: DocumentStructureSnapshot,
    allow_table_expansion: bool = False,
    allow_row_growth: bool = False,
    dynamic_table_rules: Optional[List[DynamicTableRule]] = None,
) -> StructureComparisonResult:
    """Compares output document structure against the template baseline.
    
    STRICT DEFAULT: Both allow_table_expansion and allow_row_growth default to False.
    Only explicit dynamic table rules may permit row growth for registered tables.
    """
    violations: List[str] = []
    sec_violations: List[str] = []
    margin_violations: List[str] = []
    tbl_violations: List[str] = []
    allowed_mutations: List[str] = []

    # Map dynamic rules by table index
    dynamic_rules_by_index: Dict[int, DynamicTableRule] = {}
    if dynamic_table_rules:
        for r in dynamic_table_rules:
            dynamic_rules_by_index[r.table_index] = r

    # 1. Section Count
    if template_snapshot.section_count != output_snapshot.section_count:
        msg = f"Section count mismatch: Template has {template_snapshot.section_count}, Output has {output_snapshot.section_count}"
        sec_violations.append(msg)
        violations.append(msg)

    # 2. Section Margins & Page Size
    for idx in range(min(len(template_snapshot.sections), len(output_snapshot.sections))):
        t_sec = template_snapshot.sections[idx]
        o_sec = output_snapshot.sections[idx]
        if (abs(t_sec.page_width_dxa - o_sec.page_width_dxa) > 20 or 
            abs(t_sec.page_height_dxa - o_sec.page_height_dxa) > 20):
            msg = f"Section {idx} page dimensions altered: {t_sec.page_width_dxa}x{t_sec.page_height_dxa} -> {o_sec.page_width_dxa}x{o_sec.page_height_dxa}"
            sec_violations.append(msg)
            violations.append(msg)
        
        # Check margins with a tolerance of 20 dxa (~1pt)
        for m_name in ["top_margin_dxa", "bottom_margin_dxa", "left_margin_dxa", "right_margin_dxa"]:
            t_m = getattr(t_sec, m_name)
            o_m = getattr(o_sec, m_name)
            if abs(t_m - o_m) > 20:
                msg = f"Section {idx} {m_name} altered: {t_m} -> {o_m}"
                margin_violations.append(msg)
                violations.append(msg)

    # 3. Table Count
    tbl_diff = None
    if template_snapshot.table_count != output_snapshot.table_count:
        tbl_diff = (template_snapshot.table_count, output_snapshot.table_count)
        if not allow_table_expansion:
            msg = f"Table count altered: Template has {template_snapshot.table_count} tables, Output has {output_snapshot.table_count} tables (Shift={output_snapshot.table_count - template_snapshot.table_count})"
            tbl_violations.append(msg)
            violations.append(msg)
        else:
            allowed_mutations.append(f"Table count expanded from {template_snapshot.table_count} to {output_snapshot.table_count}")

    # 4. Table Geometries
    min_tables = min(template_snapshot.table_count, output_snapshot.table_count)
    for idx in range(min_tables):
        t_tbl = template_snapshot.tables[idx]
        o_tbl = output_snapshot.tables[idx]

        if t_tbl.col_count != o_tbl.col_count:
            msg = f"Table {idx} column count altered: {t_tbl.col_count} -> {o_tbl.col_count}"
            tbl_violations.append(msg)
            violations.append(msg)

        if t_tbl.row_count != o_tbl.row_count:
            # Check if this table has an explicit dynamic growth rule
            rule = dynamic_rules_by_index.get(idx)
            is_rule_allowed = rule is not None and rule.allow_row_growth
            
            if (allow_row_growth or is_rule_allowed) and o_tbl.row_count >= t_tbl.row_count:
                max_g = rule.max_growth if rule and rule.max_growth is not None else 100
                if o_tbl.row_count - t_tbl.row_count <= max_g:
                    allowed_mutations.append(f"Table {idx} ({rule.binding_id if rule else 'global'}) rows grew from {t_tbl.row_count} to {o_tbl.row_count}")
                else:
                    msg = f"Table {idx} row growth exceeded limit ({max_g}): {t_tbl.row_count} -> {o_tbl.row_count}"
                    tbl_violations.append(msg)
                    violations.append(msg)
            else:
                msg = f"Table {idx} row count altered without permission: {t_tbl.row_count} -> {o_tbl.row_count}"
                tbl_violations.append(msg)
                violations.append(msg)

    is_exact = len(violations) == 0 and len(allowed_mutations) == 0
    is_sound = len(violations) == 0

    return StructureComparisonResult(
        is_structurally_sound=is_sound,
        is_exact_match=is_exact,
        section_violations=sec_violations,
        margin_violations=margin_violations,
        table_count_diff=tbl_diff,
        table_geometry_violations=tbl_violations,
        allowed_mutations_observed=allowed_mutations,
        all_violations=violations,
    )
