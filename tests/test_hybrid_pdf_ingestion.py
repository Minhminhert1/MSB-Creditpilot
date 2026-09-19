# -*- coding: utf-8 -*-
"""
Tests cho Patch 1.5A: Hybrid Page-Level PDF Ingestion.
Bảo đảm:
1. ALL DIGITAL: 3 trang kỹ thuật số -> OCR nhận 0 cuộc gọi, mode='digital', markers [PAGE 1..3].
2. ALL SCANNED: 3 trang quét ảnh -> OCR đúng 3 lần, mode='ocr', số trang bảo toàn.
3. MIXED: 4 trang xen kẽ (1 digital, 2 scanned, 3 digital, 4 scanned) -> OCR chỉ gọi cho trang 2 và 4, mode='hybrid'.
4. BLANK / IMAGE PAGE INSIDE DIGITAL PDF: Không kích hoạt OCR cho toàn bộ các trang.
5. OCR FAILURE ON ONE REQUIRED PAGE: Báo lỗi trực tiếp, không bao giờ trả kết quả thành công một phần.
6. PAGE COUNT INVARIANT: result.page_count == physical_page_count.
7. Tương thích hoàn toàn với tài liệu thuần digital.
8. Tương thích hoàn toàn với tài liệu thuần scanned.
9. ACCEPTANCE TEST: Tệp 10 trang chỉ có trang 3 và 8 bị scan -> OCR engine chỉ nhận trang 3 và 8, không nhận trang nào khác.
"""

import os
from typing import Dict, List
import pytest
import pypdf

from msb_eb_copilot.src.ingestion.router import (
    DocumentIngestionRouter,
    DocumentIngestionResult,
)
from msb_eb_copilot.src.ingestion.pdf_ocr import (
    BaseOCREngine,
    OCRTimeoutError,
    OCRNoTextError,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")
SAMPLE_MULTIPAGE_PDF = os.path.join(FIXTURES_DIR, "sample_multipage.pdf")
SCANNED_FIXTURE_PDF = os.path.join(FIXTURES_DIR, "scanned_legal_fixture.pdf")


class RecordingOCREngine(BaseOCREngine):
    """Mock OCR Engine ghi lại chi tiết các trang vật lý đã nhận dạng."""
    provider_name = "recording_engine"

    def __init__(self, responses: Dict[int, str] = None, fail_pages: Dict[int, Exception] = None):
        self.responses = responses or {}
        self.fail_pages = fail_pages or {}
        self.recorded_pages: List[int] = []

    def ocr_page(self, base64_png: str, page_num: int) -> str:
        self.recorded_pages.append(page_num)
        if page_num in self.fail_pages:
            raise self.fail_pages[page_num]
        return self.responses.get(page_num, f"Nội dung nhận dạng OCR trang {page_num}")


@pytest.fixture
def digital_page_obj():
    reader = pypdf.PdfReader(SAMPLE_MULTIPAGE_PDF)
    return reader.pages[0]


@pytest.fixture
def scanned_page_obj():
    reader = pypdf.PdfReader(SCANNED_FIXTURE_PDF)
    return reader.pages[0]


def create_pdf(tmp_path, filename: str, pages: List) -> str:
    writer = pypdf.PdfWriter()
    for page in pages:
        writer.add_page(page)
    out_file = str(tmp_path / filename)
    with open(out_file, "wb") as f:
        writer.write(f)
    return out_file


# ==============================================================================
# 1. ALL DIGITAL (3 DIGITAL PAGES)
# ==============================================================================
def test_all_digital_three_pages(tmp_path, digital_page_obj):
    pdf_path = create_pdf(tmp_path, "all_digital.pdf", [digital_page_obj, digital_page_obj, digital_page_obj])
    engine = RecordingOCREngine()

    result = DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine)

    assert isinstance(result, DocumentIngestionResult)
    assert result.mode == "digital"
    assert result.provider == "pypdf"
    assert result.fallback_reason is None
    assert result.page_count == 3
    assert len(engine.recorded_pages) == 0

    assert result.tagged_text.startswith("[PAGE 1]\n")
    assert "\n\n[PAGE 2]\n" in result.tagged_text
    assert "\n\n[PAGE 3]\n" in result.tagged_text


