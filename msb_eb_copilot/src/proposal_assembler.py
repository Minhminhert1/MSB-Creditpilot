"""Module: proposal_assembler.py
Description: Authoritative MSB MB07 Master Proposal Assembler.
Enforces strict in-place template mutation and template fidelity quality gating.
Eliminates fallback document reconstruction and preserves original MB07 template geometry.
"""

from __future__ import annotations
import os
import copy
from typing import Optional, Dict, List
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from .section_a.renderer import SectionARenderer
from .section_c.models import SectionCData
from .section_d.models import SectionDData
from .section_e.models import SectionEData
from .mb07_inplace_mutator import MB07InPlaceMutator
from .template_rendering.structure_guard import (
    StructureGuard,
    MB07FidelityError,
    UnsupportedTemplateVersionError,
    validate_template_compatibility,
)
from .template_verification.structure_fingerprint import DynamicTableRule


class CreditProposalAssembler:
    """Master assembler for full MSB MB07 credit proposals."""

    def __init__(self, template_path: str = None):
        if template_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            template_path = os.path.join(base_dir, "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - thực hiện rà soát - tái cấp.docx")
        self.template_path = template_path

    def assemble(
        self,
        facts_a: dict,
        data_b_processed: dict,
        data_c: SectionCData,
        data_d: SectionDData,
        data_e: SectionEData,
        output_path: str,
        highlight_new_features: bool = False,
        accepted_narratives: Optional[Dict[str, str]] = None,
        enforce_fidelity: bool = True,
    ) -> str:
        """Assembles the full proposal by mutating the authoritative MB07 template in place."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # 0. Validate template compatibility (fail-closed if unsupported or corrupted)
        validate_template_compatibility(self.template_path)

        # Setup StructureGuard quality gate
        # Allow dynamic row growth only for allowlisted repeatable tables (e.g. Table 32 CIC relations)
        guard = StructureGuard(
            template_path=self.template_path,
            dynamic_table_rules=[
                DynamicTableRule(table_index=32, binding_id="cic_credit_relations", allow_row_growth=True, max_growth=50),
            ],
            allow_table_expansion=False,
            allow_row_growth=False,
        )

        # 1. Render Section A directly onto the template copy
        facts_for_renderer = {k: v for k, v in facts_a.items() if hasattr(v, "canonical_key")}
        renderer_a = SectionARenderer()
        renderer_a.render(
            facts=facts_for_renderer,
            template_path=self.template_path,
            output_path=output_path,
            skip_validation=False,
        )

        master_doc = docx.Document(output_path)

        def _get_fact_val(key: str, default: str = "") -> str:
            if key not in facts_a:
                return default
            val = facts_a[key]
            if hasattr(val, "value") and val.value is not None:
                if hasattr(val.value, "value"):
                    return str(val.value.value)
                return str(val.value)
            return str(val) if val is not None else default

        # === IN-PLACE TEMPLATE MUTATION ===
        mutator = MB07InPlaceMutator(master_doc)
        mutator.mutate_metadata(
            unit_name=_get_fact_val("submission.unit_name", ""),
            proposal_no=_get_fact_val("submission.proposal_no", ""),
            date_str=_get_fact_val("submission.proposal_date", ""),
            rm_name=_get_fact_val("submission.rm_name", ""),
            rm_phone=_get_fact_val("submission.rm_phone", ""),
            support_name=_get_fact_val("submission.support_name", ""),
            support_phone=_get_fact_val("submission.support_phone", ""),
            manager_name=_get_fact_val("submission.manager_name", ""),
            manager_phone=_get_fact_val("submission.manager_phone", ""),
        )
        mutator.mutate_syndicated_block()
        mutator.mutate_section_b(data_b_processed)
        mutator.mutate_section_c(data_c, accepted_narratives=accepted_narratives)
        mutator.mutate_section_d(data_d, accepted_narratives=accepted_narratives)
        mutator.mutate_section_e(data_e, accepted_narratives=accepted_narratives)
        mutator.mutate_credit_evaluation_and_mb09()

        # Handle non-destructive inapplicable markers
        mutator.prune_inapplicable_and_empty_sections()
        # Clean red guidance text
        mutator.clean_template_guidance_and_red_texts()

        if highlight_new_features:
            mutator.apply_new_template_highlights()
        else:
            mutator.strip_all_highlights_and_shading()

        master_doc.save(output_path)

        # 2. Template Fidelity Quality Gate Verification
        if enforce_fidelity:
            guard.verify(output_path, raise_on_violation=True)

        return output_path
