#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script: scripts/compare_mb07_template.py
Description: CLI Diagnostic Tool to verify structural fidelity between an original MB07 template
and a generated proposal DOCX output.
Usage:
    python scripts/compare_mb07_template.py <path_to_template.docx> <path_to_output.docx>
"""

import sys
import os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from msb_eb_copilot.src.template_verification.structure_fingerprint import (
    DynamicTableRule,
    compare_template_structure,
    snapshot_template_structure,
)


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/compare_mb07_template.py <template.docx> <output.docx>")
        sys.exit(2)

    template_path = sys.argv[1]
    output_path = sys.argv[2]

    if not os.path.exists(template_path):
        print(f"Error: Template file not found: {template_path}")
        sys.exit(2)

    if not os.path.exists(output_path):
        print(f"Error: Output file not found: {output_path}")
        sys.exit(2)

    print("=" * 70)
    print("   MSB MB07 TEMPLATE FIDELITY VERIFICATION")
    print("=" * 70)
    print(f"Template baseline: {template_path}")
    print(f"Generated output:  {output_path}")
    print("-" * 70)

    try:
        t_snap = snapshot_template_structure(template_path)
        o_snap = snapshot_template_structure(output_path)

        # Allow dynamic row growth on Table 32 (CIC Credit Relations) by default
        dynamic_rules = [
            DynamicTableRule(table_index=32, binding_id="cic_credit_relations", allow_row_growth=True, max_growth=50)
        ]

        result = compare_template_structure(
            template_snapshot=t_snap,
            output_snapshot=o_snap,
            allow_table_expansion=False,
            allow_row_growth=False,
            dynamic_table_rules=dynamic_rules,
        )

        print(f"Template SHA256: {t_snap.sha256[:16]}... | Sections: {t_snap.section_count} | Tables: {t_snap.table_count}")
        print(f"Output SHA256:   {o_snap.sha256[:16]}... | Sections: {o_snap.section_count} | Tables: {o_snap.table_count}")
        print("-" * 70)

        if result.allowed_mutations_observed:
            print(f"Allowed Dynamic Mutations ({len(result.allowed_mutations_observed)}):")
            for m in result.allowed_mutations_observed:
                print(f"  [+] {m}")
            print("-" * 70)

        if result.is_structurally_sound:
            print("MB07 TEMPLATE FIDELITY: PASS")
            if result.is_exact_match:
                print("(Document structure matches template baseline exactly)")
            else:
                print("(Document structure preserved; all observed mutations are within approved dynamic policies)")
            print("=" * 70)
            sys.exit(0)
        else:
            print("MB07 TEMPLATE FIDELITY: FAIL")
            print(f"\nDetected {len(result.all_violations)} structural invariant violation(s):")
            for v in result.all_violations:
                print(f"  [!] {v}")
            print("=" * 70)
            sys.exit(1)

    except Exception as e:
        print(f"Verification encountered error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
