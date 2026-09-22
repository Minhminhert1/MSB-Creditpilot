# -*- coding: utf-8 -*-
"""Developer-only: builds precomputed demo Narrative snapshots for the
preloaded demo cases (PSD, GAS_SOUTH, PHYTOPHARMA) ENTIRELY LOCALLY AND
DETERMINISTICALLY from canonical FactManifest facts, then saves the validated
result to

    msb_eb_copilot/data/demo_narrative_snapshots/<CASE_ID>.json

WHY DETERMINISTIC (not live GLM):
The previous version of this script called the real live pipeline
(GLMInsightDiscoveryAgent -> PythonInsightVerifier -> GLMNarrativeWriterAgent)
once per case. In practice this was unreliable right before the hackathon
submission: PSD/GAS_SOUTH live narratives had numeric claims the deterministic
validator correctly rejected as insufficiently grounded, and PHYTOPHARMA timed
out entirely. This version makes ZERO GreenNode/AI/network calls. It builds
short, template-based NarrativeBlocks directly from FactManifest FactItems --
every number or text claim is copied verbatim from exactly one FactItem's own
`value`/`display_representations`, and that FactItem's fact_id is always
included in the block's `facts_used`. If a desired fact does not exist for a
case, the corresponding clause (or whole block) is simply omitted -- nothing
is ever invented. This is a change to HOW snapshots are authored, not to the
validator: DeterministicNarrativeValidator (validator.py) is used completely
unmodified as the acceptance gate below.

This is the ONLY code path allowed to write these files. The running
application (web_copilot_app.py) only ever READS them, via
msb_eb_copilot/src/demo_narrative_cache.py, and never regenerates them at
runtime -- if a snapshot is missing or stale (its source_manifest_hash no
longer matches the live FactManifest hash), the app transparently and safely
falls back to the live pipeline (Zero Silent Fallback; unchanged).

Usage:
    python scripts/build_demo_narrative_snapshots.py [CASE_ID ...]

With no arguments, builds a snapshot for every preloaded demo case. No API
key, network access, or GreenNode credentials are required or used.

Re-run this script whenever the canonical demo data for PSD / GAS_SOUTH /
PHYTOPHARMA in web_copilot_app.py's CASES_DB changes -- otherwise the fast
path correctly detects the manifest hash mismatch and every request for that
case transparently falls back to the live pipeline (no code changes needed
for that safety net to work).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import web_copilot_app as w  # noqa: E402
from msb_eb_copilot.src.demo_narrative_cache import (  # noqa: E402
    PRELOADED_DEMO_CASE_IDS,
    _SNAPSHOT_DIR,
    is_preloaded_demo_case,
)
from msb_eb_copilot.src.narrative.fact_packager import FactPackager  # noqa: E402
from msb_eb_copilot.src.narrative.models import (  # noqa: E402
    FactItem,
    FactManifest,
    NarrativeBlock,
    NarrativeTargetBinding,
)
from msb_eb_copilot.src.narrative.validator import DeterministicNarrativeValidator  # noqa: E402

DETERMINISTIC_MODEL_ID = "DETERMINISTIC_DEMO_SNAPSHOT"


# ==============================================================================
# 1. SAFE, DETERMINISTIC REPRESENTATION PICKERS
# ==============================================================================
# Every picker returns ONLY a string already present in the fact's own
# display_representations (or, for a plain text fact with no numeric
# representations, its raw value) -- never a reformatted/recomputed value.
# This guarantees the numeric-audit self-consistency the validator requires:
# whatever number-like token appears in the picked string was already counted
# as "trusted" from that same fact's own representations.

def _pick_text(fact: FactItem) -> Optional[str]:
    reps = fact.display_representations or []
    if reps:
        return reps[0]
    if fact.value not in (None, "", []):
        return str(fact.value)
    return None


def _pick_by_suffix(fact: FactItem, suffixes: tuple) -> Optional[str]:
    reps = fact.display_representations or []
    if not reps:
        return None
    for suffix in suffixes:
        candidates = [r for r in reps if r.endswith(suffix) and "," in r]
        if candidates:
            return min(candidates, key=len)
    for suffix in suffixes:
        candidates = [r for r in reps if r.endswith(suffix)]
        if candidates:
            return min(candidates, key=len)
    return reps[0]


def _pick_money(fact: FactItem) -> Optional[str]:
    return _pick_by_suffix(fact, ("tỷ đồng",))


def _pick_percent(fact: FactItem) -> Optional[str]:
    return _pick_by_suffix(fact, ("%",))


def _pick_ratio(fact: FactItem) -> Optional[str]:
    return _pick_by_suffix(fact, ("lần",))


# ==============================================================================
# 2. BLOCK-BUILDING HELPERS
# ==============================================================================
def _get(manifest: FactManifest, fact_id: str) -> Optional[FactItem]:
    return manifest.get_fact(fact_id)


def _add_clause(
    clauses: List[str],
    facts_used: List[str],
    label: str,
    fact: Optional[FactItem],
    picker: Callable[[FactItem], Optional[str]],
) -> None:
    """Appends '{label}: {picked_value}' ONLY if the fact exists and a value
    could be picked from it -- if the fact is absent, nothing is added (no
    invented claim), matching "if the fact_id cannot be identified, do not
    include the claim"."""
    if fact is None:
        return
    value = picker(fact)
    if not value:
        return
    clauses.append(f"{label}: {value}")
    if fact.fact_id not in facts_used:
        facts_used.append(fact.fact_id)


