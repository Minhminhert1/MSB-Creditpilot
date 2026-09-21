# -*- coding: utf-8 -*-
"""
Module: router.py
Mô tả: Bộ điều hướng nhập liệu tài liệu PDF (DocumentIngestionRouter).
Cung cấp một điểm vào (entry point) duy nhất cho việc tiếp nhận tệp PDF:
1. Thử nghiệm trích xuất văn bản kỹ thuật số (Digital Text) bằng PDFTextIngestor trước tiên.
2. Chỉ chuyển hướng sang OCR fallback (PDFOCRIngestor) khi phát hiện trang ảnh/quét
   thông qua lỗi PDFBlankPageError.
3. Không fallback và giữ nguyên lan truyền các ngoại lệ:
   - PDFFileNotFoundError (tệp không tồn tại)
   - PDFEncryptedError (tệp bị khóa mật khẩu)
   - PDFNoTextError thông thường (tệp 0 trang)
   - PDFIngestionError thông thường (tệp hỏng)
4. Mọi ngoại lệ OCR (OCRTimeoutError, OCRServiceError,...) khi fallback đều được lan truyền trung thực.
5. Cung cấp metadata nguồn gốc xác thực (DocumentIngestionResult) lấy từ nguồn chân lý (Source of Truth).
"""

import os
from typing import Callable, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

import pypdf
import pypdfium2 as pdfium

from msb_eb_copilot.src.ingestion.pdf_text import (
    PDFTextIngestor,
    PDFBlankPageError,
    PDFNoTextError,
    PDFFileNotFoundError,
    PDFEncryptedError,
    PDFIngestionError,
)
from msb_eb_copilot.src.ingestion.pdf_ocr import (
    PDFOCRIngestor,
    BaseOCREngine,
    QwenVisionOCREngine,
    OCRDocumentResult,
    OCRFailedPageInfo,
    OCRTimeoutError,
    OCRServiceError,
    OCRIngestionError,
    OCRRenderError,
    OCRNoTextError,
    OCRPageCountError,
    OCR_UNREADABLE_PAGE_MARKER,
)


class DocumentIngestionResult(BaseModel):
    """Kết quả hoàn chỉnh của quá trình nhập liệu tài liệu PDF."""
    tagged_text: str = Field(
        ...,
        description="Chuỗi văn bản định dạng thẻ [PAGE X] chuẩn hợp đồng không bị chèn metadata"
    )
    mode: Literal["digital", "ocr", "hybrid"] = Field(
        ...,
        description="Chế độ xử lý thành công: 'digital', 'ocr' hoặc 'hybrid'"
    )
    page_count: int = Field(
        ...,
        description="Tổng số trang vật lý của tài liệu được xác định từ nguồn chân lý"
    )
    fallback_reason: Optional[str] = Field(
        default=None,
        description="Tên lớp ngoại lệ kích hoạt OCR fallback (chỉ có khi mode='ocr' hoặc mode='hybrid', ví dụ: 'PDFBlankPageError')"
    )
    provider: Optional[str] = Field(
        default=None,
        description="Tên định danh của engine trích xuất thành công ('pypdf', OCR provider, hoặc 'pypdf+{ocr_provider}')"
    )
    failed_pages: List[OCRFailedPageInfo] = Field(
        default_factory=list,
        description="Các trang OCR được dung thứ là không đọc được sau khi hết mọi lần thử lại "
                    "-- CHỈ khác rỗng khi caller truyền max_failed_pages (hiện tại: chỉ luồng OCR tài chính)."
    )


