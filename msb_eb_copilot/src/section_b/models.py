# -*- coding: utf-8 -*-
"""Pydantic data models and schemas for Section B: Nội dung đề xuất cấp tín dụng."""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from .enums import (
    CreditNeedId, ProposalType, IssuanceStructure, LoanTermType,
    TenorClassification, ProductTypeLC, ProductTypeDiscount,
    CounterpartySubProduct
)


class FacilityData21(BaseModel):
    """Mục 2.1: Cho vay VLĐ theo hạn mức (ECS1101)."""
    proposal_type: ProposalType = ProposalType.CAP_MOI
    approved_limit_vnd: Optional[float] = None
    proposed_limit_vnd: float = Field(..., gt=0, description="Hạn mức đề xuất mới (triệu VND)")
    note: Optional[str] = ""
    purpose: Optional[str] = ""
    duration_months: Optional[int] = 12
    effective_date_rule: Optional[str] = "Kể từ ngày ký Hợp đồng tín dụng"
    effective_date_custom: Optional[str] = ""
    max_promissory_note_duration_months: Optional[int] = 6
    lending_interest_rate: Optional[str] = ""
    disbursement_method: Optional[str] = ""
    repayment_period: Optional[str] = ""
    other_conditions: Optional[str] = ""


class FacilityData22(BaseModel):
    """Mục 2.2: Cho vay VLĐ hạn mức trên 12 tháng (ECS1101)."""
    proposal_type: ProposalType = ProposalType.CAP_MOI
    approved_limit_vnd: Optional[float] = None
    proposed_limit_vnd: float = Field(..., gt=0, description="Hạn mức đề xuất mới (triệu VND)")
    note: Optional[str] = ""
    purpose: Optional[str] = ""
    facility_duration_months: Optional[int] = 24
    effective_date_rule: Optional[str] = "Kể từ ngày ký Hợp đồng tín dụng"
    effective_date_custom: Optional[str] = ""
    max_promissory_note_duration_months: Optional[int] = 6
    lending_interest_rate: Optional[str] = ""
    disbursement_method: Optional[str] = ""
    repayment_period: Optional[str] = ""
    other_conditions: Optional[str] = ""


class FacilityData23(BaseModel):
    """Mục 2.3: Vay ngắn hạn từng lần (ECS1109)."""
    proposal_type: ProposalType = ProposalType.CAP_MOI
    approved_limit_vnd: Optional[float] = None
    proposed_amount_vnd: float = Field(..., gt=0, description="Số tiền đề xuất (triệu VND)")
    note: Optional[str] = ""
    purpose: Optional[str] = ""
    loan_duration_months: Optional[int] = 6
    effective_date_rule: Optional[str] = "Kể từ ngày ký Hợp đồng tín dụng"
    lending_interest_rate: Optional[str] = ""
    disbursement_method: Optional[str] = ""
    repayment_period: Optional[str] = ""
    other_conditions: Optional[str] = ""


class FacilityData24(BaseModel):
    """Mục 2.4: Vay trung/dài hạn (ECS2100/ECS3100)."""
    loan_term_type: Optional[LoanTermType] = None
    proposal_type: ProposalType = ProposalType.CAP_MOI
    approved_limit_vnd: Optional[float] = None
    proposed_amount_vnd: float = Field(..., gt=0, description="Số tiền đề xuất (triệu VND)")
    note: Optional[str] = ""
    purpose: Optional[str] = ""
    loan_duration_months: Optional[int] = 36
    grace_period: Optional[str] = ""
    drawdown_period: Optional[str] = ""
    lending_interest_rate: Optional[str] = ""
    disbursement_method: Optional[str] = ""
    principal_repayment: Optional[str] = ""
    interest_repayment: Optional[str] = ""
    other_conditions: Optional[str] = ""


class FacilityData25(BaseModel):
    """Mục 2.5: Hạn mức/từng lần phát hành L/C/Nhờ thu (ECS1308/1309/...)."""
    issuance_structure: IssuanceStructure = IssuanceStructure.HAN_MUC
    product_type: ProductTypeLC = ProductTypeLC.LC
    term_classification: TenorClassification = TenorClassification.NGAN_HAN
    proposal_type: ProposalType = ProposalType.CAP_MOI
    approved_limit_vnd: Optional[float] = None
    proposed_limit_vnd: float = Field(..., gt=0, description="Số tiền/Hạn mức đề xuất (triệu VND)")
    note: Optional[str] = ""
    purpose: Optional[str] = ""
    facility_duration_months: Optional[int] = 12
    effective_date_rule: Optional[str] = "Kể từ ngày ký Hợp đồng tín dụng"
    lc_collection_type: Optional[str] = ""
    min_margin_cash_percentage: Optional[str] = ""
    financing_rate_per_lc_value: Optional[str] = ""
    lc_fee: Optional[str] = ""
    other_conditions: Optional[str] = ""


