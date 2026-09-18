"""Tests for semantic document classification (Phase 4)."""

import unittest

from msb_eb_copilot.src.document_classification import (
    DocumentClass,
    DocumentClassificationResult,
    Modality,
    SemanticDocumentClassifier,
)


class SemanticDocumentClassifierTests(unittest.TestCase):
    """Test suite for semantic document classification and modality routing."""

    def setUp(self) -> None:
        self.classifier = SemanticDocumentClassifier(min_confidence_threshold=0.70)

    def test_enterprise_registration_classified_from_content_with_random_filename(self):
        """Rule: Do not depend on filenames. Even with scan001.pdf, content classifies as GPKD."""
        text = (
            "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
            "SỞ KẾ HOẠCH VÀ ĐẦU TƯ TỈNH BÀ RỊA - VŨNG TÀU\n"
            "PHÒNG ĐĂNG KÝ KINH DOANH\n"
            "GIẤY CHỨNG NHẬN ĐĂNG KÝ DOANH NGHIỆP\n"
            "Mã số doanh nghiệp: 3502269994\n"
            "Đăng ký thay đổi lần thứ 8 ngày 15/10/2024\n"
            "Tên công ty: CÔNG TY TNHH MTV THÉP MIỀN NAM - VNSTEEL\n"
            "Người đại diện theo pháp luật: NGUYỄN NGUYÊN NGỌC\n"
            "Vốn điều lệ: 900.000.000.000 đồng"
        )
        result = self.classifier.classify(
            document_id="doc-gpkd-01",
            text_content=text,
            original_filename="scan001.pdf",
        )
        self.assertEqual(result.document_class, DocumentClass.ENTERPRISE_REGISTRATION)
        self.assertEqual(result.modality, Modality.TEXT_PDF)
        self.assertGreaterEqual(result.confidence, 0.70)
        self.assertFalse(result.needs_rm_confirmation)
        self.assertIn("giấy chứng nhận đăng ký doanh nghiệp", result.detected_markers)

    def test_company_charter_classified_from_content(self):
        text = (
            "ĐIỀU LỆ CÔNG TY\n"
            "ĐIỀU LỆ TỔ CHỨC VÀ HOẠT ĐỘNG CỦA CÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM\n"
            "Căn cứ Luật Doanh nghiệp số 59/2020/QH14 được Quốc hội thông qua..."
        )
        result = self.classifier.classify(
            document_id="doc-charter-01",
            text_content=text,
            original_filename="abc.pdf",
        )
        self.assertEqual(result.document_class, DocumentClass.COMPANY_CHARTER)
        self.assertEqual(result.modality, Modality.TEXT_PDF)
        self.assertGreaterEqual(result.confidence, 0.70)
        self.assertFalse(result.needs_rm_confirmation)

    def test_audited_financial_statements_classified_from_content(self):
        text = (
            "BÁO CÁO TÀI CHÍNH ĐÃ ĐƯỢC KIỂM TOÁN\n"
            "BÁO CÁO KIỂM TOÁN ĐỘC LẬP\n"
            "Kính gửi: Các cổ đông và Hội đồng Quản trị\n"
            "Ý kiến của kiểm toán viên độc lập về Báo cáo tài chính hợp nhất..."
        )
        result = self.classifier.classify(
            document_id="doc-audit-01",
            text_content=text,
            original_filename="tailieu2024.pdf",
        )
        self.assertEqual(result.document_class, DocumentClass.AUDITED_FINANCIAL_STATEMENTS)
        self.assertEqual(result.modality, Modality.TEXT_PDF)
        self.assertGreaterEqual(result.confidence, 0.70)
        self.assertFalse(result.needs_rm_confirmation)

    def test_financial_workbook_mb09_classified_from_sheets_and_content(self):
        result = self.classifier.classify(
            document_id="doc-mb09-01",
            text_content="Bảng tính nhu cầu vốn lưu động và hạn mức cấp tín dụng theo TT39/NHNN",
            original_filename="data_export.xlsx",
            sheet_names=["MB09", "Vong_quay_VLD", "Chi_phi_KD"],
        )
        self.assertEqual(result.document_class, DocumentClass.FINANCIAL_WORKBOOK_MB09)
        self.assertEqual(result.modality, Modality.SPREADSHEET)
        self.assertGreaterEqual(result.confidence, 0.70)
        self.assertFalse(result.needs_rm_confirmation)

    def test_credit_report_cic_classified_from_content(self):
        text = (
            "NGÂN HÀNG NHÀ NƯỚC VIỆT NAM\n"
            "TRUNG TÂM THÔNG TIN TÍN DỤNG QUỐC GIA VIỆT NAM (CIC)\n"
            "BÁO CÁO QUAN HỆ TÍN DỤNG CỦA KHÁCH HÀNG DOANH NGHIỆP\n"
            "Tổng dư nợ tại các TCTD: 1.250.000.000 VND. Nhóm nợ cao nhất: Nhóm 1."
        )
        result = self.classifier.classify(
            document_id="doc-cic-01",
            text_content=text,
            original_filename="rpt_123456.pdf",
        )
        self.assertEqual(result.document_class, DocumentClass.CREDIT_INSTITUTION_REPORT_CIC)
        self.assertEqual(result.modality, Modality.TEXT_PDF)
        self.assertGreaterEqual(result.confidence, 0.70)
        self.assertFalse(result.needs_rm_confirmation)

    def test_scanned_image_pdf_detected_and_flags_ocr_needed(self):
        """Rule: Image-only PDFs without extracted text must be detected as SCANNED_IMAGE_PDF."""
        result = self.classifier.classify(
            document_id="doc-scan-01",
            text_content="",  # No text extracted by standard PDF parser
            original_filename="GPKD_scan.pdf",
            is_scanned_image_pdf=True,
        )
        self.assertEqual(result.modality, Modality.SCANNED_IMAGE_PDF)
        self.assertTrue(result.needs_rm_confirmation)
        self.assertIn("OCR", result.notes or "")

    def test_weak_filename_hint_only_yields_low_confidence_and_requires_confirmation(self):
        """Rule: Filename alone is only a weak hint, never sufficient for automatic high confidence."""
        result = self.classifier.classify(
            document_id="doc-weak-01",
            text_content="random generic body text without specific banking markers",
            original_filename="dieu_le_cong_ty_2024.pdf",
        )
        # Even though filename matched 'điều lệ công ty', confidence is capped and requires RM confirmation
        self.assertEqual(result.document_class, DocumentClass.COMPANY_CHARTER)
        self.assertLess(result.confidence, 0.70)
        self.assertTrue(result.needs_rm_confirmation)

    def test_unknown_document_handling(self):
        result = self.classifier.classify(
            document_id="doc-unk-01",
            text_content="Hello world this is an unclassified random document.",
            original_filename="notes.txt",
        )
        self.assertEqual(result.document_class, DocumentClass.UNKNOWN)
        self.assertEqual(result.confidence, 0.0)
        self.assertTrue(result.needs_rm_confirmation)

    def test_serialization_round_trip(self):
        res = DocumentClassificationResult(
            document_id="doc-test-99",
            document_class=DocumentClass.ENTERPRISE_REGISTRATION,
            modality=Modality.TEXT_PDF,
            confidence=0.85,
            detected_markers=("mã số doanh nghiệp", "vốn điều lệ"),
            needs_rm_confirmation=False,
            notes=None,
        )
        serialized = res.to_dict()
        self.assertEqual(serialized["document_class"], "ENTERPRISE_REGISTRATION")
        self.assertEqual(serialized["modality"], "TEXT_PDF")
        self.assertEqual(serialized["confidence"], 0.85)

        reconstructed = DocumentClassificationResult.from_dict(serialized)
        self.assertEqual(reconstructed, res)

    def test_validations_on_result_model(self):
        # Invalid confidence bounds
        with self.assertRaises(ValueError):
            DocumentClassificationResult(
                document_id="doc-1",
                document_class=DocumentClass.COMPANY_CHARTER,
                modality=Modality.TEXT_PDF,
                confidence=1.05,
            )
        # Invalid confidence type
        with self.assertRaises(TypeError):
            DocumentClassificationResult(
                document_id="doc-1",
                document_class=DocumentClass.COMPANY_CHARTER,
                modality=Modality.TEXT_PDF,
                confidence="0.8",  # type: ignore
            )


if __name__ == "__main__":
    unittest.main()
