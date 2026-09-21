# -*- coding: utf-8 -*-
"""Unit tests for Patch 1.5C: Chunked Financial Extraction.

Validates:
1. PAGE PARSER
2. CHUNKING
3. CHUNK PROMPT PROVENANCE
4. SUCCESSFUL MULTI-CHUNK EXTRACTION
5. SAME PERIOD FIELD-BY-FIELD MERGE
6. IDENTICAL DUPLICATE FACT
7. CONFLICTING DUPLICATE FACT
8. MALFORMED JSON IN ONE CHUNK
9. PAGE RANGE INCLUDED IN FAILURE
10. GROUNDING PAGE NUMBERS
11. DOCUMENT UNIT / PAGE UNIT MERGE
12. CONFIGURATION & CONCURRENCY
13. BACKWARD COMPATIBILITY
"""

import os
import json
import time
import threading
from typing import Any, Dict, List, Optional
from unittest.mock import patch
import pytest

from msb_eb_copilot.src.extraction.financial_extraction import (
    FinancialDocumentExtraction,
    FinancialDocumentExtractor,
    FinancialEvidenceField,
    FinancialGroundingAuditor,
    FinancialPeriodExtraction,
    FinancialUnitInfo,
    FinancialPageMarkerError,
    FinancialChunkExtractionError,
    FinancialMergeConflictError,
    parse_tagged_pages,
    chunk_pages,
    merge_financial_extractions,
    get_financial_pages_per_chunk,
    get_financial_extraction_max_workers,
    DEFAULT_FINANCIAL_PAGES_PER_CHUNK,
    MAX_FINANCIAL_PAGES_PER_CHUNK,
    DEFAULT_FINANCIAL_EXTRACTION_MAX_WORKERS,
    MAX_FINANCIAL_EXTRACTION_MAX_WORKERS,
    FINANCIAL_SOURCE_FACT_FIELDS,
    normalize_financial_extraction_raw_dict,
    is_note_disclosure_cogs,
    get_financial_ocr_max_failed_pages,
    DEFAULT_FINANCIAL_OCR_MAX_FAILED_PAGES,
)
from msb_eb_copilot.src.ingestion.pdf_ocr import OCR_UNREADABLE_PAGE_MARKER


class MockAIClient:
    def __init__(
        self,
        chunk_responses: Optional[Dict[str, Any]] = None,
        default_response: Optional[str] = None,
        delay: float = 0.0,
        delays: Optional[Dict[str, float]] = None,
    ):
        self.chunk_responses = chunk_responses or {}
        self.default_response = default_response or "{}"
        self.delay = delay
        self.delays = delays or {}
        self.recorded_calls: List[Dict[str, Any]] = []
        self.active_calls = 0
        self.max_active_calls = 0
        self._lock = threading.Lock()

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        api_key: Optional[str] = None,
        operation: str = "chat",
    ) -> str:
        with self._lock:
            self.active_calls += 1
            if self.active_calls > self.max_active_calls:
                self.max_active_calls = self.active_calls
            self.recorded_calls.append({
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "operation": operation,
            })

        specific_delay = self.delays.get(operation, self.delay)
        if specific_delay > 0:
            time.sleep(specific_delay)

        try:
            resp = self.chunk_responses.get(operation, self.default_response)
            if isinstance(resp, Exception):
                raise resp
            return resp
        finally:
            with self._lock:
                self.active_calls -= 1


def build_tagged_text(num_pages: int, content_fn=None) -> str:
    blocks = []
    for idx in range(1, num_pages + 1):
        content = content_fn(idx) if content_fn else f"Nội dung văn bản trang {idx}"
        blocks.append(f"[PAGE {idx}]\n{content}")
    return "\n\n".join(blocks)


def test_page_parser_preserves_numbering():
    tagged = build_tagged_text(12)
    pages = parse_tagged_pages(tagged)
    assert len(pages) == 12
    for idx, (p_num, content) in enumerate(pages, start=1):
        assert p_num == idx
        assert f"Nội dung văn bản trang {idx}" in content


def test_page_parser_preamble_non_whitespace_fails():
    tagged = "Văn bản rác trước thẻ\n[PAGE 1]\nNội dung"
    with pytest.raises(FinancialPageMarkerError, match="không phải khoảng trắng"):
        parse_tagged_pages(tagged)


def test_page_parser_duplicate_page_marker_fails():
    tagged = "[PAGE 1]\nNội dung 1\n\n[PAGE 2]\nNội dung 2\n\n[PAGE 1]\nTrùng lặp trang 1"
    with pytest.raises(FinancialPageMarkerError, match="Phát hiện trùng lặp"):
        parse_tagged_pages(tagged)


def test_page_parser_non_positive_page_number_fails():
    tagged = "[PAGE 0]\nNội dung"
    with pytest.raises(FinancialPageMarkerError, match="phải > 0"):
        parse_tagged_pages(tagged)

    tagged_neg = "[PAGE -2]\nNội dung"
    with pytest.raises(FinancialPageMarkerError, match="phải > 0"):
        parse_tagged_pages(tagged_neg)


def test_page_parser_missing_page_marker_fails():
    tagged = "Toàn bộ tài liệu không có bất kỳ thẻ trang nào."
    with pytest.raises(FinancialPageMarkerError, match="không chứa bất kỳ thẻ trang"):
        parse_tagged_pages(tagged)


def test_chunking_twelve_pages_chunk_size_five():
    tagged = build_tagged_text(12)
    pages = parse_tagged_pages(tagged)
    chunks = chunk_pages(pages, pages_per_chunk=5)

    assert len(chunks) == 3
    assert chunks[0].chunk_index == 1
    assert chunks[0].start_page == 1
    assert chunks[0].end_page == 5
    assert chunks[0].page_nums == [1, 2, 3, 4, 5]

    assert chunks[1].chunk_index == 2
    assert chunks[1].start_page == 6
    assert chunks[1].end_page == 10
    assert chunks[1].page_nums == [6, 7, 8, 9, 10]

    assert chunks[2].chunk_index == 3
    assert chunks[2].start_page == 11
    assert chunks[2].end_page == 12
    assert chunks[2].page_nums == [11, 12]

    all_pages = [p for c in chunks for p in c.page_nums]
    assert all_pages == list(range(1, 13))


def test_chunking_thirteen_pages_chunk_size_five():
    tagged = build_tagged_text(13)
    pages = parse_tagged_pages(tagged)
    chunks = chunk_pages(pages, pages_per_chunk=5)

    assert len(chunks) == 3
    assert chunks[0].page_nums == [1, 2, 3, 4, 5]
    assert chunks[1].page_nums == [6, 7, 8, 9, 10]
    assert chunks[2].page_nums == [11, 12, 13]


