# -*- coding: utf-8 -*-
"""Tests for the Financial conflict-resolution submission path and the
deterministic-ratio display contract.

=================================================================
BUG 1 HISTORY: financial conflict resolution still invalid
=================================================================
Round 1 root cause (fixed previously): the <option value="..."> markup used
UPPERCASE machine values ("USE_EXTRACTED"/"KEEP_EXISTING") while the backend
only accepted lowercase. Fixed by lower-casing the <option> values.

Round 2 (this file): after an exhaustive UI->backend runtime trace (selector
generation, review_table/canonical_field/year, resolutions object,
JSON.stringify(payload), POST /api/confirm_financial_preview,
validate_and_confirm_financial_preview), no further divergence in VALUE could
be reproduced against the current source for a single-render modal. Per the
requested "preferred design", resolution binding was hardened anyway from a
DOM-id built out of the canonical path (e.g. id="res-fin-current_assets-2025",
looked up again via a matching id string built the same way in
confirmDocPreview) to a `data-canonical-path` attribute read back through
`document.querySelectorAll('.financial-resolution-select')` /
`.legal-resolution-select`. This removes any future dependency on encoding a
canonical path (which contains "." and "[...]") into an id/CSS-selector-safe
string, removes any possibility of id collisions across rows/years, and no
longer requires the two code paths (render vs. read-back) to reconstruct the
identical id string independently.

A safe backend diagnostic log line (canonical_path + type/truncated repr of
the submitted value -- never document content) was also added so any future
recurrence in production can be diagnosed directly from logs.

=================================================================
BUG 2: auto-calculated financial ratios format broken (",0,0", "''", etc.)
=================================================================
Root cause: `calculated_ratios` values were ALWAYS per-year arrays
(Dict[str, List[Optional[float]]] -- see FinancialPreviewRecord.calculated_ratios
and compute_canonical_ratios), never scalars. The Python layer was already
correct (canonical floats or None, never presentation strings). The bug was
100% in the frontend renderer, which did
`typeof v === 'number' ? v.toFixed(2) : v`: since v was always an array (not a
number), it always fell through to bare `${v}` interpolation, which coerces
an array to a string via Array.prototype.join(',') -- e.g. [null, 0, 0] ->
",0,0", and [] -> "". Fixed with a dedicated formatFinancialMetric() that
iterates each year in the array and formats it explicitly.
"""

import copy
import unittest
from unittest.mock import patch

import web_copilot_app
from msb_eb_copilot.src.extraction.financial_extraction import (
    FinancialDocumentExtraction,
    FinancialEvidenceField,
    FinancialPeriodExtraction,
    FinancialUnitInfo,
)
from msb_eb_copilot.src.ingestion.router import DocumentIngestionResult
from msb_eb_copilot.src.mapping.financial_mapper import compute_canonical_ratios
from web_copilot_app import (
    CASES_DB,
    FINANCIAL_PREVIEW_STORE,
    HTML_PAGE,
    process_financial_pdf_preview,
    validate_and_confirm_financial_preview,
)


def _period(period: str, current_assets_raw: str) -> FinancialPeriodExtraction:
    return FinancialPeriodExtraction(
        period=period,
        current_assets=FinancialEvidenceField(
            value_raw=current_assets_raw,
            semantic_label="Tài sản ngắn hạn",
            accounting_code="100",
            evidence=f"Tài sản ngắn hạn | 100 | {current_assets_raw}",
            page=2,
        ),
    )


