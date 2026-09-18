# -*- coding: utf-8 -*-
"""Unit tests for Phase 4: CICDocumentMapper, is_msb_institution, and Section E Derivations."""

import unittest
import copy

from msb_eb_copilot.src.section_e.models import is_msb_institution, DebtGroup
from msb_eb_copilot.src.extraction.cic_extraction import (
    CICEvidenceField,
    CICFacilityItem,
    CICInstitutionItem,
    CICDocumentExtraction,
)
from msb_eb_copilot.src.mapping.cic_mapper import CICDocumentMapper
from msb_eb_copilot.src.mapping.models import MappingSourceMetadata


class TestIsMSBInstitution(unittest.TestCase):
    """Test MSB bank name resolution single authority."""

    def test_msb_positive_cases(self):
        positives = [
            "Ngân hàng TMCP Hàng Hải Việt Nam",
            "Ngân hàng TMCP Hàng Hải Việt Nam - CN Hà Nội",
            "MSB",
            "NH TMCP HANG HAI VIET NAM",
            "Ngân hàng TMCP Hàng hải",
            "Ngân hàng Hàng Hải (MSB) - PGD Cầu Giấy",
            "MSB - Chi nhánh Đô Thành",
        ]
        for name in positives:
            self.assertTrue(is_msb_institution(name), f"Failed to identify MSB for: {name}")

    def test_msb_negative_cases(self):
        negatives = [
            "Ngân hàng TMCP Quân Đội (MBBank)",
            "MBBank",
            "MB Bank",
            "Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank)",
            "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam (BIDV)",
            "Ngân hàng TNHH MTV Shinhan Việt Nam",
            "VPBank",
            "Techcombank",
            None,
            "",
        ]
        for name in negatives:
            self.assertFalse(is_msb_institution(name), f"Incorrectly identified MSB for: {name}")