def test_chunking_three_pages_chunk_size_five():
    tagged = build_tagged_text(3)
    pages = parse_tagged_pages(tagged)
    chunks = chunk_pages(pages, pages_per_chunk=5)

    assert len(chunks) == 1
    assert chunks[0].start_page == 1
    assert chunks[0].end_page == 3
    assert chunks[0].page_nums == [1, 2, 3]


def test_chunk_prompt_provenance_preserves_original_page_numbers():
    tagged = build_tagged_text(10)
    mock_client = MockAIClient(default_response=json.dumps({"periods": []}))
    extractor = FinancialDocumentExtractor(ai_client=mock_client, pages_per_chunk=5, max_workers=1)

    extractor.extract(tagged)

    assert len(mock_client.recorded_calls) == 2

    chunk1_call = mock_client.recorded_calls[0]
    assert chunk1_call["operation"] == "financial_extraction_pages_1_5"
    assert "[PAGE 1] đến [PAGE 5]" in chunk1_call["user_prompt"]
    assert "[PAGE 1]" in chunk1_call["user_prompt"]
    assert "[PAGE 5]" in chunk1_call["user_prompt"]
    assert "[PAGE 6]" not in chunk1_call["user_prompt"]

    chunk2_call = mock_client.recorded_calls[1]
    assert chunk2_call["operation"] == "financial_extraction_pages_6_10"
    assert "[PAGE 6] đến [PAGE 10]" in chunk2_call["user_prompt"]
    assert "[PAGE 6]" in chunk2_call["user_prompt"]
    assert "[PAGE 10]" in chunk2_call["user_prompt"]
    assert "[PAGE 1]" not in chunk2_call["user_prompt"]
    assert "[PAGE 2]" not in chunk2_call["user_prompt"]


def test_successful_multi_chunk_extraction():
    chunk1_json = json.dumps({
        "document_title": "BÁO CÁO TÀI CHÍNH KIỂM TOÁN 2025",
        "document_unit": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1},
        "page_units": {"1": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1}},
        "periods": [
            {
                "period": "2025",
                "net_revenue": {
                    "value_raw": "120.000.000.000",
                    "semantic_label": "Doanh thu thuần",
                    "accounting_code": "10",
                    "evidence": "Doanh thu thuần 120.000.000.000",
                    "page": 1,
                },
            }
        ]
    })
    chunk2_json = json.dumps({
        "page_units": {"6": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 6}},
        "periods": [
            {
                "period": "2025",
                "current_assets": {
                    "value_raw": "65.000.000.000",
                    "semantic_label": "Tài sản ngắn hạn",
                    "accounting_code": "100",
                    "evidence": "Tài sản ngắn hạn 65.000.000.000",
                    "page": 6,
                },
            }
        ]
    })
    chunk3_json = json.dumps({
        "periods": [
            {
                "period": "2024",
                "net_revenue": {
                    "value_raw": "100.000.000.000",
                    "semantic_label": "Doanh thu thuần",
                    "accounting_code": "10",
                    "evidence": "Doanh thu thuần 100.000.000.000",
                    "page": 11,
                },
            }
        ]
    })

    mock_client = MockAIClient(chunk_responses={
        "financial_extraction_pages_1_5": chunk1_json,
        "financial_extraction_pages_6_10": chunk2_json,
        "financial_extraction_pages_11_12": chunk3_json,
    })

    tagged = build_tagged_text(12)
    extractor = FinancialDocumentExtractor(ai_client=mock_client, pages_per_chunk=5, max_workers=1)
    res = extractor.extract(tagged)

    assert isinstance(res, FinancialDocumentExtraction)
    assert res.document_title == "BÁO CÁO TÀI CHÍNH KIỂM TOÁN 2025"
    assert res.document_unit.unit_raw == "VND"
    assert len(res.page_units) == 2
    assert res.page_units[1].page == 1
    assert res.page_units[6].page == 6

    assert len(res.periods) == 2
    p2025 = next(p for p in res.periods if p.period == "2025")
    assert p2025.net_revenue.value_raw == "120.000.000.000"
    assert p2025.current_assets.value_raw == "65.000.000.000"

    p2024 = next(p for p in res.periods if p.period == "2024")
    assert p2024.net_revenue.value_raw == "100.000.000.000"


def test_same_period_field_by_field_merge():
    ext_a = FinancialDocumentExtraction(
        periods=[
            FinancialPeriodExtraction(
                period="2025",
                net_revenue=FinancialEvidenceField(
                    value_raw="120.000.000.000",
                    semantic_label="Doanh thu thuần",
                    page=1,
                    evidence="Doanh thu thuần 120.000.000.000"
                )
            )
        ]
    )
    ext_b = FinancialDocumentExtraction(
        periods=[
            FinancialPeriodExtraction(
                period="2025",
                equity=FinancialEvidenceField(
                    value_raw="45.000.000.000",
                    semantic_label="Vốn chủ sở hữu",
                    page=2,
                    evidence="Vốn chủ sở hữu 45.000.000.000"
                )
            )
        ]
    )

    merged = merge_financial_extractions([ext_a, ext_b])
    assert len(merged.periods) == 1
    p = merged.periods[0]
    assert p.period == "2025"
    assert p.net_revenue.value_raw == "120.000.000.000"
    assert p.equity.value_raw == "45.000.000.000"


def test_identical_duplicate_fact_coalesces_deterministically():
    field_data = FinancialEvidenceField(
        value_raw="120.000.000.000",
        semantic_label="Doanh thu thuần",
        accounting_code="10",
        unit_raw="VND",
        evidence="Doanh thu thuần 120.000.000.000",
        page=1,
    )
    ext1 = FinancialDocumentExtraction(
        periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_data)]
    )
    ext2 = FinancialDocumentExtraction(
        periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_data)]
    )

    merged = merge_financial_extractions([ext1, ext2])
    assert len(merged.periods) == 1
    assert merged.periods[0].net_revenue.value_raw == "120.000.000.000"
    assert merged.periods[0].net_revenue.page == 1


def test_conflicting_duplicate_fact_raises_explicit_error():
    field_a = FinancialEvidenceField(
        value_raw="120.000.000.000",
        semantic_label="Doanh thu thuần",
        page=1,
        evidence="Doanh thu 120.000.000.000"
    )
    field_b = FinancialEvidenceField(
        value_raw="95.000.000.000",
        semantic_label="Doanh thu thuần",
        page=1,
        evidence="Doanh thu 95.000.000.000"
    )
    ext1 = FinancialDocumentExtraction(
        periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_a)]
    )
    ext2 = FinancialDocumentExtraction(
        periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_b)]
    )

    with pytest.raises(FinancialMergeConflictError, match="Xung đột dữ liệu không thể hợp nhất"):
        merge_financial_extractions([ext1, ext2])