class FacilityData26(BaseModel):
    """Mục 2.6: Hạn mức/từng lần Bảo lãnh (ECS1200/2200/3200)."""
    issuance_structure: IssuanceStructure = IssuanceStructure.HAN_MUC
    term_classification: TenorClassification = TenorClassification.NGAN_HAN
    proposal_type: ProposalType = ProposalType.CAP_MOI
    approved_limit_vnd: Optional[float] = None
    proposed_limit_vnd: float = Field(..., gt=0, description="Số tiền/Hạn mức đề xuất (triệu VND)")
    note: Optional[str] = ""
    purpose: Optional[str] = ""
    guarantee_types: Optional[str] = ""
    facility_duration_months: Optional[int] = 12
    effective_date_rule: Optional[str] = "Kể từ ngày ký Hợp đồng tín dụng"
    single_guarantee_duration: Optional[str] = ""
    min_margin_cash_percentage: Optional[str] = ""
    other_conditions: Optional[str] = ""


class FacilityData27(BaseModel):
    """Mục 2.7: Hạn mức/từng lần chiết khấu BCT/Bao thanh toán (ECS1102/...)."""
    product_type: ProductTypeDiscount = ProductTypeDiscount.CHIET_KHAU
    issuance_structure: IssuanceStructure = IssuanceStructure.HAN_MUC
    proposal_type: ProposalType = ProposalType.CAP_MOI
    approved_limit_vnd: Optional[float] = None
    proposed_amount_vnd: float = Field(..., gt=0, description="Số tiền đề xuất (triệu VND)")
    discount_limit_vnd: Optional[float] = None
    note: Optional[str] = ""
    facility_duration_months: Optional[int] = 12
    effective_date_rule: Optional[str] = "Kể từ ngày ký Hợp đồng tín dụng"
    discount_tenor: Optional[str] = ""
    discount_rate_percentage: Optional[str] = ""
    interest_rate: Optional[str] = ""
    other_conditions: Optional[str] = ""


class FacilityData28(BaseModel):
    """Mục 2.8: Hạn mức rủi ro tín dụng đối tác (ECS9000/ECS9100/9200/9300)."""
    proposal_type: ProposalType = ProposalType.CAP_MOI
    approved_limit_vnd: Optional[float] = None
    proposed_limit_vnd: float = Field(..., gt=0, description="Hạn mức đề xuất (triệu VND)")
    note: Optional[str] = ""
    facility_duration_months: Optional[int] = 12
    effective_date_rule: Optional[str] = "Kể từ ngày ký Hợp đồng tín dụng"
    selected_sub_products: List[CounterpartySubProduct] = []
    fx_limit_vnd: Optional[float] = None
    fx_max_tenor: Optional[str] = ""
    fx_margin_rate: Optional[str] = ""
    ir_limit_vnd: Optional[float] = None
    ir_max_tenor: Optional[str] = ""
    ir_margin_rate: Optional[str] = ""
    other_conditions: Optional[str] = ""


class SectionBDerivedTotals(BaseModel):
    """Dữ liệu tổng hợp và tính toán tự động của Phần B."""
    total_group_a: float = 0.0
    total_group_b: float = 0.0
    total_group_c: float = 0.0
    total_group_d: float = 0.0
    grand_total: float = 0.0
    max_lending_limit: float = 0.0
    grand_total_str: str = ""
    max_lending_str: str = ""
    grand_total_words: str = ""
    max_lending_words: str = ""


class SectionBValidationReport(BaseModel):
    """Báo cáo kiểm tra tính hợp lệ và cảnh báo nghiệp vụ."""
    is_valid: bool = True
    warnings: List[str] = []
    blocking_errors: List[str] = []


class SectionBInputState(BaseModel):
    """Trạng thái toàn bộ dữ liệu đầu vào Phần B do RM cung cấp."""
    selected_needs: List[CreditNeedId] = Field(default_factory=list)
    currency: str = "VND"
    facilities_data: Dict[str, Any] = Field(default_factory=dict)
