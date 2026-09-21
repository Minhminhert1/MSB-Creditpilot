# -*- coding: utf-8 -*-
"""
Module: pdf_ocr.py
Mô tả: Tầng chuyển đổi OCR tài liệu PDF quét/ảnh (Scanned/Image-based PDF Ingestion Layer)
sử dụng pypdfium2 để rasterize từng trang độc lập sang PNG và mô hình thị giác
qwen/qwen3.6-flash (chạy trên GreenNode MaaS) làm engine nhận dạng ký tự (OCR).

Tuân thủ nghiêm ngặt các nguyên tắc:
1. 100% Deterministic Page-to-Image Mapping: 1 trang PDF vật lý -> đúng 1 ảnh PNG.
2. Xử lý tuần tự (Lazy/Sequential resource lifecycle): Giải phóng bitmap từng trang ngay lập tức.
3. Hợp đồng đầu ra tương thích hoàn toàn:
   [PAGE 1]
   <nội dung OCR trang 1>

   [PAGE 2]
   <nội dung OCR trang 2>
4. Bất biến số trang (Page-Count Invariant):
   pypdf physical count == PDFium physical count == OCRPageResult count == [PAGE X] block count.
5. Kiểm định văn bản OCR tất định:
   - None -> OCRNoTextError
   - Chuỗi rỗng/chỉ khoảng trắng -> OCRNoTextError
   - Không chứa bất kỳ ký tự chữ hoặc số Unicode nào -> OCRNoTextError
6. KHÔNG can thiệp ngữ nghĩa: Không tóm tắt, không sửa lỗi chính tả, không chuẩn hóa số,
   không gọi LegalDocumentExtractor bên trong.
"""

import os
import io
import base64
import logging
import threading
import concurrent.futures
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

import pypdf
import pypdfium2 as pdfium
from openai import OpenAI, APIError, APITimeoutError, APIConnectionError

logger = logging.getLogger(__name__)

# Hard cap on how much of an exception's own message text we ever log, as
# defense-in-depth against a pathological upstream error response echoing back
# request content. This is independent of, and in addition to, only ever reading
# an explicit allow-list of attributes off the exception (never the raw request/
# response objects, never the messages/base64 image payload we sent).
_MAX_LOGGED_ERROR_MESSAGE_CHARS = 300
_REDACTED_PLACEHOLDER = "***REDACTED***"


def _redact_known_secrets(text: str, secrets: Optional[List[str]]) -> str:
    """Removes any occurrence of a known secret value (e.g. the resolved API key)
    from a free-text string before it is ever logged. This is active redaction —
    not just truncation — so a secret is scrubbed even if it appears at the very
    start of an exception's own message (e.g. a low-level connection error that
    happens to echo the outgoing Authorization header)."""
    if not text or not secrets:
        return text
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, _REDACTED_PLACEHOLDER)
    return redacted


def _sanitize_exception_message_in_place(exc: BaseException, secrets: Optional[List[str]]) -> None:
    """Mutates exc's own message/args in place so str(exc) — and therefore the
    traceback logger.exception() independently renders for it via sys.exc_info()
    — can never surface a known secret. A real traceback (correct file/line/call
    stack) is still attached and still useful for debugging; only the exception's
    own text is sanitized, and only if a known secret was actually found in it (in
    the normal case, with no secret present, this is a no-op and the message is
    completely unchanged)."""
    if not secrets:
        return
    original = str(exc)
    redacted = _redact_known_secrets(original, secrets)
    if redacted == original:
        return
    try:
        exc.args = (redacted,)
    except Exception:
        pass
    if hasattr(exc, "message"):
        try:
            exc.message = redacted
        except Exception:
            pass


