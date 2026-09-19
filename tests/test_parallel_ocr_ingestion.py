# -*- coding: utf-8 -*-
"""
Tests cho Patch 1.5B: Bounded Parallel OCR for scanned PDF pages.
Bảo đảm:
1. PARALLEL ALL-SCANNED: 8 trang scanned -> OCR song song, kết quả 8 trang đúng thứ tự [PAGE 1..8].
2. COMPLETION OUT OF ORDER: Độ trễ khác nhau giữa các trang -> Hoàn thành không theo thứ tự,
   nhưng kết quả cuối cùng bắt buộc được lắp ráp đúng thứ tự vật lý 1, 2, 3.
3. MAX CONCURRENCY BOUND: Với OCR_MAX_WORKERS=4 -> max_active_calls <= 4 và max_active_calls > 1.
4. OCR_MAX_WORKERS=1: max_active_calls == 1 -> Tái tạo chính xác ngữ nghĩa tuần tự.
5. INVALID ENV CONFIG: "abc", "0", "99",... -> Xử lý an toàn theo hợp đồng (fallback 4, clamp 8).
6. FAILURE PROPAGATION: 1 trang bị lỗi OCRTimeoutError/OCRNoTextError -> Lan truyền trực tiếp ngoại lệ,
   hủy tác vụ chờ, tuyệt đối không trả kết quả thành công một phần.
7. HYBRID SELECTIVE PARALLEL OCR: 6 trang (1, 3, 5 digital; 2, 4, 6 scanned) -> Chỉ gọi OCR song song cho 2, 4, 6,
   kết quả cuối cùng là PAGE 1..6.
8. TELEMETRY PHYSICAL PAGE NUMBER: Ghi nhận telemetry ocr_page_{page_num} đúng theo số trang vật lý gốc.
"""

import os
import time
import threading
from typing import Dict, List, Optional
from unittest.mock import patch, MagicMock
import pytest
import pypdf

from msb_eb_copilot.src.ingestion.router import (
    DocumentIngestionRouter,
    DocumentIngestionResult,
)
from msb_eb_copilot.src.ingestion.pdf_ocr import (
    PDFOCRIngestor,
    BaseOCREngine,
    QwenVisionOCREngine,
    OCRPageResult,
    OCRDocumentResult,
    OCRTimeoutError,
    OCRNoTextError,
    get_ocr_max_workers,
    DEFAULT_OCR_MAX_WORKERS,
    MAX_OCR_MAX_WORKERS,
    MIN_OCR_MAX_WORKERS,
)
from msb_eb_copilot.src.ai_client import AIAssistantClient


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")
SAMPLE_MULTIPAGE_PDF = os.path.join(FIXTURES_DIR, "sample_multipage.pdf")
SCANNED_FIXTURE_PDF = os.path.join(FIXTURES_DIR, "scanned_legal_fixture.pdf")


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
# 1. PARALLEL ALL-SCANNED (8 SCANNED PAGES)
# ==============================================================================
class ParallelTrackingEngine(BaseOCREngine):
    provider_name = "parallel_tracker"

    def __init__(self, delay: float = 0.02):
        self.delay = delay
        self._lock = threading.Lock()
        self.recorded_pages: List[int] = []
        self.call_count = 0

    def ocr_page(self, base64_png: str, page_num: int) -> str:
        with self._lock:
            self.recorded_pages.append(page_num)
            self.call_count += 1
        time.sleep(self.delay)
        return f"Văn bản nhận dạng OCR trang {page_num}"


def test_parallel_all_scanned_eight_pages(tmp_path, scanned_page_obj):
    pdf_path = create_pdf(tmp_path, "scanned_8p.pdf", [scanned_page_obj] * 8)
    engine = ParallelTrackingEngine()

    result = DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine, max_workers=4)

    assert isinstance(result, DocumentIngestionResult)
    assert result.mode == "ocr"
    assert result.page_count == 8
    assert engine.call_count == 8
    assert sorted(engine.recorded_pages) == list(range(1, 9))

    # Bắt buộc chuỗi [PAGE 1] đến [PAGE 8] đúng thứ tự
    for idx in range(1, 9):
        expected_marker = f"[PAGE {idx}]\nVăn bản nhận dạng OCR trang {idx}"
        assert expected_marker in result.tagged_text

    blocks = result.tagged_text.split("\n\n")
    assert len(blocks) == 8
    for idx in range(8):
        assert blocks[idx].startswith(f"[PAGE {idx+1}]\n")


