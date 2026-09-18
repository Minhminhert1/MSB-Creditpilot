import os
import docx
from docx.enum.table import WD_TABLE_ALIGNMENT

def test_proposal_quality_gate():
    """Verify quality gate for MB07 proposal document generation.
    
    Self-contained & reproducible across fresh git clones:
    - If deep analysis reference fixture is present: verifies full enriched package (>=1.5MB, >=68 tables, >=9 images).
    - If clean clone without local output artifacts: deterministically builds and verifies standard proposal (>=200KB, >=50 tables, full sections A-E, centered alignment, required keywords).
    """
    target_file = "output/TO_TRINH_MB07_PSD_NEW_TEMPLATE_BAN_FULL.docx"
    if not os.path.exists(target_file):
        import test_psd_pipeline_new_template
        test_psd_pipeline_new_template.run_psd_test()
    assert os.path.exists(target_file), f"File {target_file} does not exist!"
    
    chi_tiet_ref = os.path.join("output", "TO_TRINH_MB07_PSD_FULL_A_B_D_CHI_TIET.docx")
    has_deep_enrichment = os.path.exists(chi_tiet_ref)
    
    size = os.path.getsize(target_file)
    if has_deep_enrichment:
        assert size >= 1_500_000, f"File size too small ({size} bytes). Deep analysis or images might be missing!"
    else:
        assert size >= 200_000, f"File size too small ({size} bytes). Standard proposal corrupted!"
    
    doc = docx.Document(target_file)
    
    # Table count check: Must have full tables across sections A, B, C, D, E
    table_count = len(doc.tables)
    min_tables = 68 if has_deep_enrichment else 50
    assert table_count >= min_tables, f"Expected at least {min_tables} tables, got {table_count}."
    
    if has_deep_enrichment:
        image_count = len(doc.inline_shapes)
        assert image_count >= 9, f"Expected at least 9 BCTC images, got {image_count}."
    
    # All tables must be centered
    for idx, tbl in enumerate(doc.tables):
        assert tbl.alignment == WD_TABLE_ALIGNMENT.CENTER, f"Table {idx} is not centered!"
        
    # Verify key enterprise partners and line items are present
    full_text = "\n".join([p.text for p in doc.paragraphs] + [cell.text for tbl in doc.tables for row in tbl.rows for cell in row.cells])
    required_keywords = ["Thế Giới Di Động", "FPT", "Apple", "Dell", "Hàng tồn kho", "Phải thu khách hàng"]
    for kw in required_keywords:
        assert kw in full_text, f"Missing critical enterprise partner / narrative keyword: {kw}"

    print(f"Quality Gate PASSED: {size:,} bytes | {len(doc.paragraphs)} paragraphs | {table_count} tables")

if __name__ == "__main__":
    test_proposal_quality_gate()