def _safe_ocr_error_fields(
    exc: BaseException,
    page_num: Optional[int] = None,
    model: Optional[str] = None,
    secrets_to_redact: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Builds a diagnostic dict for logging a GreenNode OCR call failure.

    SAFE BY CONSTRUCTION: only reads a fixed allow-list of attributes that the
    openai SDK's exception classes expose (status_code, request_id, code/type,
    a Retry-After response header, and the exception's own str(), redacted and
    truncated). Never reads/logs: API keys, Authorization headers, the base64
    image payload, document/OCR text, or the raw request/response objects (which
    could contain the full request body).

    `secrets_to_redact` should be the caller's actual resolved API key(s) (e.g.
    `self.client.api_key`), which is proactively scrubbed from the free-text
    message field even if it happens to appear there.
    """
    status_code = getattr(exc, "status_code", None)
    request_id = getattr(exc, "request_id", None)
    error_code = getattr(exc, "code", None) or getattr(exc, "type", None)

    retry_after = None
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            retry_after = response.headers.get("Retry-After")
        except Exception:
            retry_after = None

    message = _redact_known_secrets(str(exc), secrets_to_redact)
    if len(message) > _MAX_LOGGED_ERROR_MESSAGE_CHARS:
        message = message[:_MAX_LOGGED_ERROR_MESSAGE_CHARS] + "...(truncated)"

    return {
        "page_num": page_num,
        "model": model,
        "exception_class": type(exc).__name__,
        "http_status_code": status_code,
        "request_id": request_id,
        "error_code": error_code,
        "retry_after": retry_after,
        "message": message,
    }


# ==============================================================================
# 1. TYPED OCR EXCEPTION HIERARCHY
# ==============================================================================
class OCRIngestionError(Exception):
    """Lỗi cơ sở cho tất cả các sự cố trong quá trình OCR tài liệu PDF."""
    pass


class OCRFileNotFoundError(OCRIngestionError):
    """Lỗi khi đường dẫn tệp PDF không tồn tại hoặc không phải là tệp hợp lệ."""
    pass


class OCREncryptedError(OCRIngestionError):
    """Lỗi khi tệp PDF bị khóa bằng mật khẩu."""
    pass


class OCRRenderError(OCRIngestionError):
    """Lỗi xảy ra trong quá trình rasterize trang PDF sang hình ảnh bằng PDFium."""
    pass


class OCRServiceError(OCRIngestionError):
    """Lỗi kết nối hoặc lỗi dịch vụ từ API nhận dạng OCR."""
    pass


class OCRTimeoutError(OCRServiceError):
    """Lỗi vượt quá thời gian chờ (timeout) khi gọi dịch vụ OCR."""
    pass


class OCRNoTextError(OCRIngestionError):
    """Lỗi khi trang hoặc toàn bộ tài liệu sau OCR không có ký tự chữ/số nào."""
    pass


class OCRPageCountError(OCRIngestionError):
    """Lỗi không bảo đảm tính bất biến về số lượng trang qua các tầng xử lý."""
    pass


# ==============================================================================
# 2. DATA MODELS (Pydantic)
# ==============================================================================
class OCRPageResult(BaseModel):
    """Kết quả trích xuất OCR thô cho một trang PDF vật lý cụ thể."""
    page_num: int = Field(..., description="Số thứ tự trang vật lý 1-based trong tài liệu PDF")
    text: str = Field(..., description="Văn bản trích xuất thô từ trang PDF qua OCR")
    provider: str = Field(default="qwen_vision", description="Tên định danh của OCR engine")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Metadata phụ trợ (DPI, kích thước ảnh)")


class OCRDocumentResult(BaseModel):
    """Tập hợp kết quả OCR cấp tài liệu chứa đầy đủ từng trang vật lý."""
    tagged_text: str = Field(..., description="Chuỗi văn bản định dạng thẻ [PAGE X] chuẩn hợp đồng")
    page_count: int = Field(..., description="Tổng số trang vật lý đã xử lý thành công")
    pages: List[OCRPageResult] = Field(..., description="Danh sách kết quả OCR chi tiết cho từng trang")
    provider: str = Field(default="qwen_vision", description="Tên định danh của OCR engine")


# ==============================================================================
# 3. BASE OCR ENGINE & QWEN VISION ADAPTER
# ==============================================================================
class BaseOCREngine(ABC):
    """Giao diện trừu tượng cho các bộ nhận dạng OCR."""

    provider_name: str = "base_ocr"

    @abstractmethod
    def ocr_page(self, base64_png: str, page_num: int) -> str:
        """Nhận diện văn bản từ chuỗi Base64 của ảnh PNG đơn trang.
        
        Args:
            base64_png: Chuỗi Base64 của dữ liệu ảnh PNG trang PDF.
            page_num: Số thứ tự trang vật lý 1-based (dùng cho logging/diagnostics).
            
        Returns:
            Văn bản thô được nhận diện từ ảnh.
        """
        pass


class QwenVisionOCREngine(BaseOCREngine):
    """Bộ chuyển đổi OCR sử dụng mô hình thị giác qwen/qwen3.6-flash trên GreenNode MaaS."""

    provider_name: str = "qwen_vision"

    OCR_SYSTEM_PROMPT = (
        "You are an OCR transcription engine.\n"
        "Transcribe ONLY visible text.\n"
        "Do not summarize.\n"
        "Do not explain.\n"
        "Do not correct spelling.\n"
        "Do not normalize numbers.\n"
        "Do not infer missing characters.\n"
        "Preserve line order as closely as possible.\n"
        "Return raw text only."
    )

    DEFAULT_BASE_URL = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"
    DEFAULT_MODEL = "qwen/qwen3.6-flash"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 60.0
    ):
        resolved_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("AI_PLATFORM_API_KEY")
            or os.getenv("GREENNODE_API_KEY")
        )
        if not resolved_key:
            raise OCRServiceError("Không tìm thấy AI_PLATFORM_API_KEY hoặc GREENNODE_API_KEY hoặc LLM_API_KEY trong môi trường.")

        self.base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or os.getenv("GREENNODE_BASE_URL", self.DEFAULT_BASE_URL)
        )
        self.model = (
            model
            or os.getenv("VISION_MODEL")
            or os.getenv("GREENNODE_VISION_MODEL")
            or self.DEFAULT_MODEL
        )
        self.timeout = timeout

        # Strict: max_retries=0 để tắt cơ chế ẩn retry của SDK OpenAI,
        # đảm bảo đúng 1 lời gọi logic cho 1 trang vật lý
        self.client = OpenAI(
            api_key=resolved_key,
            base_url=self.base_url,
            max_retries=0,
            timeout=self.timeout
        )

    def _known_secrets(self) -> List[str]:
        """The actual resolved secret value(s) for this engine instance, used only
        to proactively redact them from diagnostic log messages (see
        _safe_ocr_error_fields) -- never logged, read, or exposed otherwise here."""
        api_key = getattr(self.client, "api_key", None)
        return [api_key] if api_key else []

    def ocr_page(self, base64_png: str, page_num: int) -> str:
        messages = [
            {"role": "system", "content": self.OCR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this document image."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64_png}"}
                    }
                ]
            }
        ]

        import time
        start_time = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                max_tokens=2048,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            content = response.choices[0].message.content

            in_tok = getattr(response.usage, "prompt_tokens", None) if hasattr(response, "usage") and response.usage else None
            out_tok = getattr(response.usage, "completion_tokens", None) if hasattr(response, "usage") and response.usage else None
            tot_tok = getattr(response.usage, "total_tokens", None) if hasattr(response, "usage") and response.usage else None
            try:
                from msb_eb_copilot.src.ai_client import AIAssistantClient
                AIAssistantClient.record_telemetry(
                    operation=f"ocr_page_{page_num}",
                    model=self.model,
                    latency_ms=latency_ms,
                    success=True,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    total_tokens=tot_tok,
                )
            except Exception:
                pass

            return content if content is not None else ""
        except APITimeoutError as exc:
            secrets = self._known_secrets()
            _sanitize_exception_message_in_place(exc, secrets)
            logger.exception(
                "GreenNode OCR request timed out (fail-closed, no retry/behavior change): %s",
                _safe_ocr_error_fields(exc, page_num, self.model, secrets_to_redact=secrets),
            )
            raise OCRTimeoutError(f"Thời gian chờ OCR trang {page_num} vượt quá {self.timeout}s: {str(exc)}") from exc
        except (APIError, APIConnectionError) as exc:
            secrets = self._known_secrets()
            _sanitize_exception_message_in_place(exc, secrets)
            logger.exception(
                "GreenNode OCR API/connection error: %s",
                _safe_ocr_error_fields(exc, page_num, self.model, secrets_to_redact=secrets),
            )
            raise OCRServiceError(f"Lỗi dịch vụ OCR khi xử lý trang {page_num}: {str(exc)}") from exc
        except Exception as exc:
            secrets = self._known_secrets()
            _sanitize_exception_message_in_place(exc, secrets)
            logger.exception(
                "Unexpected error during GreenNode OCR call: %s",
                _safe_ocr_error_fields(exc, page_num, self.model, secrets_to_redact=secrets),
            )
            raise OCRServiceError(f"Lỗi không xác định khi gọi OCR trang {page_num}: {str(exc)}") from exc


DEFAULT_OCR_MAX_WORKERS = 4
MIN_OCR_MAX_WORKERS = 1
MAX_OCR_MAX_WORKERS = 8


def get_ocr_max_workers(configured: Optional[int] = None) -> int:
    """Xác định số lượng worker xử lý OCR song song có giới hạn an toàn.

    Quy tắc:
    - Nếu truyền trực tiếp `configured`: sử dụng giá trị đó (sau khi kiểm tra/clamp).
    - Nếu không, đọc biến môi trường OCR_MAX_WORKERS.
    - Nếu không có biến môi trường hoặc rỗng: mặc định là DEFAULT_OCR_MAX_WORKERS (4).
    - Giá trị không hợp lệ (không phải số nguyên, chuỗi không parse được, giá trị < 1): an toàn trả về mặc định 4.
    - Giá trị vượt quá giới hạn an toàn (> 8): kẹp (clamp) về tối đa MAX_OCR_MAX_WORKERS (8).
    - Giá trị từ 1 đến 8: giữ nguyên (giá trị 1 tái tạo ngữ nghĩa tuần tự).
    """
    raw_val = configured
    if raw_val is None:
        raw_env = os.getenv("OCR_MAX_WORKERS")
        if raw_env is not None and str(raw_env).strip():
            try:
                raw_val = int(str(raw_env).strip())
            except ValueError:
                return DEFAULT_OCR_MAX_WORKERS
        else:
            return DEFAULT_OCR_MAX_WORKERS

    if not isinstance(raw_val, int):
        try:
            raw_val = int(raw_val)
        except (ValueError, TypeError):
            return DEFAULT_OCR_MAX_WORKERS

    if raw_val < MIN_OCR_MAX_WORKERS:
        return DEFAULT_OCR_MAX_WORKERS
    if raw_val > MAX_OCR_MAX_WORKERS:
        return MAX_OCR_MAX_WORKERS
    return raw_val


# ==============================================================================
# 4. PDF OCR INGESTOR (ORCHESTRATOR & PREFLIGHT)
# ==============================================================================
class PDFOCRIngestor:
    """Điều phối toàn bộ quy trình OCR tài liệu PDF quét/ảnh:
    1. Preflight kiểm tra tính hợp lệ và mã hóa bằng pypdf
    2. Đối chiếu số trang vật lý giữa pypdf và pypdfium2
    3. Rasterize từng trang độc lập sang PNG (150 DPI mặc định)
    4. Gửi nhận dạng qua OCR Engine (hỗ trợ thực thi song song có giới hạn OCR_MAX_WORKERS)
    5. Kiểm định văn bản OCR tất định
    6. Lắp ráp thành chuỗi [PAGE X] chuẩn hợp đồng
    """

    DEFAULT_DPI = 150
    DEFAULT_MAX_WORKERS = DEFAULT_OCR_MAX_WORKERS
    _pdfium_render_lock = threading.Lock()

    @classmethod
    def _preflight_pdf(cls, pdf_path: str) -> int:
        """Kiểm tra sự tồn tại, quyền truy cập, tính mã hóa và số trang vật lý bằng pypdf."""
        if not os.path.exists(pdf_path) or not os.path.isfile(pdf_path):
            raise OCRFileNotFoundError(f"Tệp PDF không tồn tại hoặc không phải là file: {pdf_path}")

        try:
            reader = pypdf.PdfReader(pdf_path)
            if reader.is_encrypted:
                raise OCREncryptedError(f"Tệp PDF bị khóa bằng mật khẩu: {pdf_path}")
            expected_pages = len(reader.pages)
            if expected_pages == 0:
                raise OCRNoTextError(f"Tệp PDF không có trang nào: {pdf_path}")
            return expected_pages
        except (OCREncryptedError, OCRNoTextError):
            raise
        except Exception as exc:
            raise OCRRenderError(f"Lỗi tiền kiểm tra tệp PDF: {str(exc)}") from exc

    @classmethod
    def ocr_single_page(
        cls,
        doc_or_path: Any,
        page_num: int,
        engine: Optional[BaseOCREngine] = None,
        dpi: int = DEFAULT_DPI,
    ) -> OCRPageResult:
        """Thực hiện rasterize và OCR cho đúng một trang PDF vật lý cụ thể (1-based page_num).

        Args:
            doc_or_path: Đường dẫn tệp PDF (str) hoặc đối tượng pdfium.PdfDocument đã mở.
                Khuyến nghị truyền đường dẫn tệp (str) khi chạy đa luồng để bảo đảm an toàn bộ nhớ C++.
            page_num: Số thứ tự trang vật lý 1-based (dùng cho logging, OCR engine, và telemetry).
            engine: Engine OCR để nhận dạng. Nếu None, mặc định sử dụng QwenVisionOCREngine().
            dpi: Độ phân giải rasterize (mặc định 150 DPI).

        Returns:
            OCRPageResult chứa số trang, văn bản thô chuẩn hóa và metadata.

        Raises:
            OCRRenderError: Nếu lỗi truy xuất trang hoặc rasterize từ PDFium.
            OCRNoTextError: Nếu nội dung sau OCR rỗng hoặc không có ký tự chữ/số nào.
            OCRTimeoutError: Nếu yêu cầu OCR bị quá thời gian chờ.
            OCRServiceError: Nếu dịch vụ OCR gặp sự cố mạng hoặc lỗi máy chủ.
        """
        active_engine = engine or QwenVisionOCREngine()
        page_idx = page_num - 1
        scale = dpi / 72.0

        # Rasterize trang sang ảnh PIL an toàn với PDFium C++ global runtime
        with cls._pdfium_render_lock:
            should_close_doc = False
            if isinstance(doc_or_path, str):
                try:
                    pdfium_doc = pdfium.PdfDocument(doc_or_path)
                    should_close_doc = True
                except Exception as exc:
                    raise OCRRenderError(f"Không thể mở tài liệu bằng PDFium: {str(exc)}") from exc
            else:
                pdfium_doc = doc_or_path

            try:
                try:
                    page = pdfium_doc[page_idx]
                except Exception as exc:
                    raise OCRRenderError(f"Lỗi truy xuất trang {page_num} từ PDFium: {str(exc)}") from exc

                # Rasterize trang sang ảnh PIL và đóng handle trang ngay
                try:
                    try:
                        pil_img = page.render(scale=scale).to_pil()
                    except Exception as exc:
                        raise OCRRenderError(f"Lỗi rasterize trang {page_num} tại {dpi} DPI: {str(exc)}") from exc
                finally:
                    page.close()  # Giải phóng bitmap C++ của trang ngay lập tức
            finally:
                if should_close_doc:
                    pdfium_doc.close()  # Đóng tài liệu PDFium ngay lập tức trước khi gọi OCR!

        # Mã hóa ảnh sang định dạng PNG Base64 trong bộ nhớ
        try:
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            b64_png = base64.b64encode(buf.getvalue()).decode("utf-8")
        finally:
            pil_img.close()
            del pil_img
            del buf

        # Gọi OCR Engine cho đúng 1 trang vật lý
        raw_text = active_engine.ocr_page(b64_png, page_num=page_num)

        # Kiểm định văn bản OCR tất định (Strict validation)
        if raw_text is None:
            raise OCRNoTextError(f"Trang {page_num} không nhận được kết quả OCR từ engine.")

        norm_text = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip("\n\r\t ")

        if not norm_text:
            raise OCRNoTextError(f"Trang {page_num} có nội dung OCR hoàn toàn rỗng.")

        if not any(ch.isalnum() for ch in norm_text):
            raise OCRNoTextError(f"Trang {page_num} không chứa bất kỳ ký tự chữ hoặc số Unicode nào.")

        return OCRPageResult(
            page_num=page_num,
            text=norm_text,
            provider=getattr(active_engine, "provider_name", "qwen_vision"),
            metadata={"dpi": dpi, "scale": scale}
        )

    @classmethod
    def ocr_pages_parallel(
        cls,
        pdf_path: str,
        page_nums: List[int],
        engine: Optional[BaseOCREngine] = None,
        dpi: int = DEFAULT_DPI,
        max_workers: Optional[int] = None,
    ) -> Dict[int, OCRPageResult]:
        """Thực hiện OCR song song có giới hạn (Bounded Parallel OCR) cho danh sách các trang vật lý.

        Args:
            pdf_path: Đường dẫn tới file PDF.
            page_nums: Danh sách số thứ tự trang vật lý 1-based cần OCR.
            engine: OCR Engine tùy chọn.
            dpi: Độ phân giải rasterize (mặc định 150 DPI).
            max_workers: Số luồng tối đa (mặc định đọc từ OCR_MAX_WORKERS hoặc 4, bounded [1, 8]).

        Returns:
            Dict mapping từ page_num -> OCRPageResult.

        Raises:
            OCRIngestionError (OCRTimeoutError, OCRNoTextError, OCRServiceError, OCRRenderError,...):
            Nếu bất kỳ trang nào thất bại, ngoại lệ nguyên gốc được lan truyền và hủy các tác vụ chờ.
        """
        if not page_nums:
            return {}

        active_engine = engine or QwenVisionOCREngine()
        workers = get_ocr_max_workers(max_workers)
        effective_workers = min(workers, len(page_nums))

        # Nếu chỉ có 1 trang hoặc workers == 1: chạy tuần tự an toàn
        if effective_workers == 1:
            results: Dict[int, OCRPageResult] = {}
            for p_num in page_nums:
                page_res = cls.ocr_single_page(
                    doc_or_path=pdf_path,
                    page_num=p_num,
                    engine=active_engine,
                    dpi=dpi
                )
                results[p_num] = page_res
            return results

        # Chạy song song có giới hạn bằng ThreadPoolExecutor
        results: Dict[int, OCRPageResult] = {}
        first_exception: Optional[Exception] = None

        with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as executor:
            future_to_page = {
                executor.submit(
                    cls.ocr_single_page,
                    doc_or_path=pdf_path,
                    page_num=p_num,
                    engine=active_engine,
                    dpi=dpi
                ): p_num
                for p_num in page_nums
            }

            for future in concurrent.futures.as_completed(future_to_page):
                p_num = future_to_page[future]
                try:
                    res = future.result()
                    results[p_num] = res
                except Exception as exc:
                    if first_exception is None:
                        first_exception = exc
                    # Hủy các future còn đang pending trong queue
                    for f in future_to_page:
                        f.cancel()

        if first_exception is not None:
            raise first_exception

        return results

    @classmethod
    def extract_document(
        cls,
        pdf_path: str,
        engine: Optional[BaseOCREngine] = None,
        dpi: int = DEFAULT_DPI,
        max_workers: Optional[int] = None,
    ) -> OCRDocumentResult:
        """Thực hiện OCR toàn bộ tài liệu PDF và trả về đối tượng kết quả có cấu trúc."""
        # 1. Preflight xác định số trang dự kiến bằng pypdf
        expected_page_count = cls._preflight_pdf(pdf_path)

        # 2. Khởi tạo engine mặc định nếu chưa truyền vào
        active_engine = engine or QwenVisionOCREngine()

        # 3. Mở tài liệu bằng pypdfium2 và kiểm tra đối chiếu số trang
        try:
            pdfium_doc = pdfium.PdfDocument(pdf_path)
            try:
                actual_pdfium_page_count = len(pdfium_doc)
                if actual_pdfium_page_count != expected_page_count:
                    raise OCRPageCountError(
                        f"Bất đồng số trang vật lý: pypdf xác nhận {expected_page_count} trang, "
                        f"nhưng PDFium phát hiện {actual_pdfium_page_count} trang."
                    )
            finally:
                pdfium_doc.close()
        except OCRPageCountError:
            raise
        except Exception as exc:
            raise OCRRenderError(f"Không thể mở tài liệu bằng PDFium: {str(exc)}") from exc

        # 4. Thực hiện OCR song song có giới hạn cho toàn bộ các trang 1..N
        all_pages = list(range(1, expected_page_count + 1))
        results_by_page = cls.ocr_pages_parallel(
            pdf_path=pdf_path,
            page_nums=all_pages,
            engine=active_engine,
            dpi=dpi,
            max_workers=max_workers,
        )

        # 5. Đối chiếu bất biến số lượng kết quả
        if len(results_by_page) != expected_page_count:
            raise OCRPageCountError(
                f"Bất biến số trang bị vi phạm: Dự kiến {expected_page_count} trang, "
                f"nhưng chỉ thu được {len(results_by_page)} kết quả OCR."
            )

        # 6. Lắp ráp chuỗi định dạng thẻ [PAGE X] chuẩn hợp đồng theo đúng thứ tự 1..N
        page_results = [results_by_page[p_num] for p_num in range(1, expected_page_count + 1)]
        tagged_blocks = [f"[PAGE {p.page_num}]\n{p.text}" for p in page_results]
        tagged_text = "\n\n".join(tagged_blocks)

        return OCRDocumentResult(
            tagged_text=tagged_text,
            page_count=expected_page_count,
            pages=page_results,
            provider=getattr(active_engine, "provider_name", "qwen_vision")
        )

    @classmethod
    def extract_text_with_page_markers(
        cls,
        pdf_path: str,
        engine: Optional[BaseOCREngine] = None,
        dpi: int = DEFAULT_DPI,
        max_workers: Optional[int] = None,
    ) -> str:
        """Trích xuất văn bản gắn thẻ [PAGE X] từ tài liệu PDF quét/ảnh.

        Đây là giao diện drop-in trực tiếp tương thích hoàn toàn với LegalDocumentExtractor.extract().
        """
        doc_result = cls.extract_document(pdf_path, engine=engine, dpi=dpi, max_workers=max_workers)
        return doc_result.tagged_text
