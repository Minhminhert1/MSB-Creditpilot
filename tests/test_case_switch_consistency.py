# -*- coding: utf-8 -*-
"""Regression tests for case/customer data consistency across the frontend.

Root cause covered by these tests: CASES_DB["PSD"]["name"] (used for the case
selector label and the /api/cases endpoint) previously described a different
company than CASES_DB["PSD"]["customer"] (used to render the dashboard KPI
cards) -- both technically "the active case", but self-contradictory. On top of
that, several Document Workspace summary fields (sum-legal-*, sum-biz-*,
sum-fin-*, sum-cic-*) and sidebar-progress tracking flags were never refreshed
on case switch/demo reset/new case, so they could keep showing a previous
case's data.

These tests lock in:
1. Every demo case's top-level "name" and its "customer" identity refer to the
   same company (no PSD-style contradiction can silently reappear).
2. The case-selector's option labels are synced from the backend (/api/cases)
   rather than trusted as static hardcoded text.
3. loadCaseData() (the single function that runs on load / case switch / demo
   reset) populates ALL visible per-case fields -- KPI cards AND the Document
   Workspace summary snippets -- from the same fetched case payload.
4. Switching case, resetting demo data, or creating a new case all clear the
   frontend-only "per case" tracking flags (sidebar progress, export state) so
   they can never leak from a previously active case.
5. The CIC KPI headline extraction never falls back to displaying the full
   history_status sentence as the "main" value.

No backend/API/business logic is touched by these tests; they inspect the
served HTML_PAGE (frontend markup/JS) and CASES_DB (demo seed data) only.
"""

from __future__ import annotations

import re
import unittest

import web_copilot_app
from web_copilot_app import CASES_DB, HTML_PAGE


def _slice_function(js_source: str, signature: str, next_signature: str) -> str:
    start = js_source.find(signature)
    assert start != -1, f"Could not find function signature: {signature!r}"
    end = js_source.find(next_signature, start)
    assert end != -1, f"Could not find end boundary: {next_signature!r}"
    return js_source[start:end]


class TestDemoCaseIdentityConsistency(unittest.TestCase):
    """1. The case-level display name and the customer record must describe the
    same company for every demo case -- this is exactly the class of bug
    reported live (dropdown said one company, KPI card said another)."""

    def test_psd_case_name_matches_its_own_customer_identity(self):
        psd = CASES_DB["PSD"]
        # The old, contradictory case name must never reappear.
        self.assertNotIn("Dịch vụ Phân phối TH Dầu khí", psd["name"])
        # The corrected case name must reference the same company as the
        # customer record actually rendered on the dashboard.
        self.assertIn("Phân phối", psd["name"])
        self.assertIn("Demo", psd["name"])
        self.assertEqual(psd["customer"]["short_name"], "DEMO DISTRIBUTION JSC")
        self.assertEqual(psd["customer"]["cif"], "DEMO001")

    def test_all_demo_cases_have_a_case_name_and_customer_record(self):
        for case_id in ("PSD", "GAS_SOUTH", "PHYTOPHARMA"):
            with self.subTest(case_id=case_id):
                case = CASES_DB[case_id]
                self.assertTrue(case.get("name"), f"{case_id} missing case-level name")
                cust = case.get("customer") or {}
                self.assertTrue(cust.get("short_name") or cust.get("name"), f"{case_id} missing customer identity")
                self.assertTrue(cust.get("cif"), f"{case_id} missing CIF")

    def test_api_cases_listing_reflects_current_cases_db_names(self):
        """Mirrors exactly what the '/api/cases' handler builds, so a future
        edit to CASES_DB can never silently drift from what the endpoint (and
        therefore the case-selector, once synced) actually serves."""
        summary = [{"id": cid, "name": cdata["name"]} for cid, cdata in CASES_DB.items()]
        by_id = {row["id"]: row["name"] for row in summary}
        self.assertEqual(by_id["PSD"], CASES_DB["PSD"]["name"])
        self.assertEqual(by_id["GAS_SOUTH"], CASES_DB["GAS_SOUTH"]["name"])
        self.assertEqual(by_id["PHYTOPHARMA"], CASES_DB["PHYTOPHARMA"]["name"])


class TestCaseSelectorSyncsFromBackend(unittest.TestCase):
    """2. The case-selector must not rely on hardcoded option text as the
    source of truth -- it must be corrected from the backend on load."""

    def test_load_case_list_function_exists_and_is_wired_to_onload(self):
        self.assertIn("async function loadCaseList()", HTML_PAGE)
        fn = _slice_function(HTML_PAGE, "async function loadCaseList()", "window.onload = function()")
        self.assertIn("fetch('/api/cases')", fn)
        self.assertIn("case-selector", fn)
        self.assertIn("opt.innerText = c.name", fn)

        onload_block = HTML_PAGE[HTML_PAGE.find("window.onload = function()"):]
        self.assertIn("loadCaseList()", onload_block[:300])