def test_malformed_json_in_one_chunk_fails_entire_extraction_with_page_range():
    valid_json = json.dumps({"periods": [{"period": "2025"}]})
    truncated_json = '{"document_title": "BCTC 2025", "periods": [{"period": "2025", "net_revenue": {"val'

    mock_client = MockAIClient(chunk_responses={
        "financial_extraction_pages_1_5": valid_json,
        "financial_extraction_pages_6_10": valid_json,
        "financial_extraction_pages_11_12": truncated_json,
    })

    tagged = build_tagged_text(12)
    extractor = FinancialDocumentExtractor(ai_client=mock_client, pages_per_chunk=5, max_workers=1)

    with pytest.raises(FinancialChunkExtractionError) as exc_info:
        extractor.extract(tagged)

    err_msg = str(exc_info.value)
    assert "pages 11-12" in err_msg
    assert "invalid JSON" in err_msg


def test_grounding_page_numbers_preserve_physical_pages():
    content_p6 = "BẢNG CÂN ĐỐI KẾ TOÁN\nĐơn vị tính: VND\nVốn chủ sở hữu | 400 | 45.000.000.000"
    tagged = build_tagged_text(10, content_fn=lambda idx: content_p6 if idx == 6 else f"Trang {idx}")

    chunk2_json = json.dumps({
        "periods": [
            {
                "period": "2025",
                "equity": {
                    "value_raw": "45.000.000.000",
                    "semantic_label": "Vốn chủ sở hữu",
                    "accounting_code": "400",
                    "evidence": "Vốn chủ sở hữu | 400 | 45.000.000.000",
                    "page": 6,
                }
            }
        ]
    })

    mock_client = MockAIClient(chunk_responses={
        "financial_extraction_pages_1_5": json.dumps({"periods": []}),
        "financial_extraction_pages_6_10": chunk2_json,
    })

    extractor = FinancialDocumentExtractor(ai_client=mock_client, pages_per_chunk=5, max_workers=1)
    res = extractor.extract(tagged)

    eq_field = res.periods[0].equity
    assert eq_field.page == 6
    assert eq_field.value_raw == "45.000.000.000"

    errs = FinancialGroundingAuditor.audit_field("equity", eq_field, tagged, 10)
    assert errs == []


def test_c_k_ocr_unreadable_page_contributes_no_grounding_evidence():
    """C/K: a page marked with OCR_UNREADABLE_PAGE_MARKER (degraded OCR page)
    contains no usable evidence. Even if a fact hallucinated a citation to that
    page (which the prompt explicitly forbids), FinancialGroundingAuditor still
    fails it closed -- proving no fabricated evidence can ever be accepted for
    a failed page, independent of prompt compliance."""
    tagged = build_tagged_text(3, content_fn=lambda idx: (
        OCR_UNREADABLE_PAGE_MARKER if idx == 2
        else "BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH\nĐơn vị tính: VND\nDoanh thu thuần | 10 | 120.000.000.000"
    ))
    assert f"[PAGE 2]\n{OCR_UNREADABLE_PAGE_MARKER}" in tagged

    hallucinated_field = FinancialEvidenceField(
        value_raw="999.000.000.000",
        semantic_label="Doanh thu thuần",
        accounting_code="10",
        evidence="Doanh thu thuần | 10 | 999.000.000.000",
        page=2,  # the OCR_UNREADABLE page -- this evidence can never actually be there
    )
    errs = FinancialGroundingAuditor.audit_field("net_revenue", hallucinated_field, tagged, 3)
    assert any("Evidence not found on declared Page 2" in e for e in errs)

    # Sanity: a legitimately-grounded fact on the readable page 1 still passes.
    real_field = FinancialEvidenceField(
        value_raw="120.000.000.000",
        semantic_label="Doanh thu thuần",
        accounting_code="10",
        evidence="Doanh thu thuần | 10 | 120.000.000.000",
        page=1,
    )
    assert FinancialGroundingAuditor.audit_field("net_revenue", real_field, tagged, 3) == []


def test_k_ocr_unreadable_marker_never_contains_alphanumeric_evidence_shape():
    """K: sanity check that the marker text itself can never be mistaken for a
    real evidence line (no digits, no accounting separators)."""
    assert OCR_UNREADABLE_PAGE_MARKER == "[OCR_UNREADABLE]"
    assert not any(ch.isdigit() for ch in OCR_UNREADABLE_PAGE_MARKER)


def test_unit_merge_and_conflict_handling():
    u1 = FinancialUnitInfo(unit_raw="VND", evidence="Đơn vị tính: VND", page=1)
    u2 = FinancialUnitInfo(unit_raw="VND", evidence="Đơn vị tính: VND", page=6)
    ext1 = FinancialDocumentExtraction(document_unit=u1)
    ext2 = FinancialDocumentExtraction(document_unit=u2)
    merged = merge_financial_extractions([ext1, ext2])
    assert merged.document_unit.unit_raw == "VND"

    u_diff = FinancialUnitInfo(unit_raw="triệu đồng", evidence="Đơn vị tính: triệu đồng", page=6)
    ext_conflict = FinancialDocumentExtraction(document_unit=u_diff)
    with pytest.raises(FinancialMergeConflictError, match="Xung đột đơn vị tính tài liệu"):
        merge_financial_extractions([ext1, ext_conflict])

    ext_p1 = FinancialDocumentExtraction(page_units={1: u1})
    ext_p2 = FinancialDocumentExtraction(page_units={1: u1})
    merged_p = merge_financial_extractions([ext_p1, ext_p2])
    assert len(merged_p.page_units) == 1

    ext_p_conflict = FinancialDocumentExtraction(page_units={1: u_diff})
    with pytest.raises(FinancialMergeConflictError, match="Xung đột đơn vị tính tại trang 1"):
        merge_financial_extractions([ext_p1, ext_p_conflict])


