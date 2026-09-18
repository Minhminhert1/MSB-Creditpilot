# -*- coding: utf-8 -*-
"""Unit tests for deterministic Business Document Mapper.

Module: tests.test_business_mapper
"""

import copy
import pytest

from msb_eb_copilot.src.extraction.business_extraction import (
    BusinessEvidenceField,
    CapitalMilestoneItem,
    ShareholderItem,
    ManagementItem,
    ProductItem,
    WarehouseItem,
    EquipmentItem,
    SupplierItem,
    CustomerItem,
    CompetitorItem,
    BusinessDocumentExtraction,
    GroundingAuditResult,
)
from msb_eb_copilot.src.mapping.business_mapper import BusinessDocumentMapper
from msb_eb_copilot.src.mapping.models import MappingSourceMetadata


@pytest.fixture
def sample_business_extraction():
    return BusinessDocumentExtraction(
        company_name=BusinessEvidenceField(
            value_raw="CÔNG TY CP CÔNG NGHỆ VÀ TRUYỀN THÔNG ĐÔNG NAM Á",
            semantic_label="Tên công ty",
            evidence="Tên công ty: CÔNG TY CP CÔNG NGHỆ...",
            page=1,
        ),
        tax_code=BusinessEvidenceField(
            value_raw="0108889999",
            semantic_label="Mã số thuế",
            evidence="Mã số thuế: 0108889999",
            page=1,
        ),
        history_narrative=BusinessEvidenceField(
            value_raw="Thành lập năm 2015 tiền thân là Trung tâm Công nghệ Viễn thông...",
            semantic_label="Quá trình hình thành",
            evidence="Thành lập năm 2015 tiền thân...",
            page=1,
        ),
        parent_company_or_owner=BusinessEvidenceField(
            value_raw="Tập đoàn Công nghệ Viễn thông Quốc tế Á Châu",
            semantic_label="Chủ sở hữu",
            evidence="trực thuộc sở hữu của Tập đoàn Công nghệ...",
            page=1,
        ),
        capital_milestones=[
            CapitalMilestoneItem(
                effective_date=BusinessEvidenceField(
                    value_raw="2020",
                    semantic_label="Thời điểm",
                    evidence="Năm 2020 tăng vốn",
                    page=1,
                ),
                charter_capital_raw=BusinessEvidenceField(
                    value_raw="50.000",
                    semantic_label="Vốn điều lệ",
                    evidence="đạt 50.000 triệu VND",
                    page=1,
                ),
                event_description=BusinessEvidenceField(
                    value_raw="Tăng vốn điều lệ từ phát hành cổ phần",
                    semantic_label="Sự kiện",
                    evidence="Tăng vốn điều lệ từ phát hành cổ phần",
                    page=1,
                ),
                page=1,
            )
        ],
        shareholders=[
            ShareholderItem(
                shareholder_name=BusinessEvidenceField(
                    value_raw="Tập đoàn Công nghệ Viễn thông Quốc tế Á Châu",
                    semantic_label="Tên cổ đông",
                    evidence="Tập đoàn Á Châu sở hữu 51.0%",
                    page=1,
                ),
                id_tax_code=BusinessEvidenceField(
                    value_raw="0102345678",
                    semantic_label="MST",
                    evidence="MST: 0102345678",
                    page=1,
                ),
                ownership_percentage_raw=BusinessEvidenceField(
                    value_raw="51.0%",
                    semantic_label="Tỷ lệ",
                    evidence="sở hữu 51.0%",
                    page=1,
                ),
                contributed_capital_raw=BusinessEvidenceField(
                    value_raw="61.200",
                    semantic_label="Vốn góp",
                    evidence="vốn góp 61.200 triệu VND",
                    page=1,
                ),
                page=1,
            ),
            ShareholderItem(
                shareholder_name=BusinessEvidenceField(
                    value_raw="Nguyễn Văn Toàn",
                    semantic_label="Tên cổ đông",
                    evidence="Nguyễn Văn Toàn sở hữu 25.5%",
                    page=1,
                ),
                id_tax_code=BusinessEvidenceField(
                    value_raw="001080009876",
                    semantic_label="CCCD",
                    evidence="CCCD: 001080009876",
                    page=1,
                ),
                ownership_percentage_raw=BusinessEvidenceField(
                    value_raw="25.5%",
                    semantic_label="Tỷ lệ",
                    evidence="sở hữu 25.5%",
                    page=1,
                ),
                contributed_capital_raw=BusinessEvidenceField(
                    value_raw="30.600",
                    semantic_label="Vốn góp",
                    evidence="vốn góp 30.600 triệu VND",
                    page=1,
                ),
                page=1,
            ),
            ShareholderItem(
                shareholder_name=BusinessEvidenceField(
                    value_raw="Trần Thị Mai Phương",
                    semantic_label="Tên cổ đông",
                    evidence="Trần Thị Mai Phương sở hữu 15.0%",
                    page=1,
                ),
                id_tax_code=BusinessEvidenceField(
                    value_raw="001185004321",
                    semantic_label="CCCD",
                    evidence="CCCD: 001185004321",
                    page=1,
                ),
                ownership_percentage_raw=BusinessEvidenceField(
                    value_raw="15.0%",
                    semantic_label="Tỷ lệ",
                    evidence="sở hữu 15.0%",
                    page=1,
                ),
                contributed_capital_raw=BusinessEvidenceField(
                    value_raw="18.000",
                    semantic_label="Vốn góp",
                    evidence="vốn góp 18.000 triệu VND",
                    page=1,
                ),
                page=1,
            ),
        ],
        management=[
            ManagementItem(
                full_name=BusinessEvidenceField(
                    value_raw="Nguyễn Văn Toàn",
                    semantic_label="Họ tên",
                    evidence="Chủ tịch HĐQT: Nguyễn Văn Toàn",
                    page=2,
                ),
                position=BusinessEvidenceField(
                    value_raw="Chủ tịch HĐQT kiêm Tổng Giám đốc",
                    semantic_label="Chức vụ",
                    evidence="Chủ tịch HĐQT kiêm Tổng Giám đốc",
                    page=2,
                ),
                explicit_experience_years_raw=BusinessEvidenceField(
                    value_raw="18",
                    semantic_label="Kinh nghiệm",
                    evidence="hơn 18 năm kinh nghiệm",
                    page=2,
                ),
                profile_summary=BusinessEvidenceField(
                    value_raw="Kỹ sư Viễn thông, hơn 18 năm kinh nghiệm",
                    semantic_label="Tóm tắt",
                    evidence="Kỹ sư Viễn thông, hơn 18 năm kinh nghiệm",
                    page=2,
                ),
                page=2,
            ),
            ManagementItem(
                full_name=BusinessEvidenceField(
                    value_raw="Lê Quốc Hưng",
                    semantic_label="Họ tên",
                    evidence="Giám đốc Kỹ thuật: Lê Quốc Hưng",
                    page=2,
                ),
                position=BusinessEvidenceField(
                    value_raw="Giám đốc Kỹ thuật & Vận hành",
                    semantic_label="Chức vụ",
                    evidence="Giám đốc Kỹ thuật & Vận hành",
                    page=2,
                ),
                explicit_experience_years_raw=None,  # Career dates only!
                career_history_raw=BusinessEvidenceField(
                    value_raw="2016-2021: Trưởng phòng IoT; 2021-nay: Giám đốc Kỹ thuật",
                    semantic_label="Lịch sử",
                    evidence="2016-2021: Trưởng phòng IoT; 2021-nay...",
                    page=2,
                ),
                profile_summary=BusinessEvidenceField(
                    value_raw="Chuyên gia IoT và viễn thông",
                    semantic_label="Tóm tắt",
                    evidence="Chuyên gia IoT và viễn thông",
                    page=2,
                ),
                page=2,
            ),
        ],
        operating_model_description=BusinessEvidenceField(
            value_raw="Doanh nghiệp hoạt động theo mô hình sản xuất và phân phối các thiết bị đầu cuối viễn thông và giải pháp IoT.",
            semantic_label="Mô hình vận hành",
            evidence="hoạt động theo mô hình sản xuất và phân phối...",
            page=2,
        ),
        products=[
            ProductItem(
                product_name=BusinessEvidenceField(
                    value_raw="Thiết bị định vị & cảm biến IoT thông minh",
                    semantic_label="Tên SP",
                    evidence="Thiết bị định vị & cảm biến IoT",
                    page=2,
                ),
                brand_or_spec=BusinessEvidenceField(
                    value_raw="Chuẩn công nghiệp IP67",
                    semantic_label="Quy cách",
                    evidence="Chuẩn công nghiệp IP67",
                    page=2,
                ),
                revenue_share_percentage_raw=BusinessEvidenceField(
                    value_raw="45.0%",
                    semantic_label="Tỷ trọng DT",
                    evidence="chiếm 45.0% doanh thu",
                    page=2,
                ),
                page=2,
            )
        ],
        suppliers=[
            SupplierItem(
                supplier_name=BusinessEvidenceField(
                    value_raw="Công ty TNHH Linh Kiện Điện Tử Qualcomm Việt Nam",
                    semantic_label="Tên NCC",
                    evidence="Qualcomm Việt Nam chiếm 32.0%",
                    page=2,
                ),
                supplied_goods=BusinessEvidenceField(
                    value_raw="Chipset 4G/5G và vi xử lý IoT",
                    semantic_label="Hàng hóa",
                    evidence="Chipset 4G/5G và vi xử lý IoT",
                    page=2,
                ),
                purchase_share_percentage_raw=BusinessEvidenceField(
                    value_raw="32.0%",
                    semantic_label="Tỷ trọng mua",
                    evidence="chiếm 32.0%",
                    page=2,
                ),
                payment_terms=BusinessEvidenceField(
                    value_raw="L/C trả ngay",
                    semantic_label="Điều khoản TT",
                    evidence="L/C trả ngay",
                    page=2,
                ),
                page=2,
            )
        ],
        customers=[
            CustomerItem(
                customer_name=BusinessEvidenceField(
                    value_raw="Tổng Công ty Viễn thông Viettel",
                    semantic_label="Tên KH",
                    evidence="Viettel chiếm 34.5%",
                    page=2,
                ),
                product_purchased=BusinessEvidenceField(
                    value_raw="Thiết bị cảm biến và Gateway IoT",
                    semantic_label="Sản phẩm",
                    evidence="Thiết bị cảm biến và Gateway IoT",
                    page=2,
                ),
                revenue_share_percentage_raw=BusinessEvidenceField(
                    value_raw="34.5%",
                    semantic_label="Tỷ trọng DT",
                    evidence="chiếm 34.5%",
                    page=2,
                ),
                credit_terms=BusinessEvidenceField(
                    value_raw="Bảo lãnh thanh toán 45 ngày",
                    semantic_label="Công nợ",
                    evidence="Bảo lãnh thanh toán 45 ngày",
                    page=2,
                ),
                page=2,
            )
        ],
        market_share_claim=BusinessEvidenceField(
            value_raw="Chiếm khoảng 22% thị phần phân phối thiết bị IoT chuyên dụng tại Việt Nam.",
            semantic_label="Thị phần",
            evidence="Chiếm khoảng 22% thị phần...",
            page=2,
        ),
        competitors=[
            CompetitorItem(
                competitor_name=BusinessEvidenceField(
                    value_raw="Công ty Cổ phần Viễn thông Á Châu",
                    semantic_label="Đối thủ",
                    evidence="Đối thủ chính: Công ty Cổ phần Viễn thông Á Châu",
                    page=2,
                ),
                page=2,
            )
        ],
        competitive_advantages_claim=BusinessEvidenceField(
            value_raw="Lợi thế về dây chuyền công nghệ kiểm thử SMT đạt chuẩn quốc tế.",
            semantic_label="Lợi thế",
            evidence="Lợi thế về dây chuyền công nghệ...",
            page=2,
        ),
    )


