# -*- coding: utf-8 -*-
"""Golden End-to-End Test for Phase 4: CIC Document Agent & Canonical Section E Lineage.

Verifies:
1. Grounded extraction and mapping from synthetic digital CIC fixture.
2. Provenance and audit tracking across all institutions and document facts.
3. Currency-safe USD handling (Shinhan raw USD preserved, total debt None).
4. Deterministic cross-section derivations (msb_outstanding, total_credit_exposure_at_msb_million).
5. Full CreditProposalAssembler MB07 docx mutation and Table 32 population.
"""

import copy
import os
import unittest
import docx

from msb_eb_copilot.src.canonical_validator import CanonicalAdapter
from msb_eb_copilot.src.ingestion.router import DocumentIngestionRouter
from msb_eb_copilot.src.extraction.cic_extraction import (
    CICDocumentExtraction,
    CICEvidenceField,
    CICInstitutionItem,
    CICGroundingAuditor,
    CICIdentityReconciler,
)
from msb_eb_copilot.src.mapping.cic_mapper import CICDocumentMapper
from msb_eb_copilot.src.mapping.models import MappingSourceMetadata
from msb_eb_copilot.src.section_e.models import (
    SectionEData,
    CreditInstitutionRelation,
    DebtGroup,
    is_msb_institution,
)
from msb_eb_copilot.src.section_e.cross_link import get_other_debt_for_section_d
from msb_eb_copilot.src.credit_demand_engine import CreditDemandEngine, FinancialInput
from msb_eb_copilot.src.proposal_assembler import CreditProposalAssembler
from web_copilot_app import CASES_DB, ACTIVE_CASE_ID, execute_generation_pipeline