def test_pages_per_chunk_and_workers_configuration():
    with patch.dict(os.environ, {}, clear=True):
        assert get_financial_pages_per_chunk() == DEFAULT_FINANCIAL_PAGES_PER_CHUNK
    with patch.dict(os.environ, {"FINANCIAL_PAGES_PER_CHUNK": "abc"}):
        assert get_financial_pages_per_chunk() == 5
    with patch.dict(os.environ, {"FINANCIAL_PAGES_PER_CHUNK": "0"}):
        assert get_financial_pages_per_chunk() == 5
    with patch.dict(os.environ, {"FINANCIAL_PAGES_PER_CHUNK": "1"}):
        assert get_financial_pages_per_chunk() == 5
    with patch.dict(os.environ, {"FINANCIAL_PAGES_PER_CHUNK": "99"}):
        assert get_financial_pages_per_chunk() == MAX_FINANCIAL_PAGES_PER_CHUNK
    with patch.dict(os.environ, {"FINANCIAL_PAGES_PER_CHUNK": "7"}):
        assert get_financial_pages_per_chunk() == 7

    assert get_financial_pages_per_chunk(configured=8) == 8
    assert get_financial_pages_per_chunk(configured=1) == 5
    assert get_financial_pages_per_chunk(configured=50) == 10

    with patch.dict(os.environ, {}, clear=True):
        assert get_financial_extraction_max_workers() == DEFAULT_FINANCIAL_EXTRACTION_MAX_WORKERS
    with patch.dict(os.environ, {"FINANCIAL_EXTRACTION_MAX_WORKERS": "abc"}):
        assert get_financial_extraction_max_workers() == 2
    with patch.dict(os.environ, {"FINANCIAL_EXTRACTION_MAX_WORKERS": "0"}):
        assert get_financial_extraction_max_workers() == 2
    with patch.dict(os.environ, {"FINANCIAL_EXTRACTION_MAX_WORKERS": "10"}):
        assert get_financial_extraction_max_workers() == MAX_FINANCIAL_EXTRACTION_MAX_WORKERS
    with patch.dict(os.environ, {"FINANCIAL_EXTRACTION_MAX_WORKERS": "3"}):
        assert get_financial_extraction_max_workers() == 3

    assert get_financial_extraction_max_workers(configured=3) == 3
    assert get_financial_extraction_max_workers(configured=0) == 2
    assert get_financial_extraction_max_workers(configured=99) == 4


def test_g_financial_ocr_max_failed_pages_configuration():
    """G. FINANCIAL_OCR_MAX_FAILED_PAGES env var override works, with a safe
    default of 2 and safe fallback for invalid/negative values."""
    with patch.dict(os.environ, {}, clear=True):
        assert get_financial_ocr_max_failed_pages() == DEFAULT_FINANCIAL_OCR_MAX_FAILED_PAGES == 2
    with patch.dict(os.environ, {"FINANCIAL_OCR_MAX_FAILED_PAGES": "abc"}):
        assert get_financial_ocr_max_failed_pages() == 2
    with patch.dict(os.environ, {"FINANCIAL_OCR_MAX_FAILED_PAGES": "-1"}):
        assert get_financial_ocr_max_failed_pages() == 2
    with patch.dict(os.environ, {"FINANCIAL_OCR_MAX_FAILED_PAGES": "1"}):
        assert get_financial_ocr_max_failed_pages() == 1
    with patch.dict(os.environ, {"FINANCIAL_OCR_MAX_FAILED_PAGES": "0"}):
        assert get_financial_ocr_max_failed_pages() == 0  # 0 is valid: tolerate zero failures
    with patch.dict(os.environ, {"FINANCIAL_OCR_MAX_FAILED_PAGES": "5"}):
        assert get_financial_ocr_max_failed_pages() == 5  # no upper clamp by design

    assert get_financial_ocr_max_failed_pages(configured=1) == 1
    assert get_financial_ocr_max_failed_pages(configured=0) == 0


def test_bounded_concurrency_and_out_of_order_merge():
    delays = {
        "financial_extraction_pages_1_5": 0.15,
        "financial_extraction_pages_6_10": 0.08,
        "financial_extraction_pages_11_12": 0.01,
    }
    chunk1_json = json.dumps({"periods": [{"period": "2025", "net_revenue": {"value_raw": "120.000.000.000", "page": 1}}]})
    chunk2_json = json.dumps({"periods": [{"period": "2024", "net_revenue": {"value_raw": "100.000.000.000", "page": 6}}]})
    chunk3_json = json.dumps({"periods": [{"period": "2023", "net_revenue": {"value_raw": "80.000.000.000", "page": 11}}]})

    mock_client = MockAIClient(
        chunk_responses={
            "financial_extraction_pages_1_5": chunk1_json,
            "financial_extraction_pages_6_10": chunk2_json,
            "financial_extraction_pages_11_12": chunk3_json,
        },
        delays=delays
    )

    tagged = build_tagged_text(12)
    extractor = FinancialDocumentExtractor(ai_client=mock_client, pages_per_chunk=5, max_workers=3)
    res = extractor.extract(tagged)

    assert mock_client.max_active_calls > 1
    assert mock_client.max_active_calls <= 3
    assert [p.period for p in res.periods] == ["2025", "2024", "2023"]


def test_parallel_worker_failure_cancels_all_and_fails_whole_extraction():
    delays = {
        "financial_extraction_pages_1_5": 0.20,
        "financial_extraction_pages_6_10": 0.01,
        "financial_extraction_pages_11_12": 0.20,
    }
    valid_json = json.dumps({"periods": [{"period": "2025"}]})
    mock_client = MockAIClient(
        chunk_responses={
            "financial_extraction_pages_1_5": valid_json,
            "financial_extraction_pages_6_10": "NOT VALID JSON",
            "financial_extraction_pages_11_12": valid_json,
        },
        delays=delays
    )

    tagged = build_tagged_text(12)
    extractor = FinancialDocumentExtractor(ai_client=mock_client, pages_per_chunk=5, max_workers=3)

    with pytest.raises(FinancialChunkExtractionError, match="pages 6-10"):
        extractor.extract(tagged)


def test_backward_compatibility_single_document():
    single_page_tagged = "[PAGE 1]\nBáo cáo tài chính\nDoanh thu: 120.000.000.000"
    payload = json.dumps({
        "document_title": "BCTC Đơn Trang",
        "document_unit": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1},
        "periods": [
            {
                "period": "2025",
                "net_revenue": {
                    "value_raw": "120.000.000.000",
                    "page": 1,
                    "evidence": "Doanh thu: 120.000.000.000"
                }
            }
        ]
    })
    mock_client = MockAIClient(default_response=payload)
    extractor = FinancialDocumentExtractor(ai_client=mock_client)
    res = extractor.extract(single_page_tagged, page_count=1)

    assert isinstance(res, FinancialDocumentExtraction)
    assert res.document_title == "BCTC Đơn Trang"
    assert len(res.periods) == 1
    assert res.periods[0].period == "2025"
    assert res.periods[0].net_revenue.value_raw == "120.000.000.000"


# ==============================================================================
# PATCH 1.5C.1: CONTINUITY, PAGE COUNT INVARIANT & CROSS-PAGE MERGE TESTS
# ==============================================================================

def test_parse_tagged_pages_fails_on_page_gap():
    """Case 1: parse_tagged_pages fails on page gap: [PAGE 1], [PAGE 2], [PAGE 4]."""
    tagged = "[PAGE 1]\nNội dung trang 1\n\n[PAGE 2]\nNội dung trang 2\n\n[PAGE 4]\nNội dung trang 4"
    with pytest.raises(FinancialPageMarkerError) as exc_info:
        parse_tagged_pages(tagged)
    assert "gián đoạn" in str(exc_info.value) or "PAGE 3" in str(exc_info.value)


