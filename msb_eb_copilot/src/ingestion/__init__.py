# -*- coding: utf-8 -*-
"""Package ingestion: PDF text and OCR document ingestion layers."""

from msb_eb_copilot.src.ingestion.pdf_text import (
    PDFTextIngestor,
    PDFIngestionError,
    PDFFileNotFoundError,
    PDFEncryptedError,
    PDFNoTextError,
    PDFBlankPageError,
)
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
)
from msb_eb_copilot.src.ingestion.router import (
    DocumentIngestionRouter,
    DocumentIngestionResult,
)

__all__ = [
    "PDFTextIngestor",
    "PDFIngestionError",
    "PDFFileNotFoundError",
    "PDFEncryptedError",
    "PDFNoTextError",
    "PDFBlankPageError",
    "PDFOCRIngestor",
    "BaseOCREngine",
    "QwenVisionOCREngine",
    "OCRPageResult",
    "OCRDocumentResult",
    "OCRIngestionError",
    "OCRFileNotFoundError",
    "OCREncryptedError",
    "OCRRenderError",
    "OCRServiceError",
    "OCRTimeoutError",
    "OCRNoTextError",
    "OCRPageCountError",
    "DocumentIngestionRouter",
    "DocumentIngestionResult",
]