class TestBusinessDocumentMapper:
    def test_section_c_isolation_and_deepcopy(self, sample_business_extraction):
        """Verify that mapper leaves customer identity and other sections completely untouched."""
        orig_case_data = {
            "customer": {"name": "ORIGINAL NAME", "tax_code": "0108889999"},
            "section_a": {"key_a": "value_a"},
            "section_b": {"total_limit": 500000},
            "section_d": {"net_revenue": [1000, 2000, 3000]},
            "section_e": {"msb_outstanding": 7200},
            "section_c": {
                "rm_management_assessment": "Đánh giá quản trị ban lãnh đạo rất tốt.",
                "rm_market_position": "Vị thế hàng đầu thị trường.",
            },
        }
        case_copy = copy.deepcopy(orig_case_data)
        src_meta = MappingSourceMetadata("business_doc.pdf", "digital", "BusinessDocumentExtractor")

        res = BusinessDocumentMapper.map(orig_case_data, sample_business_extraction, src_meta)

        # 1. Non-mutating
        assert orig_case_data == case_copy

        # 2. Customer identity untouched
        assert res.case_data["customer"]["name"] == "ORIGINAL NAME"
        assert res.case_data["customer"]["tax_code"] == "0108889999"

        # 3. Sections A, B, D, E untouched
        assert res.case_data["section_a"] == orig_case_data["section_a"]
        assert res.case_data["section_b"] == orig_case_data["section_b"]
        assert res.case_data["section_d"] == orig_case_data["section_d"]
        assert res.case_data["section_e"] == orig_case_data["section_e"]

        # 4. RM-owned fields preserved
        assert res.case_data["section_c"]["rm_management_assessment"] == "Đánh giá quản trị ban lãnh đạo rất tốt."
        assert res.case_data["section_c"]["rm_market_position"] == "Vị thế hàng đầu thị trường."

    def test_management_experience_semantics(self, sample_business_extraction):
        """Explicit number -> int; dates only -> None (never 0)."""
        src_meta = MappingSourceMetadata("business_doc.pdf", "digital", "BusinessDocumentExtractor")
        res = BusinessDocumentMapper.map({}, sample_business_extraction, src_meta)

        mgmt = res.case_data["section_c"]["management"]
        assert len(mgmt) == 2

        # Manager 1: explicit 18 years
        assert mgmt[0]["name"] == "Nguyễn Văn Toàn"
        assert mgmt[0]["exp"] == 18

        # Manager 2: career dates only -> exp must be strictly None!
        assert mgmt[1]["name"] == "Lê Quốc Hưng"
        assert mgmt[1]["exp"] is None
        assert "2016-2021" in mgmt[1]["note"] or "Chuyên gia" in mgmt[1]["note"]

    def test_capital_milestone_date_precision(self, sample_business_extraction):
        """Must preserve year only '2020', never invent '01/01/2020'."""
        src_meta = MappingSourceMetadata("business_doc.pdf", "digital", "BusinessDocumentExtractor")
        res = BusinessDocumentMapper.map({}, sample_business_extraction, src_meta)

        milestones = res.case_data["section_c"]["capital_milestones"]
        assert len(milestones) == 1
        assert milestones[0]["effective_date"] == "2020"
        assert milestones[0]["charter_capital_million_vnd"] == 50000.0

    def test_derived_fields_computed_correctly(self, sample_business_extraction):
        """is_major_shareholder (pct >= 5.0) and has_cic_check (share >= 30.0)."""
        src_meta = MappingSourceMetadata("business_doc.pdf", "digital", "BusinessDocumentExtractor")
        res = BusinessDocumentMapper.map({}, sample_business_extraction, src_meta)

        # Shareholders
        sh = res.case_data["section_c"]["shareholders"]
        assert len(sh) == 3
        assert sh[0]["pct"] == 51.0
        assert sh[0]["is_major_shareholder"] is True
        assert sh[1]["pct"] == 25.5
        assert sh[1]["is_major_shareholder"] is True
        assert sh[2]["pct"] == 15.0
        assert sh[2]["is_major_shareholder"] is True

        # Supplier has_cic_check (32.0% >= 30.0 -> True)
        sups = res.case_data["section_c"]["suppliers"]
        assert len(sups) == 1
        assert sups[0]["share"] == 32.0
        assert sups[0]["has_cic_check"] is True

    def test_canonical_eligibility_rejection_gate(self, sample_business_extraction):
        """Rejected facts are never written to canonical section_c."""
        src_meta = MappingSourceMetadata("business_doc.pdf", "digital", "BusinessDocumentExtractor")
        audits = {
            "section_c.parent_company_or_owner": GroundingAuditResult(
                status="REJECTED",
                field_name="section_c.parent_company_or_owner",
                reason="Value hallucinated on page 1.",
                value_raw="Tập đoàn Á Châu",
                page=1,
            )
        }

        res = BusinessDocumentMapper.map({}, sample_business_extraction, src_meta, grounding_audits=audits)
        assert "parent_company_or_owner" not in res.case_data["section_c"]
        assert any(w.canonical_path == "section_c.parent_company_or_owner" for w in res.warnings)

    def test_conflict_detection_and_resolution(self, sample_business_extraction):
        """Conflicting field surfaces MappingConflict and obeys RM resolution."""
        existing_case = {
            "section_c": {
                "parent_company_or_owner": "Tập đoàn Cũ Khác",
            }
        }
        src_meta = MappingSourceMetadata("business_doc.pdf", "digital", "BusinessDocumentExtractor")

        # 1. Unresolved conflict
        res1 = BusinessDocumentMapper.map(existing_case, sample_business_extraction, src_meta)
        assert len(res1.conflicts) == 1
        assert res1.conflicts[0].canonical_path == "section_c.parent_company_or_owner"
        assert res1.conflicts[0].existing_value == "Tập đoàn Cũ Khác"
        # Keeps existing when unresolved
        assert res1.case_data["section_c"]["parent_company_or_owner"] == "Tập đoàn Cũ Khác"

        # 2. Resolved with use_extracted
        res2 = BusinessDocumentMapper.map(
            existing_case,
            sample_business_extraction,
            src_meta,
            resolutions={"section_c.parent_company_or_owner": "use_extracted"},
        )
        assert res2.case_data["section_c"]["parent_company_or_owner"] == "Tập đoàn Công nghệ Viễn thông Quốc tế Á Châu"

        # 3. Resolved with keep_existing
        res3 = BusinessDocumentMapper.map(
            existing_case,
            sample_business_extraction,
            src_meta,
            resolutions={"section_c.parent_company_or_owner": "keep_existing"},
        )
        assert res3.case_data["section_c"]["parent_company_or_owner"] == "Tập đoàn Cũ Khác"

    def test_canonical_section_c_contains_business_state_only(self, sample_business_extraction):
        """Verify section_c contains only business state and no workflow/metadata keys."""
        src_meta = MappingSourceMetadata("business_doc.pdf", "digital", "BusinessDocumentExtractor")
        res = BusinessDocumentMapper.map({}, sample_business_extraction, src_meta)
        sec_c = res.case_data["section_c"]
        forbidden_keys = {
            "_preview",
            "_source_metadata",
            "_provenance",
            "_grounding",
            "warnings",
            "conflicts",
            "identity_reconciliation",
        }
        found_forbidden = forbidden_keys.intersection(sec_c.keys())
        assert not found_forbidden, f"Found forbidden workflow keys in canonical section_c: {found_forbidden}"
        assert "_provenance" not in res.case_data
        assert "_source_metadata" not in res.case_data