def test_parse_tagged_pages_fails_when_starting_from_page_two():
    """Case 2: parse_tagged_pages fails when starting from page 2: [PAGE 2], [PAGE 3]."""
    tagged = "[PAGE 2]\nNội dung trang 2\n\n[PAGE 3]\nNội dung trang 3"
    with pytest.raises(FinancialPageMarkerError) as exc_info:
        parse_tagged_pages(tagged)
    assert "bắt đầu từ trang 1" in str(exc_info.value)


def test_parse_tagged_pages_fails_on_out_of_order_pages():
    """Case 3: parse_tagged_pages fails on out-of-order pages: [PAGE 1], [PAGE 3], [PAGE 2]."""
    tagged = "[PAGE 1]\nNội dung trang 1\n\n[PAGE 3]\nNội dung trang 3\n\n[PAGE 2]\nNội dung trang 2"
    with pytest.raises(FinancialPageMarkerError) as exc_info:
        parse_tagged_pages(tagged)
    assert "sai thứ tự" in str(exc_info.value) or "PAGE 2" in str(exc_info.value)


def test_extract_fails_if_page_count_too_large():
    """Case 4: extract() fails if page_count=5 but document only has 4 pages."""
    tagged = build_tagged_text(4)
    mock_client = MockAIClient(default_response=json.dumps({"periods": []}))
    extractor = FinancialDocumentExtractor(ai_client=mock_client)
    with pytest.raises(FinancialPageMarkerError) as exc_info:
        extractor.extract(tagged, page_count=5)
    assert "Bất đồng số lượng trang" in str(exc_info.value)


def test_extract_fails_if_page_count_too_small():
    """Case 5: extract() fails if page_count=3 but document has 4 pages."""
    tagged = build_tagged_text(4)
    mock_client = MockAIClient(default_response=json.dumps({"periods": []}))
    extractor = FinancialDocumentExtractor(ai_client=mock_client)
    with pytest.raises(FinancialPageMarkerError) as exc_info:
        extractor.extract(tagged, page_count=3)
    assert "Bất đồng số lượng trang" in str(exc_info.value)


def test_extract_succeeds_when_page_count_matches_parsed_pages_exactly():
    """Case 6: extract() succeeds when page_count matches parsed 1..N pages exactly."""
    tagged = build_tagged_text(4)
    mock_client = MockAIClient(default_response=json.dumps({
        "periods": [{"period": "2025", "net_revenue": {"value_raw": "100.000.000.000", "page": 1}}]
    }))
    extractor = FinancialDocumentExtractor(ai_client=mock_client, pages_per_chunk=5)
    res = extractor.extract(tagged, page_count=4)
    assert isinstance(res, FinancialDocumentExtraction)
    assert len(res.periods) == 1
    assert res.periods[0].period == "2025"
    assert res.periods[0].net_revenue.value_raw == "100.000.000.000"


def test_merge_identical_fact_on_same_page_succeeds():
    """Case 7: Merging identical fact on same page: succeeds."""
    field_a = FinancialEvidenceField(
        value_raw="120.000.000.000",
        semantic_label="Doanh thu thuần",
        accounting_code="10",
        unit_raw="VND",
        evidence="Doanh thu thuần 120.000.000.000",
        page=8,
    )
    field_b = FinancialEvidenceField(
        value_raw="120.000.000.000",
        semantic_label="Doanh thu thuần",
        accounting_code="10",
        unit_raw="VND",
        evidence="Doanh thu thuần 120.000.000.000",
        page=8,
    )
    ext1 = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_a)])
    ext2 = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_b)])

    merged = merge_financial_extractions([ext1, ext2])
    assert len(merged.periods) == 1
    p = merged.periods[0]
    assert p.net_revenue.value_raw == "120.000.000.000"
    assert p.net_revenue.page == 8


def test_merge_identical_fact_on_different_pages_picks_lowest_page():
    """Case 8: Merging identical fact on different pages (e.g. page 8 vs page 21): succeeds, picks lowest page."""
    field_page_8 = FinancialEvidenceField(
        value_raw="120.000.000.000",
        semantic_label="Doanh thu bán hàng và cung cấp dịch vụ",
        accounting_code="01",
        unit_raw="VND",
        evidence="Báo cáo kết quả hoạt động kinh doanh trang 8: 120.000.000.000",
        page=8,
    )
    field_page_21 = FinancialEvidenceField(
        value_raw="120.000.000.000",
        semantic_label="Thuyết minh doanh thu thuần",
        accounting_code="10",
        unit_raw="VND",
        evidence="Thuyết minh BCTC trang 21: 120.000.000.000",
        page=21,
    )
    ext_8 = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_page_8)])
    ext_21 = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_page_21)])

    # Thứ tự 8 trước, 21 sau -> chọn trang 8
    merged_1 = merge_financial_extractions([ext_8, ext_21])
    assert merged_1.periods[0].net_revenue.page == 8
    assert merged_1.periods[0].net_revenue.value_raw == "120.000.000.000"

    # Thứ tự 21 trước, 8 sau -> vẫn phải chọn trang 8
    merged_2 = merge_financial_extractions([ext_21, ext_8])
    assert merged_2.periods[0].net_revenue.page == 8
    assert merged_2.periods[0].net_revenue.value_raw == "120.000.000.000"

    # Trường hợp một bên có page, một bên page=None
    field_no_page = FinancialEvidenceField(
        value_raw="120.000.000.000",
        unit_raw="VND",
        page=None,
    )
    ext_no_page = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_no_page)])
    merged_3 = merge_financial_extractions([ext_no_page, ext_8])
    assert merged_3.periods[0].net_revenue.page == 8

    merged_4 = merge_financial_extractions([ext_8, ext_no_page])
    assert merged_4.periods[0].net_revenue.page == 8


def test_merge_identical_fact_different_formatting_succeeds():
    """Case 9: Merging identical fact with different formatting (e.g. '123.456' vs '123,456' or '123 456'): succeeds."""
    field_dot = FinancialEvidenceField(
        value_raw="123.456",
        page=8,
        evidence="Trang 8: 123.456",
    )
    field_comma = FinancialEvidenceField(
        value_raw="123,456",
        page=21,
        evidence="Trang 21: 123,456",
    )
    field_space = FinancialEvidenceField(
        value_raw="123 456",
        page=30,
        evidence="Trang 30: 123 456",
    )

    ext_dot = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_dot)])
    ext_comma = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_comma)])
    ext_space = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_space)])

    merged = merge_financial_extractions([ext_comma, ext_dot, ext_space])
    assert len(merged.periods) == 1
    assert merged.periods[0].net_revenue.page == 8
    assert merged.periods[0].net_revenue.value_raw == "123.456"


