"""Tests for Section A Document Renderer and End-to-End Pipeline (Phase 14)."""

import os
import shutil
import tempfile
import unittest
import docx
from docx.oxml.ns import qn

from msb_eb_copilot.src.section_a import (
    CandidateStatus,
    CanonicalFact,
    CanonicalValue,
    FactValueType,
    SourceCategory,
)
from msb_eb_copilot.src.section_a.renderer import (
    SectionARenderResult,
    SectionARenderer,
    SectionARenderingError,
)
from msb_eb_copilot.src.section_a.review_session import SectionAReviewSession
from msb_eb_copilot.src.template_verification import (
    AUTHORITATIVE_MB07_SHA256,
    MB07TemplateVerifier,
)


def _build_valid_populated_session(case_id: str = "CASE-RENDER-001") -> SectionAReviewSession:
    """Build a completely valid Section A review session passing all business rules."""
    session = SectionAReviewSession(case_id)

    # Document extracted & confirmed facts
    session.confirm_fact_with_rm("company.legal_name", "CÔNG TY CỔ PHẦN NÔNG SẢN SAO VÀNG")
    session.confirm_fact_with_rm("company.short_name", "SAO VANG AGRI")
    session.confirm_fact_with_rm("company.legal_type", "Công ty Cổ phần")
    session.confirm_fact_with_rm("company.group_name", "TẬP ĐOÀN SAO VÀNG")
    session.confirm_fact_with_rm("company.registered_address", "Số 123 Đường Nam Kỳ Khởi Nghĩa, Quận 1, TP. Hồ Chí Minh")
    session.confirm_fact_with_rm("company.registration_no", "0312345678")
    session.confirm_fact_with_rm("company.registration_issue_date", "15/06/2012")
    session.confirm_fact_with_rm("company.registration_issue_place", "Sở Kế hoạch và Đầu tư TP. Hồ Chí Minh")
    session.confirm_fact_with_rm("company.operation_start_date_or_year", "2012")
    session.confirm_fact_with_rm("company.legal_representative.name", "Nguyễn Văn Nam")
    session.confirm_fact_with_rm("company.legal_representative.title", "Chủ tịch HĐQT")

    # RM selected
    session.set_rm_selected("relationship.customer_status", "KH_HIEN_HUU")
    session.set_rm_selected("relationship.segment", "LC")
    session.set_rm_selected("compliance.restricted_credit_subject", "KHONG")
    session.set_rm_selected("compliance.esg_assessment_required", "BAT_BUOC_DANH_GIA")
    session.set_rm_selected("credit_relation.regulatory_limit_status", "TRONG_GIOI_HAN")
    session.set_rm_selected("approval.authority", "HĐTD&ĐT")
    session.set_rm_selected("proposal.request_type", "TAI_CAP")

    # RM provided
    session.set_rm_provided("relationship.cif", "CIF998877")
    session.set_rm_provided("proposal.credit_request_representative.name", "Lê Thị Thảo")
    session.set_rm_provided("proposal.credit_request_representative.title", "Giám đốc Điều hành")
    session.confirm_fact_with_rm("financial.latest_net_revenue", 680000, unit="triệu đồng")
    session.confirm_fact_with_rm("financial.latest_revenue_year", 2023)
    session.set_rm_provided("business.primary_industry.code_level_5", "01110")
    session.set_rm_provided("business.primary_industry.name", "Trồng lúa và ngũ cốc")
    session.set_rm_provided("business.primary_industry.revenue_share_pct", 80)
    session.set_rm_provided("business.main_products", ("Gạo ST25", "Bột mì sạch"))
    session.confirm_fact_with_rm("capital.registered_capital", 150000, unit="triệu đồng")
    session.confirm_fact_with_rm("capital.paid_in_capital", 150000, unit="triệu đồng")
    session.confirm_fact_with_rm("capital.paid_in_capital_as_of", "31/12/2023")
    session.set_rm_provided("internal_rating.case_id", "XHTD-2024-SV")
    session.set_rm_provided("internal_rating.grade", "AAA")
    from decimal import Decimal
    session.set_rm_provided("internal_rating.score", Decimal("92.5"))
    session.set_rm_provided("approval.existing_limit.total", 50000, unit="triệu đồng")
    session.set_rm_provided("approval.existing_limit.unsecured", 10000, unit="triệu đồng")
    session.set_rm_provided("approval.proposed_limit.total", 70000, unit="triệu đồng")
    session.set_rm_provided("approval.proposed_limit.unsecured", 15000, unit="triệu đồng")
    session.set_rm_provided("approval.aggregate_limit.total", 70000, unit="triệu đồng")
    session.set_rm_provided("approval.aggregate_limit.unsecured", 15000, unit="triệu đồng")
    session.set_rm_provided("approval.previous_approval_period", "06/2023")

    # Section E linked facts
    session.link_cross_section_fact("credit_relation.loan_outstanding_at_msb", 35000, unit="triệu đồng")
    session.link_cross_section_fact("credit_relation.total_credit_exposure_at_msb", 45000, unit="triệu đồng")

    return session


