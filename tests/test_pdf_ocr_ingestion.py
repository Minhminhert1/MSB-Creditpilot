# -*- coding: utf-8 -*-
"""
Tests cho module pdf_ocr.py (Scanned/Image-based PDF Ingestion Layer).
Bảo đảm:
- 100% Deterministic Offline Tests: ZERO network calls, ZERO real GreenNode API calls.
- Kiểm thử đầy đủ các điều kiện biên: File not found, Encrypted, Render error, Service error,
  Timeout, Empty/Whitespace OCR, Non-alphanumeric OCR, Page count mismatch.
- Kiểm định tính chất tệp PDF quét: pypdf extract_text trả về rỗng, nhưng PDFium render ra ảnh hợp lệ.
- Kiểm thử tích hợp trọn vẹn: scanned_legal_fixture.pdf -> PDFPageRenderer -> Qwen OCR ->
  tagged_text -> Locked LegalDocumentExtractor.
"""

import logging
import os
import json
import pytest
import pypdf
import pypdfium2 as pdfium
from typing import Dict, List, Optional
from unittest.mock import patch, MagicMock

from msb_eb_copilot.src.ingestion.pdf_ocr import (
    PDFOCRIngestor,
    BaseOCREngine,
    QwenVisionOCREngine,
    OCRPageResult,
    OCRDocumentResult,
    OCRIngestionError,
    OCRFileNotFoundError,
    OCREncryptedError,
    OCRRenderError,
    OCRServiceError,
    OCRTimeoutError,
    OCRNoTextError,
    OCRPageCountError,
    _safe_ocr_error_fields,
    OCRRateLimiter,
    get_shared_ocr_rate_limiter,
    reset_shared_ocr_rate_limiter_for_tests,
    _ocr_rate_limit_enabled_from_env,
    _ocr_rpm_limit_from_env,
    _compute_rate_limit_wait_seconds,
    _parse_retry_after_seconds,
    _parse_resets_in_seconds,
    DEFAULT_OCR_RPM_LIMIT,
    OCR_MAX_CONTENT_ATTEMPTS,
    _classify_ocr_text,
)
from msb_eb_copilot.src.extraction.legal_extraction import (
    LegalDocumentExtractor,
    LegalDocumentExtraction
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")
SCANNED_FIXTURE_PDF = os.path.join(FIXTURES_DIR, "scanned_legal_fixture.pdf")
SAMPLE_SINGLE_PAGE_PDF = os.path.join(FIXTURES_DIR, "sample_single_page.pdf")
ENCRYPTED_PDF = os.path.join(FIXTURES_DIR, "encrypted.pdf")
BLANK_PDF = os.path.join(FIXTURES_DIR, "blank.pdf")


@pytest.fixture(autouse=True)
def _isolate_shared_ocr_rate_limiter(monkeypatch):
    """The process-wide proactive rate limiter singleton (get_shared_ocr_rate_limiter)
    would otherwise be shared across every test in this file/session. Force it
    disabled by default so unrelated tests constructing a real QwenVisionOCREngine
    never incur a real wait; tests that specifically exercise rate limiting
    override OCR_RATE_LIMIT_ENABLED/OCR_RPM_LIMIT locally and reset again."""
    monkeypatch.setenv("OCR_RATE_LIMIT_ENABLED", "false")
    reset_shared_ocr_rate_limiter_for_tests()
    yield
    reset_shared_ocr_rate_limiter_for_tests()


# Dummy engine for unit tests without network calls
class MockOCREngine(BaseOCREngine):
    provider_name = "mock_engine"

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.call_count = 0

    def ocr_page(self, base64_png: str, page_num: int) -> str:
        self.call_count += 1
        if page_num in self.responses:
            val = self.responses[page_num]
            if isinstance(val, Exception):
                raise val
            return val
        return f"Nội dung văn bản nhận dạng được của trang {page_num}"


# ==============================================================================
# 1. SCANNED FIXTURE DUAL-PROPERTY TESTS (pypdf text empty vs PDFium image valid)
# ==============================================================================
def test_scanned_fixture_pypdf_has_zero_extractable_text():
    """Tệp scanned_legal_fixture.pdf là ảnh thuần túy: pypdf extract_text() trả về chuỗi rỗng."""
    assert os.path.exists(SCANNED_FIXTURE_PDF)
    reader = pypdf.PdfReader(SCANNED_FIXTURE_PDF)
    assert len(reader.pages) == 2
    for idx, page in enumerate(reader.pages):
        raw_text = page.extract_text() or ""
        assert raw_text.strip() == "", f"Trang {idx+1} không được chứa text stream có thể trích xuất trực tiếp"


def test_scanned_fixture_pdfium_renders_valid_images():
    """PDFium mở tệp và rasterize thành công cả 2 trang thành đối tượng ảnh PIL hợp lệ."""
    assert os.path.exists(SCANNED_FIXTURE_PDF)
    doc = pdfium.PdfDocument(SCANNED_FIXTURE_PDF)
    assert len(doc) == 2
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        img = page.render(scale=150 / 72.0).to_pil()
        assert img is not None
        assert img.width > 0 and img.height > 0
        page.close()
    doc.close()


# ==============================================================================
# 2. ERROR AND BOUNDARY TESTS
# ==============================================================================
def test_missing_file_raises_not_found():
    non_existent = os.path.join(FIXTURES_DIR, "non_existent_ocr.pdf")
    with pytest.raises(OCRFileNotFoundError, match="không tồn tại"):
        PDFOCRIngestor.extract_text_with_page_markers(non_existent)


def test_directory_path_raises_not_found():
    with pytest.raises(OCRFileNotFoundError, match="không phải là file"):
        PDFOCRIngestor.extract_text_with_page_markers(FIXTURES_DIR)


def test_encrypted_pdf_raises_encrypted_error():
    assert os.path.exists(ENCRYPTED_PDF)
    with pytest.raises(OCREncryptedError, match="bị khóa bằng mật khẩu"):
        PDFOCRIngestor.extract_text_with_page_markers(ENCRYPTED_PDF)


def test_ocr_returning_none_raises_no_text_error():
    engine = MockOCREngine(responses={1: None, 2: "Trang 2"})
    with pytest.raises(OCRNoTextError, match="không nhận được kết quả OCR"):
        PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)