def test_merge_conflicting_value_different_pages_raises_error():
    """Case 10: Merging conflicting value on different pages: raises FinancialMergeConflictError."""
    field_p8 = FinancialEvidenceField(
        value_raw="120.000.000",
        page=8,
        evidence="Trang 8: Doanh thu 120.000.000",
    )
    field_p21 = FinancialEvidenceField(
        value_raw="95.000.000",
        page=21,
        evidence="Trang 21: Doanh thu 95.000.000",
    )
    ext1 = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_p8)])
    ext2 = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_p21)])

    with pytest.raises(FinancialMergeConflictError) as exc_info:
        merge_financial_extractions([ext1, ext2])

    err = str(exc_info.value)
    assert "2025" in err
    assert "net_revenue" in err
    assert "120.000.000" in err
    assert "95.000.000" in err
    assert "8" in err
    assert "21" in err


def test_merge_conflicting_unit_different_pages_raises_error():
    """Case 11: Merging conflicting unit on different pages: raises FinancialMergeConflictError."""
    field_vnd = FinancialEvidenceField(
        value_raw="100.000.000",
        unit_raw="VND",
        page=8,
        evidence="Trang 8: Doanh thu 100.000.000 VND",
    )
    field_trieu = FinancialEvidenceField(
        value_raw="100.000.000",
        unit_raw="triệu đồng",
        page=21,
        evidence="Trang 21: Doanh thu 100.000.000 triệu đồng",
    )
    ext1 = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_vnd)])
    ext2 = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_trieu)])

    with pytest.raises(FinancialMergeConflictError) as exc_info:
        merge_financial_extractions([ext1, ext2])

    err = str(exc_info.value)
    assert "Xung đột đơn vị tính" in err
    assert "VND" in err
    assert "triệu đồng" in err


def test_merge_representative_preservation_intact_evidence():
    """Case 12: Representative preservation: verify that after merging page 8 and page 21,
    the resulting field's page is 8 AND its evidence belongs to page 8 (not mixed).
    """
    ev_p8 = "Báo cáo KQKD (Trang 8) - Dòng 10: Doanh thu thuần về bán hàng 120.000.000.000 VND"
    ev_p21 = "Thuyết minh BCTC (Trang 21) - Mục 25: Chi tiết doanh thu thuần 120.000.000.000 VND"

    field_p8 = FinancialEvidenceField(
        value_raw="120.000.000.000",
        semantic_label="Doanh thu thuần về bán hàng",
        accounting_code="10",
        unit_raw="VND",
        unit_evidence="Đơn vị tính: VND",
        evidence=ev_p8,
        page=8,
    )
    field_p21 = FinancialEvidenceField(
        value_raw="120.000.000.000",
        semantic_label="Chi tiết doanh thu thuần",
        accounting_code="10",
        unit_raw="VND",
        unit_evidence="Đơn vị tính: VND",
        evidence=ev_p21,
        page=21,
    )

    ext8 = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_p8)])
    ext21 = FinancialDocumentExtraction(periods=[FinancialPeriodExtraction(period="2025", net_revenue=field_p21)])

    # Kiểm tra cả 2 chiều hợp nhất: [ext8, ext21] và [ext21, ext8]
    for ext_list in ([ext8, ext21], [ext21, ext8]):
        merged = merge_financial_extractions(ext_list)
        p = merged.periods[0].net_revenue
        # Đại diện trang 8 được chọn
        assert p.page == 8
        # Evidence thuộc về đúng trang 8, không bị pha trộn hay nối chuỗi
        assert p.evidence == ev_p8
        assert ev_p21 not in p.evidence
        assert p.value_raw == "120.000.000.000"


# ==============================================================================
# PATCH 1.5C.2: NULL FINANCIAL FACT SAFE NORMALIZATION TESTS
# ==============================================================================

def test_explicit_null_source_fact_matches_omitted_default():
    """Case 1: Explicit null source fact passes and matches omitted default state."""
    raw_payload = json.dumps({
        "periods": [
            {
                "period": "2024",
                "gross_profit": None,
            }
        ]
    })
    mock_client = MockAIClient(default_response=raw_payload)
    extractor = FinancialDocumentExtractor(ai_client=mock_client)
    res = extractor.extract("[PAGE 1]\nNội dung BCTC 2024", page_count=1)

    assert len(res.periods) == 1
    p = res.periods[0]
    assert p.period == "2024"
    # Resulting field has same default state as if gross_profit had been omitted
    default_field = FinancialEvidenceField()
    assert p.gross_profit == default_field
    assert p.gross_profit.value_raw is None
    assert p.gross_profit.page is None
    assert p.gross_profit.evidence is None


def test_multiple_explicit_null_financial_fields_pass():
    """Case 2: Multiple explicit null financial fields in LLM response pass cleanly."""
    raw_payload = json.dumps({
        "periods": [
            {
                "period": "2024",
                "gross_profit": None,
                "sga_expenses": None,
                "current_assets": None,
                "cash": None,
                "interest_expenses": None,
                "equity": None,
            }
        ]
    })
    mock_client = MockAIClient(default_response=raw_payload)
    extractor = FinancialDocumentExtractor(ai_client=mock_client)
    res = extractor.extract("[PAGE 1]\nNội dung", page_count=1)

    assert len(res.periods) == 1
    p = res.periods[0]
    assert p.gross_profit.value_raw is None
    assert p.sga_expenses.value_raw is None
    assert p.current_assets.value_raw is None
    assert p.cash.value_raw is None
    assert p.interest_expenses.value_raw is None
    assert p.equity.value_raw is None


def test_mixed_valid_and_null_facts_preserves_valid():
    """Case 3: Mixed valid + null preserves valid facts while null facts are absent/default."""
    raw_payload = json.dumps({
        "periods": [
            {
                "period": "2024",
                "net_revenue": {
                    "value_raw": "1000000",
                    "page": 31,
                    "evidence": "Doanh thu trang 31: 1000000",
                },
                "gross_profit": None,
                "cash": None,
            }
        ]
    })
    mock_client = MockAIClient(default_response=raw_payload)
    extractor = FinancialDocumentExtractor(ai_client=mock_client)
    res = extractor.extract(build_tagged_text(31), page_count=31)

    assert len(res.periods) == 1
    p = res.periods[0]
    assert p.net_revenue.value_raw == "1000000"
    assert p.net_revenue.page == 31
    assert p.net_revenue.evidence == "Doanh thu trang 31: 1000000"
    assert p.gross_profit.value_raw is None
    assert p.cash.value_raw is None


def test_invalid_non_null_value_still_fails_validation():
    """Case 4: Invalid non-null value (e.g. string '123' instead of dict) still fails Pydantic validation."""
    raw_payload = json.dumps({
        "periods": [
            {
                "period": "2024",
                "net_revenue": "123",
            }
        ]
    })
    mock_client = MockAIClient(default_response=raw_payload)
    extractor = FinancialDocumentExtractor(ai_client=mock_client)
    with pytest.raises(FinancialChunkExtractionError) as exc_info:
        extractor.extract("[PAGE 1]\nNội dung", page_count=1)

    assert "Lỗi kiểm thực Pydantic" in str(exc_info.value)