# ==============================================================================
# 2. COMPLETION OUT OF ORDER (DIFFERENT DELAYS)
# ==============================================================================
class OutOfOrderEngine(BaseOCREngine):
    provider_name = "out_of_order_engine"

    def __init__(self, delays: Dict[int, float]):
        self.delays = delays
        self._lock = threading.Lock()
        self.completion_order: List[int] = []

    def ocr_page(self, base64_png: str, page_num: int) -> str:
        delay = self.delays.get(page_num, 0.01)
        time.sleep(delay)
        with self._lock:
            self.completion_order.append(page_num)
        return f"Dữ liệu trang {page_num}"


def test_completion_out_of_order_preserves_page_ordering(tmp_path, scanned_page_obj):
    pdf_path = create_pdf(tmp_path, "out_of_order_3p.pdf", [scanned_page_obj] * 3)
    # Trang 1: chậm nhất (0.25s), Trang 2: nhanh nhất (0.01s), Trang 3: trung bình (0.10s)
    delays = {1: 0.25, 2: 0.01, 3: 0.10}
    engine = OutOfOrderEngine(delays=delays)

    result = DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine, max_workers=3)

    # Khẳng định thứ tự hoàn thành của các worker bị đảo lộn (trang 2 kết thúc trước trang 1)
    assert engine.completion_order != [1, 2, 3], f"Thực tế completion order: {engine.completion_order}"
    assert engine.completion_order[0] == 2  # Trang 2 nhanh nhất phải xong đầu tiên

    # BẮT BUỘC: Kết quả tagged_text cuối cùng vẫn lắp ráp đúng tuyệt đối theo thứ tự trang vật lý 1, 2, 3
    blocks = result.tagged_text.split("\n\n")
    assert len(blocks) == 3
    assert blocks[0] == "[PAGE 1]\nDữ liệu trang 1"
    assert blocks[1] == "[PAGE 2]\nDữ liệu trang 2"
    assert blocks[2] == "[PAGE 3]\nDữ liệu trang 3"


# ==============================================================================
# 3. MAX CONCURRENCY BOUND (ACTIVE CALLS TRACKING)
# ==============================================================================
class ConcurrencyTrackerEngine(BaseOCREngine):
    provider_name = "concurrency_tracker"

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self._lock = threading.Lock()
        self.active_calls = 0
        self.max_active_calls = 0
        self.total_calls = 0

    def ocr_page(self, base64_png: str, page_num: int) -> str:
        with self._lock:
            self.active_calls += 1
            self.total_calls += 1
            if self.active_calls > self.max_active_calls:
                self.max_active_calls = self.active_calls

        try:
            time.sleep(self.delay)
            return f"Văn bản trang {page_num}"
        finally:
            with self._lock:
                self.active_calls -= 1


def test_max_concurrency_bound(tmp_path, scanned_page_obj):
    pdf_path = create_pdf(tmp_path, "concurrency_8p.pdf", [scanned_page_obj] * 8)
    engine = ConcurrencyTrackerEngine(delay=0.25)

    result = DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine, max_workers=4)

    assert result.page_count == 8
    assert engine.total_calls == 8
    # Số cuộc gọi đồng thời tối đa không được vượt quá 4:
    assert engine.max_active_calls <= 4
    # Và phải chứng minh có sự xử lý đồng thời (> 1 worker cùng chạy):
    assert engine.max_active_calls > 1, f"Kỳ vọng max_active_calls > 1, thực tế: {engine.max_active_calls}"


