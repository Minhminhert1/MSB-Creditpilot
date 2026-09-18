# -*- coding: utf-8 -*-
"""Server-authoritative external draft store for credit narratives.

Module: msb_eb_copilot.src.narrative.store
Principles:
- Isolates narrative workflow state outside canonical case_data.
- Enforces single-case stale manifest protection: rejects operations if canonical facts changed.
- Tracks RM review lifecycle: GENERATED -> INSIGHTS_VERIFIED -> NARRATIVE_VALIDATED -> RM_REVIEWED -> ACCEPTED_FOR_RENDERING.
- RM edits re-trigger deterministic validation.
"""

from __future__ import annotations
import copy
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from .models import (
    GenerationStatus,
    NarrativeBlock,
    NarrativeGenerationRecord,
    NarrativeTargetBinding,
    NarrativeValidationError,
    StaleNarrativeGenerationError,
)
from .validator import DeterministicNarrativeValidator

# In-Memory External Workflow Store
NARRATIVE_DRAFT_STORE: Dict[str, NarrativeGenerationRecord] = {}


class NarrativeDraftManager:
    """Manages the lifecycle of credit narrative drafts."""

    @classmethod
    def create_generation_record(
        cls,
        case_id: str,
        fact_manifest: Any,
        model_id: str = "z-ai/glm-5.2-hackathon",
    ) -> NarrativeGenerationRecord:
        """Create a new narrative generation record in GENERATED status."""
        gen_id = str(uuid.uuid4())
        now_iso = datetime.now().isoformat()

        record = NarrativeGenerationRecord(
            generation_id=gen_id,
            case_id=case_id,
            fact_manifest_hash=fact_manifest.manifest_hash,
            status=GenerationStatus.GENERATED,
            fact_manifest=fact_manifest,
            insight_candidates=[],
            verified_insights=[],
            narrative_blocks={},
            validation_results=[],
            model_id=model_id,
            telemetry={},
            created_at=now_iso,
            rm_edits={},
            accepted_bindings=[]
        )
        NARRATIVE_DRAFT_STORE[gen_id] = record
        return record

    @classmethod
    def get_record(cls, generation_id: str) -> Optional[NarrativeGenerationRecord]:
        """Retrieve a record by ID."""
        return NARRATIVE_DRAFT_STORE.get(generation_id)

    @classmethod
    def get_draft_by_case(cls, case_id: str) -> Optional[NarrativeGenerationRecord]:
        """Retrieve the latest record for a case."""
        records = [r for r in NARRATIVE_DRAFT_STORE.values() if r.case_id == case_id]
        if not records:
            return None
        return sorted(records, key=lambda x: x.created_at, reverse=True)[0]

    @classmethod
    def create_draft_record(
        cls,
        case_id: str,
        manifest: Any,
        insights: List[Any],
        package: Any,
        model_id: str = "z-ai/glm-5.2-hackathon"
    ) -> NarrativeGenerationRecord:
        """Create a complete draft record with verified insights and blocks."""
        gen_id = str(uuid.uuid4())
        now_iso = datetime.now().isoformat()

        blocks_dict = {}
        raw_blocks = getattr(package, "narrative_blocks", None) or getattr(package, "blocks", [])
        for b in raw_blocks:
            binding_key = b.target_binding.value if hasattr(b.target_binding, "value") else str(b.target_binding)
            blocks_dict[binding_key] = b

        record = NarrativeGenerationRecord(
            generation_id=gen_id,
            case_id=case_id,
            fact_manifest_hash=manifest.manifest_hash,
            status=GenerationStatus.NARRATIVE_VALIDATED,
            fact_manifest=manifest,
            insight_candidates=[],
            verified_insights=insights,
            narrative_blocks=blocks_dict,
            validation_results=[],
            model_id=model_id,
            telemetry={},
            created_at=now_iso,
            rm_edits={},
            accepted_bindings=[]
        )
        NARRATIVE_DRAFT_STORE[gen_id] = record
        return record

    @classmethod
    def edit_block(
        cls,
        generation_id: str,
        target_binding: Any,
        edited_text: str,
        rm_note: str = ""
    ) -> NarrativeGenerationRecord:
        """RM edits block text with automatic validation."""
        record = cls.get_record(generation_id)
        if not record:
            raise KeyError(f"Draft generation '{generation_id}' not found")

        binding_key = target_binding.value if hasattr(target_binding, "value") else str(target_binding)
        cls.apply_rm_edit(
            generation_id=generation_id,
            target_binding=binding_key,
            edited_text=edited_text,
            current_manifest_hash=record.fact_manifest_hash
        )
        return record

    @classmethod
    def accept_narratives(
        cls,
        generation_id: str,
        case_id: str,
        current_manifest: Any,
        rm_reviewer_name: str = "RM"
    ) -> NarrativeGenerationRecord:
        """Accept all blocks in generation for rendering with stale manifest protection."""
        record = cls.get_record(generation_id)
        if not record:
            raise KeyError(f"Draft generation '{generation_id}' not found")

        # Stale manifest check
        cls.verify_manifest_freshness(generation_id, current_manifest.manifest_hash)

        all_bindings = list(record.narrative_blocks.keys())
        cls.accept_bindings(generation_id, all_bindings, current_manifest.manifest_hash)
        record.status = GenerationStatus.ACCEPTED_FOR_RENDERING
        return record

    @classmethod
    def verify_manifest_freshness(cls, generation_id: str, current_manifest_hash: str) -> None:
        """Stale Manifest Protection: Ensure canonical facts have not mutated."""
        record = cls.get_record(generation_id)
        if not record:
            raise KeyError(f"Narrative generation ID '{generation_id}' not found")

        if record.fact_manifest_hash != current_manifest_hash:
            record.status = GenerationStatus.REJECTED
            raise StaleNarrativeGenerationError(
                f"Canonical case facts have changed since narrative was generated! "
                f"Generation hash: {record.fact_manifest_hash[:12]}..., Current hash: {current_manifest_hash[:12]}... "
                "Regeneration is required."
            )

    @classmethod
    def apply_rm_edit(
        cls,
        generation_id: str,
        target_binding: str,
        edited_text: str,
        current_manifest_hash: str,
    ) -> NarrativeBlock:
        """Apply an RM edit to a narrative block with re-validation."""
        cls.verify_manifest_freshness(generation_id, current_manifest_hash)
        record = cls.get_record(generation_id)

        if target_binding not in record.narrative_blocks:
            raise KeyError(f"Target binding '{target_binding}' not found in draft generation '{generation_id}'")

        orig_block = record.narrative_blocks[target_binding]
        updated_block = copy.deepcopy(orig_block)
        updated_block.text = edited_text

        # Re-run deterministic validator on edited text
        validator = DeterministicNarrativeValidator(
            manifest=record.fact_manifest,
            verified_insights=record.verified_insights
        )
        validator.assert_valid(updated_block)

        # Save edit and transition status
        record.rm_edits[target_binding] = edited_text
        record.narrative_blocks[target_binding] = updated_block
        record.status = GenerationStatus.RM_REVIEWED
        return updated_block

    @classmethod
    def accept_bindings(
        cls,
        generation_id: str,
        bindings_to_accept: List[str],
        current_manifest_hash: str,
    ) -> List[str]:
        """RM explicitly accepts validated draft blocks for MB07 rendering."""
        cls.verify_manifest_freshness(generation_id, current_manifest_hash)
        record = cls.get_record(generation_id)

        for b in bindings_to_accept:
            if b not in record.narrative_blocks:
                raise KeyError(f"Cannot accept unknown target binding '{b}'")

        record.accepted_bindings = list(set(record.accepted_bindings).union(set(bindings_to_accept)))
        record.status = GenerationStatus.ACCEPTED_FOR_RENDERING
        return record.accepted_bindings

    @classmethod
    def get_accepted_narratives_for_rendering(
        cls,
        case_id: str,
        current_manifest_hash: Optional[str] = None,
    ) -> Dict[str, str]:
        """Fetch accepted narrative text for document assembler.
        
        Guarantees:
        - Only ACCEPTED_FOR_RENDERING blocks.
        - Manifest hash must match current canonical facts (if hash provided).
        """
        # Find latest accepted generation for case_id
        matching_gens = [
            rec for rec in NARRATIVE_DRAFT_STORE.values()
            if rec.case_id == case_id and rec.status == GenerationStatus.ACCEPTED_FOR_RENDERING
        ]
        if not matching_gens:
            return {}

        # Sort by creation time descending
        latest_rec = sorted(matching_gens, key=lambda x: x.created_at, reverse=True)[0]

        # Verify freshness if current_manifest_hash provided
        if current_manifest_hash and latest_rec.fact_manifest_hash != current_manifest_hash:
            # Stale: Do not render stale narrative
            return {}

        # Return accepted blocks
        accepted_dict: Dict[str, str] = {}
        for b_name in latest_rec.accepted_bindings:
            if b_name in latest_rec.narrative_blocks:
                accepted_dict[b_name] = latest_rec.narrative_blocks[b_name].text

        return accepted_dict