def test_ocr_returning_whitespace_only_raises_no_text_error():
    engine = MockOCREngine(responses={1: "   \n\t  \n  ", 2: "Trang 2"})
    with pytest.raises(OCRNoTextError, match="có nội dung OCR hoàn toàn rỗng"):
        PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)


def test_ocr_returning_non_alphanumeric_raises_no_text_error():
    engine = MockOCREngine(responses={1: "--- === *** !!!", 2: "Trang 2"})
    with pytest.raises(OCRNoTextError, match="không chứa bất kỳ ký tự chữ hoặc số"):
        PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)


def test_page_count_mismatch_between_pypdf_and_pdfium_raises_error():
    """Giả lập sự cố bất đồng số trang giữa pypdf và pypdfium2."""
    engine = MockOCREngine()
    with patch("msb_eb_copilot.src.ingestion.pdf_ocr.PDFOCRIngestor._preflight_pdf", return_value=5):
        with pytest.raises(OCRPageCountError, match="Bất đồng số trang vật lý"):
            PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)


def test_ocr_render_failure_raises_render_error():
    """Giả lập lỗi ném ra từ thư viện PDFium khi mở tệp."""
    engine = MockOCREngine()
    with patch("pypdfium2.PdfDocument", side_effect=Exception("PDFium internal crash")):
        with pytest.raises(OCRRenderError, match="Không thể mở tài liệu bằng PDFium"):
            PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)


def test_qwen_engine_missing_api_key_raises_service_error():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(OCRServiceError, match="Không tìm thấy AI_PLATFORM_API_KEY"):
            QwenVisionOCREngine(api_key=None)


def test_qwen_engine_timeout_raises_timeout_error():
    from openai import APITimeoutError
    engine = QwenVisionOCREngine(api_key="mock_key")
    with patch.object(engine.client.chat.completions, "create", side_effect=APITimeoutError(request=None)):
        with pytest.raises(OCRTimeoutError, match="vượt quá"):
            engine.ocr_page("dummy_b64", page_num=1)


def test_qwen_engine_api_error_raises_service_error():
    from openai import APIError
    engine = QwenVisionOCREngine(api_key="mock_key")
    with patch.object(engine.client.chat.completions, "create", side_effect=APIError("Internal Server Error", request=None, body=None)):
        with pytest.raises(OCRServiceError, match="Lỗi dịch vụ OCR"):
            engine.ocr_page("dummy_b64", page_num=1)


# ==============================================================================
# 2b. SAFE DIAGNOSTIC LOGGING: exceptions are logged, but never leak secrets
# ==============================================================================
FAKE_API_KEY = "sk-LIVE-super-secret-do-not-log-abcdef123456"
FAKE_BASE64_IMAGE = "AAAABASE64FAKEIMAGEPAYLOAD" * 50  # stand-in for a real page image


def test_timeout_error_is_logged_with_safe_fields_and_no_secrets(caplog):
    from openai import APITimeoutError

    engine = QwenVisionOCREngine(api_key=FAKE_API_KEY)
    with patch.object(engine.client.chat.completions, "create", side_effect=APITimeoutError(request=None)):
        with caplog.at_level(logging.ERROR, logger="msb_eb_copilot.src.ingestion.pdf_ocr"):
            with pytest.raises(OCRTimeoutError):
                engine.ocr_page(FAKE_BASE64_IMAGE, page_num=7)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None  # logger.exception() attaches traceback

    log_text = caplog.text
    # Safe diagnostic fields must be present.
    assert "'page_num': 7" in log_text
    assert f"'model': '{engine.model}'" in log_text
    assert "'exception_class': 'APITimeoutError'" in log_text
    # Secrets/payloads must never appear anywhere in the emitted log text.
    assert FAKE_API_KEY not in log_text
    assert FAKE_BASE64_IMAGE not in log_text
    assert "Authorization" not in log_text
    assert "Bearer" not in log_text


def test_api_error_is_logged_with_safe_fields_and_no_secrets(caplog):
    from openai import APIError

    engine = QwenVisionOCREngine(api_key=FAKE_API_KEY)
    with patch.object(
        engine.client.chat.completions, "create",
        side_effect=APIError("Internal Server Error", request=None, body=None),
    ):
        with caplog.at_level(logging.ERROR, logger="msb_eb_copilot.src.ingestion.pdf_ocr"):
            with pytest.raises(OCRServiceError):
                engine.ocr_page(FAKE_BASE64_IMAGE, page_num=3)

    log_text = caplog.text
    assert "'exception_class': 'APIError'" in log_text
    assert "'page_num': 3" in log_text
    assert FAKE_API_KEY not in log_text
    assert FAKE_BASE64_IMAGE not in log_text


def test_unexpected_exception_is_logged_with_safe_fields_and_no_secrets(caplog):
    engine = QwenVisionOCREngine(api_key=FAKE_API_KEY)
    boom = RuntimeError(f"socket reset while sending Authorization: Bearer {FAKE_API_KEY}")
    with patch.object(engine.client.chat.completions, "create", side_effect=boom):
        with caplog.at_level(logging.ERROR, logger="msb_eb_copilot.src.ingestion.pdf_ocr"):
            with pytest.raises(OCRServiceError):
                engine.ocr_page(FAKE_BASE64_IMAGE, page_num=9)

    log_text = caplog.text
    assert "'exception_class': 'RuntimeError'" in log_text
    assert "'page_num': 9" in log_text
    # Even though the *cause* of this synthetic exception's own message contains
    # the fake key, the logged message is truncated to _MAX_LOGGED_ERROR_MESSAGE_CHARS
    # and the test still asserts the raw secret never survives into the log output.
    assert FAKE_API_KEY not in log_text
    assert FAKE_BASE64_IMAGE not in log_text


