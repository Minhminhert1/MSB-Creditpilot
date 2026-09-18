# -*- coding: utf-8 -*-
"""E2E and Integration tests for Grounded Credit Narrative Layer and MB07 Assembler."""

import os
import unittest
import docx

from msb_eb_copilot.src.narrative.models import (
    FactItem, FactAuthority, FactNature, FactCompleteness,
    FactManifest, NarrativeBlock, NarrativeTargetBinding,
    CreditNarrativePackage, VerificationStatus, VerifiedInsight,
    TrendDirection, StaleNarrativeGenerationError, NarrativeValidationError
)
from msb_eb_copilot.src.narrative.fact_packager import FactPackager
from msb_eb_copilot.src.narrative.insight_verifier import PythonInsightVerifier
from msb_eb_copilot.src.narrative.validator import DeterministicNarrativeValidator
from msb_eb_copilot.src.narrative.store import NarrativeDraftManager, NARRATIVE_DRAFT_STORE
from msb_eb_copilot.src.proposal_assembler import CreditProposalAssembler
from msb_eb_copilot.src.section_c.models import SectionCData, BusinessModelType
from msb_eb_copilot.src.section_d.models import (
    SectionDData, AccountingGovernance, IncomeStatement3Y, BalanceSheet3Y, CashFlowStatement3Y, FinancialRatios3Y, PnLAnalysis
)
from msb_eb_copilot.src.section_e.models import (
    SectionEData, CreditInstitutionRelation, DebtGroup
)


