# -*- coding: utf-8 -*-
"""Demo fast path for the Narrative workspace (hackathon demo only).

Module: msb_eb_copilot.src.demo_narrative_cache

Problem: even for the preloaded demo cases (PSD, GAS_SOUTH, PHYTOPHARMA),
/api/narrative/generate always ran the full live pipeline (FactManifest ->
GLM-5.2 Insight Discovery -> Python verification -> GLM-5.2 Narrative Writer
-> Deterministic Narrative Validator), which is dominated by two real network
calls to GreenNode and is too slow for a live demo.

This module lets a preloaded demo case reuse a PRECOMPUTED, already-verified
narrative result instead of re-running the two GLM calls, while leaving the
live pipeline completely untouched for every other case (and even for a demo
case whose canonical facts have since changed).

Safety contract (Zero Silent Fallback):
- Only applies to a case explicitly flagged `case_data["_is_preloaded_demo"] is True`
  (see CASES_DB in web_copilot_app.py) -- never inferred from company name,
  case_id string matching, or any other heuristic.
- A snapshot is only used when its `source_manifest_hash` (a SHA-256 over the
  exact same canonical facts FactPackager would package right now) matches the
  CURRENT FactManifest hash for that case, computed fresh on every request.
  Any mismatch -- from a new document confirmation, an RM edit, a renewal
  change, or anything else that alters canonical case_data -- means the
  fast path is silently NOT used and the caller must run the live pipeline.
- A snapshot is bound to exactly one case_id; it is never applied to a
  different case, even if (implausibly) hashes were to collide.
- This module never calls GreenNode/AIAssistantClient and never mutates
  CASES_DB. It only reads pre-built, developer-authored JSON snapshot files
  (see scripts/build_demo_narrative_snapshots.py) that were themselves
  produced by running the real live pipeline once, offline.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from .narrative.models import NarrativeBlock, VerifiedInsight

# Mirrors the frontend's authoritative preloaded-demo-case list (see the
# 'DEMO DATA (PRELOADED)' badge logic in web_copilot_app.py's embedded JS).
# Kept here only as a documentation cross-reference -- the actual runtime
# check is the explicit `_is_preloaded_demo` flag on case_data, not this set,
# so a real case can never accidentally match by reusing one of these ids.
PRELOADED_DEMO_CASE_IDS = frozenset({"PSD", "GAS_SOUTH", "PHYTOPHARMA"})

_SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "demo_narrative_snapshots")


class DemoNarrativeSnapshot(BaseModel):
    """A precomputed, already-validated narrative result for exactly one
    preloaded demo case, keyed to the canonical facts it was generated from.

    model_id="DETERMINISTIC_DEMO_SNAPSHOT" identifies snapshots built entirely
    locally (see scripts/build_demo_narrative_snapshots.py) from canonical
    FactManifest facts, with zero GreenNode/AI/network calls -- as opposed to
    the (no longer used) live-GLM-generated snapshot format, which recorded a
    real model id such as "z-ai/glm-5.2-hackathon"."""
    model_config = ConfigDict(extra="forbid")

    case_id: str
    source_manifest_hash: str
    model_id: str = "z-ai/glm-5.2-hackathon"
    narrative_blocks: list[NarrativeBlock]
    verified_insights: list[VerifiedInsight]
    # Observability only (never read by get_valid_demo_snapshot's validity
    # check): records how/when/by what mechanism this snapshot was produced,
    # so it's always possible to confirm a snapshot was NOT generated live by
    # GLM. Optional/defaulted for backward compatibility with any
    # already-loaded snapshot that predates this field.
    execution_provenance: Dict[str, Any] = Field(default_factory=dict)


def is_preloaded_demo_case(case_data: Optional[Dict]) -> bool:
    """Authoritative demo-mode check. Explicit flag only -- never inferred from
    company name, case_id, or any other heuristic."""
    return bool(case_data) and case_data.get("_is_preloaded_demo") is True


def _load_snapshot_from_disk(case_id: str) -> Optional[DemoNarrativeSnapshot]:
    path = os.path.join(_SNAPSHOT_DIR, f"{case_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    snapshot = DemoNarrativeSnapshot.model_validate(raw)
    if snapshot.case_id != case_id:
        # Defense in depth: a snapshot file must never be usable under a
        # different case_id than the one it was saved as.
        raise ValueError(
            f"Demo narrative snapshot file '{path}' has case_id={snapshot.case_id!r}, "
            f"expected {case_id!r}."
        )
    return snapshot


def _load_all_snapshots() -> Dict[str, DemoNarrativeSnapshot]:
    snapshots: Dict[str, DemoNarrativeSnapshot] = {}
    for case_id in PRELOADED_DEMO_CASE_IDS:
        try:
            snap = _load_snapshot_from_disk(case_id)
        except Exception:
            # A malformed/missing snapshot file must never crash the app or
            # silently corrupt another case's result -- it just means this
            # case falls back to the live pipeline, same as if no snapshot
            # existed at all.
            snap = None
        if snap is not None:
            snapshots[case_id] = snap
    return snapshots


# Loaded once at import time (small, local, developer-authored JSON files --
# never regenerated automatically at runtime; see scripts/build_demo_narrative_snapshots.py).
DEMO_NARRATIVE_SNAPSHOTS: Dict[str, DemoNarrativeSnapshot] = _load_all_snapshots()


def get_valid_demo_snapshot(
    case_id: str,
    case_data: Optional[Dict],
    current_manifest_hash: str,
) -> Optional[DemoNarrativeSnapshot]:
    """Returns the demo snapshot to use for this request, or None if the live
    pipeline must run instead.

    None is returned (never an exception) for any of:
    - case_data is not explicitly flagged as a preloaded demo case,
    - no snapshot was ever built for this case_id,
    - the snapshot belongs to a different case_id than requested,
    - the snapshot's source_manifest_hash does not match the CURRENT
      canonical facts (i.e. something changed since the snapshot was built).
    """
    if not is_preloaded_demo_case(case_data):
        return None

    snapshot = DEMO_NARRATIVE_SNAPSHOTS.get(case_id)
    if snapshot is None:
        return None
    if snapshot.case_id != case_id:
        return None
    if snapshot.source_manifest_hash != current_manifest_hash:
        return None
    return snapshot