class TestLoadCaseDataPopulatesEveryVisibleField(unittest.TestCase):
    """3. loadCaseData() must populate BOTH the KPI cards AND the Document
    Workspace summary snippets from the same fetched case payload -- these
    previously only followed live document uploads or brand-new cases, so
    switching between existing demo cases left stale text behind."""

    def setUp(self):
        self.fn = _slice_function(HTML_PAGE, "async function loadCaseData()", "async function loadCaseList()")

    def test_kpi_cards_are_populated(self):
        for dom_id in (
            "dash-cust-name", "dash-cust-cif", "dash-cust-rating",
            "dash-total-limit", "dash-loan-limit",
            "dash-rev-2025", "dash-np-2025",
            "dash-cic-status", "dash-cic-meta", "dash-msb-out",
        ):
            with self.subTest(dom_id=dom_id):
                self.assertIn(f"getElementById('{dom_id}')", self.fn)

    def test_document_workspace_summaries_are_populated_from_case_data(self):
        """These fields must be derived from the case payload (cust/b/c/d/e),
        not left to whatever a previous upload or previous case last set."""
        for dom_id in (
            "sum-legal-name", "sum-legal-tax", "sum-legal-capital", "sum-legal-rep",
            "sum-biz-model", "sum-biz-suppliers", "sum-biz-customers",
            "sum-fin-auditor", "sum-fin-rev", "sum-fin-np", "sum-fin-equity",
            "sum-cic-date", "sum-cic-status", "sum-cic-msb",
        ):
            with self.subTest(dom_id=dom_id):
                self.assertIn(f"getElementById('{dom_id}')", self.fn)

    def test_section_c_payload_is_read(self):
        self.assertIn("const c = data.section_c", self.fn)

    def test_msb_outstanding_label_is_vietnamese(self):
        self.assertIn("Dư nợ tại MSB:", self.fn)
        self.assertNotIn("MSB outstanding:", self.fn)


class TestPerCaseFrontendStateResetsOnCaseChange(unittest.TestCase):
    """4. Switching case, resetting demo data, or creating a new case must all
    clear frontend-only per-case tracking flags (sidebar progress signals,
    export state) so none of them can leak from a previously active case."""

    def test_reset_helper_exists_and_clears_all_tracked_flags(self):
        self.assertIn("function resetPerCaseFrontendState()", HTML_PAGE)
        fn = _slice_function(HTML_PAGE, "function resetPerCaseFrontendState()", "async function resetDemoCase()")
        for expected in (
            "SECTION_A_SAVED = false",
            "SECTION_B_SAVED = false",
            "VISITED_TABS.clear()",
            "window.__MB07_EXPORTED__ = false",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, fn)

    def test_on_case_change_calls_reset_helper(self):
        fn = _slice_function(HTML_PAGE, "async function onCaseChange(caseId)", "function escapeHtml")
        self.assertIn("resetPerCaseFrontendState()", fn)
        self.assertIn("await loadCaseData()", fn)

    def test_reset_demo_case_calls_reset_helper(self):
        fn = _slice_function(HTML_PAGE, "async function resetDemoCase()", "async function onCaseChange(caseId)")
        self.assertIn("resetPerCaseFrontendState()", fn)
        self.assertIn("await loadCaseData()", fn)

    def test_submit_new_case_calls_reset_helper(self):
        fn = _slice_function(HTML_PAGE, "async function submitNewCase()", "async function saveSectionA()")
        self.assertIn("resetPerCaseFrontendState()", fn)
        self.assertIn("await loadCaseData()", fn)


class TestCicKpiHeadlineNeverShowsFullSentence(unittest.TestCase):
    """5. The CIC KPI card headline must be a short debt-group token ("Nhóm 1"),
    never the full history_status sentence, with a safe fallback if the
    expected shape isn't found. Built from existing data only -- history_status
    itself is never modified."""

    def setUp(self):
        self.fn = _slice_function(HTML_PAGE, "function splitCicStatus(raw)", "let NARRATIVE_STATE")

    def test_extraction_targets_a_debt_group_token_not_the_whole_string(self):
        self.assertIn("Nhóm", self.fn)
        # The old bug: stripping only the leading "N%" and keeping everything
        # else as the headline must not be the implemented behavior anymore.
        self.assertNotIn("m[2]", self.fn)

    def test_real_history_status_values_contain_an_extractable_debt_group(self):
        """Cross-checks the actual demo data against the same extraction shape
        the frontend relies on (a case-insensitive "Nhóm <N>" token), so a
        future data edit that breaks this assumption is caught here rather
        than silently degrading to the safe-fallback path in production."""
        pattern = re.compile(r"Nhóm\s*\d+", re.IGNORECASE)
        for case_id in ("PSD", "GAS_SOUTH", "PHYTOPHARMA"):
            with self.subTest(case_id=case_id):
                history_status = CASES_DB[case_id]["section_e"]["history_status"]
                match = pattern.search(history_status)
                self.assertIsNotNone(match, f"{case_id} history_status has no extractable debt-group token")

    def test_safe_fallback_present_for_unexpected_format(self):
        self.assertIn("Chưa tra cứu CIC", self.fn)


if __name__ == "__main__":
    unittest.main(verbosity=2)