class DocumentIngestionRouter:
    """Bộ điều hướng nhập liệu tài liệu PDF cấp tài liệu (Document-Level Router)."""

    DEFAULT_DPI: int = 150

    @classmethod
    def ingest_document(
        cls,
        pdf_path: str,
        ocr_engine: Optional[BaseOCREngine] = None,
        dpi: int = DEFAULT_DPI,
        max_workers: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
        max_failed_pages: Optional[int] = None,
    ) -> DocumentIngestionResult:
        """Nhập liệu tệp PDF với chính sách ưu tiên digital text, chỉ fallback sang OCR khi cần thiết.

        Args:
            pdf_path: Đường dẫn tuyệt đối hoặc tương đối tới tệp PDF.
            ocr_engine: Engine OCR tùy chọn (mặc định khởi tạo QwenVisionOCREngine).
            dpi: Độ phân giải rasterize trang khi kích hoạt OCR fallback (mặc định 150).
            max_workers: Số luồng OCR song song tối đa (mặc định đọc từ OCR_MAX_WORKERS hoặc 4, bounded [1, 8]).
            progress_callback: Tùy chọn, chuyển tiếp thẳng xuống PDFOCRIngestor khi cần
                OCR fallback -- gọi lại (page_num, completed_count, total_pages) sau mỗi
                trang OCR hoàn tất. Không tác động tới đường đi digital-only (không OCR).
            max_failed_pages: Tùy chọn (mặc định None -- giữ NGUYÊN hành vi hiện tại, bất
                kỳ trang lỗi nào cũng làm hỏng toàn bộ). Khi được truyền (hiện tại: CHỈ
                luồng OCR tài chính), bật chế độ dung thứ trang lỗi -- xem
                PDFOCRIngestor.ocr_pages_parallel/extract_document để biết chi tiết.
                Không tác động tới đường đi digital-only, và không thay đổi hành vi
                legal/business/CIC (các luồng đó không truyền tham số này).

        Returns:
            DocumentIngestionResult chứa tagged_text và metadata nguồn gốc.

        Raises:
            PDFFileNotFoundError: Khi tệp không tồn tại hoặc là thư mục.
            PDFEncryptedError: Khi tệp PDF bị khóa bằng mật khẩu.
            PDFNoTextError: Khi tệp PDF có 0 trang (không fallback).
            PDFIngestionError: Khi tệp PDF bị hỏng hoặc lỗi cú pháp.
            OCRTimeoutError: Khi OCR fallback vượt quá thời gian chờ.
            OCRServiceError: Khi dịch vụ OCR gặp sự cố mạng hoặc lỗi máy chủ.
        """
        try:
            # 1. Thử nghiệm trích xuất văn bản kỹ thuật số (Digital-first attempt)
            digital_text = PDFTextIngestor.extract_text_with_page_markers(pdf_path)

            # Lấy số trang vật lý trực tiếp từ nguồn chân lý pypdf.PdfReader
            physical_page_count = len(pypdf.PdfReader(pdf_path).pages) if os.path.exists(pdf_path) else digital_text.count("[PAGE ")

            return DocumentIngestionResult(
                tagged_text=digital_text,
                mode="digital",
                page_count=physical_page_count,
                fallback_reason=None,
                provider="pypdf"
            )

        except PDFBlankPageError as exc:
            # Khi phát hiện trang trắng/scan ảnh trong tài liệu:
            # Nếu file không tồn tại trên đĩa (ví dụ trong mock tests): chuyển thẳng cho extract_document
            if not os.path.exists(pdf_path):
                ocr_result = PDFOCRIngestor.extract_document(
                    pdf_path,
                    engine=ocr_engine,
                    dpi=dpi,
                    max_workers=max_workers,
                    progress_callback=progress_callback,
                    max_failed_pages=max_failed_pages,
                )
                return DocumentIngestionResult(
                    tagged_text=ocr_result.tagged_text,
                    mode="ocr",
                    page_count=ocr_result.page_count,
                    fallback_reason=type(exc).__name__,
                    provider=ocr_result.provider,
                    failed_pages=ocr_result.failed_pages,
                )

            # Đánh giá chi tiết từng trang vật lý (Page-level evaluation)
            reader = pypdf.PdfReader(pdf_path)
            total_pages = len(reader.pages)
            if total_pages == 0:
                raise PDFNoTextError(f"Tệp PDF không chứa bất kỳ trang nào: {pdf_path}")

            digital_pages: Dict[int, str] = {}
            ocr_page_indices: List[int] = []

            for idx, page in enumerate(reader.pages, start=1):
                page_text = PDFTextIngestor.extract_page_text(page, page_num=idx, total_pages=total_pages)
                if page_text is not None:
                    digital_pages[idx] = page_text
                else:
                    ocr_page_indices.append(idx)

            active_engine = ocr_engine or QwenVisionOCREngine()

            # TRƯỜNG HỢP A: Toàn bộ các trang đều cần OCR (ALL SCANNED)
            if len(ocr_page_indices) == total_pages:
                ocr_result = PDFOCRIngestor.extract_document(
                    pdf_path,
                    engine=active_engine,
                    dpi=dpi,
                    max_workers=max_workers,
                    progress_callback=progress_callback,
                    max_failed_pages=max_failed_pages,
                )
                return DocumentIngestionResult(
                    tagged_text=ocr_result.tagged_text,
                    mode="ocr",
                    page_count=ocr_result.page_count,
                    fallback_reason=type(exc).__name__,
                    provider=ocr_result.provider,
                    failed_pages=ocr_result.failed_pages,
                )

            # TRƯỜNG HỢP B: Hỗn hợp (HYBRID: một số trang digital, một số trang cần OCR)
            try:
                pdfium_doc = pdfium.PdfDocument(pdf_path)
                try:
                    actual_pdfium_page_count = len(pdfium_doc)
                    if actual_pdfium_page_count != total_pages:
                        raise OCRPageCountError(
                            f"Bất đồng số trang vật lý: pypdf xác nhận {total_pages} trang, "
                            f"nhưng PDFium phát hiện {actual_pdfium_page_count} trang."
                        )
                finally:
                    pdfium_doc.close()
            except OCRPageCountError:
                raise
            except Exception as render_exc:
                raise OCRRenderError(f"Không thể mở tài liệu bằng PDFium: {str(render_exc)}") from render_exc

            # Thực hiện OCR song song có giới hạn CHỈ cho các trang trong ocr_page_indices
            failed_pages: List[OCRFailedPageInfo] = []
            ocr_pages_result = PDFOCRIngestor.ocr_pages_parallel(
                pdf_path=pdf_path,
                page_nums=ocr_page_indices,
                engine=active_engine,
                dpi=dpi,
                max_workers=max_workers,
                progress_callback=progress_callback,
                max_failed_pages=max_failed_pages,
                failed_pages_out=failed_pages,
            )
            ocr_pages = {p_num: res.text for p_num, res in ocr_pages_result.items()}
            failed_page_num_set = {fp.page for fp in failed_pages}

            # Bất biến số trang: Lắp ráp tất định theo đúng thứ tự trang vật lý 1..N.
            # Trang lỗi (dung thứ) dùng marker tất định OCR_UNREADABLE_PAGE_MARKER --
            # TUYỆT ĐỐI KHÔNG bịa đặt nội dung, KHÔNG bỏ qua thẻ [PAGE X].
            assembled_blocks: List[str] = []
            for idx in range(1, total_pages + 1):
                if idx in digital_pages:
                    assembled_blocks.append(f"[PAGE {idx}]\n{digital_pages[idx]}")
                elif idx in ocr_pages:
                    assembled_blocks.append(f"[PAGE {idx}]\n{ocr_pages[idx]}")
                elif idx in failed_page_num_set:
                    assembled_blocks.append(f"[PAGE {idx}]\n{OCR_UNREADABLE_PAGE_MARKER}")
                else:
                    raise OCRPageCountError(f"Thiếu nội dung trang {idx} trong quá trình tổng hợp hybrid.")

            ocr_provider_name = getattr(active_engine, "provider_name", "qwen_vision")
            return DocumentIngestionResult(
                tagged_text="\n\n".join(assembled_blocks),
                mode="hybrid",
                page_count=total_pages,
                fallback_reason=type(exc).__name__,
                provider=f"pypdf+{ocr_provider_name}",
                failed_pages=failed_pages,
            )

        except (PDFNoTextError, PDFFileNotFoundError, PDFEncryptedError, PDFIngestionError):
            # Các lỗi tiền kiểm tra, tệp 0 trang, tệp mã hóa hoặc hỏng cú pháp:
            # Lan truyền trung thực, TUYỆT ĐỐI KHÔNG fallback sang OCR
            raise

    @classmethod
    def ingest_to_tagged_text(
        cls,
        pdf_path: str,
        ocr_engine: Optional[BaseOCREngine] = None,
        dpi: int = DEFAULT_DPI,
        max_workers: Optional[int] = None,
    ) -> str:
        """Giao diện tiện ích: Trả về trực tiếp chuỗi văn bản [PAGE X] sạch.

        Tương thích trực tiếp để truyền thẳng vào LegalDocumentExtractor.extract().
        """
        result = cls.ingest_document(pdf_path, ocr_engine=ocr_engine, dpi=dpi, max_workers=max_workers)
        return result.tagged_text
