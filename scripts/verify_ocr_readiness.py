#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify OCR & PDFium readiness for GreenNode AgentBase packaging."""
import os
import sys
import io

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, ".")

def verify():
    results = {}
    
    # 1. Verify pypdfium2 can initialize and render
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument.new()
        page = pdf.new_page(200, 200)
        bitmap = page.render(scale=1.0)
        pil_image = bitmap.to_pil()
        assert pil_image.size == (200, 200)
        results["pdfium_rasterize"] = "PASS"
    except Exception as e:
        results["pdfium_rasterize"] = f"FAIL ({e})"

    # 2. Verify QwenVisionOCREngine model and initialization
    try:
        from msb_eb_copilot.src.ingestion.pdf_ocr import QwenVisionOCREngine
        engine = QwenVisionOCREngine(api_key="mock_key_for_init_check")
        assert engine.model == "qwen/qwen3.6-flash"
        results["ocr_engine_init"] = "PASS"
        results["ocr_model"] = engine.model
    except Exception as e:
        results["ocr_engine_init"] = f"FAIL ({e})"

    # 3. Verify router detects scanned/image-only PDF correctly
    try:
        from msb_eb_copilot.src.ingestion.router import DocumentIngestionRouter
        from msb_eb_copilot.src.ingestion.pdf_ocr import BaseOCREngine
        
        class MockEngine(BaseOCREngine):
            provider_name = "mock_vision"
            def ocr_page(self, base64_png: str, page_num: int) -> str:
                return f"Transcribed text on page {page_num}"
        
        fixture_path = "tests/fixtures/pdf/scanned_legal_fixture.pdf"
        if os.path.exists(fixture_path):
            res = DocumentIngestionRouter.ingest_document(fixture_path, ocr_engine=MockEngine())
            assert res.mode == "ocr"
            assert res.page_count == 2
            assert "[PAGE 1]" in res.tagged_text
            results["image_pdf_detection"] = "PASS"
        else:
            results["image_pdf_detection"] = "SKIP (fixture not found)"
    except Exception as e:
        results["image_pdf_detection"] = f"FAIL ({e})"

    print("=" * 50)
    print("OCR & PDFium Readiness Report")
    print("=" * 50)
    for k, v in results.items():
        print(f"{k}: {v}")
    print("=" * 50)
    return all(v == "PASS" or k == "ocr_model" or v.startswith("SKIP") for k, v in results.items())

if __name__ == "__main__":
    ok = verify()
    sys.exit(0 if ok else 1)