def test_safe_ocr_error_fields_direct_unit_contract():
    """Unit-level contract test for the field-extraction helper itself."""
    exc = RuntimeError("boom")
    fields = _safe_ocr_error_fields(exc, page_num=2, model="qwen/qwen3.6-flash")

    assert fields == {
        "page_num": 2,
        "model": "qwen/qwen3.6-flash",
        "exception_class": "RuntimeError",
        "http_status_code": None,
        "request_id": None,
        "error_code": None,
        "retry_after": None,
        "message": "boom",
    }
    # Exactly the allow-listed keys -- nothing extra (e.g. no 'request', 'body',
    # 'headers', 'api_key') can silently sneak into the log payload.
    assert set(fields.keys()) == {
        "page_num", "model", "exception_class", "http_status_code",
        "request_id", "error_code", "retry_after", "message",
    }


def test_safe_ocr_error_fields_extracts_status_code_request_id_and_retry_after():
    """Simulates a rich openai APIStatusError-style exception (e.g. 429 rate limit)
    carrying a Retry-After header alongside an unrelated, sensitive-looking header,
    and asserts only the allow-listed Retry-After value is ever extracted."""
    fake_response = MagicMock()
    fake_response.status_code = 429
    fake_response.headers = {
        "Retry-After": "12",
        "Authorization": f"Bearer {FAKE_API_KEY}",
        "x-api-key": FAKE_API_KEY,
    }

    class _FakeRateLimitError(Exception):
        status_code = 429
        request_id = "req_abc123"
        code = "rate_limit_exceeded"
        response = fake_response

    exc = _FakeRateLimitError("Rate limit exceeded")
    fields = _safe_ocr_error_fields(exc, page_num=1, model="qwen/qwen3.6-flash")

    assert fields["http_status_code"] == 429
    assert fields["request_id"] == "req_abc123"
    assert fields["error_code"] == "rate_limit_exceeded"
    assert fields["retry_after"] == "12"
    # Only the Retry-After header value is read -- nothing else off the exception's
    # response/headers (Authorization, x-api-key) ever enters the returned dict.
    assert FAKE_API_KEY not in json.dumps(fields, default=str)


def test_safe_ocr_error_fields_truncates_overlong_messages():
    exc = RuntimeError("x" * 5000)
    fields = _safe_ocr_error_fields(exc, page_num=1, model="m")
    assert len(fields["message"]) <= 320
    assert fields["message"].endswith("...(truncated)")


# ==============================================================================
# 2c. GREENNODE 429 RATE-LIMIT RETRY + PROACTIVE RPM PACING
# ==============================================================================
import httpx2
import openai as _openai_pkg


def _make_status_error(exc_cls, status_code: int, message: str, headers: Optional[dict] = None):
    """Builds a real openai SDK exception (e.g. RateLimitError/BadRequestError) with
    a genuine httpx2.Response so .status_code / .response.headers behave exactly
    as they do against the real GreenNode API."""
    req = httpx2.Request("POST", "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1/chat/completions")
    resp = httpx2.Response(status_code, headers=headers or {}, request=req)
    return exc_cls(message, response=resp, body=None)


def _make_success_response(text: str = "OCR'd text"):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    resp.usage = None
    return resp