def _financial_years(manifest: FactManifest) -> List[str]:
    years = {f.period for f in manifest.financial_facts.values() if f.period and f.period.isdigit()}
    return sorted(years, key=int)


def _finalize_block(
    section: str,
    binding: NarrativeTargetBinding,
    title: str,
    clauses: List[str],
    facts_used: List[str],
) -> Optional[NarrativeBlock]:
    if not facts_used:
        return None
    return NarrativeBlock(
        section=section,
        target_binding=binding,
        title=title,
        text=". ".join(clauses) + ".",
        facts_used=facts_used,
        insights_used=[],
        data_gaps=[],
    )


# ==============================================================================
# 3. THE 5 DETERMINISTIC BLOCK CATEGORIES
# ==============================================================================
def build_business_overview(manifest: FactManifest) -> Optional[NarrativeBlock]:
    """A. Legal/company name, business model, parent group -- no inferred
    establishment/history dates (no such fact_id exists in the manifest)."""
    clauses: List[str] = []
    facts_used: List[str] = []
    _add_clause(clauses, facts_used, "Tên doanh nghiệp", _get(manifest, "LEGAL_NAME"), _pick_text)
    _add_clause(clauses, facts_used, "Tên viết tắt", _get(manifest, "LEGAL_SHORT_NAME"), _pick_text)
    _add_clause(clauses, facts_used, "Mã số thuế", _get(manifest, "LEGAL_TAX_CODE"), _pick_text)
    _add_clause(clauses, facts_used, "Mô hình kinh doanh", _get(manifest, "BIZ_MODEL"), _pick_text)
    _add_clause(clauses, facts_used, "Công ty mẹ / Tập đoàn", _get(manifest, "PARENT_GROUP"), _pick_text)
    _add_clause(clauses, facts_used, "Vốn điều lệ", _get(manifest, "LEGAL_CHARTER_CAPITAL"), _pick_money)
    _add_clause(clauses, facts_used, "Địa chỉ trụ sở", _get(manifest, "LEGAL_ADDRESS"), _pick_text)
    return _finalize_block("BUSINESS", NarrativeTargetBinding.BUSINESS_OVERVIEW, "Tổng quan doanh nghiệp", clauses, facts_used)


def build_management_summary(manifest: FactManifest) -> Optional[NarrativeBlock]:
    """B. Legal representative / management facts only -- no fabricated
    assessments of management quality."""
    clauses: List[str] = []
    facts_used: List[str] = []
    _add_clause(clauses, facts_used, "Người đại diện pháp luật", _get(manifest, "LEGAL_REP_NAME"), _pick_text)

    mgmt_fact = _get(manifest, "BIZ_MANAGEMENT")
    if mgmt_fact is not None:
        count_rep = next((r for r in (mgmt_fact.display_representations or []) if "thành viên" in r), None)
        if count_rep:
            clauses.append(f"Quy mô ban điều hành: {count_rep}")
            facts_used.append(mgmt_fact.fact_id)

    return _finalize_block("BUSINESS", NarrativeTargetBinding.MANAGEMENT_SUMMARY, "Ban điều hành & Người đại diện pháp luật", clauses, facts_used)


