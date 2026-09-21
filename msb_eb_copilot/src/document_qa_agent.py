# -*- coding: utf-8 -*-
"""Module: document_qa_agent.py
Description: Final Document QA layer for MSB MB07 credit proposals, run AFTER
DOCX generation (Assembler -> Fidelity-safe Formatter -> DOCX), BEFORE export.

Architecture:
    Authoritative MB07 Template
        -> Assembler
        -> Fidelity-safe Formatter
        -> Deterministic DOCX QA          (this module, Section 2)
        -> GreenNode Visual Document QA   (this module, Section 3, AI REVIEWER ONLY)
        -> PASS  -> allow export
        -> FAIL  -> block export, return explicit QA issues

Absolute rules:
1. The AI (GreenNode vision model) is a REVIEWER ONLY. It never edits, repairs,
   or mutates the DOCX. This module contains no code path that writes to the
   generated document.
2. Deterministic, structural checks always run first and are authoritative for
   layout/structure invariants. The vision model is only consulted for
   things structure alone cannot see (rendered fonts, spacing, broken tables,
   clipped text, blank areas, etc.).
3. No silent fallback: if the visual renderer is unavailable, the result status
   is the explicit `VISUAL_QA_UNAVAILABLE` state, never a silent PASS.
4. Fail-closed: any GreenNode API exception or malformed/non-JSON response is
   treated as a visual QA FAILURE, never a PASS.
"""

from __future__ import annotations

import base64
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Type

import docx
from docx.oxml.ns import qn
from lxml import etree

from .template_verification.structure_fingerprint import (
    DynamicTableRule,
    compare_template_structure,
    snapshot_template_structure,
)

try:
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover - pypdfium2 is a hard project dependency
    pdfium = None

try:
    import json as _json
except ImportError:  # pragma: no cover
    _json = None

logger = logging.getLogger(__name__)


# ==============================================================================
# 0. CONSTANTS & DEFAULTS
# ==============================================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
DEFAULT_AUTHORITATIVE_TEMPLATE_PATH = os.path.join(
    _PROJECT_ROOT,
    "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - thực hiện rà soát - tái cấp.docx",
)

# Matches the dynamic table growth allowance used by CreditProposalAssembler /
# StructureGuard for Table 32 (CIC credit relations repeatable rows).
DEFAULT_DYNAMIC_TABLE_RULES: List[DynamicTableRule] = [
    DynamicTableRule(table_index=32, binding_id="cic_credit_relations", allow_row_growth=True, max_growth=50),
]

REQUIRED_ZIP_ENTRIES = ("[Content_Types].xml", "_rels/.rels", "word/document.xml")

DEFAULT_VISUAL_QA_MAX_PAGES = int(os.getenv("DOCUMENT_QA_MAX_PAGES", "6") or "6")
DEFAULT_RENDER_DPI = int(os.getenv("DOCUMENT_QA_RENDER_DPI", "150") or "150")

# Small, configurable pacing delay between successful GreenNode page calls (independent of
# retry backoff), to stay comfortably under rate limits on multi-page documents.
DEFAULT_PAGE_DELAY_SECONDS = float(os.getenv("DOCUMENT_QA_PAGE_DELAY_SECONDS", "2.0") or "2.0")

# Retry policy for retryable GreenNode API errors (HTTP 429/500/502/503/504) ONLY.
# Non-retryable errors (4xx other than 429) and malformed JSON responses are never retried
# and fail closed immediately.
MAX_VISUAL_QA_ATTEMPTS = 4
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# Approximate exponential backoff between attempts 1->2, 2->3, 3->4.
_RETRY_BACKOFF_SCHEDULE_SECONDS: Tuple[float, ...] = (2.0, 5.0, 10.0)
_RETRY_JITTER_MAX_SECONDS = 1.0

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_VISUAL_QA_UNAVAILABLE = "VISUAL_QA_UNAVAILABLE"
# Deterministic QA all PASS, and the only visual-QA failure is font_consistency: export
# is allowed (non-blocking), but the finding is still surfaced so it is never silently
# discarded. See _WARNING_ONLY_VISUAL_CATEGORIES below for the export-policy rationale.
STATUS_PASS_WITH_WARNING = "PASS_WITH_WARNING"

_VISUAL_CHECK_KEYS = (
    "logo",
    "header_footer",
    "font_consistency",
    "table_layout",
    "spacing_alignment",
)
_ALL_VISUAL_KEYS = _VISUAL_CHECK_KEYS + ("overall_visual_fidelity",)

# Export policy: a FAIL on any of these categories still blocks export (genuine visual
# defects: broken logo, corrupted header/footer, broken table layout, broken spacing/
# alignment). font_consistency is deliberately excluded — cross-platform LibreOffice/
# Linux font substitution produces frequent, subjective, non-blocking rendering
# differences (e.g. a name rendering sans-serif, or parenthetical text rendering roman
# instead of italic) that must be visible as a warning but must never block export on
# their own. Structural/deterministic checks are entirely unaffected by this policy.
_BLOCKING_VISUAL_CATEGORIES = tuple(k for k in _VISUAL_CHECK_KEYS if k != "font_consistency")
_WARNING_ONLY_VISUAL_CATEGORIES = ("font_consistency",)


# ==============================================================================
# 1. EXCEPTION HIERARCHY
# ==============================================================================
class DocumentQAError(Exception):
    """Base error for all Document QA layer failures."""


class VisualQAUnavailableError(DocumentQAError):
    """Raised when no DOCX->image rendering mechanism is available in this environment."""