class _FakeClock:
    """Deterministic monotonic clock + sleep double: sleep() advances the clock by
    exactly the requested amount instead of actually waiting, so tests never sleep
    for real seconds."""

    def __init__(self, start: float = 0.0):
        self.now = start
        self.sleeps: List[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _rl_engine(rate_limiter=None, sleep_fn=None):
    """A QwenVisionOCREngine with the shared process-wide rate limiter bypassed by
    an explicit injected one (or disabled), and a mockable sleep function for the
    429-retry wait -- fully isolated from real time and from other tests."""
    if rate_limiter is None:
        rate_limiter = OCRRateLimiter(rpm_limit=999999, enabled=False)
    return QwenVisionOCREngine(api_key=FAKE_API_KEY, rate_limiter=rate_limiter, sleep_fn=sleep_fn or MagicMock())


# --- A/B/C/D: 429 retry-with-wait behavior -----------------------------------

def test_429_with_retry_after_header_waits_buffered_retry_after_and_succeeds():
    """A. 429 with Retry-After=2 -> waits ~3s (2 + 1s safety buffer) -> retries the
    SAME page -> succeeds."""
    err_429 = _make_status_error(
        _openai_pkg.RateLimitError, 429,
        "model rpm limit exceeded (5/5), resets in 2s",
        headers={"Retry-After": "2"},
    )
    sleep_mock = MagicMock()
    engine = _rl_engine(sleep_fn=sleep_mock)

    with patch.object(
        engine.client.chat.completions, "create",
        side_effect=[err_429, _make_success_response("hello page 1")],
    ) as mock_create:
        result = engine.ocr_page(FAKE_BASE64_IMAGE, page_num=1)

    assert result == "hello page 1"
    assert mock_create.call_count == 2  # same page retried, not restarted document
    sleep_mock.assert_called_once()
    (waited,), _ = sleep_mock.call_args
    assert waited == pytest.approx(3.0)  # 2 + 1s safety buffer


def test_429_with_resets_in_message_only_parses_and_waits_buffered_and_succeeds():
    """B. 429 with no Retry-After but message 'resets in 29s' -> parses 29 -> waits
    30s (29 + 1s buffer) -> retries successfully."""
    err_429 = _make_status_error(
        _openai_pkg.RateLimitError, 429,
        "model rpm limit exceeded (5/5), resets in 29s",
        headers={},  # no Retry-After header
    )
    sleep_mock = MagicMock()
    engine = _rl_engine(sleep_fn=sleep_mock)

    with patch.object(
        engine.client.chat.completions, "create",
        side_effect=[err_429, _make_success_response("hello page 2")],
    ) as mock_create:
        result = engine.ocr_page(FAKE_BASE64_IMAGE, page_num=2)

    assert result == "hello page 2"
    assert mock_create.call_count == 2
    sleep_mock.assert_called_once()
    (waited,), _ = sleep_mock.call_args
    assert waited == pytest.approx(30.0)


def test_429_retry_after_header_takes_priority_over_resets_in_message():
    """C. When BOTH a Retry-After header and a 'resets in Ns' message are present,
    the header wins (2 + 1 = 3s), not the message's 29s."""
    err_429 = _make_status_error(
        _openai_pkg.RateLimitError, 429,
        "model rpm limit exceeded (5/5), resets in 29s",
        headers={"Retry-After": "2"},
    )
    sleep_mock = MagicMock()
    engine = _rl_engine(sleep_fn=sleep_mock)

    with patch.object(
        engine.client.chat.completions, "create",
        side_effect=[err_429, _make_success_response("ok")],
    ):
        engine.ocr_page(FAKE_BASE64_IMAGE, page_num=3)

    (waited,), _ = sleep_mock.call_args
    assert waited == pytest.approx(3.0)


def test_429_exhausts_all_4_attempts_then_raises_ocr_service_error():
    """D. All 4 attempts hit 429 -> OCRServiceError raised, exception chain preserved,
    and exactly 4 calls were made to the underlying API (same page, never restarted)."""
    err_429 = _make_status_error(
        _openai_pkg.RateLimitError, 429,
        "model rpm limit exceeded (5/5), resets in 1s",
        headers={"Retry-After": "1"},
    )
    sleep_mock = MagicMock()
    engine = _rl_engine(sleep_fn=sleep_mock)

    with patch.object(
        engine.client.chat.completions, "create", side_effect=[err_429, err_429, err_429, err_429],
    ) as mock_create:
        with pytest.raises(OCRServiceError) as exc_info:
            engine.ocr_page(FAKE_BASE64_IMAGE, page_num=4)

    assert mock_create.call_count == 4
    assert exc_info.value.__cause__ is err_429
    # Only 3 waits happen (before attempts 2, 3, 4); the 4th failure raises instead
    # of waiting/retrying again.
    assert sleep_mock.call_count == 3


# --- E/F/G: non-retryable HTTP statuses --------------------------------------

@pytest.mark.parametrize(
    "exc_cls,status_code",
    [
        (_openai_pkg.BadRequestError, 400),
        (_openai_pkg.AuthenticationError, 401),
        (_openai_pkg.PermissionDeniedError, 403),
    ],
)
def test_non_429_client_errors_are_never_retried(exc_cls, status_code):
    """E/F/G. HTTP 400/401/403 must never be retried -- exactly one call, immediate
    OCRServiceError."""
    err = _make_status_error(exc_cls, status_code, f"error {status_code}")
    sleep_mock = MagicMock()
    engine = _rl_engine(sleep_fn=sleep_mock)

    with patch.object(engine.client.chat.completions, "create", side_effect=err) as mock_create:
        with pytest.raises(OCRServiceError):
            engine.ocr_page(FAKE_BASE64_IMAGE, page_num=5)

    assert mock_create.call_count == 1
    sleep_mock.assert_not_called()


# --- K: no secret leakage during rate-limit retries/exhaustion ---------------

def test_rate_limit_retry_logging_never_leaks_secrets(caplog):
    err_429 = _make_status_error(
        _openai_pkg.RateLimitError, 429,
        f"model rpm limit exceeded (5/5), resets in 2s -- key={FAKE_API_KEY}",
        headers={"Retry-After": "2"},
    )
    sleep_mock = MagicMock()
    engine = _rl_engine(sleep_fn=sleep_mock)

    with patch.object(
        engine.client.chat.completions, "create",
        side_effect=[err_429, _make_success_response("ok")],
    ):
        with caplog.at_level(logging.WARNING, logger="msb_eb_copilot.src.ingestion.pdf_ocr"):
            engine.ocr_page(FAKE_BASE64_IMAGE, page_num=6)

    log_text = caplog.text
    assert "OCR rate limited page=6" in log_text
    assert "wait_seconds=3" in log_text
    assert "source=retry_after" in log_text
    assert FAKE_API_KEY not in log_text
    assert FAKE_BASE64_IMAGE not in log_text


def test_rate_limit_exhaustion_logging_never_leaks_secrets(caplog):
    err_429 = _make_status_error(
        _openai_pkg.RateLimitError, 429,
        f"model rpm limit exceeded (5/5), resets in 1s -- key={FAKE_API_KEY}",
        headers={"Retry-After": "1"},
    )
    sleep_mock = MagicMock()
    engine = _rl_engine(sleep_fn=sleep_mock)

    with patch.object(engine.client.chat.completions, "create", side_effect=[err_429] * 4):
        with caplog.at_level(logging.ERROR, logger="msb_eb_copilot.src.ingestion.pdf_ocr"):
            with pytest.raises(OCRServiceError):
                engine.ocr_page(FAKE_BASE64_IMAGE, page_num=7)

    log_text = caplog.text
    assert FAKE_API_KEY not in log_text
    assert FAKE_BASE64_IMAGE not in log_text
    assert "Authorization" not in log_text


# --- H/I/J: proactive RPM limiter --------------------------------------------

def test_proactive_limiter_allows_up_to_rpm_limit_without_waiting():
    """H (part 1). The first `rpm_limit` acquisitions never sleep."""
    clock = _FakeClock()
    limiter = OCRRateLimiter(rpm_limit=5, enabled=True, clock=clock.time, sleep_fn=clock.sleep)
    for _ in range(5):
        limiter.acquire()
    assert clock.sleeps == []


def test_proactive_limiter_blocks_the_6th_call_within_the_window():
    """H (part 2). The 6th call within the same 60s window must wait for the
    oldest call to age out -- it must never be allowed to exceed rpm_limit."""
    clock = _FakeClock()
    limiter = OCRRateLimiter(rpm_limit=5, enabled=True, window_seconds=60.0, clock=clock.time, sleep_fn=clock.sleep)
    for _ in range(5):
        limiter.acquire()
    assert clock.now == 0.0

    limiter.acquire()
    assert clock.sleeps == [60.0]  # waited for the full window since no time had passed
    assert clock.now == 60.0


def test_proactive_limiter_disabled_never_waits():
    clock = _FakeClock()
    limiter = OCRRateLimiter(rpm_limit=1, enabled=False, clock=clock.time, sleep_fn=clock.sleep)
    for _ in range(10):
        limiter.acquire()
    assert clock.sleeps == []


def test_proactive_limiter_shared_across_concurrent_threads():
    """I. Multiple concurrent worker threads sharing ONE limiter instance must
    collectively respect the RPM budget -- not each get their own independent window.
    Uses a small REAL window (well under a second) so this stays fast without
    needing to fake time across real OS threads."""
    import threading as _threading
    import time as _time

    limiter = OCRRateLimiter(rpm_limit=2, enabled=True, window_seconds=0.25)
    call_times = []
    call_times_lock = _threading.Lock()

    def worker():
        limiter.acquire()
        with call_times_lock:
            call_times.append(_time.monotonic())

    threads = [_threading.Thread(target=worker) for _ in range(4)]
    start = _time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    elapsed = _time.monotonic() - start

    assert len(call_times) == 4
    # 4 calls against an rpm_limit of 2 forces at least one real wait for the
    # window to roll over -- proving the threads shared one window, not four
    # independent ones (which would never have needed to wait at all).
    assert elapsed >= 0.2


def test_proactive_limiter_shared_regardless_of_worker_count_via_engine():
    """J. OCR_MAX_WORKERS > 1 (simulated here via a real ThreadPoolExecutor calling
    engine.ocr_page from multiple threads) must not create independent rate-limit
    windows -- all worker threads share the ONE limiter instance passed to the
    single shared engine, exactly like PDFOCRIngestor.ocr_pages_parallel does."""
    import concurrent.futures
    import time as _time

    limiter = OCRRateLimiter(rpm_limit=2, enabled=True, window_seconds=0.25)
    engine = QwenVisionOCREngine(api_key=FAKE_API_KEY, rate_limiter=limiter)

    with patch.object(engine.client.chat.completions, "create", return_value=_make_success_response("ok")):
        start = _time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(engine.ocr_page, FAKE_BASE64_IMAGE, page_num=p) for p in range(1, 5)]
            results = [f.result(timeout=5) for f in futures]
        elapsed = _time.monotonic() - start

    assert results == ["ok", "ok", "ok", "ok"]
    assert elapsed >= 0.2


