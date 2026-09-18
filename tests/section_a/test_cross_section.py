"""Tests for Section E cross-section dependency contract (Phase 9)."""

from decimal import Decimal
import unittest

from msb_eb_copilot.src.section_a import SourceCategory
from msb_eb_copilot.src.section_a.cross_section import (
    SectionECreditReportData,
    SectionEDependencyConnector,
)
from msb_eb_copilot.src.section_a.review_session import SectionAReviewSession


class SectionECrossSectionTests(unittest.TestCase):
    """Test suite for Section E to Section A data linkage."""

    def setUp(self) -> None:
        self.session = SectionAReviewSession("case-test-01")
        self.connector = SectionEDependencyConnector()

    def test_initial_session_has_pending_dependencies(self):
        loan = self.session.get_fact("credit_relation.loan_outstanding_at_msb")
        total = self.session.get_fact("credit_relation.total_credit_exposure_at_msb")
        self.assertTrue(loan.pending_section_dependency)
        self.assertTrue(total.pending_section_dependency)
        self.assertIsNone(loan.value)
        self.assertIsNone(total.value)

    def test_linkage_resolves_pending_dependency(self):
        credit_data = SectionECreditReportData(
            loan_outstanding_at_msb=Decimal("350000"),
            total_credit_exposure_at_msb=Decimal("500000"),
            regulatory_limit_status="TRONG_GIOI_HAN",
            unit="triệu đồng",
        )
        self.connector.link_section_e_data(self.session, credit_data)

        loan = self.session.get_fact("credit_relation.loan_outstanding_at_msb")
        total = self.session.get_fact("credit_relation.total_credit_exposure_at_msb")
        limit_status = self.session.get_fact("credit_relation.regulatory_limit_status")

        # Must no longer be pending
        self.assertFalse(loan.pending_section_dependency)
        self.assertFalse(total.pending_section_dependency)

        # Source category must be CROSS_SECTION_LINKED
        self.assertEqual(loan.value.source_category, SourceCategory.CROSS_SECTION_LINKED)
        self.assertEqual(total.value.source_category, SourceCategory.CROSS_SECTION_LINKED)
        self.assertEqual(loan.value.value, Decimal("350000"))
        self.assertEqual(total.value.value, Decimal("500000"))

        # Regulatory limit status updated
        self.assertEqual(limit_status.value.value, "TRONG_GIOI_HAN")

    def test_credit_report_data_validations(self):
        # Negative amount rejected
        with self.assertRaises(ValueError):
            SectionECreditReportData(
                loan_outstanding_at_msb=Decimal("-100"),
                total_credit_exposure_at_msb=Decimal("500"),
            )

        # Exposure less than loan rejected
        with self.assertRaises(ValueError):
            SectionECreditReportData(
                loan_outstanding_at_msb=Decimal("500"),
                total_credit_exposure_at_msb=Decimal("400"),
            )

        # Invalid float rejected
        with self.assertRaises(TypeError):
            SectionECreditReportData(
                loan_outstanding_at_msb=100.5,  # type: ignore
                total_credit_exposure_at_msb=Decimal("200"),
            )


if __name__ == "__main__":
    unittest.main()