def test_null_fact_never_becomes_numeric_zero():
    """Case 5: Null fact must never become numeric zero (0 or '0')."""
    raw_payload = json.dumps({
        "periods": [
            {
                "period": "2024",
                "gross_profit": None,
                "cash": None,
            }
        ]
    })
    mock_client = MockAIClient(default_response=raw_payload)
    extractor = FinancialDocumentExtractor(ai_client=mock_client)
    res = extractor.extract("[PAGE 1]\nNội dung", page_count=1)

    p = res.periods[0]
    for field_name in ["gross_profit", "cash"]:
        f_val = getattr(p, field_name).value_raw
        assert f_val is None
        assert f_val != 0
        assert f_val != "0"
        assert f_val != "0.0"


def test_existing_omitted_field_behavior_remains_unchanged():
    """Case 6: Existing omitted-field behavior remains completely unchanged."""
    raw_payload_omitted = json.dumps({
        "periods": [
            {
                "period": "2024",
                "net_revenue": {
                    "value_raw": "500000",
                    "page": 1,
                    "evidence": "Doanh thu 500000",
                },
            }
        ]
    })
    raw_payload_null = json.dumps({
        "periods": [
            {
                "period": "2024",
                "net_revenue": {
                    "value_raw": "500000",
                    "page": 1,
                    "evidence": "Doanh thu 500000",
                },
                "gross_profit": None,
            }
        ]
    })

    mock_omitted = MockAIClient(default_response=raw_payload_omitted)
    ext_omitted = FinancialDocumentExtractor(ai_client=mock_omitted).extract("[PAGE 1]\nNội dung", page_count=1)

    mock_null = MockAIClient(default_response=raw_payload_null)
    ext_null = FinancialDocumentExtractor(ai_client=mock_null).extract("[PAGE 1]\nNội dung", page_count=1)

    p_omitted = ext_omitted.periods[0]
    p_null = ext_null.periods[0]

    assert p_omitted.net_revenue == p_null.net_revenue
    assert p_omitted.gross_profit == p_null.gross_profit
    assert p_omitted.cogs == p_null.cogs


# ==============================================================================
# PATCH 1.5C.3: DOCUMENT TITLE MERGE RELAXATION TESTS
# ==============================================================================

def test_same_document_title_across_chunks_coalesces():
    """Case 1: Same title across chunks behaves as before."""
    ext1 = FinancialDocumentExtraction(document_title="Báo cáo tài chính hợp nhất 2024")
    ext2 = FinancialDocumentExtraction(document_title="Báo cáo tài chính hợp nhất 2024")
    merged = merge_financial_extractions([ext1, ext2])
    assert merged.document_title == "Báo cáo tài chính hợp nhất 2024"


def test_different_document_title_wording_across_chunks_no_conflict():
    """Case 2: Different title wording across chunks does not raise FinancialMergeConflictError."""
    title_chunk1 = "Báo cáo tài chính hợp nhất Cho năm tài chính kết thúc ngày 31 tháng 12 năm 2024"
    title_chunk2 = "Báo cáo tài chính hợp nhất năm 2024 - Công ty Cổ phần Kinh doanh Khí miền Nam"

    ext1 = FinancialDocumentExtraction(document_title=title_chunk1)
    ext2 = FinancialDocumentExtraction(document_title=title_chunk2)

    merged = merge_financial_extractions([ext1, ext2])
    assert merged.document_title == title_chunk1


def test_first_non_empty_document_title_wins():
    """Case 3: First non-empty title wins deterministically."""
    title_first = "BCTC Kiểm toán 2024 - Báo cáo ban Tổng Giám đốc"
    title_second = "Báo cáo tài chính hợp nhất năm 2024"

    ext1 = FinancialDocumentExtraction(document_title=title_first)
    ext2 = FinancialDocumentExtraction(document_title=title_second)

    merged_forward = merge_financial_extractions([ext1, ext2])
    assert merged_forward.document_title == title_first

    merged_reverse = merge_financial_extractions([ext2, ext1])
    assert merged_reverse.document_title == title_second


def test_empty_or_null_title_in_early_chunk_picks_later_non_empty_title():
    """Case 4: Empty/null title in early chunk + non-empty later title selects the non-empty title."""
    title_later = "Báo cáo tài chính hợp nhất 2024"

    ext_none = FinancialDocumentExtraction(document_title=None)
    ext_empty = FinancialDocumentExtraction(document_title="   ")
    ext_valid = FinancialDocumentExtraction(document_title=title_later)

    merged = merge_financial_extractions([ext_none, ext_empty, ext_valid])
    assert merged.document_title == title_later


def test_multiple_different_later_titles_keep_first_selected_title():
    """Case 5: Multiple different later titles leave first selected title unchanged."""
    title_1 = "Tiêu đề phân đoạn 1"
    title_2 = "Tiêu đề phân đoạn 2 khác biệt"
    title_3 = "Tiêu đề phân đoạn 3 hoàn toàn khác"

    ext1 = FinancialDocumentExtraction(document_title=title_1)
    ext2 = FinancialDocumentExtraction(document_title=title_2)
    ext3 = FinancialDocumentExtraction(document_title=title_3)

    merged = merge_financial_extractions([ext1, ext2, ext3])
    assert merged.document_title == title_1


def test_financial_fact_conflicts_still_raise_merge_conflict_error():
    """Case 6: Ensure financial fact conflicts still strictly raise FinancialMergeConflictError."""
    # Khác biệt tiêu đề không gây lỗi...
    ext1 = FinancialDocumentExtraction(
        document_title="Tiêu đề 1",
        periods=[
            FinancialPeriodExtraction(
                period="2024",
                net_revenue=FinancialEvidenceField(value_raw="100.000.000", page=1, evidence="100tr")
            )
        ]
    )
    # ...nhưng xung đột số liệu tài chính BẮT BUỘC vẫn phải raise FinancialMergeConflictError
    ext2 = FinancialDocumentExtraction(
        document_title="Tiêu đề 2 khác",
        periods=[
            FinancialPeriodExtraction(
                period="2024",
                net_revenue=FinancialEvidenceField(value_raw="200.000.000", page=1, evidence="200tr")
            )
        ]
    )

    with pytest.raises(FinancialMergeConflictError, match="Xung đột dữ liệu không thể hợp nhất"):
        merge_financial_extractions([ext1, ext2])


# ==============================================================================
# PATCH 1.5C.4: CANONICAL STATEMENTS VS NOTE DISCLOSURES TESTS
# ==============================================================================