# --- Environment variable defaults/overrides ---------------------------------

def test_ocr_rpm_limit_env_defaults_to_5(monkeypatch):
    monkeypatch.delenv("OCR_RPM_LIMIT", raising=False)
    assert _ocr_rpm_limit_from_env() == 5
    assert DEFAULT_OCR_RPM_LIMIT == 5


def test_ocr_rpm_limit_env_override(monkeypatch):
    monkeypatch.setenv("OCR_RPM_LIMIT", "12")
    assert _ocr_rpm_limit_from_env() == 12


def test_ocr_rpm_limit_env_invalid_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("OCR_RPM_LIMIT", "not-a-number")
    assert _ocr_rpm_limit_from_env() == 5


def test_ocr_rate_limit_enabled_env_defaults_to_true(monkeypatch):
    monkeypatch.delenv("OCR_RATE_LIMIT_ENABLED", raising=False)
    assert _ocr_rate_limit_enabled_from_env() is True


def test_ocr_rate_limit_enabled_env_can_be_disabled(monkeypatch):
    monkeypatch.setenv("OCR_RATE_LIMIT_ENABLED", "false")
    assert _ocr_rate_limit_enabled_from_env() is False


def test_engine_uses_shared_limiter_configured_from_env_by_default(monkeypatch):
    """Confirms a freshly-constructed engine, with no explicit rate_limiter=
    override, picks up OCR_RATE_LIMIT_ENABLED/OCR_RPM_LIMIT via the shared
    singleton -- without ever actually calling ocr_page (so no real waiting)."""
    monkeypatch.setenv("OCR_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("OCR_RPM_LIMIT", "7")
    reset_shared_ocr_rate_limiter_for_tests()
    try:
        engine = QwenVisionOCREngine(api_key=FAKE_API_KEY)
        assert engine.rate_limiter is get_shared_ocr_rate_limiter()
        assert engine.rate_limiter.enabled is True
        assert engine.rate_limiter.rpm_limit == 7
    finally:
        reset_shared_ocr_rate_limiter_for_tests()


# --- L: existing successful-request behavior is unchanged --------------------

def test_successful_ocr_request_behavior_unchanged_with_rate_limiting_active():
    """L. A normal successful call still returns the OCR text unchanged, still
    calls the API exactly once, with the (disabled-by-default-in-tests) rate
    limiter integrated but not altering the golden path."""
    engine = _rl_engine()
    with patch.object(
        engine.client.chat.completions, "create",
        return_value=_make_success_response("normal OCR text"),
    ) as mock_create:
        result = engine.ocr_page(FAKE_BASE64_IMAGE, page_num=1)

    assert result == "normal OCR text"
    assert mock_create.call_count == 1


def test_compute_rate_limit_wait_seconds_priority_and_fallback():
    """Direct unit contract for the wait-time priority order and the fallback
    exponential backoff when neither Retry-After nor a parsable message exists."""
    err_with_header = _make_status_error(
        _openai_pkg.RateLimitError, 429, "resets in 29s", headers={"Retry-After": "5"}
    )
    wait, source = _compute_rate_limit_wait_seconds(err_with_header, attempt=1)
    assert (wait, source) == (6.0, "retry_after")

    err_message_only = _make_status_error(_openai_pkg.RateLimitError, 429, "resets in 10s", headers={})
    wait, source = _compute_rate_limit_wait_seconds(err_message_only, attempt=1)
    assert (wait, source) == (11.0, "response_message")

    err_no_hint = _make_status_error(_openai_pkg.RateLimitError, 429, "rate limited", headers={})
    wait, source = _compute_rate_limit_wait_seconds(err_no_hint, attempt=1)
    assert source == "fallback_backoff"
    assert wait == pytest.approx(2.0)
    wait2, _ = _compute_rate_limit_wait_seconds(err_no_hint, attempt=2)
    assert wait2 == pytest.approx(4.0)
    wait3, _ = _compute_rate_limit_wait_seconds(err_no_hint, attempt=3)
    assert wait3 == pytest.approx(8.0)


# ==============================================================================
# 2d. OCR CONTENT-EMPTY RETRY (page-level, separate from the 429 retry above)
# ==============================================================================
class SequentialMockOCREngine(BaseOCREngine):
    """Returns a pre-scripted sequence of raw OCR results per page_num, one per
    call, so tests can simulate 'first attempt garbage, later attempt good text'
    without any real network or rate-limit machinery. Raises loudly if called
    more times than the test scripted -- this is what would catch an accidental
    uncontrolled/unbounded retry loop."""

    provider_name = "mock_engine"
    model = "mock-vision-model"

    def __init__(self, sequences: Dict[int, List[Optional[str]]] = None):
        self.sequences = {k: list(v) for k, v in (sequences or {}).items()}
        self.call_log: List[int] = []

    def ocr_page(self, base64_png: str, page_num: int) -> str:
        self.call_log.append(page_num)
        queue = self.sequences.get(page_num)
        if queue is None:
            return f"Nội dung văn bản trang {page_num} với số liệu 2024"
        if not queue:
            raise AssertionError(
                f"ocr_page(page_num={page_num}) called more times than the test "
                f"scripted responses for -- possible unbounded retry loop"
            )
        return queue.pop(0)


def test_content_retry_first_empty_then_valid_succeeds():
    """A. First OCR result empty string, second call returns valid text -> succeeds,
    same page retried (not the whole PDF), exactly 2 engine calls."""
    engine = SequentialMockOCREngine({1: ["", "Nội dung hợp lệ trang 1 với số liệu 12345"]})
    result = PDFOCRIngestor.ocr_single_page(doc_or_path=SCANNED_FIXTURE_PDF, page_num=1, engine=engine)
    assert result.text == "Nội dung hợp lệ trang 1 với số liệu 12345"
    assert engine.call_log == [1, 1]


def test_content_retry_none_then_valid_succeeds():
    """B. First OCR result None, second call returns valid text -> succeeds."""
    engine = SequentialMockOCREngine({1: [None, "Nội dung hợp lệ số 2 với ký tự 999"]})
    result = PDFOCRIngestor.ocr_single_page(doc_or_path=SCANNED_FIXTURE_PDF, page_num=1, engine=engine)
    assert result.text == "Nội dung hợp lệ số 2 với ký tự 999"
    assert engine.call_log == [1, 1]


def test_content_retry_punctuation_only_then_valid_succeeds():
    """C. First OCR result punctuation-only (no alnum), second call valid -> succeeds."""
    engine = SequentialMockOCREngine({1: ["--- === *** !!!", "Nội dung hợp lệ số 3 (ABC123)"]})
    result = PDFOCRIngestor.ocr_single_page(doc_or_path=SCANNED_FIXTURE_PDF, page_num=1, engine=engine)
    assert result.text == "Nội dung hợp lệ số 3 (ABC123)"
    assert engine.call_log == [1, 1]


def test_content_retry_three_consecutive_empty_raises_ocr_no_text_error():
    """D. 3 consecutive empty results -> OCRNoTextError, exactly 3 attempts (bounded,
    not more)."""
    engine = SequentialMockOCREngine({1: ["", "", ""]})
    with pytest.raises(OCRNoTextError, match="có nội dung OCR hoàn toàn rỗng"):
        PDFOCRIngestor.ocr_single_page(doc_or_path=SCANNED_FIXTURE_PDF, page_num=1, engine=engine)
    assert engine.call_log == [1, 1, 1]


def test_content_retry_three_consecutive_none_raises_ocr_no_text_error():
    engine = SequentialMockOCREngine({1: [None, None, None]})
    with pytest.raises(OCRNoTextError, match="không nhận được kết quả OCR"):
        PDFOCRIngestor.ocr_single_page(doc_or_path=SCANNED_FIXTURE_PDF, page_num=1, engine=engine)
    assert engine.call_log == [1, 1, 1]


def test_content_retry_three_consecutive_non_alnum_raises_ocr_no_text_error():
    engine = SequentialMockOCREngine({1: ["---", "***", "==="]})
    with pytest.raises(OCRNoTextError, match="không chứa bất kỳ ký tự chữ hoặc số"):
        PDFOCRIngestor.ocr_single_page(doc_or_path=SCANNED_FIXTURE_PDF, page_num=1, engine=engine)
    assert engine.call_log == [1, 1, 1]


def test_content_retry_logs_warning_on_each_retry_but_not_on_final_exhaustion(caplog):
    engine = SequentialMockOCREngine({1: ["", "", ""]})
    with caplog.at_level(logging.WARNING, logger="msb_eb_copilot.src.ingestion.pdf_ocr"):
        with pytest.raises(OCRNoTextError):
            PDFOCRIngestor.ocr_single_page(doc_or_path=SCANNED_FIXTURE_PDF, page_num=1, engine=engine)

    warning_lines = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_lines) == 2  # only before attempts 2 and 3 -- not after the 3rd (final) failure
    for rec in warning_lines:
        msg = rec.getMessage()
        assert "OCR returned empty content page=1" in msg
        assert "model=mock-vision-model" in msg
        assert "retrying same page" in msg
    assert "attempt=1/3" in warning_lines[0].getMessage()
    assert "attempt=2/3" in warning_lines[1].getMessage()


