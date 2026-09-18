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

from typing import Literal, Optional
from pydantic import BaseModel, Field

import pypdf

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
    OCRDocumentResult,
    OCRTimeoutError,
    OCRServiceError,
    OCRIngestionError,
)


class DocumentIngestionResult(BaseModel):
    """Kết quả hoàn chỉnh của quá trình nhập liệu tài liệu PDF."""
    tagged_text: str = Field(
        ...,
        description="Chuỗi văn bản định dạng thẻ [PAGE X] chuẩn hợp đồng không bị chèn metadata"
    )
    mode: Literal["digital", "ocr"] = Field(
        ...,
        description="Chế độ xử lý thành công: 'digital' hoặc 'ocr'"
    )
    page_count: int = Field(
        ...,
        description="Tổng số trang vật lý của tài liệu được xác định từ nguồn chân lý"
    )
    fallback_reason: Optional[str] = Field(
        default=None,
        description="Tên lớp ngoại lệ kích hoạt OCR fallback (chỉ có khi mode='ocr', ví dụ: 'PDFBlankPageError')"
    )
    provider: Optional[str] = Field(
        default=None,
        description="Tên định danh của engine trích xuất thành công ('pypdf' hoặc provider từ OCRDocumentResult)"
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
    ) -> DocumentIngestionResult:
        """Nhập liệu tệp PDF với chính sách ưu tiên digital text, chỉ fallback sang OCR khi cần thiết.
        
        Args:
            pdf_path: Đường dẫn tuyệt đối hoặc tương đối tới tệp PDF.
            ocr_engine: Engine OCR tùy chọn (mặc định khởi tạo QwenVisionOCREngine).
            dpi: Độ phân giải rasterize trang khi kích hoạt OCR fallback (mặc định 150).
            
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
            reader = pypdf.PdfReader(pdf_path)
            physical_page_count = len(reader.pages)

            return DocumentIngestionResult(
                tagged_text=digital_text,
                mode="digital",
                page_count=physical_page_count,
                fallback_reason=None,
                provider="pypdf"
            )

        except PDFBlankPageError as exc:
            # CORRECTION 1: Chỉ fallback sang OCR khi gặp PDFBlankPageError
            # (bao gồm PDF quét hoàn toàn, PDF hỗn hợp có trang quét/ảnh, hoặc trang trắng)
            ocr_result = PDFOCRIngestor.extract_document(
                pdf_path,
                engine=ocr_engine,
                dpi=dpi
            )

            # CORRECTION 2: Trích xuất metadata trực tiếp từ đối tượng kết quả OCRDocumentResult
            return DocumentIngestionResult(
                tagged_text=ocr_result.tagged_text,
                mode="ocr",
                page_count=ocr_result.page_count,
                fallback_reason=type(exc).__name__,
                provider=ocr_result.provider
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
    ) -> str:
        """Giao diện tiện ích: Trả về trực tiếp chuỗi văn bản [PAGE X] sạch.
        
        Tương thích trực tiếp để truyền thẳng vào LegalDocumentExtractor.extract().
        """
        result = cls.ingest_document(pdf_path, ocr_engine=ocr_engine, dpi=dpi)
        return result.tagged_text