def test_primary_pl_cogs_with_code_11_allowed():
    """Case 1: Primary P&L 'Giá vốn hàng bán và dịch vụ cung cấp' with code 11 is allowed."""
    cogs_pl = {
        "value_raw": "5.495.063.722.526",
        "semantic_label": "Giá vốn hàng bán và dịch vụ cung cấp",
        "accounting_code": "11",
        "evidence": "Giá vốn hàng bán và dịch vụ cung cấp | 11 | 5.495.063.722.526",
        "page": 10,
    }
    assert is_note_disclosure_cogs(cogs_pl) is False

    raw_payload = json.dumps({
        "periods": [
            {
                "period": "2024",
                "cogs": cogs_pl,
            }
        ]
    })
    mock_client = MockAIClient(default_response=raw_payload)
    extractor = FinancialDocumentExtractor(ai_client=mock_client)
    res = extractor.extract(build_tagged_text(10), page_count=10)

    assert len(res.periods) == 1
    p = res.periods[0]
    assert p.cogs.value_raw == "5.495.063.722.526"
    assert p.cogs.accounting_code == "11"
    assert p.cogs.page == 10


def test_expense_by_nature_note_cogs_rejected_from_canonical():
    """Case 2: Expense-by-nature note (e.g. section 'CHI PHÍ SẢN XUẤT, KINH DOANH THEO YẾU TỐ',
    row 'Giá vốn hàng hóa') must NOT become canonical cogs.
    """
    cogs_note = {
        "value_raw": "5.171.771.689.976",
        "semantic_label": "Giá vốn hàng hóa",
        "accounting_code": None,
        "evidence": "27. CHI PHÍ SẢN XUẤT, KINH DOANH THEO YẾU TỐ: Giá vốn hàng hóa 5.171.771.689.976",
        "page": 36,
    }
    assert is_note_disclosure_cogs(cogs_note) is True

    raw_dict = {
        "period": "2024",
        "cogs": cogs_note,
    }
    cleaned = normalize_financial_extraction_raw_dict(raw_dict)
    assert "cogs" not in cleaned


def test_chunk_with_only_note_components_leaves_cogs_default():
    """Case 3: A chunk containing only note components leaves cogs absent/default."""
    cogs_note = {
        "value_raw": "5.171.771.689.976",
        "semantic_label": "Giá vốn hàng hóa",
        "evidence": "27. CHI PHÍ SẢN XUẤT, KINH DOANH THEO YẾU TỐ ...",
        "page": 36,
    }
    raw_payload = json.dumps({
        "periods": [
            {
                "period": "2024",
                "cogs": cogs_note,
            }
        ]
    })
    mock_client = MockAIClient(default_response=raw_payload)
    extractor = FinancialDocumentExtractor(ai_client=mock_client)
    res = extractor.extract(build_tagged_text(36), page_count=36)

    assert len(res.periods) == 1
    p = res.periods[0]
    assert p.cogs.value_raw is None
    assert p.cogs.page is None


def test_existing_valid_cogs_extraction_remains_unchanged():
    """Case 4: Existing valid cogs extraction without code 11 (e.g. standard 'Giá vốn hàng bán' label)
    remains completely supported.
    """
    cogs_valid = {
        "value_raw": "96.000.000.000",
        "semantic_label": "Giá vốn hàng bán",
        "evidence": "Giá vốn hàng bán 96.000.000.000",
        "page": 3,
    }
    assert is_note_disclosure_cogs(cogs_valid) is False

    raw_payload = json.dumps({
        "periods": [
            {
                "period": "2025",
                "cogs": cogs_valid,
            }
        ]
    })
    mock_client = MockAIClient(default_response=raw_payload)
    extractor = FinancialDocumentExtractor(ai_client=mock_client)
    res = extractor.extract(build_tagged_text(3), page_count=3)

    assert res.periods[0].cogs.value_raw == "96.000.000.000"
    assert res.periods[0].cogs.page == 3


def test_multi_chunk_cogs_canonical_preserved_over_note_component():
    """Case 5: Multi-chunk real scenario: Page 10 has canonical COGS (code 11),
    Page 36 has note disclosure component (expense by nature).
    Merging both chunks succeeds cleanly with Page 10's canonical COGS preserved.
    """
    chunk1_json = json.dumps({
        "periods": [
            {
                "period": "2024",
                "cogs": {
                    "value_raw": "5.495.063.722.526",
                    "semantic_label": "Giá vốn hàng bán và dịch vụ cung cấp",
                    "accounting_code": "11",
                    "evidence": "Giá vốn hàng bán và dịch vụ cung cấp | 11 | 5.495.063.722.526",
                    "page": 10,
                },
            }
        ]
    })
    chunk8_json = json.dumps({
        "periods": [
            {
                "period": "2024",
                "cogs": {
                    "value_raw": "5.171.771.689.976",
                    "semantic_label": "Giá vốn hàng hóa",
                    "evidence": "27. CHI PHÍ SẢN XUẤT, KINH DOANH THEO YẾU TỐ: Giá vốn hàng hóa 5.171.771.689.976",
                    "page": 36,
                },
            }
        ]
    })

    mock_client = MockAIClient(chunk_responses={
        "financial_extraction_pages_1_5": json.dumps({"periods": []}),
        "financial_extraction_pages_6_10": chunk1_json,
        "financial_extraction_pages_36_40": chunk8_json,
    })

    tagged = build_tagged_text(40)
    extractor = FinancialDocumentExtractor(ai_client=mock_client, pages_per_chunk=5, max_workers=1)
    res = extractor.extract(tagged, page_count=40)

    p2024 = res.periods[0]
    assert p2024.cogs.value_raw == "5.495.063.722.526"
    assert p2024.cogs.page == 10
    assert p2024.cogs.accounting_code == "11"
    assert "Giá vốn hàng bán và dịch vụ cung cấp" in p2024.cogs.evidence


def test_genuinely_conflicting_canonical_facts_still_raise_merge_conflict():
    """Case 6: Merge conflict behavior remains strictly enforced for genuinely conflicting canonical facts."""
    ext1 = FinancialDocumentExtraction(
        periods=[
            FinancialPeriodExtraction(
                period="2024",
                cogs=FinancialEvidenceField(
                    value_raw="5.495.063.722.526",
                    semantic_label="Giá vốn hàng bán",
                    accounting_code="11",
                    page=10,
                    evidence="Giá vốn 5.495.063.722.526",
                )
            )
        ]
    )
    ext2 = FinancialDocumentExtraction(
        periods=[
            FinancialPeriodExtraction(
                period="2024",
                cogs=FinancialEvidenceField(
                    value_raw="6.000.000.000.000",
                    semantic_label="Giá vốn hàng bán",
                    accounting_code="11",
                    page=10,
                    evidence="Giá vốn 6.000.000.000.000",
                )
            )
        ]
    )

    with pytest.raises(FinancialMergeConflictError, match="Xung đột dữ liệu không thể hợp nhất"):
        merge_financial_extractions([ext1, ext2])