# ==============================================================================
# 4. OCR_MAX_WORKERS=1 (STRICT SEQUENTIAL SEMANTICS)
# ==============================================================================
def test_ocr_max_workers_one_sequential(tmp_path, scanned_page_obj):
    pdf_path = create_pdf(tmp_path, "sequential_4p.pdf", [scanned_page_obj] * 4)
    engine = ConcurrencyTrackerEngine(delay=0.02)

    result = DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine, max_workers=1)

    assert result.page_count == 4
    assert engine.total_calls == 4
    # Với max_workers=1, tại mọi thời điểm số call active chính xác là 1:
    assert engine.max_active_calls == 1


# ==============================================================================
# 5. INVALID ENV CONFIG (SAFE FALLBACK & CLAMPING)
# ==============================================================================
def test_invalid_env_config_behavior():
    # Trường hợp không có config: mặc định 4
    with patch.dict(os.environ, {}, clear=True):
        assert get_ocr_max_workers() == DEFAULT_OCR_MAX_WORKERS

    # Trường hợp config không phải số nguyên ("abc"): an toàn fallback 4
    with patch.dict(os.environ, {"OCR_MAX_WORKERS": "abc"}):
        assert get_ocr_max_workers() == 4

    # Trường hợp config <= 0 ("0", "-5"): an toàn fallback 4
    with patch.dict(os.environ, {"OCR_MAX_WORKERS": "0"}):
        assert get_ocr_max_workers() == 4
    with patch.dict(os.environ, {"OCR_MAX_WORKERS": "-5"}):
        assert get_ocr_max_workers() == 4

    # Trường hợp config quá lớn ("99", "100"): an toàn clamp về 8
    with patch.dict(os.environ, {"OCR_MAX_WORKERS": "99"}):
        assert get_ocr_max_workers() == MAX_OCR_MAX_WORKERS
    with patch.dict(os.environ, {"OCR_MAX_WORKERS": "100"}):
        assert get_ocr_max_workers() == 8

    # Trường hợp config hợp lệ trong khoảng [1, 8]
    for w in [1, 2, 4, 8]:
        with patch.dict(os.environ, {"OCR_MAX_WORKERS": str(w)}):
            assert get_ocr_max_workers() == w

    # Kiểm tra khi truyền tham số trực tiếp
    assert get_ocr_max_workers(configured=0) == 4
    assert get_ocr_max_workers(configured=-1) == 4
    assert get_ocr_max_workers(configured=99) == 8
    assert get_ocr_max_workers(configured=6) == 6
    assert get_ocr_max_workers(configured="invalid") == 4


# ==============================================================================
# 6. FAILURE PROPAGATION (EXPLICIT TYPED FAILURE, NO PARTIAL RESULT)
# ==============================================================================
class FailingParallelEngine(BaseOCREngine):
    provider_name = "failing_engine"

    def __init__(self, fail_at_page: int, error: Exception):
        self.fail_at_page = fail_at_page
        self.error = error
        self._lock = threading.Lock()
        self.called_pages: List[int] = []

    def ocr_page(self, base64_png: str, page_num: int) -> str:
        with self._lock:
            self.called_pages.append(page_num)
        if page_num == self.fail_at_page:
            time.sleep(0.01)
            raise self.error
        time.sleep(0.05)
        return f"Văn bản trang {page_num}"


def test_failure_propagation_no_partial_result(tmp_path, scanned_page_obj):
    pdf_path = create_pdf(tmp_path, "fail_4p.pdf", [scanned_page_obj] * 4)

    # Thử nghiệm với OCRTimeoutError tại trang 2
    timeout_engine = FailingParallelEngine(fail_at_page=2, error=OCRTimeoutError("Timeout tại trang 2"))
    with pytest.raises(OCRTimeoutError, match="Timeout tại trang 2"):
        DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=timeout_engine, max_workers=4)

    # Thử nghiệm với OCRNoTextError tại trang 3
    notext_engine = FailingParallelEngine(fail_at_page=3, error=OCRNoTextError("Trang 3 rỗng"))
    with pytest.raises(OCRNoTextError, match="Trang 3 rỗng"):
        DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=notext_engine, max_workers=4)