class SectionARendererTests(unittest.TestCase):
    """Test suite for Section A Document Renderer pipeline."""

    def setUp(self) -> None:
        self.repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        self.template_path = os.path.join(
            self.repo_root, "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - thực hiện rà soát - tái cấp.docx"
        )
        self.tmp_dir = tempfile.mkdtemp()
        self.output_path = os.path.join(self.tmp_dir, "rendered_proposal.docx")
        self.renderer = SectionARenderer()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_rendering_blocks_when_facts_invalid(self):
        empty_session = SectionAReviewSession("EMPTY-001")
        with self.assertRaises(SectionARenderingError) as ctx:
            self.renderer.render(
                empty_session.facts,
                self.template_path,
                self.output_path,
                skip_validation=False,
            )
        self.assertIn("Validation failed", str(ctx.exception))
        # Ensure output file was not left behind or partially corrupted
        self.assertFalse(os.path.exists(self.output_path))

    def test_rendering_blocks_when_template_invalid(self):
        fake_template = os.path.join(self.tmp_dir, "fake_template.docx")
        with open(fake_template, "wb") as f:
            f.write(b"not a valid template")

        valid_session = _build_valid_populated_session()
        with self.assertRaises(SectionARenderingError) as ctx:
            self.renderer.render(
                valid_session.facts,
                fake_template,
                self.output_path,
            )
        self.assertIn("Failed to verify template", str(ctx.exception))

    def test_render_valid_session_successfully(self):
        session = _build_valid_populated_session()
        result: SectionARenderResult = self.renderer.render(
            session.facts,
            self.template_path,
            self.output_path,
            skip_validation=False,
        )

        self.assertTrue(result.is_success)
        self.assertTrue(os.path.exists(result.output_path))
        self.assertGreater(len(result.fields_rendered), 35)
        self.assertEqual(
            set(result.unresolved_fields),
            {"relationship.segment_other_description", "financial.latest_revenue_year"},
        )

        # Source template must remain completely unchanged (immutable)
        actual_template_sha = MB07TemplateVerifier().compute_sha256(self.template_path)
        self.assertEqual(actual_template_sha, AUTHORITATIVE_MB07_SHA256)

        # Verify mutated document content
        rendered_doc = docx.Document(result.output_path)
        t1 = rendered_doc.tables[1]
        offset = 2 if len(t1.rows) == 32 else 0

        # Row 0 + offset: Legal name
        r0_cells = list(dict.fromkeys(t1.rows[0 + offset].cells))
        self.assertEqual(r0_cells[1].text, "CÔNG TY CỔ PHẦN NÔNG SẢN SAO VÀNG")

        # Row 1 + offset: Short name
        r1_cells = list(dict.fromkeys(t1.rows[1 + offset].cells))
        self.assertEqual(r1_cells[1].text, "SAO VANG AGRI")

        # Row 2 + offset: Legal type SDT dropdown
        row2 = t1.rows[2 + offset]
        sdt_nodes = row2._tr.xpath(".//w:sdtContent")
        self.assertGreater(len(sdt_nodes), 0)
        t_nodes = sdt_nodes[0].findall(".//" + qn("w:t"))
        self.assertEqual(t_nodes[0].text, "Công ty Cổ phần")
        # Ensure red placeholder color was removed
        colors = sdt_nodes[0].findall(".//" + qn("w:color"))
        self.assertEqual(len(colors), 0)

        # Row 3 + offset: Customer status checkbox & CIF
        r3_cells = list(dict.fromkeys(t1.rows[3 + offset].cells))
        self.assertIn("CIF998877", r3_cells[2].text)
        ffdata3 = t1.rows[3 + offset]._tr.xpath(".//w:ffData")
        if ffdata3:
            cb0 = ffdata3[0].find(qn("w:checkBox"))
            cb1 = ffdata3[1].find(qn("w:checkBox"))
            self.assertEqual(cb0.find(qn("w:checked")).get(qn("w:val")), "0")
            self.assertEqual(cb1.find(qn("w:checked")).get(qn("w:val")), "1")
        else:
            sdt3 = t1.rows[3 + offset]._tr.xpath(".//w:sdtContent")
            self.assertGreater(len(sdt3), 0)
            t_txt = "".join(sdt3[0].itertext())
            self.assertIn("KH hiện hữu", t_txt)

        # Row 15 + offset: Primary industry
        r15_cells = list(dict.fromkeys(t1.rows[15 + offset].cells))
        self.assertEqual(r15_cells[1].text, "01110")
        self.assertEqual(r15_cells[2].text, "Trồng lúa và ngũ cốc")
        self.assertIn("80%", r15_cells[3].text)

        # Row 16 + offset: Main products
        r16_cells = list(dict.fromkeys(t1.rows[16 + offset].cells))
        self.assertEqual(r16_cells[2].text, "Gạo ST25, Bột mì sạch")

        # Row 29 + offset: Request type checkbox / dropdown
        ffdata29 = t1.rows[29 + offset]._tr.xpath(".//w:ffData")
        if ffdata29:
            cb29_0 = ffdata29[0].find(qn("w:checkBox"))
            cb29_1 = ffdata29[1].find(qn("w:checkBox"))
            self.assertEqual(cb29_0.find(qn("w:checked")).get(qn("w:val")), "1")
            self.assertEqual(cb29_1.find(qn("w:checked")).get(qn("w:val")), "0")
        else:
            sdt29 = t1.rows[29 + offset]._tr.xpath(".//w:sdtContent")
            self.assertGreater(len(sdt29), 0)
            t_txt = "".join(sdt29[0].itertext())
            self.assertIn("Tái cấp", t_txt)

        # Stale sample values must NOT be present in Section A (Table 1)
        t1_text = " ".join(c.text for r in t1.rows for c in r.cells)
        self.assertNotIn("AgriS Gia Lai", t1_text)
        self.assertNotIn("46321", t1_text)
        self.assertNotIn("Bán buôn thịt và các sản phẩm từ thịt", t1_text)
        self.assertNotIn("Lúa, điều, gạo", t1_text)

    def test_skip_validation_renders_partial_facts(self):
        session = SectionAReviewSession("PARTIAL-001")
        session.confirm_fact_with_rm("company.legal_name", "DOANH NGHIEP THU NGHIEM")

        result = self.renderer.render(
            session.facts,
            self.template_path,
            self.output_path,
            skip_validation=True,
        )
        self.assertTrue(result.is_success)
        self.assertIn("company.legal_name", result.fields_rendered)
        self.assertIn("relationship.customer_status", result.fields_skipped)


if __name__ == "__main__":
    unittest.main()