class GreenNodeVisionQAError(DocumentQAError):
    """Raised when the GreenNode visual reviewer call fails or returns malformed output.

    Any occurrence of this exception must be treated as fail-closed (FAIL), never PASS.
    """


class DocumentQAFailedError(DocumentQAError):
    """Raised by the export gate when the full QA result status is FAIL. Carries the full qa_result."""

    def __init__(self, qa_result: Dict[str, Any]):
        self.qa_result = qa_result
        preview = "; ".join(qa_result.get("issues", [])[:5]) or "no details available"
        super().__init__(f"Document QA FAILED: {preview}")


# ==============================================================================
# 2. DETERMINISTIC DOCX QA
# ==============================================================================
def _check_docx_opens(path: str) -> Tuple[bool, List[str], Optional["docx.Document"]]:
    if not path or not os.path.exists(path):
        return False, [f"Generated DOCX not found at '{path}'."], None
    try:
        document = docx.Document(path)
        return True, [], document
    except Exception as exc:
        return False, [f"Failed to open generated DOCX with python-docx: {exc}"], None


def _check_package_integrity(path: str) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                issues.append(f"Corrupted ZIP member detected in DOCX package: {bad_member}")
                return False, issues

            names = set(zf.namelist())
            missing = [n for n in REQUIRED_ZIP_ENTRIES if n not in names]
            if missing:
                issues.append(f"DOCX package missing required OPC parts: {', '.join(missing)}")
                return False, issues

            try:
                etree.fromstring(zf.read("word/document.xml"))
            except Exception as exc:
                issues.append(f"word/document.xml is not well-formed XML: {exc}")
                return False, issues

        return True, issues
    except FileNotFoundError:
        return False, [f"Generated DOCX not found at '{path}'."]
    except Exception as exc:
        return False, [f"DOCX is not a valid ZIP/OPC package: {exc}"]


def _check_structure(
    template_path: str,
    output_path: str,
    dynamic_table_rules: List[DynamicTableRule],
) -> Tuple[Dict[str, bool], List[str]]:
    checks = {
        "section_count_preserved": False,
        "section_orientation_margins_preserved": False,
        "table_count_structurally_compatible": False,
    }
    issues: List[str] = []

    try:
        template_snapshot = snapshot_template_structure(template_path)
        output_snapshot = snapshot_template_structure(output_path)
    except Exception as exc:
        issues.append(f"Failed to snapshot document structure for comparison against authoritative template: {exc}")
        return checks, issues

    checks["section_count_preserved"] = template_snapshot.section_count == output_snapshot.section_count

    comparison = compare_template_structure(
        template_snapshot=template_snapshot,
        output_snapshot=output_snapshot,
        allow_table_expansion=False,
        allow_row_growth=False,
        dynamic_table_rules=dynamic_table_rules,
    )

    checks["section_orientation_margins_preserved"] = (
        len(comparison.section_violations) == 0 and len(comparison.margin_violations) == 0
    )
    checks["table_count_structurally_compatible"] = len(comparison.table_geometry_violations) == 0

    if not checks["section_count_preserved"]:
        issues.append(
            f"Section count mismatch vs authoritative template: template={template_snapshot.section_count}, "
            f"output={output_snapshot.section_count}"
        )
    issues.extend(comparison.margin_violations)
    issues.extend(v for v in comparison.section_violations if "Section count mismatch" not in v)
    issues.extend(comparison.table_geometry_violations)

    return checks, issues


def _check_header_footer_relationships(output_doc: "docx.Document") -> Tuple[bool, List[str]]:
    issues: List[str] = []
    ok = True
    rels = output_doc.part.rels
    sect_prs = output_doc.element.body.xpath(".//w:sectPr")

    if not sect_prs:
        return False, ["No w:sectPr section properties found in the generated document body."]

    found_any_ref = False
    for idx, sect_pr in enumerate(sect_prs):
        for tag in ("headerReference", "footerReference"):
            for ref in sect_pr.findall(qn(f"w:{tag}")):
                found_any_ref = True
                rid = ref.get(qn("r:id"))
                if not rid or rid not in rels:
                    issues.append(f"Section {idx}: dangling w:{tag} relationship id '{rid}'.")
                    ok = False
                    continue
                try:
                    target_part = rels[rid].target_part
                    if target_part is None or target_part.blob is None:
                        issues.append(f"Section {idx}: w:{tag} '{rid}' resolves to an empty/missing part.")
                        ok = False
                except Exception as exc:
                    issues.append(f"Section {idx}: w:{tag} '{rid}' failed to resolve: {exc}")
                    ok = False

    if not found_any_ref:
        issues.append("No header/footer relationships found in any section (headerReference/footerReference missing).")
        ok = False

    return ok, issues


def _count_image_relationships(doc: "docx.Document") -> int:
    return sum(1 for rel in doc.part.rels.values() if rel.reltype.endswith("/image"))


def _check_image_logo_relationships(template_doc: "docx.Document", output_doc: "docx.Document") -> Tuple[bool, List[str]]:
    template_count = _count_image_relationships(template_doc)
    output_count = _count_image_relationships(output_doc)

    if template_count == 0:
        return True, []

    if output_count < template_count:
        return False, [
            f"Template has {template_count} image/logo relationship(s); generated document only has "
            f"{output_count}. Logo/image relationship appears to be missing."
        ]

    return True, []


