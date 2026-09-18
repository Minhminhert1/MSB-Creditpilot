# -*- coding: utf-8 -*-
"""Unit tests for Business Document Extraction, Grounding Auditor, and Identity Reconciler.

Module: tests.test_business_extraction
"""

import pytest
from pydantic import ValidationError

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
    BusinessGroundingAuditor,
    BusinessIdentityReconciler,
    BusinessModelClassifier,
    GroundingAuditResult,
)
from msb_eb_copilot.src.mapping.business_mapper import BusinessNormalizer


class TestBusinessExtractionSchema:
    def test_strict_schema_forbid_extra(self):
        """Verify that extra fields raise ValidationError across all models."""
        with pytest.raises(ValidationError):
            BusinessEvidenceField(value_raw="test", extra_field="forbidden")

        with pytest.raises(ValidationError):
            ShareholderItem(page=1, random_attr="bad")

        with pytest.raises(ValidationError):
            ManagementItem(page=1, extra_notes="bad")

        with pytest.raises(ValidationError):
            BusinessDocumentExtraction(unsupported_field="fail")

    def test_valid_root_extraction(self):
        """Verify valid instantiations with per-field evidence."""
        extraction = BusinessDocumentExtraction(
            company_name=BusinessEvidenceField(
                value_raw="CÔNG TY CP ĐÔNG NAM Á",
                semantic_label="Tên công ty",
                evidence="Tên công ty: CÔNG TY CP ĐÔNG NAM Á",
                page=1,
            ),
            tax_code=BusinessEvidenceField(
                value_raw="0108889999",
                semantic_label="Mã số thuế",
                evidence="Mã số thuế: 0108889999",
                page=1,
            ),
            established_year=BusinessEvidenceField(
                value_raw="2015",
                semantic_label="Năm thành lập",
                evidence="Năm thành lập: 2015",
                page=1,
            ),
            shareholders=[
                ShareholderItem(
                    shareholder_name=BusinessEvidenceField(
                        value_raw="Nguyễn Văn Toàn",
                        semantic_label="Tên cổ đông",
                        evidence="Nguyễn Văn Toàn sở hữu 25.5%",
                        page=1,
                    ),
                    ownership_percentage_raw=BusinessEvidenceField(
                        value_raw="25.5%",
                        semantic_label="Tỷ lệ",
                        evidence="sở hữu 25.5%",
                        page=1,
                    ),
                    page=1,
                )
            ],
            management=[
                ManagementItem(
                    full_name=BusinessEvidenceField(
                        value_raw="Lê Quốc Hưng",
                        semantic_label="Họ tên",
                        evidence="Giám đốc Kỹ thuật: Lê Quốc Hưng",
                        page=2,
                    ),
                    explicit_experience_years_raw=None,
                    career_history_raw=BusinessEvidenceField(
                        value_raw="2016-2021: Trưởng phòng IoT",
                        semantic_label="Lịch sử",
                        evidence="2016-2021: Trưởng phòng IoT",
                        page=2,
                    ),
                    page=2,
                )
            ],
        )
        assert extraction.company_name.value_raw == "CÔNG TY CP ĐÔNG NAM Á"
        assert len(extraction.shareholders) == 1
        assert extraction.management[0].explicit_experience_years_raw is None


class TestBusinessGroundingAuditor:
    def test_audit_verified_exact_match(self):
        pages = {1: "Công ty Cổ phần Công nghệ Đông Nam Á được thành lập năm 2015 tại Hà Nội."}
        field = BusinessEvidenceField(
            value_raw="2015",
            semantic_label="Năm thành lập",
            evidence="thành lập năm 2015",
            page=1,
        )
        res = BusinessGroundingAuditor.audit_field(field, "section_c.established_year", pages, 1)
        assert res.status == "VERIFIED"

    def test_audit_missing_field(self):
        pages = {1: "Một số nội dung khác."}
        res = BusinessGroundingAuditor.audit_field(None, "section_c.missing", pages, 1)
        assert res.status == "MISSING"

    def test_audit_page_out_of_bounds(self):
        pages = {1: "Nội dung trang 1."}
        field = BusinessEvidenceField(
            value_raw="2015",
            semantic_label="Năm thành lập",
            evidence="năm 2015",
            page=5,
        )
        res = BusinessGroundingAuditor.audit_field(field, "section_c.established_year", pages, 1)
        assert res.status == "REJECTED"
        assert "out of bounds" in res.reason

    def test_audit_empty_evidence(self):
        pages = {1: "Nội dung trang 1 năm 2015."}
        field = BusinessEvidenceField(
            value_raw="2015",
            semantic_label="Năm thành lập",
            evidence="",
            page=1,
        )
        res = BusinessGroundingAuditor.audit_field(field, "section_c.established_year", pages, 1)
        assert res.status == "REJECTED"
        assert "missing supporting evidence" in res.reason.lower()

    def test_audit_rejected_hallucinated_value(self):
        pages = {1: "Công ty phân phối sản phẩm viễn thông chính hãng."}
        field = BusinessEvidenceField(
            value_raw="999.000.000.000",
            semantic_label="Doanh thu",
            evidence="Doanh thu đạt 999 tỷ đồng",
            page=1,
        )
        res = BusinessGroundingAuditor.audit_field(field, "section_c.fake_fact", pages, 1)
        assert res.status == "REJECTED"
        assert "not found on page" in res.reason


