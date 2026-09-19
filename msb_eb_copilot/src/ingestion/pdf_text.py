# -*- coding: utf-8 -*-
"""
Module: msb_eb_copilot.src.ingestion.pdf_text
Mô tả: Tầng bóc tách văn bản từ tài liệu PDF kỹ thuật số (Digital/Text-based PDF Ingestion).
Chuyển đổi tệp PDF thành văn bản có thẻ trang [PAGE X] tiền định, tương thích trực tiếp
với LegalDocumentExtractor.
"""

import os
from typing import List, Optional
import pypdf


# ==============================================================================
# HIERARCHY NGOẠI LỆ PDF INGESTION (TYPED INGESTION EXCEPTIONS)
# ==============================================================================
class PDFIngestionError(Exception):
    """Ngoại lệ cơ sở cho tầng bóc tách file PDF."""
    pass


class PDFFileNotFoundError(PDFIngestionError):
    """Ngoại lệ khi đường dẫn tệp PDF không tồn tại hoặc không phải là file hợp lệ."""
    pass


class PDFEncryptedError(PDFIngestionError):
    """Ngoại lệ khi tệp PDF bị khóa/mã hóa bằng mật khẩu."""
    pass


class PDFNoTextError(PDFIngestionError):
    """Ngoại lệ khi tài liệu PDF hoàn toàn không có nội dung văn bản kỹ thuật số (empty/scanned)."""
    pass


class PDFBlankPageError(PDFNoTextError):
    """Ngoại lệ khi phát hiện trang trắng, trang scan hình ảnh, hoặc trang không có ký tự chữ/số."""
    pass


# ==============================================================================
# BỘ BÓC TÁCH VĂN BẢN TỪ FILE PDF (PDF TEXT INGESTOR)
# ==============================================================================
class PDFTextIngestor:
    """Bóc tách văn bản từ tệp PDF kỹ thuật số theo hợp đồng phân tách trang [PAGE X].
    
    Hợp đồng bảo toàn văn bản (Preservation Contract):
    - Bảo toàn nguyên văn nội dung văn bản mà pypdf.extract_text() trích xuất được.
    - Chỉ chuẩn hóa ký tự xuống dòng (\r\n -> \n, \r -> \n) và cắt khoảng trắng đầu/cuối trang.
    - Không viết lại ngữ nghĩa, không sửa chính tả, không chuẩn hóa số liệu, không dọn dẹp bằng AI/LLM.
    - Không tuyên bố tái tạo bố cục thị giác trực quan của PDF.
    
    Quy tắc khả dụng (Usable-Text Rule):
    - Mỗi trang bắt buộc phải chứa ít nhất 1 ký tự chữ hoặc số (Unicode alphanumeric: any(ch.isalnum())).
    - Nếu trang rỗng, chỉ chứa khoảng trắng hoặc chỉ có ký tự đặc biệt (ví dụ: '---', '•••'): ném PDFBlankPageError.
    """

    @classmethod
    def extract_page_text(cls, page: pypdf.PageObject, page_num: int = 1, total_pages: int = 1) -> Optional[str]:
        """Trích xuất văn bản từ một trang pypdf cụ thể theo Preservation Contract.

        Trả về chuỗi văn bản đã chuẩn hóa nếu có ít nhất 1 ký tự chữ hoặc số khả dụng.
        Trả về None nếu trang rỗng, chỉ chứa khoảng trắng hoặc chỉ có ký tự đặc biệt.

        Args:
            page: Đối tượng trang pypdf.PageObject.
            page_num: Số thứ tự trang vật lý 1-based (dùng cho thông báo lỗi).
            total_pages: Tổng số trang (dùng cho thông báo lỗi).

        Returns:
            Chuỗi văn bản đã chuẩn hóa (\r\n -> \n, \r -> \n, strip), hoặc None nếu không có text khả dụng.

        Raises:
            PDFIngestionError: Khi xảy ra lỗi đọc từ page.extract_text().
        """
        try:
            raw_text = page.extract_text()
        except Exception as e:
            raise PDFIngestionError(f"Lỗi khi trích xuất văn bản từ trang {page_num}/{total_pages}: {e}") from e

        if raw_text is None:
            raw_text = ""

        normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
        has_usable_character = any(ch.isalnum() for ch in normalized)
        if not normalized or not has_usable_character:
            return None

        return normalized

    @classmethod
    def extract_text_with_page_markers(cls, pdf_path: str) -> str:
        """Đọc tệp PDF kỹ thuật số và trả về chuỗi văn bản phân tách trang [PAGE 1], [PAGE 2], ...

        Args:
            pdf_path: Đường dẫn tới file PDF.

        Returns:
            Chuỗi văn bản bắt đầu trực tiếp bằng [PAGE 1] (zero non-whitespace preamble).

        Raises:
            PDFFileNotFoundError: Khi file không tồn tại hoặc không phải là file.
            PDFEncryptedError: Khi file bị mã hóa/cài mật khẩu.
            PDFNoTextError: Khi file PDF có 0 trang.
            PDFBlankPageError: Khi bất kỳ trang nào không có ký tự chữ/số khả dụng.
            PDFIngestionError: Khi gặp lỗi cú pháp nhị phân hoặc lỗi đọc trang.
        """
        # 1. Kiểm tra sự tồn tại của file
        if not os.path.exists(pdf_path) or not os.path.isfile(pdf_path):
            raise PDFFileNotFoundError(f"Tệp PDF không tồn tại hoặc không phải là file: {pdf_path}")

        # 2. Khởi tạo pypdf reader
        try:
            reader = pypdf.PdfReader(pdf_path)
        except Exception as e:
            raise PDFIngestionError(f"Không thể mở tệp PDF do lỗi định dạng hoặc tệp bị hỏng: {e}") from e

        # 3. Kiểm tra mã hóa / mật khẩu (Fail immediately)
        if reader.is_encrypted:
            raise PDFEncryptedError(f"Tệp PDF đã bị mã hóa hoặc cài đặt mật khẩu bảo vệ: {pdf_path}")

        # 4. Kiểm tra số lượng trang
        total_pages = len(reader.pages)
        if total_pages == 0:
            raise PDFNoTextError(f"Tệp PDF không chứa bất kỳ trang nào: {pdf_path}")

        page_blocks: List[str] = []

        # 5. Duyệt tuần tự từng trang từ 1 đến N (1-based index)
        for idx, page in enumerate(reader.pages, start=1):
            normalized = cls.extract_page_text(page, page_num=idx, total_pages=total_pages)
            if normalized is None:
                raise PDFBlankPageError(
                    f"Trang {idx}/{total_pages} của tệp PDF không chứa văn bản kỹ thuật số hợp lệ "
                    f"(trang trắng, trang scan hình ảnh, hoặc chỉ chứa ký tự đặc biệt)."
                )

            # Đóng gói thẻ [PAGE X]
            page_blocks.append(f"[PAGE {idx}]\n{normalized}")

        # Ghép các trang lại với nhau; bắt đầu trực tiếp bằng [PAGE 1] (không có khoảng trắng phía trước)
        return "\n\n".join(page_blocks)