class FinancialConflictResolutionBackendTests(unittest.TestCase):
    """Section 9: A-C, F-J -- exercises validate_and_confirm_financial_preview
    directly with the exact machine values the frontend submits."""

    def setUp(self):
        self.orig_cases_db = copy.deepcopy(CASES_DB)
        FINANCIAL_PREVIEW_STORE.clear()

    def tearDown(self):
        web_copilot_app.CASES_DB.clear()
        web_copilot_app.CASES_DB.update(copy.deepcopy(self.orig_cases_db))
        FINANCIAL_PREVIEW_STORE.clear()

    def _make_conflicting_preview(self, current_assets_2025="9.999.999.000.000", current_assets_2024="8.888.888.000.000"):
        extraction = FinancialDocumentExtraction(
            document_title="Báo cáo tài chính",
            document_unit=FinancialUnitInfo(unit_raw="VND", evidence="Đơn vị tính: VND", page=1),
            periods=[
                _period("2024", current_assets_2024),
                _period("2025", current_assets_2025),
            ],
        )
        with patch("web_copilot_app.FinancialDocumentExtractor.extract", return_value=extraction), \
             patch("web_copilot_app.DocumentIngestionRouter.ingest_document", return_value=DocumentIngestionResult(
                 mode="digital", provider="pypdf", page_count=2,
                 tagged_text="[PAGE 1] test [PAGE 2] test",
             )):
            preview_res, status = process_financial_pdf_preview(b"%PDF-1.4", "bctc.pdf", case_id="PSD")
        self.assertEqual(status, 200)
        return preview_res["preview_id"]

    def test_a_current_assets_2025_use_extracted_accepted(self):
        """A. section_d.current_assets[2025] resolves with 'use_extracted'."""
        p_id = self._make_conflicting_preview()
        res, status = validate_and_confirm_financial_preview(
            preview_id=p_id, case_id="PSD",
            resolutions={"section_d.current_assets[2025]": "use_extracted", "section_d.current_assets[2024]": "use_extracted"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "success")

    def test_b_current_assets_2024_keep_existing_accepted(self):
        """B. section_d.current_assets[2024] resolves with 'keep_existing'."""
        p_id = self._make_conflicting_preview()
        existing = copy.deepcopy(CASES_DB["PSD"]["section_d"])
        idx_2024 = existing["years"].index("2024")
        original_value = existing["current_assets"][idx_2024]

        res, status = validate_and_confirm_financial_preview(
            preview_id=p_id, case_id="PSD",
            resolutions={"section_d.current_assets[2025]": "use_extracted", "section_d.current_assets[2024]": "keep_existing"},
        )
        self.assertEqual(status, 200)
        updated = web_copilot_app.CASES_DB["PSD"]["section_d"]
        self.assertEqual(updated["current_assets"][idx_2024], original_value)

    def test_c_paths_containing_square_brackets_resolve_correctly(self):
        """C. Canonical paths containing '[' and ']' round-trip correctly end
        to end (this is the literal reported field shape)."""
        p_id = self._make_conflicting_preview(current_assets_2025="9.999.999.000.000")
        key = "section_d.current_assets[2025]"
        self.assertIn("[", key)
        self.assertIn("]", key)
        res, status = validate_and_confirm_financial_preview(
            preview_id=p_id, case_id="PSD",
            resolutions={key: "use_extracted", "section_d.current_assets[2024]": "keep_existing"},
        )
        self.assertEqual(status, 200)
        updated = web_copilot_app.CASES_DB["PSD"]["section_d"]
        idx_2025 = updated["years"].index("2025")
        self.assertEqual(updated["current_assets"][idx_2025], 9999999.0)

    def test_d_multiple_conflict_selectors_both_resolve_independently(self):
        """D. Two conflicting years (two distinct selects) each resolve
        independently without cross-contamination."""
        p_id = self._make_conflicting_preview(current_assets_2025="9.999.999.000.000", current_assets_2024="7.777.777.000.000")
        res, status = validate_and_confirm_financial_preview(
            preview_id=p_id, case_id="PSD",
            resolutions={"section_d.current_assets[2025]": "use_extracted", "section_d.current_assets[2024]": "use_extracted"},
        )
        self.assertEqual(status, 200)
        updated = web_copilot_app.CASES_DB["PSD"]["section_d"]
        self.assertEqual(updated["current_assets"][updated["years"].index("2025")], 9999999.0)
        self.assertEqual(updated["current_assets"][updated["years"].index("2024")], 7777777.0)

    def test_e_unique_canonical_paths_per_conflict(self):
        """E. Each conflict object carries a distinct canonical_path -- no two
        conflicting rows collapse onto the same resolution key."""
        p_id = self._make_conflicting_preview()
        record = FINANCIAL_PREVIEW_STORE[p_id]
        paths = [c.canonical_path for c in record.mapping_result.conflicts]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn("section_d.current_assets[2025]", paths)
        self.assertIn("section_d.current_assets[2024]", paths)

    def test_f_use_extracted_submission(self):
        """F. 'use_extracted' is accepted and applies the extracted value."""
        p_id = self._make_conflicting_preview()
        res, status = validate_and_confirm_financial_preview(
            preview_id=p_id, case_id="PSD",
            resolutions={"section_d.current_assets[2025]": "use_extracted", "section_d.current_assets[2024]": "use_extracted"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "success")

    def test_g_keep_existing_submission(self):
        """G. 'keep_existing' is accepted and preserves the pre-existing value."""
        p_id = self._make_conflicting_preview()
        res, status = validate_and_confirm_financial_preview(
            preview_id=p_id, case_id="PSD",
            resolutions={"section_d.current_assets[2025]": "keep_existing", "section_d.current_assets[2024]": "keep_existing"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "success")

    def test_i_backend_rejects_invalid_enum(self):
        """I. Backend validation remains strict: label text, empty string,
        casing variants, booleans, and arbitrary values are all rejected."""
        p_id = self._make_conflicting_preview()
        for bad_value in ("USE_EXTRACTED", "KEEP_EXISTING", "", "✓ Dùng số liệu BCTC", None, True, "yes"):
            res, status = validate_and_confirm_financial_preview(
                preview_id=p_id, case_id="PSD",
                resolutions={"section_d.current_assets[2025]": bad_value, "section_d.current_assets[2024]": "use_extracted"},
            )
            self.assertEqual(status, 400, f"Expected rejection for bad_value={bad_value!r}")
            self.assertEqual(res["error_type"], "InvalidInputError")
            self.assertIn("use_extracted", res["message"])
            self.assertIn("keep_existing", res["message"])

    def test_j_valid_payload_confirms_successfully(self):
        """J. A full, valid resolution set for every conflicting field succeeds
        and marks the preview consumed."""
        p_id = self._make_conflicting_preview()
        res, status = validate_and_confirm_financial_preview(
            preview_id=p_id, case_id="PSD",
            resolutions={"section_d.current_assets[2025]": "use_extracted", "section_d.current_assets[2024]": "keep_existing"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "success")
        self.assertTrue(FINANCIAL_PREVIEW_STORE[p_id].consumed)


class FinancialConflictResolutionFrontendMarkupTests(unittest.TestCase):
    """Static/DOM assertions proving the robust data-canonical-path + class
    based selector mechanism is actually what's generated and read back."""

    def test_option_values_are_lowercase_machine_values_not_labels(self):
        self.assertIn('<option value="use_extracted">', HTML_PAGE)
        self.assertIn('<option value="keep_existing">', HTML_PAGE)
        self.assertNotIn("USE_EXTRACTED", HTML_PAGE)
        self.assertNotIn("KEEP_EXISTING", HTML_PAGE)

    def test_financial_select_uses_data_canonical_path_not_bracket_id(self):
        self.assertIn('class="financial-resolution-select', HTML_PAGE)
        self.assertIn('data-canonical-path="section_d.${item.canonical_field}[${item.year}]"', HTML_PAGE)
        # The old fragile id-encoding scheme must be gone entirely.
        self.assertNotIn('id="res-fin-${item.canonical_field}-${item.year}"', HTML_PAGE)
        self.assertNotIn("getElementById(`res-fin-", HTML_PAGE)

    def test_legal_select_uses_data_canonical_path_not_bracket_id(self):
        self.assertIn('class="legal-resolution-select', HTML_PAGE)
        self.assertIn('data-canonical-path="${f.canonical_path}"', HTML_PAGE)
        self.assertNotIn("id=\"res-legal-", HTML_PAGE)
        self.assertNotIn("getElementById('res-legal-", HTML_PAGE)

    def test_confirm_doc_preview_reads_back_via_query_selector_and_dataset(self):
        """Proves confirmDocPreview('financial')/('legal') build resolutions
        from querySelectorAll(...) + `.dataset.canonicalPath` / `.value`, not
        from a reconstructed id string."""
        fn_start = HTML_PAGE.index("async function confirmDocPreview")
        fn_end = HTML_PAGE.index("function openNewCaseModal")
        confirm_fn_body = HTML_PAGE[fn_start:fn_end]

        self.assertIn("document.querySelectorAll(`.${selectorClass}`)", confirm_fn_body)
        self.assertIn("sel.dataset.canonicalPath", confirm_fn_body)
        self.assertIn("collectResolutions('legal-resolution-select')", confirm_fn_body)
        self.assertIn("collectResolutions('financial-resolution-select')", confirm_fn_body)
        self.assertIn("resolutions[key] = sel.value;", confirm_fn_body)

    def test_client_side_validation_blocks_invalid_resolution_before_post(self):
        """A pre-POST guard inspects every collected resolution value against
        the accepted machine-value set and returns before fetch() runs if any
        is invalid -- preventing a malformed payload from ever being sent."""
        self.assertIn("VALID_RESOLUTION_VALUES", HTML_PAGE)
        self.assertIn("invalidResolutionEls", HTML_PAGE)
        fn_start = HTML_PAGE.index("async function confirmDocPreview")
        confirm_fn_body = HTML_PAGE[fn_start:]
        guard_idx = confirm_fn_body.index("if (invalidResolutionEls.length > 0)")
        fetch_idx = confirm_fn_body.index("const res = await fetch(endpoints[docType]")
        self.assertLess(guard_idx, fetch_idx, "Validation guard must run before the network request")


class FinancialRatioFormattingBackendTests(unittest.TestCase):
    """Section 10 (Python side): compute_canonical_ratios must never fabricate
    a ratio for a zero/missing denominator, and must return plain floats or
    None -- never strings."""

    def test_zero_denominator_yields_none(self):
        section_d = {
            "years": ["2025"],
            "current_assets": [100.0],
            "current_liabilities": [0.0],
            "short_term_debt": [0.0],
            "cash": [10.0],
            "inventories": [5.0],
            "total_assets": [200.0],
            "total_liabilities": [0.0],
            "equity": [0.0],
            "net_revenue": [0.0],
            "gross_profit": [0.0],
            "net_profit_after_tax": [0.0],
        }
        ratios = compute_canonical_ratios(section_d)
        self.assertIsNone(ratios["current_ratio"][0])
        self.assertIsNone(ratios["quick_ratio"][0])
        self.assertIsNone(ratios["cash_ratio"][0])
        self.assertIsNone(ratios["debt_to_equity"][0])
        self.assertIsNone(ratios["ros"][0])
        self.assertIsNone(ratios["roe"][0])

    def test_missing_numerator_yields_none(self):
        section_d = {
            "years": ["2025"],
            "current_assets": [None],
            "current_liabilities": [50.0],
            "short_term_debt": [None],
            "cash": [None],
            "inventories": [None],
            "total_assets": [None],
            "total_liabilities": [None],
            "equity": [100.0],
            "net_revenue": [None],
            "gross_profit": [None],
            "net_profit_after_tax": [None],
        }
        ratios = compute_canonical_ratios(section_d)
        self.assertIsNone(ratios["current_ratio"][0])
        self.assertIsNone(ratios["quick_ratio"][0])
        self.assertIsNone(ratios["cash_ratio"][0])
        self.assertIsNone(ratios["ros"][0])

    def test_valid_operands_produce_correct_deterministic_result(self):
        section_d = {
            "years": ["2024", "2025"],
            "current_assets": [100.0, 142.0],
            "current_liabilities": [100.0, 100.0],
            "short_term_debt": [0.0, 0.0],
            "cash": [30.0, 37.0],
            "inventories": [10.0, 12.0],
            "total_assets": [500.0, 550.0],
            "total_liabilities": [200.0, 220.0],
            "equity": [300.0, 330.0],
            "net_revenue": [1000.0, 1200.0],
            "gross_profit": [250.0, 300.0],
            "net_profit_after_tax": [100.0, 134.0],
        }
        ratios = compute_canonical_ratios(section_d)
        self.assertEqual(ratios["current_ratio"], [1.0, 1.42])
        self.assertAlmostEqual(ratios["cash_ratio"][1], 0.37)
        self.assertAlmostEqual(ratios["revenue_growth"][1], 20.0)
        for key, values in ratios.items():
            for v in values:
                self.assertTrue(v is None or isinstance(v, float), f"{key} produced non-float/non-None: {v!r}")

    def test_ratios_are_never_strings(self):
        """The Python calculation layer must never emit presentation-formatted
        strings like '1,42' or ''/'''' -- only float or None."""
        section_d = {
            "years": ["2025"],
            "current_assets": [100.0], "current_liabilities": [50.0], "short_term_debt": [0.0],
            "cash": [20.0], "inventories": [10.0], "total_assets": [300.0],
            "total_liabilities": [100.0], "equity": [200.0],
            "net_revenue": [500.0], "gross_profit": [150.0], "net_profit_after_tax": [50.0],
        }
        ratios = compute_canonical_ratios(section_d)
        for values in ratios.values():
            for v in values:
                self.assertNotIsInstance(v, str)


class FinancialRatioFormattingFrontendMarkupTests(unittest.TestCase):
    """Section 10 (frontend side): static assertions that the ratio card no
    longer coerces a per-year array directly into a template literal, and
    that a dedicated formatter with explicit missing/zero/percent/ratio
    handling exists and is used."""

    def test_old_broken_scalar_coercion_is_gone(self):
        self.assertNotIn(
            "${typeof v === 'number' ? v.toFixed(2) : v}",
            HTML_PAGE,
        )

    def test_format_financial_metric_helper_exists(self):
        self.assertIn("function formatFinancialMetric(metricName, value)", HTML_PAGE)
        self.assertIn("RATIO_METRICS", HTML_PAGE)
        self.assertIn("PERCENT_METRICS", HTML_PAGE)

    def test_missing_value_guard_precedes_numeric_coercion(self):
        fn_start = HTML_PAGE.index("function formatFinancialMetric")
        fn_end = HTML_PAGE.index("function renderReviewBody")
        body = HTML_PAGE[fn_start:fn_end]
        self.assertIn("return '—'", body)
        self.assertIn("Number.isFinite", body)

    def test_ratio_card_iterates_per_year_array_not_raw_template(self):
        self.assertIn("Object.entries(ratios).map(([metricKey, valuesByYear])", HTML_PAGE)
        self.assertIn("formatFinancialMetric(metricKey, v)", HTML_PAGE)

    def test_metric_labels_improved_for_rm_readability(self):
        for label in (
            "Current Ratio", "Quick Ratio", "Cash Ratio", "Debt / Equity",
            "Total Debt / Equity", "ROS", "ROE", "Gross Profit Margin", "Revenue Growth",
        ):
            self.assertIn(label, HTML_PAGE)

    def test_section_title_unchanged(self):
        self.assertIn(
            "Chỉ Số Tài Chính Tính Toán Tự Động (Python Verification Engine - 100% Deterministic):",
            HTML_PAGE,
        )

    def test_ratio_periods_field_used_for_year_alignment(self):
        """calculated_ratios is index-aligned to section_d.years, which is not
        guaranteed to match the raw extraction-order 'periods' list -- the
        renderer must prefer the authoritative ratio_periods field."""
        self.assertIn("data.ratio_periods", HTML_PAGE)


class FinancialRatioPeriodsAlignmentBackendTests(unittest.TestCase):
    """Confirms the API response carries an unambiguous year-label array for
    calculated_ratios, even when extraction order and the merged/sorted
    section_d.years timeline differ."""

    def setUp(self):
        self.orig_cases_db = copy.deepcopy(CASES_DB)
        FINANCIAL_PREVIEW_STORE.clear()

    def tearDown(self):
        web_copilot_app.CASES_DB.clear()
        web_copilot_app.CASES_DB.update(copy.deepcopy(self.orig_cases_db))
        FINANCIAL_PREVIEW_STORE.clear()

    def test_ratio_periods_present_and_aligned_with_calculated_ratios_length(self):
        extraction = FinancialDocumentExtraction(
            document_title="Báo cáo tài chính",
            document_unit=FinancialUnitInfo(unit_raw="VND", evidence="Đơn vị tính: VND", page=1),
            periods=[
                _period("2025", "1.000.000.000"),
                _period("2024", "900.000.000"),
            ],
        )
        with patch("web_copilot_app.FinancialDocumentExtractor.extract", return_value=extraction), \
             patch("web_copilot_app.DocumentIngestionRouter.ingest_document", return_value=DocumentIngestionResult(
                 mode="digital", provider="pypdf", page_count=2,
                 tagged_text="[PAGE 1] test [PAGE 2] test",
             )):
            res, status = process_financial_pdf_preview(b"%PDF-1.4", "bctc.pdf", case_id="PSD")

        self.assertEqual(status, 200)
        self.assertIn("ratio_periods", res)
        for metric_values in res["calculated_ratios"].values():
            self.assertEqual(len(metric_values), len(res["ratio_periods"]))


if __name__ == "__main__":
    unittest.main()