# ==============================================================================
# 2. ALL SCANNED (3 SCANNED PAGES)
# ==============================================================================
def test_all_scanned_three_pages(tmp_path, scanned_page_obj):
    pdf_path = create_pdf(tmp_path, "all_scanned.pdf", [scanned_page_obj, scanned_page_obj, scanned_page_obj])
    engine = RecordingOCREngine()

    result = DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine)

    assert isinstance(result, DocumentIngestionResult)
    assert result.mode == "ocr"
    assert result.provider == "recording_engine"
    assert result.fallback_reason == "PDFBlankPageError"
    assert result.page_count == 3
    assert engine.recorded_pages == [1, 2, 3]

    assert result.tagged_text.startswith("[PAGE 1]\nNội dung nhận dạng OCR trang 1")
    assert "\n\n[PAGE 2]\nNội dung nhận dạng OCR trang 2" in result.tagged_text
    assert "\n\n[PAGE 3]\nNội dung nhận dạng OCR trang 3" in result.tagged_text


# ==============================================================================
# 3. MIXED (P1 DIGITAL, P2 SCANNED, P3 DIGITAL, P4 SCANNED)
# ==============================================================================
def test_mixed_four_pages_alternating(tmp_path, digital_page_obj, scanned_page_obj):
    pdf_path = create_pdf(
        tmp_path,
        "mixed_4p.pdf",
        [digital_page_obj, scanned_page_obj, digital_page_obj, scanned_page_obj]
    )
    engine = RecordingOCREngine()

    result = DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine)

    assert isinstance(result, DocumentIngestionResult)
    assert result.mode == "hybrid"
    assert result.provider == "pypdf+recording_engine"
    assert result.fallback_reason == "PDFBlankPageError"
    assert result.page_count == 4

    # OCR CHỈ được gọi cho các trang 2 và 4
    assert engine.recorded_pages == [2, 4]

    # Kiểm tra thứ tự và cấu trúc [PAGE 1] đến [PAGE 4]
    blocks = result.tagged_text.split("\n\n")
    assert len(blocks) == 4
    assert blocks[0].startswith("[PAGE 1]\n")
    assert "CÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM" in blocks[0]

    assert blocks[1] == "[PAGE 2]\nNội dung nhận dạng OCR trang 2"

    assert blocks[2].startswith("[PAGE 3]\n")
    assert "CÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM" in blocks[2]

    assert blocks[3] == "[PAGE 4]\nNội dung nhận dạng OCR trang 4"


# ==============================================================================
# 4. BLANK / IMAGE PAGE INSIDE DIGITAL PDF (DOES NOT OCR EVERY PAGE)
# ==============================================================================
def test_blank_page_inside_digital_pdf_does_not_ocr_all(tmp_path, digital_page_obj, scanned_page_obj):
    # 5 trang: Trang 1, 2 digital, Trang 3 scanned, Trang 4, 5 digital
    pdf_path = create_pdf(
        tmp_path,
        "mostly_digital_5p.pdf",
        [digital_page_obj, digital_page_obj, scanned_page_obj, digital_page_obj, digital_page_obj]
    )
    engine = RecordingOCREngine()

    result = DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine)

    assert result.mode == "hybrid"
    assert result.page_count == 5
    # Tuyệt đối không OCR cả 5 trang: chỉ gọi duy nhất trang 3
    assert engine.recorded_pages == [3]


# ==============================================================================
# 5. OCR FAILURE ON ONE REQUIRED PAGE (EXPLICIT FAILURE)
# ==============================================================================
def test_ocr_failure_on_required_page_fails_immediately(tmp_path, digital_page_obj, scanned_page_obj):
    pdf_path = create_pdf(
        tmp_path,
        "mixed_fail.pdf",
        [digital_page_obj, scanned_page_obj, digital_page_obj]
    )

    # Thử nghiệm với OCRTimeoutError
    engine_timeout = RecordingOCREngine(fail_pages={2: OCRTimeoutError("Timeout tại trang 2")})
    with pytest.raises(OCRTimeoutError, match="Timeout tại trang 2"):
        DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine_timeout)

    # Thử nghiệm với OCRNoTextError
    engine_notext = RecordingOCREngine(fail_pages={2: OCRNoTextError("Trang 2 rỗng")})
    with pytest.raises(OCRNoTextError, match="Trang 2 rỗng"):
        DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine_notext)