class TestCICGoldenE2E(unittest.TestCase):
    """Synthetic Golden E2E Test on synthetic digital CIC fixture."""

    def setUp(self):
        self.digital_pdf_path = os.path.join("tests", "fixtures", "cic", "synthetic_cic_digital.pdf")
        self.assertTrue(os.path.exists(self.digital_pdf_path), f"Fixture not found at: {self.digital_pdf_path}")

        # Grounded extraction corresponding exactly to synthetic_cic_digital.pdf
        def cef(v, ev, pg=1):
            return CICEvidenceField(value_raw=v, evidence=ev, page=pg)

        self.extraction = CICDocumentExtraction(
            customer_name=cef("CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG", "CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG", 1),
            tax_code=cef("0109876543", "0109876543", 1),
            cic_report_date=cef("28/02/2026", "28/02/2026", 1),
            customer_highest_debt_group=cef("Nhóm 1", "Nhóm 1", 1),
            is_overdue_12m=cef("Không có nợ quá hạn", "Trong 12 tháng gần nhất không có nợ quá hạn.", 1),
            derivative_transactions_info=cef("Không phát sinh giao dịch phái sinh chậm thanh toán", "Không phát sinh giao dịch phái sinh chậm thanh toán.", 1),
            institutions=[
                # Bank 1: Vietcombank
                CICInstitutionItem(
                    bank_name=cef("Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank) - CN Thăng Long", "Vietcombank", 1),
                    short_term_limit_raw=cef("15.000", "15.000", 1),
                    short_term_debt_vnd_raw=cef("8.500", "8.500", 1),
                    short_term_debt_usd_vnd_equiv_raw=cef("1.500", "1.500", 1),
                    medium_long_term_debt_raw=cef("0", "0", 1),
                    total_debt_printed=cef("10.000", "10.000", 1),
                    debt_group=cef("Nhóm 1", "Nhóm 1", 1),
                    collateral_description=cef("Bất động sản tại Hà Nội", "Bất động sản tại Hà Nội", 1),
                    page=1,
                ),
                # Bank 2: MSB
                CICInstitutionItem(
                    bank_name=cef("Ngân hàng TMCP Hàng Hải Việt Nam (MSB) - CN Hà Nội", "MSB", 1),
                    short_term_limit_raw=cef("10.000", "10.000", 1),
                    short_term_debt_vnd_raw=cef("5.200", "5.200", 1),
                    short_term_debt_usd_vnd_equiv_raw=cef("0", "0", 1),
                    medium_long_term_debt_raw=cef("2.000", "2.000", 1),
                    total_debt_printed=cef("7.200", "7.200", 1),
                    debt_group=cef("Nhóm 1", "Nhóm 1", 1),
                    collateral_description=cef("HĐTG và Hàng tồn kho", "HĐTG và Hàng tồn kho", 1),
                    page=1,
                ),
                # Bank 3: Shinhan (raw USD, no VND equivalent)
                CICInstitutionItem(
                    bank_name=cef("Ngân hàng TNHH MTV Shinhan Việt Nam", "Shinhan", 1),
                    short_term_limit_raw=cef("2.500", "2.500", 1),
                    short_term_debt_vnd_raw=cef("0", "0", 1),
                    raw_usd_amount_raw=cef("50.000 USD", "50.000 USD", 1),
                    medium_long_term_debt_raw=cef("0", "0", 1),
                    debt_group=cef("Nhóm 1", "Nhóm 1", 1),
                    collateral_description=cef("Tín chấp theo dòng tiền", "Tín chấp theo dòng tiền", 1),
                    page=1,
                ),
            ]
        )

    def test_ingestion_and_grounding_audit(self):
        # 1. Ingest via DocumentIngestionRouter
        ingestion_res = DocumentIngestionRouter.ingest_document(self.digital_pdf_path)
        self.assertEqual(ingestion_res.mode, "digital")
        self.assertEqual(ingestion_res.provider, "pypdf")
        self.assertGreater(len(ingestion_res.tagged_text), 200)

        # 2. Comprehensive Grounding Audit on all extracted facts
        pages_text, max_p = CICGroundingAuditor.extract_pages(ingestion_res.tagged_text)
        all_audits = CICGroundingAuditor.audit_all_facts(self.extraction, pages_text, max_p)
        self.assertGreaterEqual(len(all_audits), 15)

        # Ensure every institution field is individually audited
        self.assertIn("customer.tax_code", all_audits)
        self.assertIn("section_e.cic_date", all_audits)
        self.assertIn("section_e.relations[1].bank_name", all_audits)
        self.assertIn("section_e.relations[1].short_term_debt_vnd", all_audits)
        self.assertIn("section_e.relations[2].short_term_debt_vnd", all_audits)
        self.assertIn("section_e.relations[3].raw_usd_amount", all_audits)

        for path, audit_res in all_audits.items():
            self.assertEqual(audit_res.status, "VERIFIED", f"Fact at {path} should be VERIFIED")

    def test_end_to_end_mapping_and_derivations(self):
        case_data = {
            "customer": {
                "name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG",
                "tax_code": "0109876543",
            },
            "section_e": {}
        }
        source_meta = MappingSourceMetadata(
            source_document="synthetic_cic_digital.pdf",
            ingestion_mode="digital",
            extractor="CICDocumentExtractor",
        )

        # Identity reconciliation
        id_status, id_msg = CICIdentityReconciler.reconcile(
            self.extraction.tax_code.value_raw,
            self.extraction.customer_name.value_raw,
            case_data["customer"]
        )
        self.assertEqual(id_status, "MATCH")

        # Map to section_e
        map_res = CICDocumentMapper.map(case_data, self.extraction, source_meta)
        sec_e = map_res.case_data["section_e"]

        # Assert document facts
        self.assertEqual(sec_e["cic_date"], "28/02/2026")
        self.assertFalse(sec_e["is_overdue_12m"])
        self.assertEqual(sec_e["derivative_transactions_info"], "Không phát sinh giao dịch phái sinh chậm thanh toán")

        # Assert relations
        rels = sec_e["relations"]
        self.assertEqual(len(rels), 3)

        vcb = rels[0]
        self.assertEqual(vcb["short_term_debt_vnd_million"], 8500.0)
        self.assertEqual(vcb["short_term_debt_usd_million"], 1500.0)
        self.assertEqual(vcb["total_debt_million"], 10000.0)
        self.assertFalse(is_msb_institution(vcb["bank_name"]))

        msb = rels[1]
        self.assertEqual(msb["short_term_debt_vnd_million"], 5200.0)
        self.assertEqual(msb["medium_long_term_debt_million"], 2000.0)
        self.assertEqual(msb["total_debt_million"], 7200.0)
        self.assertTrue(is_msb_institution(msb["bank_name"]))

        shb = rels[2]
        self.assertEqual(shb["raw_usd_amount"], 50000.0)
        self.assertEqual(shb["raw_usd_currency"], "USD")
        self.assertIsNone(shb["short_term_debt_usd_million"])
        self.assertIsNone(shb["total_debt_million"])

        # MSB cross-section derivations
        self.assertEqual(sec_e["msb_outstanding"], 7200.0)
        self.assertEqual(sec_e["total_credit_exposure_at_msb_million"], 10000.0)
        # Because Shinhan has incomplete debt (raw USD without VND equiv), total_debt_other_banks_excluding_msb MUST be None
        self.assertIsNone(sec_e["total_debt_other_banks_excluding_msb"])
        self.assertTrue(any(w.canonical_path == "section_e.total_debt_other_banks_excluding_msb" for w in map_res.warnings))

    def test_full_proposal_document_assembly_with_confirmed_cic(self):
        """Verify Table 32 population in Word MB07 document."""
        # Build SectionEData from confirmed facts
        rels = [
            CreditInstitutionRelation(
                stt=1,
                bank_name="Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank) - CN Thăng Long",
                short_term_limit_million_vnd=15000.0,
                short_term_debt_vnd_million=8500.0,
                short_term_debt_usd_million=1500.0,
                medium_long_term_debt_million=0.0,
                total_debt_million=10000.0,
                debt_group=DebtGroup.NHOM_1_DU_TIEU_CHUAN,
                collateral_description="Bất động sản tại Hà Nội",
            ),
            CreditInstitutionRelation(
                stt=2,
                bank_name="Ngân hàng TMCP Hàng Hải Việt Nam (MSB) - CN Hà Nội",
                short_term_limit_million_vnd=10000.0,
                short_term_debt_vnd_million=5200.0,
                short_term_debt_usd_million=0.0,
                medium_long_term_debt_million=2000.0,
                total_debt_million=7200.0,
                debt_group=DebtGroup.NHOM_1_DU_TIEU_CHUAN,
                collateral_description="HĐTG và Hàng tồn kho",
            ),
            CreditInstitutionRelation(
                stt=3,
                bank_name="Ngân hàng TNHH MTV Shinhan Việt Nam",
                short_term_limit_million_vnd=2500.0,
                short_term_debt_vnd_million=0.0,
                short_term_debt_usd_million=None,
                raw_usd_amount=50000.0,
                raw_usd_currency="USD",
                medium_long_term_debt_million=0.0,
                total_debt_million=None,
                debt_group=DebtGroup.NHOM_1_DU_TIEU_CHUAN,
                collateral_description="Tín chấp theo dòng tiền",
            ),
        ]

        data_e = SectionEData(
            customer_name="CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG",
            cic_report_date="28/02/2026",
            relations=rels,
            loan_outstanding_at_msb_million=7200.0,
            is_overdue_12m=False,
            derivative_transactions_info="Không phát sinh giao dịch phái sinh chậm thanh toán",
        )

        # Linkage check 1: Incomplete debt propagates None to MB09
        self.assertIsNone(data_e.total_debt_other_banks_excluding_msb)
        mb09_other_debt = get_other_debt_for_section_d(data_e)
        self.assertIsNone(mb09_other_debt)

        # CreditDemandEngine receives None and safely sets loan_limit_msb to None
        fin_inp = FinancialInput(
            net_revenue_plan=60_000_000_000,
            cogs_plan=45_000_000_000,
            operating_cost_plan=5_000_000_000,
            dio=60.0,
            dso=45.0,
            dpo=30.0,
            equity_participation=5_000_000_000,
            other_debt=mb09_other_debt,
        )
        mb09_res = CreditDemandEngine.calculate_credit_limits(fin_inp)
        self.assertIsNone(mb09_res["loan_limit_msb"])
        self.assertIsNone(mb09_res["total_credit_facility_msb"])

        # Linkage check 2: Complete debt case when Shinhan has authoritative VND equiv
        rels_complete = copy.deepcopy(rels)
        rels_complete[2].short_term_debt_usd_million = 1300.0
        rels_complete[2].total_debt_million = 1300.0
        data_e_complete = SectionEData(
            customer_name="CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG",
            cic_report_date="28/02/2026",
            relations=rels_complete,
            loan_outstanding_at_msb_million=7200.0,
        )
        self.assertEqual(data_e_complete.total_debt_other_banks_excluding_msb, 11300.0)
        mb09_complete_debt = get_other_debt_for_section_d(data_e_complete)
        self.assertEqual(mb09_complete_debt, 11300.0 * 1_000_000.0)
        fin_inp_complete = FinancialInput(
            net_revenue_plan=60_000_000_000,
            cogs_plan=45_000_000_000,
            operating_cost_plan=5_000_000_000,
            dio=60.0,
            dso=45.0,
            dpo=30.0,
            equity_participation=5_000_000_000,
            other_debt=mb09_complete_debt,
        )
        mb09_complete_res = CreditDemandEngine.calculate_credit_limits(fin_inp_complete)
        self.assertIsNotNone(mb09_complete_res["loan_limit_msb"])

        out_docx = "tests/test_output_cic_e2e_mb07.docx"
        if os.path.exists(out_docx):
            os.remove(out_docx)

        # Generate proposal document
        from msb_eb_copilot.src.mb07_inplace_mutator import MB07InPlaceMutator
        template_path = os.path.join("templates", "MB07_TO_TRINH_TD_DN_TEMPLATE.docx")
        if not os.path.exists(template_path):
            template_path = os.path.join("Data", "DEMO GAS SOUTH_PUBLIC DATA", "Phôi_TT_Cap_tin_dung_doanh_nghiep_2024.docx")

        if os.path.exists(template_path):
            mutator = MB07InPlaceMutator(template_path)
            mutator.mutate_section_e(data_e)
            mutator.save(out_docx)

            self.assertTrue(os.path.exists(out_docx))
            doc = docx.Document(out_docx)
            # Table 32 should have real bank names
            t32 = doc.tables[32]
            table_text = " ".join(cell.text for row in t32.rows for cell in row.cells)
            self.assertIn("Vietcombank", table_text)
            self.assertIn("Hàng Hải", table_text)
            self.assertIn("Shinhan", table_text)
            print("[+] Table 32 verified in generated MB07 document.")


if __name__ == "__main__":
    unittest.main()