class TestBusinessIdentityReconciler:
    def test_identity_match(self):
        case_customer = {
            "name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ TRUYỀN THÔNG ĐÔNG NAM Á",
            "tax_code": "0108889999",
        }
        status, msg = BusinessIdentityReconciler.reconcile("0108889999", "CÔNG TY CP ĐÔNG NAM Á", case_customer)
        assert status == "MATCH"

    def test_identity_mismatch_tax_code(self):
        case_customer = {
            "name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ ĐÔNG NAM Á",
            "tax_code": "0108889999",
        }
        status, msg = BusinessIdentityReconciler.reconcile("0100000000", "CÔNG TY CP ĐÔNG NAM Á", case_customer)
        assert status == "MISMATCH"
        assert "KHÔNG TRÙNG KHỚP" in msg

    def test_identity_warning_different_name(self):
        case_customer = {
            "name": "CÔNG TY CỔ PHẦN PHÂN PHỐI DẦU KHÍ",
            "tax_code": "",
        }
        status, msg = BusinessIdentityReconciler.reconcile("", "CÔNG TY TNHH BẢO HIỂM BƯU ĐIỆN", case_customer)
        assert status == "WARNING"


class TestBusinessModelClassifier:
    def test_suggest_mfg_and_trade_hybrid(self):
        desc = "Doanh nghiệp hoạt động theo mô hình sản xuất và phân phối thiết bị đầu cuối viễn thông."
        assert BusinessModelClassifier.suggest_model(desc) == "HON_HOP"

    def test_suggest_manufacturing(self):
        desc = "Nhà máy gia công, chế tạo bo mạch SMT và lắp ráp linh kiện điện tử."
        assert BusinessModelClassifier.suggest_model(desc) == "SAN_XUAT"

    def test_suggest_trading(self):
        desc = "Doanh nghiệp chuyên nhập khẩu, bán buôn và phân phối thiết bị CNTT."
        assert BusinessModelClassifier.suggest_model(desc) == "THUONG_MAI"

    def test_suggest_service(self):
        desc = "Cung cấp dịch vụ logistics, kho bãi và vận tải hàng hóa."
        assert BusinessModelClassifier.suggest_model(desc) == "DICH_VU"

    def test_suggest_ambiguous_returns_none(self):
        desc = "Doanh nghiệp đầu tư và phát triển các giải pháp tổng thể."
        assert BusinessModelClassifier.suggest_model(desc) is None


class TestBusinessNormalizer:
    def test_normalize_percentage(self):
        assert BusinessNormalizer.normalize_percentage("25.4%") == 25.4
        assert BusinessNormalizer.normalize_percentage("30,5 %") == 30.5
        assert BusinessNormalizer.normalize_percentage("") is None
        assert BusinessNormalizer.normalize_percentage("invalid") is None

    def test_normalize_monetary_million(self):
        assert BusinessNormalizer.normalize_monetary_million("50.000 triệu VND") == 50000.0
        assert BusinessNormalizer.normalize_monetary_million("120 tỷ VND") == 120000.0
        assert BusinessNormalizer.normalize_monetary_million("50.000.000.000") == 50000.0

    def test_normalize_experience_years(self):
        assert BusinessNormalizer.normalize_experience_years("Hơn 18 năm kinh nghiệm") == 18
        assert BusinessNormalizer.normalize_experience_years("2016-2021: Trưởng phòng") is None
        assert BusinessNormalizer.normalize_experience_years("") is None

    def test_normalize_milestone_date_preserves_precision(self):
        # Must preserve year only, never invent 01/01/2020!
        assert BusinessNormalizer.normalize_milestone_date("2020") == "2020"
        assert BusinessNormalizer.normalize_milestone_date("15/05/2023") == "15/05/2023"
        assert BusinessNormalizer.normalize_milestone_date("05-2023") == "05/2023"