def test_no_page_skipping_on_content_exhaustion_multi_page_document():
    """G. A page that never produces valid text after all retries must fail the
    whole extraction loudly -- it must never be silently skipped/omitted so the
    document ends up with fewer pages than it physically has."""
    engine = SequentialMockOCREngine({1: ["", "", ""]})  # page 2 uses the default valid fallback
    with pytest.raises(OCRNoTextError):
        PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine, max_workers=1)
    # Page 1 was retried the full bounded amount -- not given up on after 1 try,
    # and not silently replaced with empty/placeholder text.
    assert engine.call_log.count(1) == 3


def test_content_retry_respects_shared_rate_limiter():
    """E. Every content-retry attempt is a full ocr_page() call, so each one must
    still go through the engine's proactive rate limiter exactly once per attempt."""
    mock_limiter = MagicMock()
    mock_limiter.enabled = True
    engine = QwenVisionOCREngine(api_key=FAKE_API_KEY, rate_limiter=mock_limiter, sleep_fn=MagicMock())

    with patch.object(
        engine.client.chat.completions, "create",
        side_effect=[_make_success_response(""), _make_success_response("Nội dung hợp lệ 123")],
    ) as mock_create:
        result = PDFOCRIngestor.ocr_single_page(doc_or_path=SCANNED_FIXTURE_PDF, page_num=1, engine=engine)

    assert result.text == "Nội dung hợp lệ 123"
    assert mock_create.call_count == 2
    assert mock_limiter.acquire.call_count == 2  # once per content attempt


