"""Tests for generic Document Intake and Registration foundation (Phase 3)."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
import unittest

from msb_eb_copilot.src.document_intake import (
    CaseDocument,
    DocumentRegistrationResult,
    InMemoryDocumentRegistry,
    ProcessingStatus,
    RegistrationOutcome,
)


class DocumentIntakeFoundationTests(unittest.TestCase):
    """Test suite for Phase 3 document intake domain models and registry."""

    def setUp(self) -> None:
        self.registry = InMemoryDocumentRegistry()
        self.sample_sha256_a = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        self.sample_sha256_b = "ca60127f5a8a97a6b345cca3bb110cbfb8cb4a438d589131fe5b929e8be8f68b"
        self.sample_sha256_c = "8ad7df9c967e1686f64302f74a45c8f1c72ae9c2ce459e74484343e2d3579714"

    def test_successful_registration(self):
        result = self.registry.register_document(
            case_id="case-001",
            original_filename="financial_report_2025.xlsx",
            checksum_sha256=self.sample_sha256_a,
            storage_reference="/storage/cases/case-001/doc_001.xlsx",
            mime_type_hint="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            metadata={"file_size_bytes": 102400},
        )
        self.assertIsInstance(result, DocumentRegistrationResult)
        self.assertEqual(result.outcome, RegistrationOutcome.NEW_DOCUMENT)
        self.assertFalse(result.is_duplicate)
        self.assertIsNone(result.message)

        doc = result.document
        self.assertEqual(doc.case_id, "case-001")
        self.assertEqual(doc.original_filename, "financial_report_2025.xlsx")
        self.assertEqual(doc.checksum_sha256, self.sample_sha256_a)
        self.assertEqual(doc.storage_reference, "/storage/cases/case-001/doc_001.xlsx")
        self.assertEqual(
            doc.mime_type_hint,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(doc.processing_status, ProcessingStatus.REGISTERED)
        self.assertEqual(doc.metadata, {"file_size_bytes": 102400})
        self.assertIsInstance(doc.registered_at, datetime)
        self.assertEqual(len(self.registry), 1)

    def test_immutability_of_case_document(self):
        result = self.registry.register_document(
            case_id="case-001",
            original_filename="scan001.pdf",
            checksum_sha256=self.sample_sha256_a,
            storage_reference="/storage/scan001.pdf",
        )
        doc = result.document
        with self.assertRaises(FrozenInstanceError):
            doc.processing_status = ProcessingStatus.PROCESSED  # type: ignore

    def test_required_fields_non_empty(self):
        now = datetime.now(timezone.utc)
        invalid_cases = (
            ("", "case-001", "file.pdf", self.sample_sha256_a, "/ref"),
            ("   ", "case-001", "file.pdf", self.sample_sha256_a, "/ref"),
            ("doc-1", "", "file.pdf", self.sample_sha256_a, "/ref"),
            ("doc-1", "case-001", "", self.sample_sha256_a, "/ref"),
            ("doc-1", "case-001", "file.pdf", self.sample_sha256_a, ""),
        )
        for doc_id, case_id, filename, checksum, ref in invalid_cases:
            with self.subTest(doc_id=doc_id, case_id=case_id, filename=filename, ref=ref):
                with self.assertRaises(ValueError):
                    CaseDocument(
                        document_id=doc_id,
                        case_id=case_id,
                        original_filename=filename,
                        checksum_sha256=checksum,
                        storage_reference=ref,
                        registered_at=now,
                    )

    def test_type_validations_on_document_model(self):
        valid_args = {
            "document_id": "doc-01",
            "case_id": "case-001",
            "original_filename": "doc.pdf",
            "checksum_sha256": self.sample_sha256_a,
            "storage_reference": "/ref/doc.pdf",
            "registered_at": datetime.now(timezone.utc),
        }

        # invalid registered_at
        with self.assertRaises(TypeError):
            CaseDocument(**{**valid_args, "registered_at": "2026-09-12T00:00:00"})  # type: ignore

        # invalid processing_status
        with self.assertRaises(TypeError):
            CaseDocument(**{**valid_args, "processing_status": "REGISTERED"})  # type: ignore

        # invalid metadata
        with self.assertRaises(TypeError):
            CaseDocument(**{**valid_args, "metadata": ["not", "a", "dict"]})  # type: ignore

    def test_sha256_normalization_and_validation(self):
        # Uppercase sha256 normalized to lowercase
        upper_sha = self.sample_sha256_a.upper()
        doc = CaseDocument(
            document_id="doc-01",
            case_id="case-001",
            original_filename="doc.pdf",
            checksum_sha256=upper_sha,
            storage_reference="/ref/doc.pdf",
            registered_at=datetime.now(timezone.utc),
        )
        self.assertEqual(doc.checksum_sha256, self.sample_sha256_a)

        # Rejection of invalid checksums
        invalid_checksums = (
            "not-a-hash",
            "12345",
            self.sample_sha256_a[:63],  # 63 chars (too short)
            self.sample_sha256_a + "a",  # 65 chars (too long)
            "g" * 64,  # invalid hex char 'g'
            "",
            1234567890,
        )
        for invalid in invalid_checksums:
            with self.subTest(invalid=invalid):
                with self.assertRaises((ValueError, TypeError)):
                    CaseDocument(
                        document_id="doc-01",
                        case_id="case-001",
                        original_filename="doc.pdf",
                        checksum_sha256=invalid,  # type: ignore
                        storage_reference="/ref/doc.pdf",
                        registered_at=datetime.now(timezone.utc),
                    )

    def test_duplicate_detection_same_case_same_checksum(self):
        """Rule: For the same case and same checksum, duplicate content is detected.

        Does not create a second document record, returns typed result identifying existing doc.
        """
        first_result = self.registry.register_document(
            case_id="case-001",
            original_filename="bctc_2025.pdf",
            checksum_sha256=self.sample_sha256_a,
            storage_reference="/storage/case-001/bctc_2025.pdf",
        )
        self.assertEqual(first_result.outcome, RegistrationOutcome.NEW_DOCUMENT)
        self.assertFalse(first_result.is_duplicate)
        original_doc_id = first_result.document.document_id

        # Register again with same case and same checksum (even if filename differs)
        second_result = self.registry.register_document(
            case_id="case-001",
            original_filename="bctc_2025_copy.pdf",
            checksum_sha256=self.sample_sha256_a,
            storage_reference="/storage/case-001/bctc_2025_copy.pdf",
        )
        self.assertEqual(second_result.outcome, RegistrationOutcome.DUPLICATE_CONTENT)
        self.assertTrue(second_result.is_duplicate)
        self.assertIn("Duplicate content detected", second_result.message or "")
        self.assertEqual(second_result.document.document_id, original_doc_id)

        # Registry should still only contain 1 document
        self.assertEqual(len(self.registry), 1)
        case_docs = self.registry.list_documents_for_case("case-001")
        self.assertEqual(len(case_docs), 1)

    def test_non_duplicate_same_case_different_checksum_same_filename(self):
        """Rule: Same case and same filename but different checksum is NOT a duplicate."""
        res_v1 = self.registry.register_document(
            case_id="case-001",
            original_filename="bctc.xlsx",
            checksum_sha256=self.sample_sha256_a,
            storage_reference="/storage/v1/bctc.xlsx",
        )
        res_v2 = self.registry.register_document(
            case_id="case-001",
            original_filename="bctc.xlsx",
            checksum_sha256=self.sample_sha256_b,
            storage_reference="/storage/v2/bctc.xlsx",
        )
        self.assertEqual(res_v1.outcome, RegistrationOutcome.NEW_DOCUMENT)
        self.assertEqual(res_v2.outcome, RegistrationOutcome.NEW_DOCUMENT)
        self.assertNotEqual(res_v1.document.document_id, res_v2.document.document_id)
        self.assertEqual(len(self.registry.list_documents_for_case("case-001")), 2)

    def test_cross_case_isolation_same_checksum_different_cases(self):
        """Rule: Different cases and same checksum is NOT duplicate; no cross-case leakage."""
        res_case_a = self.registry.register_document(
            case_id="case-AAA",
            original_filename="annual_report.pdf",
            checksum_sha256=self.sample_sha256_a,
            storage_reference="/storage/case-AAA/annual_report.pdf",
        )
        res_case_b = self.registry.register_document(
            case_id="case-BBB",
            original_filename="annual_report.pdf",
            checksum_sha256=self.sample_sha256_a,
            storage_reference="/storage/case-BBB/annual_report.pdf",
        )
        self.assertEqual(res_case_a.outcome, RegistrationOutcome.NEW_DOCUMENT)
        self.assertEqual(res_case_b.outcome, RegistrationOutcome.NEW_DOCUMENT)
        self.assertNotEqual(res_case_a.document.document_id, res_case_b.document.document_id)
        self.assertEqual(res_case_a.document.case_id, "case-AAA")
        self.assertEqual(res_case_b.document.case_id, "case-BBB")

        # Checklists for each case remain completely separated
        self.assertEqual(len(self.registry.list_documents_for_case("case-AAA")), 1)
        self.assertEqual(len(self.registry.list_documents_for_case("case-BBB")), 1)
        self.assertEqual(
            self.registry.list_documents_for_case("case-AAA")[0].document_id,
            res_case_a.document.document_id,
        )
        self.assertEqual(
            self.registry.list_documents_for_case("case-BBB")[0].document_id,
            res_case_b.document.document_id,
        )

    def test_list_documents_for_case_ordering_and_isolation(self):
        self.registry.register_document("case-X", "doc1.pdf", self.sample_sha256_a, "/ref1")
        self.registry.register_document("case-Y", "doc2.pdf", self.sample_sha256_b, "/ref2")
        self.registry.register_document("case-X", "doc3.pdf", self.sample_sha256_c, "/ref3")

        docs_x = self.registry.list_documents_for_case("case-X")
        self.assertEqual(len(docs_x), 2)
        self.assertEqual(docs_x[0].original_filename, "doc1.pdf")
        self.assertEqual(docs_x[1].original_filename, "doc3.pdf")

        docs_y = self.registry.list_documents_for_case("case-Y")
        self.assertEqual(len(docs_y), 1)
        self.assertEqual(docs_y[0].original_filename, "doc2.pdf")

        # Empty case returns empty list
        self.assertEqual(self.registry.list_documents_for_case("case-Z"), [])

    def test_get_document_and_find_by_checksum(self):
        res = self.registry.register_document(
            case_id="case-100",
            original_filename="charter.pdf",
            checksum_sha256=self.sample_sha256_a,
            storage_reference="/ref/charter.pdf",
        )
        doc_id = res.document.document_id

        # Lookup by document_id
        found_by_id = self.registry.get_document(doc_id)
        self.assertIsNotNone(found_by_id)
        self.assertEqual(found_by_id.original_filename, "charter.pdf")

        # Non-existent ID returns None
        self.assertIsNone(self.registry.get_document("non-existent-id"))

        # Find by checksum within case
        found_by_hash = self.registry.find_by_checksum("case-100", self.sample_sha256_a)
        self.assertIsNotNone(found_by_hash)
        self.assertEqual(found_by_hash.document_id, doc_id)

        # Find by checksum in wrong case returns None
        self.assertIsNone(self.registry.find_by_checksum("wrong-case", self.sample_sha256_a))

    def test_update_status(self):
        res = self.registry.register_document(
            case_id="case-001",
            original_filename="doc.pdf",
            checksum_sha256=self.sample_sha256_a,
            storage_reference="/ref/doc.pdf",
        )
        doc_id = res.document.document_id
        self.assertEqual(res.document.processing_status, ProcessingStatus.REGISTERED)

        updated = self.registry.update_status(doc_id, ProcessingStatus.PENDING)
        self.assertEqual(updated.processing_status, ProcessingStatus.PENDING)
        self.assertEqual(self.registry.get_document(doc_id).processing_status, ProcessingStatus.PENDING)

        updated_proc = self.registry.update_status(doc_id, ProcessingStatus.PROCESSED)
        self.assertEqual(updated_proc.processing_status, ProcessingStatus.PROCESSED)

        # Invalid document id raises KeyError
        with self.assertRaises(KeyError):
            self.registry.update_status("missing-id", ProcessingStatus.PROCESSED)

        # Invalid status type raises TypeError
        with self.assertRaises(TypeError):
            self.registry.update_status(doc_id, "PROCESSED")  # type: ignore

    def test_serialization_round_trip(self):
        now = datetime(2026, 9, 12, 15, 30, 45, tzinfo=timezone.utc)
        doc = CaseDocument(
            document_id="doc-12345",
            case_id="case-999",
            original_filename="dieu_le.pdf",
            checksum_sha256=self.sample_sha256_b,
            storage_reference="s3://bucket/cases/999/dieu_le.pdf",
            registered_at=now,
            mime_type_hint="application/pdf",
            processing_status=ProcessingStatus.PROCESSED,
            metadata={"source": "rm_upload", "page_count": 42},
        )
        serialized = doc.to_dict()
        self.assertIsInstance(serialized, dict)
        self.assertEqual(serialized["document_id"], "doc-12345")
        self.assertEqual(serialized["processing_status"], "PROCESSED")

        # JSON serializability check
        json_str = json.dumps(serialized)
        self.assertIsInstance(json_str, str)

        reconstructed = CaseDocument.from_dict(json.loads(json_str))
        self.assertEqual(reconstructed, doc)

    def test_reject_duplicate_explicit_document_id(self):
        self.registry.register_document(
            case_id="case-1",
            original_filename="f1.pdf",
            checksum_sha256=self.sample_sha256_a,
            storage_reference="/ref/1",
            document_id="fixed-id-001",
        )
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.registry.register_document(
                case_id="case-2",
                original_filename="f2.pdf",
                checksum_sha256=self.sample_sha256_b,
                storage_reference="/ref/2",
                document_id="fixed-id-001",
            )

    def test_case_id_cannot_be_empty_in_registry(self):
        with self.assertRaises(ValueError):
            self.registry.register_document(
                case_id="   ",
                original_filename="f.pdf",
                checksum_sha256=self.sample_sha256_a,
                storage_reference="/ref",
            )


if __name__ == "__main__":
    unittest.main()