class TestCICDocumentMapper(unittest.TestCase):
    """Test deterministic mapping from CICDocumentExtraction to canonical section_e."""

    def setUp(self):
        self.source_meta = MappingSourceMetadata(
            source_document="test_cic.pdf",
            ingestion_mode="digital",
            extractor="CICDocumentExtractor",
        )
        self.initial_case = {
            "customer": {
                "name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG",
                "tax_code": "0109876543",
            },
            "section_e": {
                "cic_date": "01/01/2026",
                "msb_outstanding": 0.0,
                "history_status": "Lịch sử bình thường",
                "is_overdue_12m": False,
                "relations": [],
            }
        }

    def test_non_mutating_mapping(self):
        empty_case = copy.deepcopy(self.initial_case)
        empty_case["section_e"]["cic_date"] = None
        orig_copy = copy.deepcopy(empty_case)

        ext = CICDocumentExtraction(
            cic_report_date=CICEvidenceField(value_raw="28/02/2026", page=1, evidence="Ngày: 28/02/2026")
        )
        res = CICDocumentMapper.map(empty_case, ext, self.source_meta)
        self.assertEqual(empty_case, orig_copy)
        self.assertEqual(res.case_data["section_e"]["cic_date"], "28/02/2026")
        self.assertIsNone(empty_case["section_e"]["cic_date"])

    def test_document_level_conflicts_and_derivations(self):
        ext = CICDocumentExtraction(
            cic_report_date=CICEvidenceField(value_raw="28/02/2026", page=1, evidence="Ngày: 28/02/2026"),
            history_status=CICEvidenceField(value_raw="Tốt, không nợ xấu", page=1, evidence="Lịch sử tốt, không nợ xấu"),
            is_overdue_12m=CICEvidenceField(value_raw="Không có nợ quá hạn", page=1, evidence="Trong 12 tháng gần nhất không có nợ quá hạn"),
            derivative_transactions_info=CICEvidenceField(value_raw="Không phát sinh chậm thanh toán", page=1, evidence="Không phát sinh phái sinh"),
        )
        res = CICDocumentMapper.map(self.initial_case, ext, self.source_meta)
        
        # Conflict on cic_date ("01/01/2026" vs "28/02/2026"):
        # Server retains existing value until RM resolves!
        self.assertTrue(any(c.canonical_path == "section_e.cic_date" for c in res.conflicts))
        c_obj = next(c for c in res.conflicts if c.canonical_path == "section_e.cic_date")
        self.assertEqual(c_obj.existing_value, "01/01/2026")
        self.assertEqual(c_obj.extracted_value, "28/02/2026")
        self.assertEqual(res.case_data["section_e"]["cic_date"], "01/01/2026")

        self.assertFalse(res.case_data["section_e"]["is_overdue_12m"])
        self.assertEqual(res.case_data["section_e"]["derivative_transactions_info"], "Không phát sinh chậm thanh toán")

    def test_missing_derivative_yields_none(self):
        """NO EVIDENCE -> NO FACT: absent derivative info must remain None, never fabricated."""
        ext = CICDocumentExtraction(
            derivative_transactions_info=CICEvidenceField(value_raw=None, page=None, evidence=None)
        )
        res = CICDocumentMapper.map(self.initial_case, ext, self.source_meta)
        self.assertIsNone(res.case_data["section_e"]["derivative_transactions_info"])

    def test_institution_relations_and_msb_derivation(self):
        ext = CICDocumentExtraction(
            institutions=[
                # Bank 1: Vietcombank
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank)", page=1, evidence="VCB"),
                    short_term_limit_raw=CICEvidenceField(value_raw="15.000", page=1, evidence="HMTD 15.000"),
                    short_term_debt_vnd_raw=CICEvidenceField(value_raw="8.500", page=1, evidence="VND 8.500"),
                    short_term_debt_usd_vnd_equiv_raw=CICEvidenceField(value_raw="1.500", page=1, evidence="USD qđ 1.500"),
                    debt_group=CICEvidenceField(value_raw="Nhóm 1", page=1, evidence="Nhóm 1"),
                ),
                # Bank 2: MSB
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="Ngân hàng TMCP Hàng Hải Việt Nam (MSB) - CN Hà Nội", page=1, evidence="MSB Hà Nội"),
                    short_term_limit_raw=CICEvidenceField(value_raw="10.000", page=1, evidence="HMTD 10.000"),
                    short_term_debt_vnd_raw=CICEvidenceField(value_raw="5.200", page=1, evidence="VND 5.200"),
                    medium_long_term_debt_raw=CICEvidenceField(value_raw="2.000", page=1, evidence="TDH 2.000"),
                    debt_group=CICEvidenceField(value_raw="Nhóm 1", page=1, evidence="Nhóm 1"),
                ),
            ]
        )
        res = CICDocumentMapper.map(self.initial_case, ext, self.source_meta)
        rels = res.case_data["section_e"]["relations"]
        self.assertEqual(len(rels), 2)

        # Vietcombank check: total_debt = 8500 + 1500 = 10000
        vcb = rels[0]
        self.assertEqual(vcb["short_term_debt_vnd_million"], 8500.0)
        self.assertEqual(vcb["short_term_debt_usd_million"], 1500.0)
        self.assertEqual(vcb["total_debt_million"], 10000.0)

        # MSB check: total_debt = 5200 + 2000 = 7200
        msb = rels[1]
        self.assertEqual(msb["short_term_debt_vnd_million"], 5200.0)
        self.assertEqual(msb["medium_long_term_debt_million"], 2000.0)
        self.assertEqual(msb["total_debt_million"], 7200.0)

        # MSB cross-section derivations:
        # msb_outstanding is sum of total debt at MSB: 7200
        self.assertEqual(res.case_data["section_e"]["msb_outstanding"], 7200.0)
        # total_credit_exposure_at_msb_million is max(limit 10000, total_debt 7200) = 10000.0
        self.assertEqual(res.case_data["section_e"]["total_credit_exposure_at_msb_million"], 10000.0)
        # Non-MSB debt is Vietcombank: 10000.0
        self.assertEqual(res.case_data["section_e"]["total_debt_other_banks_excluding_msb"], 10000.0)

    def test_raw_usd_without_vnd_equiv_handling(self):
        """When raw USD exists without VND equivalent, canonical VND is None, total is None, warning emitted."""
        ext = CICDocumentExtraction(
            institutions=[
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="Ngân hàng TNHH MTV Shinhan Việt Nam", page=1, evidence="Shinhan"),
                    short_term_limit_raw=CICEvidenceField(value_raw="2.500", page=1, evidence="HMTD 2.500"),
                    short_term_debt_vnd_raw=CICEvidenceField(value_raw="0", page=1, evidence="0"),
                    raw_usd_amount_raw=CICEvidenceField(value_raw="50.000 USD", page=1, evidence="50.000 USD"),
                    # short_term_debt_usd_vnd_equiv_raw absent!
                    debt_group=CICEvidenceField(value_raw="Nhóm 1", page=1, evidence="Nhóm 1"),
                )
            ]
        )
        res = CICDocumentMapper.map(self.initial_case, ext, self.source_meta)
        rels = res.case_data["section_e"]["relations"]
        self.assertEqual(len(rels), 1)
        shb = rels[0]

        # Raw USD preserved in provenance
        self.assertEqual(shb["raw_usd_amount"], 50000.0)
        self.assertEqual(shb["raw_usd_currency"], "USD")
        # Canonical VND equivalent must be None
        self.assertIsNone(shb["short_term_debt_usd_million"])
        # Total debt cannot be derived deterministically without arbitrary FX
        self.assertIsNone(shb["total_debt_million"])

        # MappingWarning emitted
        self.assertTrue(any("quy đổi VND" in w.reason for w in res.warnings))
        # When Shinhan (non-MSB) has total_debt_million as None, total_debt_other_banks_excluding_msb MUST be None
        self.assertIsNone(res.case_data["section_e"]["total_debt_other_banks_excluding_msb"])

    def test_incomplete_debt_propagation_when_mixed_with_complete_banks(self):
        """If ANY non-MSB bank is incomplete, total_debt_other_banks_excluding_msb MUST be None, not partial subtotal."""
        ext = CICDocumentExtraction(
            institutions=[
                # Bank 1: Vietcombank (Complete: 10,000 trđ)
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank)", page=1, evidence="VCB"),
                    short_term_debt_vnd_raw=CICEvidenceField(value_raw="10.000", page=1, evidence="10.000"),
                ),
                # Bank 2: Shinhan (Incomplete: raw USD without VND equivalent)
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="Ngân hàng TNHH MTV Shinhan Việt Nam", page=1, evidence="Shinhan"),
                    raw_usd_amount_raw=CICEvidenceField(value_raw="50.000 USD", page=1, evidence="50.000 USD"),
                ),
            ]
        )
        res = CICDocumentMapper.map(self.initial_case, ext, self.source_meta)
        rels = res.case_data["section_e"]["relations"]
        self.assertEqual(len(rels), 2)
        self.assertEqual(rels[0]["total_debt_million"], 10000.0)
        self.assertIsNone(rels[1]["total_debt_million"])

        # Crucial: Must be None, NOT 10000.0!
        self.assertIsNone(res.case_data["section_e"]["total_debt_other_banks_excluding_msb"])
        self.assertTrue(any(w.canonical_path == "section_e.total_debt_other_banks_excluding_msb" for w in res.warnings))

    def test_complete_aggregate_flows_when_all_banks_have_vnd_equiv(self):
        """When all non-MSB banks have authoritative VND debt, aggregate is complete and correct."""
        ext = CICDocumentExtraction(
            institutions=[
                # Bank 1: Vietcombank (10,000 trđ)
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank)", page=1, evidence="VCB"),
                    short_term_debt_vnd_raw=CICEvidenceField(value_raw="10.000", page=1, evidence="10.000"),
                ),
                # Bank 2: Shinhan (With authoritative VND equivalent 1,300 trđ)
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="Ngân hàng TNHH MTV Shinhan Việt Nam", page=1, evidence="Shinhan"),
                    raw_usd_amount_raw=CICEvidenceField(value_raw="50.000 USD", page=1, evidence="50.000 USD"),
                    short_term_debt_usd_vnd_equiv_raw=CICEvidenceField(value_raw="1.300", page=1, evidence="1.300"),
                ),
                # Bank 3: MSB (7,200 trđ)
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="Ngân hàng TMCP Hàng Hải Việt Nam (MSB)", page=1, evidence="MSB"),
                    short_term_debt_vnd_raw=CICEvidenceField(value_raw="7.200", page=1, evidence="7.200"),
                ),
            ]
        )
        res = CICDocumentMapper.map(self.initial_case, ext, self.source_meta)
        sec_e = res.case_data["section_e"]
        rels = sec_e["relations"]
        self.assertEqual(len(rels), 3)

        # Non-MSB total = 10,000 + 1,300 = 11,300.0
        self.assertEqual(sec_e["total_debt_other_banks_excluding_msb"], 11300.0)
        # MSB outstanding = 7,200.0
        self.assertEqual(sec_e["msb_outstanding"], 7200.0)

    def test_grounding_rejection_blocks_canonical_mapping(self):
        """Canonical Eligibility: REJECTED status in grounding audit prevents mapping to canonical."""
        from msb_eb_copilot.src.extraction.cic_extraction import GroundingAuditResult

        ext = CICDocumentExtraction(
            cic_report_date=CICEvidenceField(value_raw="28/02/2026", page=1, evidence="Ngày 28/02/2026"),
            is_overdue_12m=CICEvidenceField(value_raw="False", page=1, evidence="Không có nợ quá hạn"),
            institutions=[
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="Ngân hàng Giả Mạo", page=1, evidence="FakeBank"),
                    short_term_debt_vnd_raw=CICEvidenceField(value_raw="5.000", page=1, evidence="5.000"),
                )
            ]
        )
        # Simulate auditor rejecting is_overdue_12m and FakeBank
        mock_audits = {
            "section_e.is_overdue_12m": GroundingAuditResult(status="REJECTED", field_name="section_e.is_overdue_12m", reason="Evidence hallucinated"),
            "section_e.relations[1].bank_name": GroundingAuditResult(status="REJECTED", field_name="section_e.relations[1].bank_name", reason="Bank name not in doc"),
            "section_e.cic_date": GroundingAuditResult(status="VERIFIED", field_name="section_e.cic_date", reason="Verified"),
        }

        empty_case = {"section_e": {}}
        res = CICDocumentMapper.map(empty_case, ext, self.source_meta, grounding_audits=mock_audits)
        sec_e = res.case_data["section_e"]

        # Verified field mapped
        self.assertEqual(sec_e["cic_date"], "28/02/2026")
        # Rejected overdue fact blocked -> set to None
        self.assertIsNone(sec_e["is_overdue_12m"])
        # Rejected institution skipped completely
        self.assertEqual(len(sec_e["relations"]), 0)
        # Rejection warnings emitted
        self.assertTrue(any("REJECTED" in w.reason for w in res.warnings))


if __name__ == "__main__":
    unittest.main()