def build_financial_summary(manifest: FactManifest) -> Optional[NarrativeBlock]:
    """C. Revenue, profit, equity, debt, and deterministic ratios for the
    latest financial year present in the manifest -- only values actually
    present are cited."""
    years = _financial_years(manifest)
    if not years:
        return None
    yr = years[-1]

    clauses: List[str] = []
    facts_used: List[str] = []
    _add_clause(clauses, facts_used, f"Doanh thu thuần năm {yr}", _get(manifest, f"FIN_REV_{yr}"), _pick_money)
    _add_clause(clauses, facts_used, f"Lợi nhuận sau thuế năm {yr}", _get(manifest, f"FIN_NP_{yr}"), _pick_money)
    _add_clause(clauses, facts_used, f"Vốn chủ sở hữu năm {yr}", _get(manifest, f"FIN_EQ_{yr}"), _pick_money)
    _add_clause(clauses, facts_used, f"Nợ vay ngắn hạn năm {yr}", _get(manifest, f"FIN_STD_{yr}"), _pick_money)
    _add_clause(clauses, facts_used, f"Hệ số thanh toán hiện hành (Current Ratio) năm {yr}", _get(manifest, f"RATIO_CURRENT_RATIO_{yr}"), _pick_ratio)
    _add_clause(clauses, facts_used, f"Tỷ suất sinh lời vốn chủ sở hữu (ROE) năm {yr}", _get(manifest, f"RATIO_ROE_{yr}"), _pick_percent)
    _add_clause(clauses, facts_used, f"Tăng trưởng doanh thu năm {yr}", _get(manifest, f"RATIO_REVENUE_GROWTH_{yr}"), _pick_percent)

    return _finalize_block("FINANCIAL", NarrativeTargetBinding.PNL_ANALYSIS, f"Tổng hợp tài chính năm {yr}", clauses, facts_used)


def build_credit_summary(manifest: FactManifest) -> Optional[NarrativeBlock]:
    """D. CIC group/history, outstanding debt, and requested credit limits --
    only documented credit facts. If the manifest carries the (rare)
    unconverted-foreign-currency CIC data gap, the caveat is included verbatim
    from that same gap fact (never a fabricated caveat)."""
    clauses: List[str] = []
    facts_used: List[str] = []
    _add_clause(clauses, facts_used, "Phân loại nợ CIC", _get(manifest, "CIC_HISTORY_STATUS"), _pick_text)
    _add_clause(clauses, facts_used, "Nợ quá hạn trong 12 tháng gần nhất", _get(manifest, "CIC_IS_OVERDUE_12M"), _pick_text)
    _add_clause(clauses, facts_used, "Dư nợ tại MSB", _get(manifest, "CIC_MSB_OUTSTANDING"), _pick_money)
    _add_clause(clauses, facts_used, "Dư nợ tại các TCTD khác", _get(manifest, "CIC_OTHER_BANKS_DEBT"), _pick_money)
    _add_clause(clauses, facts_used, "Tổng hạn mức đề xuất", _get(manifest, "REQ_TOTAL_LIMIT"), _pick_money)
    _add_clause(clauses, facts_used, "Hạn mức cho vay", _get(manifest, "REQ_LOAN_LIMIT"), _pick_money)
    _add_clause(clauses, facts_used, "Hạn mức bảo lãnh", _get(manifest, "REQ_GUARANTEE_LIMIT"), _pick_money)

    gap = next((g for g in manifest.data_gaps if g.fact_id == "GAP_CIC_EXTERNAL_DEBT_INCOMPLETE"), None)
    if gap is not None and gap.value:
        clauses.append(f"Lưu ý: {gap.value}")
        facts_used.append(gap.fact_id)

    return _finalize_block("CIC", NarrativeTargetBinding.CIC_SUMMARY, "Tổng hợp quan hệ tín dụng & Đề xuất cấp tín dụng", clauses, facts_used)


def build_risk_summary(manifest: FactManifest) -> Optional[NarrativeBlock]:
    """E. Deterministic leverage/liquidity ratio observations already
    supported by canonical facts. Omitted entirely if no such ratio exists for
    the latest year."""
    years = _financial_years(manifest)
    if not years:
        return None
    yr = years[-1]

    clauses: List[str] = []
    facts_used: List[str] = []
    _add_clause(clauses, facts_used, f"Đòn bẩy tài chính (Debt/Equity) năm {yr}", _get(manifest, f"RATIO_DEBT_TO_EQUITY_{yr}"), _pick_ratio)
    _add_clause(clauses, facts_used, f"Khả năng thanh toán nhanh (Quick Ratio) năm {yr}", _get(manifest, f"RATIO_QUICK_RATIO_{yr}"), _pick_ratio)
    _add_clause(clauses, facts_used, f"Khả năng thanh toán bằng tiền (Cash Ratio) năm {yr}", _get(manifest, f"RATIO_CASH_RATIO_{yr}"), _pick_ratio)

    return _finalize_block("FINANCIAL", NarrativeTargetBinding.RISK_OBSERVATION_SUMMARY, f"Quan sát rủi ro tài chính năm {yr}", clauses, facts_used)