class TestNarrativeMB07E2E(unittest.TestCase):
    def setUp(self):
        NARRATIVE_DRAFT_STORE.clear()
        self.case_id = "E2E_CORP"
        self.case_data = {
            "id": self.case_id,
            "name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ THỰC NGHIỆM",
            "customer": {
                "name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ THỰC NGHIỆM",
                "short_name": "TECH_EXP",
                "tax_code": "0987654321",
                "established_year": 2015,
                "address": "TP. Hà Nội",
                "charter_capital": 300000.0,
            },
            "rm_metadata": {
                "unit_name": "ĐVKD HÀ NỘI",
                "proposal_no": "99.2026 - TECH",
                "proposal_date": "17/01/2026",
                "rm_name": "Trần Văn RM",
                "rm_phone": "0901234567",
                "manager_name": "Lê Quản Lý",
                "manager_phone": "0907654321",
            },
            "section_b": {
                "total_limit": 200000.0,
                "loan_limit": 150000.0,
                "guarantee_limit": 50000.0,
                "loan_purpose": "Bổ sung vốn lưu động",
                "collateral_type": "Bất động sản",
                "cashflow_commitment_pct": 80.0,
                "cashflow_direct_pct": 50.0,
            },
            "section_c": {
                "business_model": "THUONG_MAI",
                "products": [
                    {"name": "Thiết bị mạng", "share": 70.0},
                    {"name": "Máy chủ server", "share": 30.0}
                ]
            },
            "section_d": {
                "years": ["2023", "2024", "2025"],
                "net_revenue": [1000000.0, 1200000.0, 1600000.0],
                "cogs": [850000.0, 1000000.0, 1320000.0],
                "gross_profit": [150000.0, 200000.0, 280000.0],
                "financial_expenses": [20000.0, 25000.0, 30000.0],
                "interest_expenses": [15000.0, 18000.0, 22000.0],
                "net_profit": [30000.0, 50000.0, 80000.0],
                "current_assets": [600000.0, 750000.0, 950000.0],
                "cash_and_equivalents": [50000.0, 70000.0, 120000.0],
                "receivables": [300000.0, 380000.0, 480000.0],
                "inventories": [250000.0, 300000.0, 350000.0],
                "total_assets": [700000.0, 880000.0, 1100000.0],
                "liabilities": [400000.0, 500000.0, 620000.0],
                "short_term_debt": [200000.0, 250000.0, 320000.0],
                "equity": [300000.0, 380000.0, 480000.0],
                "ocf": [40000.0, 60000.0, 90000.0],
            },
            "section_e": {
                "cic_date": "31/12/2025",
                "msb_outstanding": 120000.0,
                "history_status": "100% Nhóm 1",
                "relations": [
                    {
                        "bank_name": "Ngân hàng TMCP Hàng Hải Việt Nam (MSB)",
                        "short_term_limit_million_vnd": 150000.0,
                        "short_term_debt_vnd_million": 120000.0,
                        "debt_group": "NHOM_1_DU_TIEU_CHUAN"
                    }
                ]
            }
        }

    def test_full_pipeline_generate_accept_and_assemble_mb07(self):
        # 1. Package FactManifest
        manifest = FactPackager.package_from_case_data(self.case_data, case_id=self.case_id)
        self.assertIsNotNone(manifest.manifest_hash)

        # 2. Insights & Verification
        verified_insights = [
            VerifiedInsight(
                insight_id="INS_REV_GROWTH_24_25",
                status=VerificationStatus.VERIFIED,
                insight_type="GROWTH",
                metric="Doanh thu thuần",
                fact_ids=["FIN_REV_2024", "FIN_REV_2025"],
                verified_value=33.33,
                model_proposed_value=33.33,
                unit="PERCENT",
                trend=TrendDirection.INCREASE,
                observation="Doanh thu thuần năm 2025 tăng trưởng 33,33% so với 2024.",
                verification_formula="Formula",
                data_quality="HIGH",
                warnings=[],
                display_representations=["33.33%", "33,33%", "33.3%", "33,3%"]
            )
        ]

        # 3. Grounded Narrative Blocks
        pnl_block = NarrativeBlock(
            section="FINANCIAL",
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            title="Phân tích Kết quả Kinh doanh",
            text="Doanh thu thuần năm 2025 đạt 1600000 triệu VND (tăng trưởng 33,3% so với năm 2024 đạt 1200000 triệu VND). Lợi nhuận gộp đạt 280000 triệu VND.",
            facts_used=["FIN_REV_2024", "FIN_REV_2025", "FIN_GP_2025"],
            insights_used=["INS_REV_GROWTH_24_25"],
            data_gaps=[]
        )
        cic_block = NarrativeBlock(
            section="CIC",
            target_binding=NarrativeTargetBinding.CIC_SUMMARY,
            title="Quan hệ tín dụng CIC",
            text="Khách hàng TECH_EXP duy trì quan hệ tín dụng chuẩn mực, dư nợ tại MSB là 120000 triệu VND (100% Nhóm 1).",
            facts_used=["CIC_MSB_OUTSTANDING", "CIC_HISTORY_STATUS", "LEGAL_SHORT_NAME"],
            insights_used=[],
            data_gaps=[]
        )

        validator = DeterministicNarrativeValidator(manifest, verified_insights)
        val_res = validator.validate_blocks([pnl_block, cic_block])
        self.assertTrue(val_res.is_valid, msg=f"Validation errors: {val_res.errors}")

        # 4. Draft Store creation
        package = CreditNarrativePackage(
            case_id=self.case_id,
            fact_manifest_hash=manifest.manifest_hash,
            narrative_blocks=[pnl_block, cic_block]
        )
        record = NarrativeDraftManager.create_draft_record(
            case_id=self.case_id,
            manifest=manifest,
            insights=verified_insights,
            package=package
        )
        self.assertEqual(record.case_id, self.case_id)

        # 5. RM Acceptance
        accepted_rec = NarrativeDraftManager.accept_narratives(
            generation_id=record.generation_id,
            case_id=self.case_id,
            current_manifest=manifest,
            rm_reviewer_name="Trần Văn RM"
        )
        self.assertIn("pnl_analysis", accepted_rec.accepted_block_ids)
        self.assertIn("cic_summary", accepted_rec.accepted_block_ids)

        # 6. Retrieve for rendering
        accepted_dict = NarrativeDraftManager.get_accepted_narratives_for_rendering(self.case_id)
        self.assertIn("pnl_analysis", accepted_dict)
        self.assertIn("cic_summary", accepted_dict)

        # 7. Assemble MB07 document with in-place mutation
        data_b = {
            "total_limit": 200000.0,
            "loan_limit": 150000.0,
            "guarantee_limit": 50000.0,
            "loan_purpose": "Bổ sung vốn lưu động",
            "collateral_type": "Bất động sản",
            "cashflow_commitment_pct": 80.0,
            "cashflow_direct_pct": 50.0,
        }
        data_c = SectionCData(
            customer_name="CÔNG TY CỔ PHẦN CÔNG NGHỆ THỰC NGHIỆM",
            history_narrative="Thành lập từ năm 2015, hoạt động trong lĩnh vực phân phối thiết bị công nghệ.",
            business_model=BusinessModelType.THUONG_MAI
        )
        data_d = SectionDData(
            customer_name="CÔNG TY CỔ PHẦN CÔNG NGHỆ THỰC NGHIỆM",
            governance=AccountingGovernance(
                mandatory_audit_by_law="Có",
                audit_firm_name="PwC Việt Nam",
                audited_years="2022, 2023, 2024",
                audit_opinion="Chấp thuận toàn phần"
            ),
            income_statement=IncomeStatement3Y(
                years=["2023", "2024", "2025"],
                net_revenue=[1000000.0, 1200000.0, 1600000.0],
                cogs=[850000.0, 1000000.0, 1320000.0],
                gross_profit=[150000.0, 200000.0, 280000.0],
                gross_profit_margin_pct=[15.0, 16.7, 17.5],
                financial_income=[5000.0, 8000.0, 12000.0],
                financial_expenses=[20000.0, 25000.0, 30000.0],
                interest_expenses=[15000.0, 18000.0, 22000.0],
                sga_expenses=[95000.0, 120000.0, 160000.0],
                net_profit_before_tax=[40000.0, 63000.0, 102000.0],
                net_profit_after_tax=[30000.0, 50000.0, 80000.0]
            ),
            pnl_analysis=PnLAnalysis(
                revenue_analysis="Doanh thu tăng trưởng tốt.",
                gross_margin_analysis="Biên lãi gộp cải thiện.",
                net_profit_and_dividends_analysis="Lợi nhuận ròng tăng."
            ),
            balance_sheet=BalanceSheet3Y(
                years=["2023", "2024", "2025"],
                current_assets=[600000.0, 750000.0, 950000.0],
                cash_and_equivalents=[50000.0, 70000.0, 120000.0],
                short_term_investments=[0.0, 0.0, 0.0],
                accounts_receivable=[300000.0, 380000.0, 480000.0],
                inventories=[250000.0, 300000.0, 350000.0],
                other_current_assets=[0.0, 0.0, 0.0],
                non_current_assets=[100000.0, 130000.0, 150000.0],
                fixed_assets=[80000.0, 100000.0, 120000.0],
                construction_in_progress=[0.0, 0.0, 0.0],
                total_assets=[700000.0, 880000.0, 1100000.0],
                liabilities=[400000.0, 500000.0, 620000.0],
                short_term_debt=[200000.0, 250000.0, 320000.0],
                long_term_debt=[0.0, 0.0, 0.0],
                owner_equity=[300000.0, 380000.0, 480000.0],
                charter_capital=[300000.0, 300000.0, 300000.0]
            ),
            cash_flow=CashFlowStatement3Y(
                years=["2023", "2024", "2025"],
                ocf_cash_from_operations=[40000.0, 60000.0, 90000.0],
                icf_cash_from_investing=[-10000.0, -15000.0, -20000.0],
                fcf_cash_from_financing=[-20000.0, -25000.0, -30000.0],
                net_cash_flow=[10000.0, 20000.0, 40000.0],
                cash_beginning=[40000.0, 50000.0, 70000.0],
                cash_ending=[50000.0, 70000.0, 110000.0],
                cash_flow_analysis="Dòng tiền kinh doanh thặng dư."
            ),
            ratios=FinancialRatios3Y(
                years=["2023", "2024", "2025"],
                current_ratio=[1.5, 1.5, 1.53],
                quick_ratio=[0.88, 0.9, 0.97],
                cash_ratio=[0.13, 0.14, 0.19],
                debt_to_equity=[1.33, 1.32, 1.29],
                total_debt_to_equity=[0.67, 0.66, 0.67],
                dscr_icr=[2.67, 3.5, 4.64],
                ros=[3.0, 4.17, 5.0],
                roe=[10.0, 13.16, 16.67]
            )
        )
        data_e = SectionEData(
            customer_name="CÔNG TY CỔ PHẦN CÔNG NGHỆ THỰC NGHIỆM",
            cic_report_date="31/12/2025",
            loan_outstanding_at_msb_million=120000.0,
            relations=[
                CreditInstitutionRelation(
                    1, "Ngân hàng TMCP Hàng Hải Việt Nam (MSB)",
                    150000.0, 120000.0, 0.0, 0.0, 120000.0,
                    "Tín chấp", DebtGroup.NHOM_1_DU_TIEU_CHUAN
                )
            ]
        )

        output_path = os.path.join("output", "test_narrative_mb07_e2e.docx")
        assembler = CreditProposalAssembler()
        final_doc_path = assembler.assemble(
            facts_a={},
            data_b_processed=data_b,
            data_c=data_c,
            data_d=data_d,
            data_e=data_e,
            output_path=output_path,
            highlight_new_features=False,
            accepted_narratives=accepted_dict
        )

        self.assertTrue(os.path.exists(final_doc_path))
        doc = docx.Document(final_doc_path)
        full_text = " ".join(p.text for p in doc.paragraphs)

        # Assert accepted narrative text was bound
        self.assertIn("1600000 triệu VND", full_text)
        self.assertIn("tăng trưởng 33,3%", full_text)
        self.assertIn("TECH_EXP duy trì quan hệ tín dụng chuẩn mực", full_text)

        # Assert hardcoded PSD prototype paragraphs were NOT injected
        self.assertNotIn("Khách hàng PSD duy trì quan hệ tín dụng với 10 NHTM lớn", full_text)
        # Verified sensitive terms absent

    def test_stale_manifest_protection_rejects_acceptance(self):
        manifest = FactPackager.package_from_case_data(self.case_data, case_id=self.case_id)
        package = CreditNarrativePackage(
            case_id=self.case_id,
            fact_manifest_hash=manifest.manifest_hash,
            narrative_blocks=[]
        )
        record = NarrativeDraftManager.create_draft_record(
            case_id=self.case_id,
            manifest=manifest,
            insights=[],
            package=package
        )

        # Mutate case data after draft creation
        mutated_data = dict(self.case_data)
        mutated_data["section_d"] = dict(self.case_data["section_d"])
        mutated_data["section_d"]["net_revenue"] = [1000000.0, 1200000.0, 2000000.0]
        mutated_manifest = FactPackager.package_from_case_data(mutated_data, case_id=self.case_id)

        # Attempting acceptance with stale hash must raise StaleNarrativeGenerationError
        with self.assertRaises(StaleNarrativeGenerationError):
            NarrativeDraftManager.accept_narratives(
                generation_id=record.generation_id,
                case_id=self.case_id,
                current_manifest=mutated_manifest,
                rm_reviewer_name="Trần Văn RM"
            )

    def test_rm_edit_re_validation(self):
        manifest = FactPackager.package_from_case_data(self.case_data, case_id=self.case_id)
        pnl_block = NarrativeBlock(
            section="FINANCIAL",
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            title="Phân tích PnL",
            text="Doanh thu thuần năm 2025 đạt 1600000 triệu VND.",
            facts_used=["FIN_REV_2025"],
            insights_used=[],
            data_gaps=[]
        )
        package = CreditNarrativePackage(
            case_id=self.case_id,
            fact_manifest_hash=manifest.manifest_hash,
            narrative_blocks=[pnl_block]
        )
        record = NarrativeDraftManager.create_draft_record(
            case_id=self.case_id,
            manifest=manifest,
            insights=[],
            package=package
        )

        # Valid edit (grounded number in manifest display_representations)
        valid_edit_text = "Doanh thu thuần năm 2025 thực hiện là 1600000 triệu đồng."
        updated = NarrativeDraftManager.edit_block(
            generation_id=record.generation_id,
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            edited_text=valid_edit_text,
            rm_note="Sửa từ triệu VND thành triệu đồng"
        )
        self.assertEqual(updated.blocks[NarrativeTargetBinding.PNL_ANALYSIS.value].text, valid_edit_text)

        # Invalid edit (hallucinated number 9999999)
        with self.assertRaises(NarrativeValidationError):
            NarrativeDraftManager.edit_block(
                generation_id=record.generation_id,
                target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
                edited_text="Doanh thu thuần năm 2025 bịa đặt là 9999999 triệu VND.",
                rm_note="Thử số ảo"
            )

    def test_generation_alone_does_not_make_blocks_renderable(self):
        """Rule 1: generate != accept. Draft generation alone must NEVER make blocks renderable."""
        manifest = FactPackager.package_from_case_data(self.case_data, case_id=self.case_id)
        pnl_block = NarrativeBlock(
            section="FINANCIAL",
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            title="Phân tích PnL",
            text="Doanh thu thuần năm 2025 đạt 1600000 triệu VND.",
            facts_used=["FIN_REV_2025"],
            insights_used=[],
            data_gaps=[]
        )
        package = CreditNarrativePackage(
            case_id=self.case_id,
            fact_manifest_hash=manifest.manifest_hash,
            narrative_blocks=[pnl_block]
        )
        record = NarrativeDraftManager.create_draft_record(
            case_id=self.case_id,
            manifest=manifest,
            insights=[],
            package=package
        )
        # Status is NARRATIVE_VALIDATED, not ACCEPTED_FOR_RENDERING
        self.assertNotEqual(record.status.value, "ACCEPTED_FOR_RENDERING")

        # Rendering lookup MUST return empty dict because RM has not accepted
        render_dict = NarrativeDraftManager.get_accepted_narratives_for_rendering(self.case_id)
        self.assertEqual(render_dict, {}, msg="Unaccepted draft must not be renderable!")

        # Only after explicit RM acceptance does it become renderable
        accepted_rec = NarrativeDraftManager.accept_narratives(
            generation_id=record.generation_id,
            case_id=self.case_id,
            current_manifest=manifest,
            rm_reviewer_name="SIMULATED_RM_ACCEPTANCE_FOR_E2E_TEST"
        )
        self.assertEqual(accepted_rec.status.value, "ACCEPTED_FOR_RENDERING")
        render_dict_after = NarrativeDraftManager.get_accepted_narratives_for_rendering(self.case_id)
        self.assertIn("pnl_analysis", render_dict_after)

    def test_causal_claim_proof_a_b_c(self):
        """Rule 4: Causal claims (nhờ, do, dẫn đến, khiến) requires explicit supporting business fact."""
        manifest = FactPackager.package_from_case_data(self.case_data, case_id=self.case_id)
        validator = DeterministicNarrativeValidator(manifest, [])

        # Case A: Objective growth claim without causal word -> PASS
        block_a = NarrativeBlock(
            section="FINANCIAL",
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            title="Tăng trưởng",
            text="Doanh thu thuần năm 2025 đạt 1600000 triệu VND.",
            facts_used=["FIN_REV_2025"],
            insights_used=[]
        )
        res_a = validator.validate_block(block_a)
        self.assertTrue(res_a["valid"], f"Case A should pass: {res_a['errors']}")

        # Case B: Causal statement ('nhờ') without supporting business fact -> REJECT
        block_b = NarrativeBlock(
            section="FINANCIAL",
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            title="Tăng trưởng có nguyên nhân không căn cứ",
            text="Doanh thu thuần năm 2025 đạt 1600000 triệu VND nhờ mở rộng mạng lưới phân phối.",
            facts_used=["FIN_REV_2025"],  # Only financial fact, no business fact supporting cause
            insights_used=[]
        )
        res_b = validator.validate_block(block_b)
        self.assertFalse(res_b["valid"], "Case B must be rejected due to unsupported causal claim")
        self.assertTrue(any("Causal statement detected" in e for e in res_b["errors"]))

        # Case C: Causal statement with explicit qualitative business fact -> PASS
        # Register a qualitative business expansion fact
        facts_with_biz = dict(manifest.business_facts)
        facts_with_biz["BIZ_EXPANSION"] = FactItem(
            fact_id="BIZ_EXPANSION",
            section="BUSINESS",
            canonical_path="section_c.expansion",
            label="Mở rộng mạng lưới",
            value="mở rộng mạng lưới phân phối",
            unit="TEXT",
            period="2025",
            authority=FactAuthority.SOURCE_FACT,
            fact_nature=FactNature.OBJECTIVE_FACT,
            completeness=FactCompleteness.COMPLETE,
            display_representations=["mở rộng mạng lưới phân phối", "mạng lưới phân phối"]
        )
        manifest_c = FactManifest(
            case_id=manifest.case_id,
            manifest_hash="hash_c",
            legal_facts=manifest.legal_facts,
            business_facts=facts_with_biz,
            financial_facts=manifest.financial_facts,
            credit_request_facts=manifest.credit_request_facts,
            debt_service_facts=manifest.debt_service_facts,
            cic_facts=manifest.cic_facts,
            data_gaps=manifest.data_gaps
        )
        validator_c = DeterministicNarrativeValidator(manifest_c, [])
        block_c = NarrativeBlock(
            section="FINANCIAL",
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            title="Tăng trưởng có căn cứ định tính",
            text="Doanh thu thuần năm 2025 đạt 1600000 triệu VND nhờ mở rộng mạng lưới phân phối.",
            facts_used=["FIN_REV_2025", "BIZ_EXPANSION"],
            insights_used=[]
        )
        res_c = validator_c.validate_block(block_c)
        self.assertTrue(res_c["valid"], f"Case C should pass with supporting business fact: {res_c['errors']}")

    def test_source_claim_attribution_proof(self):
        """Rule 5: SOURCE_CLAIM authority facts require mandatory attribution."""
        facts_biz = {
            "BIZ_MARKET_SHARE": FactItem(
                fact_id="BIZ_MARKET_SHARE",
                section="BUSINESS",
                canonical_path="section_c.market_share",
                label="Thị phần",
                value="25%",
                unit="PERCENT",
                period=None,
                authority=FactAuthority.SOURCE_CLAIM,
                fact_nature=FactNature.SOURCE_CLAIM,
                completeness=FactCompleteness.COMPLETE,
                display_representations=["25%"]
            )
        }
        manifest = FactManifest(
            case_id=self.case_id,
            manifest_hash="hash_src",
            business_facts=facts_biz
        )
        validator = DeterministicNarrativeValidator(manifest, [])

        # Unattributed SOURCE_CLAIM -> REJECT
        unattributed_block = NarrativeBlock(
            section="BUSINESS",
            target_binding=NarrativeTargetBinding.MARKET_SUMMARY,
            title="Thị phần tự kê khai không nguồn",
            text="Doanh nghiệp chiếm 25% thị phần.",
            facts_used=["BIZ_MARKET_SHARE"],
            insights_used=[]
        )
        res_unattr = validator.validate_block(unattributed_block)
        self.assertFalse(res_unattr["valid"], "Unattributed SOURCE_CLAIM must be rejected")
        self.assertTrue(any("Missing mandatory source attribution" in e for e in res_unattr["errors"]))

        # Attributed SOURCE_CLAIM -> PASS
        attributed_block = NarrativeBlock(
            section="BUSINESS",
            target_binding=NarrativeTargetBinding.MARKET_SUMMARY,
            title="Thị phần tự kê khai có nguồn",
            text="Theo hồ sơ doanh nghiệp cung cấp, doanh nghiệp cho biết chiếm 25% thị phần.",
            facts_used=["BIZ_MARKET_SHARE"],
            insights_used=[]
        )
        res_attr = validator.validate_block(attributed_block)
        self.assertTrue(res_attr["valid"], f"Attributed SOURCE_CLAIM must pass: {res_attr['errors']}")

    def test_cic_incomplete_caveat_proof(self):
        """Rule 6: INCOMPLETE external debt in CIC requires explicit caveat in narrative prose."""
        cic_fact = FactItem(
            fact_id="CIC_STATUS",
            section="CIC",
            canonical_path="section_e.history_status",
            label="Lịch sử trả nợ",
            value="Nợ chuẩn",
            unit="TEXT",
            period=None,
            authority=FactAuthority.SOURCE_FACT,
            fact_nature=FactNature.OBJECTIVE_FACT,
            completeness=FactCompleteness.COMPLETE,
            display_representations=["Nợ chuẩn", "chuẩn mực"]
        )
        cic_gap = FactItem(
            fact_id="GAP_CIC_EXTERNAL_DEBT_INCOMPLETE",
            section="DATA_GAPS",
            canonical_path="section_e.other_banks_total_debt",
            label="Dư nợ ngoại tệ chưa quy đổi",
            value="Chưa quy đổi 500.000 USD",
            unit="TEXT",
            period=None,
            authority=FactAuthority.SOURCE_FACT,
            fact_nature=FactNature.DATA_GAP,
            completeness=FactCompleteness.INCOMPLETE,
            display_representations=[]
        )
        manifest = FactManifest(
            case_id=self.case_id,
            manifest_hash="hash_cic_gap",
            cic_facts={"CIC_STATUS": cic_fact},
            data_gaps=[cic_gap]
        )
        validator = DeterministicNarrativeValidator(manifest, [])

        # Statement asserting authoritative debt without caveat -> REJECT
        block_without_caveat = NarrativeBlock(
            section="CIC",
            target_binding=NarrativeTargetBinding.CIC_SUMMARY,
            title="CIC thiếu cảnh báo",
            text="Doanh nghiệp có quan hệ tín dụng chuẩn mực tại các TCTD.",
            facts_used=["CIC_STATUS"],
            insights_used=[]
        )
        res_no_caveat = validator.validate_block(block_without_caveat)
        self.assertFalse(res_no_caveat["valid"], "CIC with incomplete debt must include caveat")
        self.assertTrue(any("CIC external debt is INCOMPLETE" in e for e in res_no_caveat["errors"]))

        # Statement with required caveat -> PASS
        block_with_caveat = NarrativeBlock(
            section="CIC",
            target_binding=NarrativeTargetBinding.CIC_SUMMARY,
            title="CIC có đầy đủ cảnh báo",
            text="Tổng dư nợ tại các TCTD khác chưa thể xác định đầy đủ bằng VND do có khoản nợ ngoại tệ chưa được quy đổi.",
            facts_used=["CIC_STATUS"],
            insights_used=[],
            data_gaps=["GAP_CIC_EXTERNAL_DEBT_INCOMPLETE"]
        )
        res_caveat = validator.validate_block(block_with_caveat)
        self.assertTrue(res_caveat["valid"], f"CIC with caveat must pass: {res_caveat['errors']}")


if __name__ == "__main__":
    unittest.main()