def run_deterministic_checks(
    output_path: str,
    template_path: str = DEFAULT_AUTHORITATIVE_TEMPLATE_PATH,
    dynamic_table_rules: Optional[List[DynamicTableRule]] = None,
) -> Tuple[Dict[str, str], List[str], bool]:
    """Runs all deterministic (non-AI) DOCX QA checks against the authoritative template.

    Returns (checks_dict, issues, all_passed).
    """
    dynamic_table_rules = dynamic_table_rules if dynamic_table_rules is not None else DEFAULT_DYNAMIC_TABLE_RULES
    issues: List[str] = []
    checks: Dict[str, str] = {}

    def _set(name: str, ok: bool) -> None:
        checks[name] = STATUS_PASS if ok else STATUS_FAIL

    remaining_check_names = (
        "docx_opens",
        "package_integrity",
        "no_corruption_detected",
        "section_count_preserved",
        "section_orientation_margins_preserved",
        "table_count_structurally_compatible",
        "header_footer_relationships_present",
        "image_logo_relationships_preserved",
    )

    template_exists = os.path.exists(template_path)
    _set("authoritative_template_located", template_exists)
    if not template_exists:
        issues.append(f"Authoritative MB07 template not found at '{template_path}'. Failing closed.")
        for name in remaining_check_names:
            checks[name] = STATUS_FAIL
        return checks, issues, False

    opens_ok, open_issues, output_doc = _check_docx_opens(output_path)
    _set("docx_opens", opens_ok)
    issues.extend(open_issues)

    package_ok, package_issues = _check_package_integrity(output_path)
    _set("package_integrity", package_ok)
    _set("no_corruption_detected", opens_ok and package_ok)
    issues.extend(package_issues)

    if not opens_ok or not package_ok:
        for name in (
            "section_count_preserved",
            "section_orientation_margins_preserved",
            "table_count_structurally_compatible",
            "header_footer_relationships_present",
            "image_logo_relationships_preserved",
        ):
            checks[name] = STATUS_FAIL
        issues.append("Skipped structural/relationship checks: generated DOCX failed to open or is corrupted.")
        return checks, issues, False

    structure_checks, structure_issues = _check_structure(template_path, output_path, dynamic_table_rules)
    for key, ok in structure_checks.items():
        _set(key, ok)
    issues.extend(structure_issues)

    hf_ok, hf_issues = _check_header_footer_relationships(output_doc)
    _set("header_footer_relationships_present", hf_ok)
    issues.extend(hf_issues)

    try:
        template_doc = docx.Document(template_path)
        img_ok, img_issues = _check_image_logo_relationships(template_doc, output_doc)
    except Exception as exc:
        img_ok, img_issues = False, [f"Failed to open authoritative template to verify image relationships: {exc}"]
    _set("image_logo_relationships_preserved", img_ok)
    issues.extend(img_issues)

    all_passed = all(v == STATUS_PASS for v in checks.values())
    return checks, issues, all_passed