def test_content_retry_combined_with_429_retry_stays_bounded():
    """F. Content retry (max 3) composes with the independent 429 retry (max 4 per
    call) without creating an uncontrolled 4x3 explosion: content-attempt 1 needs
    one internal 429 retry (2 raw API calls) and still comes back empty; content-attempt
    2 succeeds immediately (1 raw API call). Total raw API calls = 3, well under the
    3 x 4 = 12 documented worst-case ceiling."""
    err_429 = _make_status_error(
        _openai_pkg.RateLimitError, 429, "model rpm limit exceeded (5/5), resets in 1s",
        headers={"Retry-After": "1"},
    )
    sleep_mock = MagicMock()
    engine = QwenVisionOCREngine(
        api_key=FAKE_API_KEY,
        rate_limiter=OCRRateLimiter(rpm_limit=999999, enabled=False),
        sleep_fn=sleep_mock,
    )

    with patch.object(
        engine.client.chat.completions, "create",
        side_effect=[
            err_429,                                  # content-attempt 1, API try 1: 429
            _make_success_response(""),                # content-attempt 1, API try 2: empty text
            _make_success_response("Nội dung hợp lệ cuối cùng"),  # content-attempt 2: valid
        ],
    ) as mock_create:
        result = PDFOCRIngestor.ocr_single_page(doc_or_path=SCANNED_FIXTURE_PDF, page_num=1, engine=engine)

    assert result.text == "Nội dung hợp lệ cuối cùng"
    assert mock_create.call_count == 3
    assert sleep_mock.call_count == 1  # exactly one 429 wait, from content-attempt 1


def test_content_retry_logging_never_leaks_secrets_base64_or_document_content(caplog):
    """H. The content-retry warning log line only ever contains page_num/model/attempt
    -- never the base64 image, never OCR'd document content, never any secret."""
    class LeakyEngine(BaseOCREngine):
        provider_name = "mock_engine"
        model = "qwen/qwen3.6-flash"

        def __init__(self):
            self.calls = 0
            self.last_base64_seen: Optional[str] = None

        def ocr_page(self, base64_png: str, page_num: int) -> str:
            self.last_base64_seen = base64_png
            self.calls += 1
            if self.calls == 1:
                return ""  # invalid -- triggers the retry-warning log path
            # Deliberately contrived: even if actual OCR'd content contained
            # something secret-looking, our log format never includes content.
            return f"Văn bản tài liệu hợp lệ, số liệu tài chính, key={FAKE_API_KEY}"

    engine = LeakyEngine()
    with caplog.at_level(logging.WARNING, logger="msb_eb_copilot.src.ingestion.pdf_ocr"):
        result = PDFOCRIngestor.ocr_single_page(doc_or_path=SCANNED_FIXTURE_PDF, page_num=1, engine=engine)

    assert FAKE_API_KEY in result.text  # sanity: the contrived secret IS in the OCR'd text/output itself
    assert engine.last_base64_seen  # the real rasterized image was passed through as usual

    log_text = caplog.text
    assert "OCR returned empty content page=1" in log_text
    assert FAKE_API_KEY not in log_text
    assert engine.last_base64_seen not in log_text
    assert "Authorization" not in log_text
    assert "Văn bản tài liệu hợp lệ" not in log_text


def test_classify_ocr_text_direct_unit_contract():
    assert _classify_ocr_text(None) == (False, None, "none")
    assert _classify_ocr_text("   \n\t  ") == (False, "", "empty")
    assert _classify_ocr_text("--- === ***") == (False, "--- === ***", "non_alnum")
    is_valid, norm, kind = _classify_ocr_text("Có số 123")
    assert is_valid is True
    assert norm == "Có số 123"
    assert kind is None


def test_ocr_max_content_attempts_is_3():
    assert OCR_MAX_CONTENT_ATTEMPTS == 3


# ==============================================================================
# 3. PAGE COUNT INVARIANT & FORMAT CONTRACT TESTS
# ==============================================================================
def test_ocr_page_count_invariant_and_formatting():
    """N trang nguồn -> Đúng N khối [PAGE X], N kết quả OCRPageResult."""
    engine = MockOCREngine(responses={
        1: "Văn bản nhận dạng trang 1\nMã số: 0312456789",
        2: "Văn bản nhận dạng trang 2\nVốn điều lệ: 85 tỷ"
    })
    doc_result = PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)

    assert isinstance(doc_result, OCRDocumentResult)
    assert doc_result.page_count == 2
    assert len(doc_result.pages) == 2
    assert doc_result.pages[0].page_num == 1
    assert doc_result.pages[1].page_num == 2

    tagged = doc_result.tagged_text
    assert tagged.startswith("[PAGE 1]\n")
    assert "\n\n[PAGE 2]\n" in tagged
    assert "[PAGE 3]" not in tagged

    # Đảm bảo engine được gọi đúng 2 lần tuần tự
    assert engine.call_count == 2


def test_crlf_normalization_and_whitespace_trimming():
    """Kiểm tra CRLF/CR được chuẩn hóa thành LF và khoảng trắng thừa ngoài biên được cắt bỏ."""
    engine = MockOCREngine(responses={
        1: "\r\n  Dòng 1 trang 1\r\nDòng 2 trang 1\r\n  ",
        2: "\n\n\nDòng 1 trang 2\nDòng 2 trang 2\n\n\n"
    })
    tagged = PDFOCRIngestor.extract_text_with_page_markers(SCANNED_FIXTURE_PDF, engine=engine)

    # Không còn \r trong output
    assert "\r" not in tagged

    # Khối thẻ trang định dạng chuẩn xác
    expected = (
        "[PAGE 1]\nDòng 1 trang 1\nDòng 2 trang 1\n\n"
        "[PAGE 2]\nDòng 1 trang 2\nDòng 2 trang 2"
    )
    assert tagged == expected