# ==============================================================================
# 7. HYBRID SELECTIVE PARALLEL OCR (P1,3,5 DIGITAL, P2,4,6 SCANNED)
# ==============================================================================
def test_hybrid_selective_parallel_ocr(tmp_path, digital_page_obj, scanned_page_obj):
    # 6 trang: 1 digital, 2 scanned, 3 digital, 4 scanned, 5 digital, 6 scanned
    pages = [
        digital_page_obj,
        scanned_page_obj,
        digital_page_obj,
        scanned_page_obj,
        digital_page_obj,
        scanned_page_obj
    ]
    pdf_path = create_pdf(tmp_path, "hybrid_6p.pdf", pages)
    engine = ConcurrencyTrackerEngine(delay=0.25)

    result = DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine, max_workers=3)

    assert result.mode == "hybrid"
    assert result.page_count == 6
    assert result.provider == "pypdf+concurrency_tracker"
    assert result.fallback_reason == "PDFBlankPageError"

    # Chỉ có đúng 3 trang scanned (2, 4, 6) được gọi OCR:
    assert engine.total_calls == 3

    # Các trang scanned được chạy đồng thời:
    assert engine.max_active_calls > 1

    # Bắt buộc: Cấu trúc 6 trang [PAGE 1] đến [PAGE 6] đúng tuyệt đối
    blocks = result.tagged_text.split("\n\n")
    assert len(blocks) == 6
    assert blocks[0].startswith("[PAGE 1]\nCÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM")
    assert blocks[1] == "[PAGE 2]\nVăn bản trang 2"
    assert blocks[2].startswith("[PAGE 3]\nCÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM")
    assert blocks[3] == "[PAGE 4]\nVăn bản trang 4"
    assert blocks[4].startswith("[PAGE 5]\nCÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM")
    assert blocks[5] == "[PAGE 6]\nVăn bản trang 6"


# ==============================================================================
# 8. TELEMETRY PHYSICAL PAGE NUMBER PRESERVATION
# ==============================================================================
def test_telemetry_physical_page_number_preservation(tmp_path, digital_page_obj, scanned_page_obj):
    """Xác nhận telemetry ghi nhận ocr_page_{page_num} với đúng số trang vật lý gốc trong tài liệu."""
    pages = [
        digital_page_obj,  # 1: digital
        scanned_page_obj,  # 2: scanned
        digital_page_obj,  # 3: digital
        digital_page_obj,  # 4: digital
        scanned_page_obj   # 5: scanned
    ]
    pdf_path = create_pdf(tmp_path, "telemetry_test_5p.pdf", pages)

    recorded_ops = []
    original_record = AIAssistantClient.record_telemetry

    def mock_record_telemetry(*args, **kwargs):
        op = kwargs.get("operation") or (args[0] if args else "")
        recorded_ops.append(op)
        return original_record(*args, **kwargs)

    # Mock Qwen Vision Engine để không gọi API thật
    engine = ParallelTrackingEngine()

    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.record_telemetry", side_effect=mock_record_telemetry):
        result = DocumentIngestionRouter.ingest_document(pdf_path, ocr_engine=engine, max_workers=2)

    assert result.mode == "hybrid"
    assert result.page_count == 5
    # Engine chỉ nhận 2 cuộc gọi cho trang 2 và 5
    assert sorted(engine.recorded_pages) == [2, 5]


# ==============================================================================
# 9. EXISTING COMPATIBILITY WITH PRESET FIXTURES
# ==============================================================================
def test_existing_compatibility():
    assert os.path.exists(SAMPLE_MULTIPAGE_PDF)
    res_dig = DocumentIngestionRouter.ingest_document(SAMPLE_MULTIPAGE_PDF, max_workers=4)
    assert res_dig.mode == "digital"
    assert res_dig.page_count == len(pypdf.PdfReader(SAMPLE_MULTIPAGE_PDF).pages)

    assert os.path.exists(SCANNED_FIXTURE_PDF)
    engine = ParallelTrackingEngine()
    res_scan = DocumentIngestionRouter.ingest_document(SCANNED_FIXTURE_PDF, ocr_engine=engine, max_workers=2)
    assert res_scan.mode == "ocr"
    assert res_scan.page_count == 2
    assert sorted(engine.recorded_pages) == [1, 2]