# ==============================================================================
# 3. DOCX -> PAGE IMAGE RENDERING (LibreOffice headless, read-only)
# ==============================================================================
class DocxPageRenderer:
    """Renders DOCX pages to PNG images for visual QA ONLY. Never mutates the source DOCX.

    Preferred mechanism: LibreOffice/soffice headless (cross-platform, no Word automation).
    If unavailable, callers must surface an explicit VISUAL_QA_UNAVAILABLE state rather than
    silently skipping visual QA.
    """

    _SOFFICE_ENV_VARS = ("LIBREOFFICE_SOFFICE_PATH", "SOFFICE_PATH")
    _COMMON_WINDOWS_PATHS = (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    )
    _COMMON_UNIX_PATHS = (
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/opt/libreoffice/program/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    )

    @classmethod
    def find_soffice(cls) -> Optional[str]:
        for env_var in cls._SOFFICE_ENV_VARS:
            candidate = os.getenv(env_var)
            if candidate and os.path.exists(candidate):
                return candidate

        which_result = shutil.which("soffice") or shutil.which("soffice.exe") or shutil.which("libreoffice")
        if which_result:
            return which_result

        for candidate in (*cls._COMMON_WINDOWS_PATHS, *cls._COMMON_UNIX_PATHS):
            if os.path.exists(candidate):
                return candidate

        return None

    @classmethod
    def is_available(cls) -> bool:
        return cls.find_soffice() is not None and pdfium is not None

    @classmethod
    def render_to_page_images(
        cls,
        docx_path: str,
        out_dir: str,
        dpi: int = DEFAULT_RENDER_DPI,
        max_pages: Optional[int] = None,
        timeout: float = 120.0,
    ) -> List[str]:
        """Converts a DOCX to PDF via headless LibreOffice, then rasterizes pages to PNG."""
        soffice_path = cls.find_soffice()
        if soffice_path is None or pdfium is None:
            raise VisualQAUnavailableError(
                "No headless DOCX->PDF renderer (LibreOffice/soffice) or pypdfium2 is available in this environment."
            )
        if not os.path.exists(docx_path):
            raise VisualQAUnavailableError(f"Cannot render: DOCX not found at '{docx_path}'.")

        os.makedirs(out_dir, exist_ok=True)

        try:
            result = subprocess.run(
                [
                    soffice_path,
                    "--headless",
                    "--norestore",
                    "--convert-to", "pdf",
                    "--outdir", out_dir,
                    docx_path,
                ],
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise VisualQAUnavailableError(f"LibreOffice headless conversion timed out: {exc}") from exc
        except Exception as exc:
            raise VisualQAUnavailableError(f"Failed to invoke LibreOffice headless conversion: {exc}") from exc

        pdf_name = os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
        pdf_path = os.path.join(out_dir, pdf_name)
        if result.returncode != 0 or not os.path.exists(pdf_path):
            stderr_preview = (result.stderr or b"").decode("utf-8", errors="ignore")[:400]
            raise VisualQAUnavailableError(
                f"LibreOffice failed to convert DOCX to PDF (exit={result.returncode}): {stderr_preview}"
            )

        try:
            pdf_doc = pdfium.PdfDocument(pdf_path)
        except Exception as exc:
            raise VisualQAUnavailableError(f"Failed to open rendered PDF with pypdfium2: {exc}") from exc

        try:
            page_count = len(pdf_doc)
            page_limit = page_count if max_pages is None else min(page_count, max_pages)
            scale = dpi / 72.0
            image_paths: List[str] = []
            for i in range(page_limit):
                page = pdf_doc[i]
                try:
                    pil_img = page.render(scale=scale).to_pil()
                    img_path = os.path.join(out_dir, f"page_{i + 1}.png")
                    pil_img.save(img_path, format="PNG")
                    image_paths.append(img_path)
                finally:
                    page.close()
                    if "pil_img" in locals():
                        del pil_img
            return image_paths
        finally:
            pdf_doc.close()


def _file_to_b64_png(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ==============================================================================
# 4. GREENNODE VISUAL DOCUMENT QA AGENT (AI REVIEWER ONLY)
# ==============================================================================
VISION_QA_SYSTEM_PROMPT = (
    "You are a strict, READ-ONLY Visual Formatting QA reviewer for MSB bank credit-proposal "
    "documents (MB07 template).\n"
    "You are a REVIEWER ONLY. You never edit, repair, rewrite, or suggest direct modification of "
    "the DOCX file. You only report PASS/FAIL/UNKNOWN judgments and structured findings.\n\n"
    "You will be shown exactly two page images in this order:\n"
    "1. The AUTHORITATIVE MB07 TEMPLATE page — a STYLE/LAYOUT REFERENCE ONLY. It is NOT an "
    "exact content replica or a page-by-page match of the final document.\n"
    "2. The GENERATED PROPOSAL page — rendered from the same MB07 template, populated with a "
    "specific customer's data.\n\n"
    "ABSOLUTE GROUND RULES — every one of the following is NORMAL and EXPECTED, and must NEVER "
    "be reported as a defect or cause a FAIL:\n"
    "- Generated content (customer names, numbers, narrative wording, dates, amounts) differs "
    "from the template's placeholder/example content.\n"
    "- Pagination differs: the generated document may have more or fewer pages than the "
    "template because customer data and narrative text have different lengths.\n"
    "- A section, table, or paragraph appears on a different page than in the template, or "
    "content flows onto the next/previous page.\n"
    "- Template guidance text, instructions, or placeholder wording intentionally disappears in "
    "the final generated document.\n"
    "- Template RED instructional text intentionally becomes normal BLACK final content — this "
    "is the intended final state, not a color/font defect.\n"
    "- Placeholder dots, ellipses, or dotted lines intentionally disappear once real data fills "
    "the field.\n"
    "- A table has fewer or more populated ROWS than the template. Row-count differences are "
    "owned entirely by deterministic structural QA, never by you.\n"
    "- Footnote numbering or footnote text presence/content differs from the template. "
    "Footnotes are NOT a visual-fidelity criterion.\n"
    "- Any missing or extra business content, rows, sections, footnotes, labels, or "
    "placeholders.\n\n"
    "DO NOT assess or comment on: document/content completeness, whether all expected content "
    "is present, business or credit meaning, financial figures, or approve/reject any credit "
    "proposal — you are not a credit reviewer. Deterministic Python QA already owns document "
    "structure (section count, table count, headers/footers existing, margins). You own ONLY "
    "visible formatting/RENDERING quality — how the things that ARE on the page actually look, "
    "never whether the right things are present.\n\n"
    "You may ONLY fail one of these 5 categories, and ONLY for a genuine VISUAL rendering/"
    "formatting defect that is completely independent of any business-content or pagination "
    "difference:\n"
    "  * logo — the MSB logo is visibly missing, broken, or corrupted where it should render.\n"
    "  * header_footer — header/footer is visibly corrupted, garbled, or overlapping other "
    "content (NOT merely a different page number or different footnote content).\n"
    "  * font_consistency — an obvious font-family or font-size inconsistency within the "
    "document's own style (e.g. a sans-serif block inside an otherwise Times New Roman "
    "document), independent of what the text actually says.\n"
    "  * table_layout — a table is structurally broken on the page: malformed or missing "
    "borders, misaligned or collapsed cell geometry, visibly wrong column widths. NOT simply a "
    "different number of populated rows.\n"
    "  * spacing_alignment — abnormal paragraph spacing/alignment, text that is visibly "
    "clipped, overflowing, or run together with no separating space (e.g. \"Chọn kết quảTái "
    "cấp và\" or \"Chọn kết quảTối đa 700 tỷ đồng\"), or a large unexplained blank area caused "
    "by a rendering/layout error (NOT merely content ending early on a page).\n\n"
    "Return STRICT JSON ONLY. No markdown code fences. No commentary before or after the JSON. "
    "The JSON object MUST match exactly this schema:\n"
    '{"logo": "PASS|FAIL|UNKNOWN", "header_footer": "PASS|FAIL|UNKNOWN", '
    '"font_consistency": "PASS|FAIL|UNKNOWN", "table_layout": "PASS|FAIL|UNKNOWN", '
    '"spacing_alignment": "PASS|FAIL|UNKNOWN", "overall_visual_fidelity": "PASS|FAIL", '
    '"findings": [{"category": '
    '"logo|header_footer|font_consistency|table_layout|spacing_alignment", '
    '"description": "short factual description of ONE genuine visual defect only"}]}\n'
    "If a category cannot be determined from this page (e.g. no table on this page), use "
    "\"UNKNOWN\" for that category only. Every category you mark FAIL MUST have at least one "
    "matching entry in \"findings\" with that exact category, describing the genuine visual "
    "defect only — NEVER a content, pagination, footnote, placeholder, or completeness "
    "observation. If you have no genuine visual defect to report, \"findings\" must be an empty "
    "list and every category must be PASS or UNKNOWN."
)

_ALLOWED_CATEGORY_VALUES = {STATUS_PASS, STATUS_FAIL, STATUS_UNKNOWN}
_ALLOWED_OVERALL_VALUES = {STATUS_PASS, STATUS_FAIL}
_ALLOWED_FINDING_CATEGORIES = set(_VISUAL_CHECK_KEYS)

# Defensive backstop (schema/prompt validation is the primary defense above): even a
# well-behaved model can still attach a content/pagination-only observation as "evidence"
# for a FAIL. A finding matching one of these keyword groups can NEVER, on its own,
# substantiate a FAIL for the category it's attached to (see _validate_visual_schema).
# Each group is a tuple of keyword stems that must ALL appear somewhere in the finding text
# (in any order/distance) for it to count as a content/pagination-only observation — this is
# deliberately looser than fixed-phrase matching, since real model wording varies
# ("missing 2 rows", "2 rows are missing", "row count differs", ...).
_CONTENT_COMPLETENESS_KEYWORD_GROUPS: Tuple[Tuple[str, ...], ...] = (
    ("missing", "row"), ("extra", "row"), ("unexpected", "row"), ("fewer", "row"), ("more", "row"),
    ("row", "count"),
    ("missing", "section"), ("extra", "section"), ("different", "section"),
    ("missing", "footnote"), ("different", "footnote"), ("footnote", "number"), ("footnote", "content"),
    ("missing", "text"), ("missing", "label"), ("missing", "wording"),
    ("placeholder",),
    ("dotted",),
    ("ellipsis",),
    ("guidance", "text"),
    ("instructional", "text"),
    ("instruction", "text"),
    ("red", "text"),
    ("becom", "black"),
    ("pagination",),
    ("page", "shift"),
    ("different", "page"),
    ("another", "page"),
    ("next", "page"),
    ("previous", "page"),
    ("flow", "page"),
    ("different", "customer"),
    ("different", "business"),
    ("content", "difference"),
    ("business", "content"),
    ("customer", "data"),
)

_COMPILED_CONTENT_COMPLETENESS_GROUPS: Tuple[Tuple["re.Pattern", ...], ...] = tuple(
    tuple(re.compile(rf"\b{re.escape(term)}", re.IGNORECASE) for term in group)
    for group in _CONTENT_COMPLETENESS_KEYWORD_GROUPS
)


def _is_content_completeness_finding(description: str) -> bool:
    """True if the finding text only describes a content/pagination difference — the kind
    of thing the vision reviewer is explicitly told is normal and must never cause a FAIL."""
    return any(
        all(pattern.search(description) for pattern in group)
        for group in _COMPILED_CONTENT_COMPLETENESS_GROUPS
    )


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _parse_strict_json(raw_content: str, page_num: int) -> Dict[str, Any]:
    if _json is None:  # pragma: no cover
        raise GreenNodeVisionQAError("json module unavailable in this runtime.")

    candidate = raw_content.strip()
    try:
        return _json.loads(candidate)
    except Exception:
        pass

    fenced = _strip_markdown_fence(candidate)
    try:
        return _json.loads(fenced)
    except Exception as exc:
        raise GreenNodeVisionQAError(
            f"GreenNode visual QA returned non-JSON or malformed JSON for page {page_num}: {exc}. "
            f"Raw content (truncated): {candidate[:300]!r}"
        ) from exc


def _validate_visual_schema(parsed: Any, page_num: int) -> Dict[str, Any]:
    """Validates the raw GreenNode response, then applies the content/pagination finding
    filter and re-derives each category (and overall_visual_fidelity) from surviving,
    genuinely-visual, category-scoped findings only.

    A category the model marked FAIL is downgraded to PASS if none of its attached findings
    survive the content-completeness filter (i.e. the only "evidence" for that FAIL was a
    content, pagination, footnote, placeholder, or completeness observation — which this
    reviewer is never allowed to use as grounds for FAIL). overall_visual_fidelity is always
    recomputed in Python from the (possibly downgraded) categories, never trusted verbatim
    from the model.
    """
    if not isinstance(parsed, dict):
        raise GreenNodeVisionQAError(f"GreenNode visual QA response for page {page_num} is not a JSON object.")

    missing = [k for k in _ALL_VISUAL_KEYS if k not in parsed]
    if missing:
        raise GreenNodeVisionQAError(
            f"GreenNode visual QA response for page {page_num} is missing required keys: {missing}."
        )

    for key in _VISUAL_CHECK_KEYS:
        value = parsed.get(key)
        if value not in _ALLOWED_CATEGORY_VALUES:
            raise GreenNodeVisionQAError(
                f"GreenNode visual QA response for page {page_num} has invalid value for '{key}': {value!r}."
            )

    overall_raw = parsed.get("overall_visual_fidelity")
    if overall_raw not in _ALLOWED_OVERALL_VALUES:
        raise GreenNodeVisionQAError(
            f"GreenNode visual QA response for page {page_num} has invalid 'overall_visual_fidelity': {overall_raw!r}."
        )

    raw_findings = parsed.get("findings")
    if raw_findings is None:
        raw_findings = []
    if not isinstance(raw_findings, list):
        raise GreenNodeVisionQAError(
            f"GreenNode visual QA response for page {page_num} has non-list 'findings' field."
        )

    genuine_findings: List[Tuple[str, str]] = []  # (category, description)
    categories_with_genuine_evidence = set()

    for item in raw_findings:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        description = item.get("description")
        if category not in _ALLOWED_FINDING_CATEGORIES:
            continue
        if not isinstance(description, str) or not description.strip():
            continue
        description = description.strip()

        if _is_content_completeness_finding(description):
            # Explicitly ignored: content/pagination/footnote/placeholder-only observation.
            continue

        genuine_findings.append((category, description))
        categories_with_genuine_evidence.add(category)

    result: Dict[str, Any] = {}
    for key in _VISUAL_CHECK_KEYS:
        model_value = parsed[key]
        if model_value == STATUS_FAIL and key not in categories_with_genuine_evidence:
            # The model claimed FAIL but every attached finding for this category was
            # content/pagination noise (or no finding was attached at all) -> no genuine
            # visual defect survives, so this is not a real fidelity failure.
            result[key] = STATUS_PASS
        else:
            result[key] = model_value

    result["overall_visual_fidelity"] = STATUS_FAIL if any(
        result[key] == STATUS_FAIL for key in _VISUAL_CHECK_KEYS
    ) else STATUS_PASS
    # Only surface findings whose category is still FAIL after the filter, so a downgraded
    # (now-PASS) category never leaves a stray "issue" string behind.
    result["issues"] = [desc for cat, desc in genuine_findings if result[cat] == STATUS_FAIL]
    return result


class GreenNodeVisualQAAgent:
    """AI REVIEWER ONLY. Compares a template page image against a generated page image using
    the GreenNode MaaS vision model. Never writes to any document.

    Reuses the same GreenNode config resolution contract as ai_client.AIAssistantClient /
    pdf_ocr.QwenVisionOCREngine: env vars LLM_API_KEY / AI_PLATFORM_API_KEY / GREENNODE_API_KEY
    for the key, LLM_BASE_URL / GREENNODE_BASE_URL for the base URL, and VISION_MODEL /
    GREENNODE_VISION_MODEL for the model (defaulting to qwen/qwen3.6-flash).
    """

    DEFAULT_BASE_URL = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"
    DEFAULT_MODEL = "qwen/qwen3.6-flash"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 90.0,
    ):
        resolved_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("AI_PLATFORM_API_KEY")
            or os.getenv("GREENNODE_API_KEY")
        )
        if not resolved_key:
            raise GreenNodeVisionQAError(
                "Missing GreenNode API key (LLM_API_KEY / AI_PLATFORM_API_KEY / GREENNODE_API_KEY). "
                "No silent fallback: visual QA cannot run without credentials."
            )

        self.base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or os.getenv("GREENNODE_BASE_URL")
            or self.DEFAULT_BASE_URL
        )
        self.model = (
            model
            or os.getenv("VISION_MODEL")
            or os.getenv("GREENNODE_VISION_MODEL")
            or self.DEFAULT_MODEL
        )
        self.timeout = timeout

        from openai import OpenAI  # local import to keep module import light for pure-deterministic use

        self.client = OpenAI(
            api_key=resolved_key,
            base_url=self.base_url,
            max_retries=0,
            timeout=self.timeout,
        )

    def compare_page(self, template_b64_png: str, generated_b64_png: str, page_num: int) -> Dict[str, Any]:
        messages = [
            {"role": "system", "content": VISION_QA_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Page {page_num}. Compare ONLY formatting/rendering fidelity. "
                            "Image 1 = authoritative MB07 template (style/layout reference only). "
                            "Image 2 = generated proposal (different customer content and pagination are "
                            "expected and must never be reported). Return strict JSON only."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{template_b64_png}"}},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{generated_b64_png}"}},
                ],
            },
        ]

        # Only the network/API call itself is retried, and only for the retryable HTTP
        # status codes below. A successful HTTP call that returns empty/malformed content
        # is NEVER retried — it fails closed immediately (see below, outside this loop).
        response = None
        for attempt in range(1, MAX_VISUAL_QA_ATTEMPTS + 1):
            start_time = time.perf_counter()
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=1024,
                )
                break
            except Exception as exc:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                status_code = getattr(exc, "status_code", None)
                retryable = status_code in RETRYABLE_STATUS_CODES

                if retryable and attempt < MAX_VISUAL_QA_ATTEMPTS:
                    wait_seconds = self._compute_retry_wait_seconds(exc, attempt)
                    logger.warning(
                        "GreenNode visual QA page %s: retryable HTTP %s on attempt %d/%d, "
                        "waiting %.2fs before retry.",
                        page_num, status_code, attempt, MAX_VISUAL_QA_ATTEMPTS, wait_seconds,
                    )
                    self._record_telemetry(
                        page_num, latency_ms, success=False,
                        error=f"HTTP {status_code} (retrying, attempt {attempt}/{MAX_VISUAL_QA_ATTEMPTS})",
                    )
                    time.sleep(wait_seconds)
                    continue

                if retryable:
                    # Exhausted all retry attempts on a retryable error -> fail closed.
                    logger.warning(
                        "GreenNode visual QA page %s: retry attempts exhausted (%d/%d) after HTTP %s.",
                        page_num, attempt, MAX_VISUAL_QA_ATTEMPTS, status_code,
                    )
                    self._record_telemetry(
                        page_num, latency_ms, success=False,
                        error=f"HTTP {status_code} (retry exhausted)",
                    )
                    raise GreenNodeVisionQAError(
                        f"GreenNode visual QA rate limit/retry exhausted for page {page_num} "
                        f"after {MAX_VISUAL_QA_ATTEMPTS} attempts (last HTTP {status_code})."
                    ) from exc

                # Non-retryable error: fail closed immediately, no retry.
                self._record_telemetry(
                    page_num, latency_ms, success=False,
                    error=f"HTTP {status_code}" if status_code is not None else "non-retryable error",
                )
                raise GreenNodeVisionQAError(
                    f"GreenNode visual QA API call failed for page {page_num} (fail-closed, non-retryable): {exc}"
                ) from exc

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        content = response.choices[0].message.content if response.choices else None
        if not content or not content.strip():
            self._record_telemetry(page_num, latency_ms, success=False, error="empty response")
            raise GreenNodeVisionQAError(f"GreenNode visual QA returned empty content for page {page_num}.")

        parsed_raw = _parse_strict_json(content, page_num)
        parsed = _validate_visual_schema(parsed_raw, page_num)
        self._record_telemetry(page_num, latency_ms, success=True)
        return parsed

    @staticmethod
    def _compute_retry_wait_seconds(exc: Exception, attempt: int) -> float:
        """Respects a server-provided Retry-After header when present; otherwise falls back
        to the approximate exponential backoff schedule (2s, 5s, 10s) plus small jitter."""
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None) if response is not None else None
        if headers is not None:
            try:
                raw_retry_after = headers.get("Retry-After")
            except Exception:
                raw_retry_after = None
            if raw_retry_after is not None:
                try:
                    return max(0.0, float(raw_retry_after))
                except (TypeError, ValueError):
                    pass

        schedule_index = min(attempt - 1, len(_RETRY_BACKOFF_SCHEDULE_SECONDS) - 1)
        return _RETRY_BACKOFF_SCHEDULE_SECONDS[schedule_index] + random.uniform(0.0, _RETRY_JITTER_MAX_SECONDS)

    def _record_telemetry(self, page_num: int, latency_ms: float, success: bool, error: Optional[str] = None) -> None:
        try:
            from .ai_client import AIAssistantClient

            AIAssistantClient.record_telemetry(
                operation=f"document_qa_visual_page_{page_num}",
                model=self.model,
                latency_ms=latency_ms,
                success=success,
                error=error,
            )
        except Exception:
            pass