# ==============================================================================
# 6. PAGE COUNT INVARIANT
# ==============================================================================
def test_page_count_invariant_across_all_modes(tmp_path, digital_page_obj, scanned_page_obj):
    # Digital mode
    dig_path = create_pdf(tmp_path, "inv_dig.pdf", [digital_page_obj] * 2)
    dig_res = DocumentIngestionRouter.ingest_document(dig_path)
    assert dig_res.page_count == 2
    assert dig_res.tagged_text.count("[PAGE ") == 2

    # Scanned mode
    scan_path = create_pdf(tmp_path, "inv_scan.pdf", [scanned_page_obj] * 2)
    scan_res = DocumentIngestionRouter.ingest_document(scan_path, ocr_engine=RecordingOCREngine())
    assert scan_res.page_count == 2
    assert scan_res.tagged_text.count("[PAGE ") == 2

    # Hybrid mode
    hyb_path = create_pdf(tmp_path, "inv_hyb.pdf", [digital_page_obj, scanned_page_obj, digital_page_obj])
    hyb_res = DocumentIngestionRouter.ingest_document(hyb_path, ocr_engine=RecordingOCREngine())
    assert hyb_res.page_count == 3
    assert hyb_res.tagged_text.count("[PAGE ") == 3


# ==============================================================================
# 7. EXISTING FULLY DIGITAL COMPATIBILITY
# ==============================================================================
def test_existing_fully_digital_compatibility():
    assert os.path.exists(SAMPLE_MULTIPAGE_PDF)
    engine = RecordingOCREngine()

    result = DocumentIngestionRouter.ingest_document(SAMPLE_MULTIPAGE_PDF, ocr_engine=engine)
    assert result.mode == "digital"
    assert result.provider == "pypdf"
    assert result.fallback_reason is None
    assert len(engine.recorded_pages) == 0


# ==============================================================================
# 8. EXISTING FULLY SCANNED COMPATIBILITY
# ==============================================================================
def test_existing_fully_scanned_compatibility():
    assert os.path.exists(SCANNED_FIXTURE_PDF)
    engine = RecordingOCREngine()

    result = DocumentIngestionRouter.ingest_document(SCANNED_FIXTURE_PDF, ocr_engine=engine)
    assert result.mode == "ocr"
    assert result.fallback_reason == "PDFBlankPageError"
    assert result.page_count == 2
    assert engine.recorded_pages == [1, 2]


# ==============================================================================
# 9. ACCEPTANCE TEST: 10-PAGE SYNTHETIC PDF WITH PAGES 3 & 8 SCANNED
# ==============================================================================
def test_acceptance_ten_page_selective_ocr(tmp_path, digital_page_obj, scanned_page_obj):
    """Kiểm thử chấp nhận (Acceptance Test):
    Tệp PDF 10 trang trong đó CHỈ CÓ trang 3 và trang 8 không có văn bản kỹ thuật số.
    Kỳ vọng:
    - pypdf trích xuất cho 8 trang (1, 2, 4, 5, 6, 7, 9, 10).
    - OCR Engine CHỈ nhận chính xác 2 cuộc gọi cho trang 3 và trang 8 (ocr_page_3, ocr_page_8).
    - KHÔNG CÓ cuộc gọi OCR nào cho các trang 1, 2, 4, 5, 6, 7, 9, 10.
    - mode == 'hybrid'
    - provider == 'pypdf+recording_engine'
    - Toàn bộ 10 trang được lắp ráp đầy đủ, đúng thứ tự [PAGE 1] đến [PAGE 10].
    """
    ten_pages = []
    for idx in range(1, 11):
        if idx in (3, 8):
            ten_pages.append(scanned_page_obj)
        else:
            ten_pages.append(digital_page_obj)

    pdf_path = create_pdf(tmp_path, "acceptance_10p.pdf", ten_pages)
    engine = RecordingOCREngine()

    result = DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine)

    assert result.mode == "hybrid"
    assert result.provider == "pypdf+recording_engine"
    assert result.page_count == 10
    assert result.fallback_reason == "PDFBlankPageError"

    # CHỈ nhận 2 cuộc gọi cho trang 3 và trang 8:
    assert engine.recorded_pages == [3, 8], f"Kỳ vọng OCR chỉ gọi [3, 8], thực tế: {engine.recorded_pages}"

    # Tuyệt đối không gọi OCR cho các trang digital:
    for non_ocr_page in [1, 2, 4, 5, 6, 7, 9, 10]:
        assert non_ocr_page not in engine.recorded_pages

    # Lắp ráp đầy đủ và đúng thứ tự 10 trang
    for page_idx in range(1, 11):
        marker = f"[PAGE {page_idx}]"
        assert marker in result.tagged_text