BLOCK_BUILDERS: List[Callable[[FactManifest], Optional[NarrativeBlock]]] = [
    build_business_overview,
    build_management_summary,
    build_financial_summary,
    build_credit_summary,
    build_risk_summary,
]


# ==============================================================================
# 4. PER-CASE ORCHESTRATION
# ==============================================================================
def build_snapshot_for_case(case_id: str) -> bool:
    case_data = w.CASES_DB.get(case_id)
    if case_data is None:
        print(f"[SKIP] {case_id}: not found in CASES_DB.")
        return False
    if not is_preloaded_demo_case(case_data):
        print(f"[SKIP] {case_id}: not flagged _is_preloaded_demo -- refusing to snapshot a non-demo case.")
        return False

    is_ready, reason = w.is_narrative_case_ready(case_data)
    if not is_ready:
        print(f"[SKIP] {case_id}: not narrative-ready ({reason}).")
        return False

    print(f"[{case_id}] Packaging canonical facts (local, deterministic, zero AI/network calls)...")
    manifest = FactPackager.package_from_case_data(case_data, case_id=case_id)
    print(f"[{case_id}] manifest_hash={manifest.manifest_hash}")

    blocks: List[NarrativeBlock] = []
    for builder in BLOCK_BUILDERS:
        block = builder(manifest)
        if block is not None:
            blocks.append(block)

    if not blocks:
        print(f"[ABORT] {case_id}: no narrative blocks could be built from available canonical facts.")
        return False

    print(f"[{case_id}] Built {len(blocks)} deterministic block(s): {[b.target_binding.value for b in blocks]}")

    print(f"[{case_id}] Validating with the existing (unmodified) DeterministicNarrativeValidator...")
    validator = DeterministicNarrativeValidator(manifest, verified_insights=[])
    val_res = validator.validate_blocks(blocks)
    if not val_res.is_valid:
        print(f"[FAIL] {case_id}: deterministic validation rejected the generated blocks -- snapshot NOT saved.")
        for err in val_res.errors:
            print(f"    * {err}")
        return False

    snapshot_dict: Dict[str, Any] = {
        "case_id": case_id,
        "source_manifest_hash": manifest.manifest_hash,
        "model_id": DETERMINISTIC_MODEL_ID,
        "narrative_blocks": [b.model_dump(mode="json") for b in blocks],
        "verified_insights": [],
        "execution_provenance": {
            "builder": "scripts/build_demo_narrative_snapshots.py",
            "method": "deterministic_local",
            "greennode_calls": 0,
            "ai_calls": 0,
            "network_calls": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    os.makedirs(_SNAPSHOT_DIR, exist_ok=True)
    out_path = os.path.join(_SNAPSHOT_DIR, f"{case_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_dict, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"[SAVED] {case_id}: {len(blocks)} block(s) -> {out_path}")
    return True


def main() -> None:
    requested = sys.argv[1:] or sorted(PRELOADED_DEMO_CASE_IDS)
    unknown = [c for c in requested if c not in PRELOADED_DEMO_CASE_IDS]
    if unknown:
        print(f"[ERROR] Not preloaded demo case id(s), refusing: {unknown}. "
              f"Known demo case ids: {sorted(PRELOADED_DEMO_CASE_IDS)}")
        sys.exit(1)

    print("================================================================================")
    print("BUILD DEMO NARRATIVE SNAPSHOTS -- deterministic, fully local, zero AI/network calls")
    print(f"Cases: {requested}")
    print("================================================================================")

    results = {cid: build_snapshot_for_case(cid) for cid in requested}

    print("\n================================================================================")
    for cid, ok in results.items():
        print(f"  {cid} -> {'SAVED' if ok else 'FAILED/SKIPPED'}")
    ok_count = sum(1 for v in results.values() if v)
    print(f"DONE: {ok_count}/{len(requested)} snapshot(s) built successfully.")
    print("================================================================================")

    if ok_count != len(requested):
        sys.exit(1)


if __name__ == "__main__":
    main()