# ==============================================================================
# 4. INTEGRATION TEST: SCANNED PDF -> PDFOCRIngestor -> Locked LegalDocumentExtractor
# ==============================================================================
def test_scanned_pdf_ingestion_end_to_end_with_legal_extractor():
    """Kiểm thử tích hợp trọn vẹn:
    1. Đọc tệp PDF quét mẫu scanned_legal_fixture.pdf bằng PDFOCRIngestor
    2. Rasterize bằng PDFium thật
    3. Mock Qwen OCR engine trả về đúng văn bản chứa nhãn và thông tin pháp lý của fixture
    4. Sinh ra chuỗi tagged_text thực tế (KHÔNG qua chỉnh sửa/bổ sung nhân tạo)
    5. Khẳng định MỌI chuỗi evidence trong mock LLM extraction đều có mặt trong tagged_text
    6. Truyền trực tiếp tagged_text vào LegalDocumentExtractor đã khóa
    7. Khẳng định trích xuất thành công, vượt qua toàn bộ audits và chuẩn hóa danh xưng.
    """
    assert os.path.exists(SCANNED_FIXTURE_PDF)

    # Mock văn bản OCR cho từng trang vật lý khớp với nội dung đã vẽ trong scanned_legal_fixture.pdf
    mock_page_texts = {
        1: (
            "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
            "Độc lập - Tự do - Hạnh phúc\n"
            "GIẤY CHỨNG NHẬN ĐĂNG KÝ DOANH NGHIỆP\n"
            "Tên doanh nghiệp: CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ THƯƠNG MẠI SAO MAI\n"
            "Tên viết tắt: SAO MAI TECH JSC\n"
            "Mã số doanh nghiệp: 0312456789\n"
            "Địa chỉ trụ sở chính: Lô CN-08, Khu Công nghiệp Tân Bình, Phường Tây Thạnh, Quận Tân Phú, Thành phố Hồ Chí Minh, Việt Nam"
        ),
        2: (
            "THÔNG TIN VỐN VÀ ĐẠI DIỆN PHÁP LUẬT\n"
            "Vốn điều lệ: 85.000.000.000 đồng\n"
            "Họ và tên: Ông Đặng Quốc Hưng\n"
            "Chức danh: Tổng Giám đốc"
        )
    }
    engine = MockOCREngine(responses=mock_page_texts)

    # Bước 1 & 2: Thực thi PDFOCRIngestor thật trên scanned_legal_fixture.pdf
    tagged_text = PDFOCRIngestor.extract_text_with_page_markers(SCANNED_FIXTURE_PDF, engine=engine)

    # Khẳng định hợp đồng định dạng
    assert tagged_text.startswith("[PAGE 1]\n")
    assert "\n\n[PAGE 2]\n" in tagged_text

    # Mock kết quả LLM extraction của LegalDocumentExtractor
    mock_llm_json = {
        "company_name": {
            "value": "CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ THƯƠNG MẠI SAO MAI",
            "evidence": "Tên doanh nghiệp: CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ THƯƠNG MẠI SAO MAI",
            "page": 1
        },
        "short_name": {
            "value": "SAO MAI TECH JSC",
            "evidence": "Tên viết tắt: SAO MAI TECH JSC",
            "page": 1
        },
        "tax_code": {
            "value": "0312456789",
            "evidence": "Mã số doanh nghiệp: 0312456789",
            "page": 1
        },
        "address": {
            "value": "Lô CN-08, Khu Công nghiệp Tân Bình, Phường Tây Thạnh, Quận Tân Phú, Thành phố Hồ Chí Minh, Việt Nam",
            "evidence": "Địa chỉ trụ sở chính: Lô CN-08, Khu Công nghiệp Tân Bình, Phường Tây Thạnh, Quận Tân Phú, Thành phố Hồ Chí Minh, Việt Nam",
            "page": 1
        },
        "charter_capital_raw": {
            "value": "85.000.000.000 đồng",
            "evidence": "Vốn điều lệ: 85.000.000.000 đồng",
            "page": 2
        },
        "legal_rep_name": {
            "value": "Ông Đặng Quốc Hưng",
            "evidence": "Họ và tên: Ông Đặng Quốc Hưng",
            "page": 2
        },
        "legal_rep_title": {
            "value": "Tổng Giám đốc",
            "evidence": "Chức danh: Tổng Giám đốc",
            "page": 2
        }
    }

    # Bước 3: Khẳng định nghiêm ngặt trước khi gọi extractor:
    # Mọi chuỗi evidence không null đều phải tồn tại nguyên vẹn trong tagged_text thực tế
    for field_name, field_data in mock_llm_json.items():
        evi = field_data["evidence"]
        if evi is not None:
            assert evi in tagged_text, f"Evidence for {field_name} not found in tagged_text: '{evi}'"

    # Bước 4: Chạy trích xuất thực tế: tagged_text từ PDFOCRIngestor được truyền trực tiếp không chỉnh sửa
    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(mock_llm_json)):
        result = LegalDocumentExtractor.extract(tagged_text)

        assert isinstance(result, LegalDocumentExtraction)
        assert result.company_name.value == "CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ THƯƠNG MẠI SAO MAI"
        assert result.short_name.value == "SAO MAI TECH JSC"
        assert result.tax_code.value == "0312456789"
        assert result.address.value == "Lô CN-08, Khu Công nghiệp Tân Bình, Phường Tây Thạnh, Quận Tân Phú, Thành phố Hồ Chí Minh, Việt Nam"
        assert result.charter_capital_raw.value == "85.000.000.000 đồng"

        # Khẳng định chuẩn hóa danh xưng hoạt động chính xác ("Ông Đặng Quốc Hưng" -> "Đặng Quốc Hưng")
        assert result.legal_rep_name.value == "Đặng Quốc Hưng"
        assert result.legal_rep_name.evidence == "Họ và tên: Ông Đặng Quốc Hưng"
        assert result.legal_rep_title.value == "Tổng Giám đốc"