def _worst_status(values: List[str]) -> str:
    if any(v == STATUS_FAIL for v in values):
        return STATUS_FAIL
    if any(v == STATUS_UNKNOWN for v in values) or not values:
        return STATUS_UNKNOWN
    return STATUS_PASS


# ==============================================================================
# 5. TOP-LEVEL ORCHESTRATOR
# ==============================================================================
def _blank_visual_checks() -> Dict[str, str]:
    return {k: STATUS_UNKNOWN for k in _ALL_VISUAL_KEYS}


def _build_result(
    status: str,
    deterministic_checks: Dict[str, str],
    visual_checks: Dict[str, str],
    issues: List[str],
    model_name: Optional[str],
    timestamp: str,
) -> Dict[str, Any]:
    return {
        "status": status,
        "deterministic_checks": deterministic_checks,
        "visual_checks": visual_checks,
        "issues": issues,
        "model": model_name,
        "qa_timestamp": timestamp,
    }


class DocumentQAAgent:
    """Orchestrates the full Document QA pipeline: deterministic checks first, then
    (if deterministic checks pass) GreenNode visual QA. AI is a reviewer only and never
    mutates the DOCX.
    """

    def __init__(
        self,
        template_path: Optional[str] = None,
        dynamic_table_rules: Optional[List[DynamicTableRule]] = None,
        renderer: Type[DocxPageRenderer] = DocxPageRenderer,
        vision_agent_factory: Optional[Any] = None,
        max_visual_pages: Optional[int] = None,
        render_dpi: Optional[int] = None,
        page_delay_seconds: Optional[float] = None,
    ):
        self.template_path = template_path or DEFAULT_AUTHORITATIVE_TEMPLATE_PATH
        self.dynamic_table_rules = dynamic_table_rules if dynamic_table_rules is not None else DEFAULT_DYNAMIC_TABLE_RULES
        self.renderer = renderer
        self.vision_agent_factory = vision_agent_factory or GreenNodeVisualQAAgent
        self.max_visual_pages = max_visual_pages if max_visual_pages is not None else DEFAULT_VISUAL_QA_MAX_PAGES
        self.render_dpi = render_dpi if render_dpi is not None else DEFAULT_RENDER_DPI
        self.page_delay_seconds = page_delay_seconds if page_delay_seconds is not None else DEFAULT_PAGE_DELAY_SECONDS

    def run_qa(self, generated_docx_path: str) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()

        deterministic_checks, issues, deterministic_ok = run_deterministic_checks(
            output_path=generated_docx_path,
            template_path=self.template_path,
            dynamic_table_rules=self.dynamic_table_rules,
        )
        issues = list(issues)

        if not deterministic_ok:
            return _build_result(STATUS_FAIL, deterministic_checks, _blank_visual_checks(), issues, None, timestamp)

        # Deterministic QA passed. Attempt visual QA. Renderer unavailability must never
        # silently become a PASS.
        if not self.renderer.is_available():
            issues.append(
                "VISUAL_QA_UNAVAILABLE: no headless DOCX renderer (LibreOffice/soffice + pypdfium2) detected "
                "in this environment. Visual fidelity could not be verified; deterministic checks above are "
                "shown separately and are unaffected."
            )
            return _build_result(
                STATUS_VISUAL_QA_UNAVAILABLE, deterministic_checks, _blank_visual_checks(), issues, None, timestamp
            )

        with tempfile.TemporaryDirectory(prefix="docqa_") as tmp_dir:
            try:
                template_images = self.renderer.render_to_page_images(
                    self.template_path,
                    os.path.join(tmp_dir, "template"),
                    dpi=self.render_dpi,
                    max_pages=self.max_visual_pages,
                )
                generated_images = self.renderer.render_to_page_images(
                    generated_docx_path,
                    os.path.join(tmp_dir, "generated"),
                    dpi=self.render_dpi,
                    max_pages=self.max_visual_pages,
                )
            except VisualQAUnavailableError as exc:
                issues.append(f"VISUAL_QA_UNAVAILABLE: {exc}")
                return _build_result(
                    STATUS_VISUAL_QA_UNAVAILABLE, deterministic_checks, _blank_visual_checks(), issues, None, timestamp
                )

            page_pairs = min(len(template_images), len(generated_images))
            if page_pairs == 0:
                issues.append("VISUAL_QA_UNAVAILABLE: rendering produced zero comparable page images.")
                return _build_result(
                    STATUS_VISUAL_QA_UNAVAILABLE, deterministic_checks, _blank_visual_checks(), issues, None, timestamp
                )

            try:
                agent = self.vision_agent_factory()
            except GreenNodeVisionQAError as exc:
                issues.append(f"Visual QA reviewer could not be initialized (fail-closed): {exc}")
                return _build_result(STATUS_FAIL, deterministic_checks, _blank_visual_checks(), issues, None, timestamp)

            model_name = getattr(agent, "model", None)
            per_category: Dict[str, List[str]] = {k: [] for k in _VISUAL_CHECK_KEYS}

            try:
                for i in range(page_pairs):
                    template_b64 = _file_to_b64_png(template_images[i])
                    generated_b64 = _file_to_b64_png(generated_images[i])
                    page_result = agent.compare_page(template_b64, generated_b64, page_num=i + 1)

                    for key in per_category:
                        per_category[key].append(page_result.get(key, STATUS_UNKNOWN))

                    for item in page_result.get("issues", []) or []:
                        issues.append(f"[page {i + 1}] {item}")

                    # Small pacing delay between successful page calls (separate from retry
                    # backoff) to stay comfortably under GreenNode rate limits.
                    if self.page_delay_seconds > 0 and i < page_pairs - 1:
                        time.sleep(self.page_delay_seconds)
            except GreenNodeVisionQAError as exc:
                issues.append(f"GreenNode visual QA failed (fail-closed): {exc}")
                return _build_result(
                    STATUS_FAIL, deterministic_checks, _blank_visual_checks(), issues, model_name, timestamp
                )

        visual_checks = {key: _worst_status(values) for key, values in per_category.items()}

        # Export policy: only a genuine FAIL on a blocking visual category (logo,
        # header_footer, table_layout, spacing_alignment) fails the whole document and
        # blocks export. A font_consistency-only FAIL is downgraded to a non-blocking
        # PASS_WITH_WARNING — the finding stays visible in `issues` and in
        # visual_checks['font_consistency'] (still reported as FAIL there), it just
        # doesn't gate export. Deterministic checks are never affected by this policy.
        has_blocking_visual_fail = any(visual_checks[key] == STATUS_FAIL for key in _BLOCKING_VISUAL_CATEGORIES)
        has_warning_only_fail = any(visual_checks[key] == STATUS_FAIL for key in _WARNING_ONLY_VISUAL_CATEGORIES)

        if has_blocking_visual_fail:
            visual_checks["overall_visual_fidelity"] = STATUS_FAIL
            overall_status = STATUS_FAIL
        elif has_warning_only_fail:
            visual_checks["overall_visual_fidelity"] = STATUS_PASS_WITH_WARNING
            overall_status = STATUS_PASS_WITH_WARNING
            issues.append(
                "font_consistency reported a rendering difference (non-blocking: cross-platform "
                "font-substitution findings do not block export per policy). Review before finalizing."
            )
        else:
            visual_checks["overall_visual_fidelity"] = STATUS_PASS
            overall_status = STATUS_PASS

        return _build_result(overall_status, deterministic_checks, visual_checks, issues, model_name, timestamp)


def run_document_qa_gate(
    generated_docx_path: str,
    template_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience export gate.

    - status PASS -> returns qa_result, caller may export.
    - status PASS_WITH_WARNING -> returns qa_result (does NOT raise); deterministic checks
      passed and the only visual-QA failure is font_consistency (non-blocking per policy —
      cross-platform font-substitution rendering differences). Caller may export, but MUST
      surface the warning explicitly (never silently treat it as a clean PASS).
    - status VISUAL_QA_UNAVAILABLE -> returns qa_result (does NOT raise); deterministic checks
      already passed, but visual fidelity could not be verified in this environment. Caller
      decides whether to still allow export, but MUST surface this state explicitly (never
      silently treat it as PASS).
    - status FAIL -> raises DocumentQAFailedError carrying the full qa_result; caller must
      block export. This includes: any deterministic check failing, or a genuine visual
      FAIL on logo/header_footer/table_layout/spacing_alignment.
    """
    agent = DocumentQAAgent(template_path=template_path)
    result = agent.run_qa(generated_docx_path)
    if result["status"] == STATUS_FAIL:
        raise DocumentQAFailedError(result)
    return result
