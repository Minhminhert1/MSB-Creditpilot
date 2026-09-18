# -*- coding: utf-8 -*-
"""Deterministic calculation engine and business rule validator for Section B."""

from typing import Dict, Any, List, Tuple
from .enums import (
    CreditNeedId, ProposalType, IssuanceStructure, LoanTermType,
    TenorClassification, ValidationSeverity
)
from .models import (
    SectionBInputState, SectionBDerivedTotals, SectionBValidationReport,
    FacilityData21, FacilityData22, FacilityData23, FacilityData24,
    FacilityData25, FacilityData26, FacilityData27, FacilityData28
)
from .number_to_words import format_amount_with_words, format_numeric_amount


def validate_and_calculate_section_b(
    input_data: Dict[str, Any]
) -> Tuple[SectionBDerivedTotals, SectionBValidationReport, Dict[str, Any]]:
    """Kiểm tra tính đầy đủ, nhất quán và tính toán tự động toàn bộ số liệu Phần B."""
    raw_needs = input_data.get("selected_needs", [])
    # normalize selected_needs to list of string values
    selected_needs = [n.value if hasattr(n, "value") else str(n) for n in raw_needs]
    fac_data = input_data.get("facilities_data", {})
    currency = input_data.get("currency", "VND")

    warnings: List[str] = []
    blocking_errors: List[str] = []

    if not selected_needs:
        blocking_errors.append("Chưa chọn nhu cầu cấp tín dụng nào tại Bước 1.")

    total_group_a = 0.0
    total_group_b = 0.0
    total_group_c = 0.0
    total_group_d = 0.0
    max_lending_limit = 0.0

    processed_facs = {}

    # 2.1 Cho vay VLĐ theo hạn mức
    if CreditNeedId.NEED_2_1.value in selected_needs or "2.1" in selected_needs:
        raw_21 = fac_data.get("need_2_1", fac_data.get("2.1", {}))
        f21 = FacilityData21(**raw_21) if isinstance(raw_21, dict) else raw_21
        amt = f21.proposed_limit_vnd or 0.0
        total_group_a += amt
        max_lending_limit += amt
        
        f21_dict = f21.model_dump() if hasattr(f21, "model_dump") else dict(f21)
        f21_dict["amount_formatted"] = format_amount_with_words(amt, currency)
        f21_dict["amount_num_str"] = format_numeric_amount(amt)
        f21_dict["approved_num_str"] = format_numeric_amount(f21.approved_limit_vnd)
        
        if f21.proposal_type == ProposalType.TAI_CAP and not f21.approved_limit_vnd:
            warnings.append("Mục 2.1: Khoản vay được chọn Tái cấp nhưng chưa có thông tin Hạn mức đã được duyệt.")
        processed_facs["need_2_1"] = f21_dict

    # 2.2 Cho vay VLĐ hạn mức trên 12 tháng
    if CreditNeedId.NEED_2_2.value in selected_needs or "2.2" in selected_needs:
        raw_22 = fac_data.get("need_2_2", fac_data.get("2.2", {}))
        f22 = FacilityData22(**raw_22) if isinstance(raw_22, dict) else raw_22
        amt = f22.proposed_limit_vnd or 0.0
        total_group_c += amt
        max_lending_limit += amt
        
        dur = f22.facility_duration_months or 0
        if dur > 0 and dur <= 12:
            warnings.append(
                f"Mục 2.2 là Hạn mức VLĐ trên 12 tháng nhưng thời hạn hiện nhập là {dur} tháng (<= 12 tháng). "
                f"Vui lòng kiểm tra lại phân loại kỳ hạn."
            )
        
        f22_dict = f22.model_dump() if hasattr(f22, "model_dump") else dict(f22)
        f22_dict["amount_formatted"] = format_amount_with_words(amt, currency)
        f22_dict["amount_num_str"] = format_numeric_amount(amt)
        f22_dict["approved_num_str"] = format_numeric_amount(f22.approved_limit_vnd)
        
        if f22.proposal_type == ProposalType.TAI_CAP and not f22.approved_limit_vnd:
            warnings.append("Mục 2.2: Khoản vay được chọn Tái cấp nhưng chưa có thông tin Hạn mức đã được duyệt.")
        processed_facs["need_2_2"] = f22_dict

    # 2.3 Vay ngắn hạn từng lần
    if CreditNeedId.NEED_2_3.value in selected_needs or "2.3" in selected_needs:
        raw_23 = fac_data.get("need_2_3", fac_data.get("2.3", {}))
        f23 = FacilityData23(**raw_23) if isinstance(raw_23, dict) else raw_23
        amt = f23.proposed_amount_vnd or 0.0
        total_group_d += amt
        max_lending_limit += amt
        
        f23_dict = f23.model_dump() if hasattr(f23, "model_dump") else dict(f23)
        f23_dict["amount_formatted"] = format_amount_with_words(amt, currency)
        f23_dict["amount_num_str"] = format_numeric_amount(amt)
        f23_dict["approved_num_str"] = format_numeric_amount(f23.approved_limit_vnd)
        
        if f23.proposal_type == ProposalType.TAI_CAP and not f23.approved_limit_vnd:
            warnings.append("Mục 2.3: Khoản vay được chọn Tái cấp nhưng chưa có thông tin Hạn mức đã được duyệt.")
        processed_facs["need_2_3"] = f23_dict

    # 2.4 Vay trung/dài hạn
    if CreditNeedId.NEED_2_4.value in selected_needs or "2.4" in selected_needs:
        raw_24 = fac_data.get("need_2_4", fac_data.get("2.4", {}))
        f24 = FacilityData24(**raw_24) if isinstance(raw_24, dict) else raw_24
        amt = f24.proposed_amount_vnd or 0.0
        total_group_d += amt
        max_lending_limit += amt
        
        if not f24.loan_term_type:
            blocking_errors.append("Mục 2.4 cần chọn phân loại 'Trung hạn' hoặc 'Dài hạn' để xác định đúng mã ECS.")
        
        f24_dict = f24.model_dump() if hasattr(f24, "model_dump") else dict(f24)
        f24_dict["amount_formatted"] = format_amount_with_words(amt, currency)
        f24_dict["amount_num_str"] = format_numeric_amount(amt)
        f24_dict["approved_num_str"] = format_numeric_amount(f24.approved_limit_vnd)
        
        if f24.proposal_type == ProposalType.TAI_CAP and not f24.approved_limit_vnd:
            warnings.append("Mục 2.4: Khoản vay được chọn Tái cấp nhưng chưa có thông tin Hạn mức đã được duyệt.")
        processed_facs["need_2_4"] = f24_dict

    # 2.5 Hạn mức/từng lần L/C & Nhờ thu
    if CreditNeedId.NEED_2_5.value in selected_needs or "2.5" in selected_needs:
        raw_25 = fac_data.get("need_2_5", fac_data.get("2.5", {}))
        f25 = FacilityData25(**raw_25) if isinstance(raw_25, dict) else raw_25
        amt = f25.proposed_limit_vnd or 0.0
        
        # Determine group
        if f25.issuance_structure == IssuanceStructure.TUNG_LAN:
            total_group_d += amt
        elif f25.term_classification == TenorClassification.TREN_12T:
            total_group_c += amt
        else:
            total_group_a += amt
            
        f25_dict = f25.model_dump() if hasattr(f25, "model_dump") else dict(f25)
        f25_dict["amount_formatted"] = format_amount_with_words(amt, currency)
        f25_dict["amount_num_str"] = format_numeric_amount(amt)
        f25_dict["approved_num_str"] = format_numeric_amount(f25.approved_limit_vnd)
        
        if f25.proposal_type == ProposalType.TAI_CAP and not f25.approved_limit_vnd:
            warnings.append("Mục 2.5: Khoản đề xuất Tái cấp nhưng chưa có thông tin Hạn mức đã được duyệt.")
        processed_facs["need_2_5"] = f25_dict

    # 2.6 Bảo lãnh
    if CreditNeedId.NEED_2_6.value in selected_needs or "2.6" in selected_needs:
        raw_26 = fac_data.get("need_2_6", fac_data.get("2.6", {}))
        f26 = FacilityData26(**raw_26) if isinstance(raw_26, dict) else raw_26
        amt = f26.proposed_limit_vnd or 0.0
        
        if f26.issuance_structure == IssuanceStructure.TUNG_LAN:
            total_group_d += amt
        elif f26.term_classification == TenorClassification.TREN_12T:
            total_group_c += amt
        else:
            total_group_a += amt
            
        f26_dict = f26.model_dump() if hasattr(f26, "model_dump") else dict(f26)
        f26_dict["amount_formatted"] = format_amount_with_words(amt, currency)
        f26_dict["amount_num_str"] = format_numeric_amount(amt)
        f26_dict["approved_num_str"] = format_numeric_amount(f26.approved_limit_vnd)
        
        if f26.proposal_type == ProposalType.TAI_CAP and not f26.approved_limit_vnd:
            warnings.append("Mục 2.6: Khoản đề xuất Tái cấp nhưng chưa có thông tin Hạn mức đã được duyệt.")
        processed_facs["need_2_6"] = f26_dict

    # 2.7 Chiết khấu BCT / Bao thanh toán
    if CreditNeedId.NEED_2_7.value in selected_needs or "2.7" in selected_needs:
        raw_27 = fac_data.get("need_2_7", fac_data.get("2.7", {}))
        f27 = FacilityData27(**raw_27) if isinstance(raw_27, dict) else raw_27
        amt = f27.proposed_amount_vnd or 0.0
        total_group_a += amt
        
        f27_dict = f27.model_dump() if hasattr(f27, "model_dump") else dict(f27)
        f27_dict["amount_formatted"] = format_amount_with_words(amt, currency)
        f27_dict["amount_num_str"] = format_numeric_amount(amt)
        f27_dict["approved_num_str"] = format_numeric_amount(f27.approved_limit_vnd)
        processed_facs["need_2_7"] = f27_dict

    # 2.8 Rủi ro tín dụng đối tác
    if CreditNeedId.NEED_2_8.value in selected_needs or "2.8" in selected_needs:
        raw_28 = fac_data.get("need_2_8", fac_data.get("2.8", {}))
        f28 = FacilityData28(**raw_28) if isinstance(raw_28, dict) else raw_28
        amt = f28.proposed_limit_vnd or 0.0
        total_group_b += amt
        
        f28_dict = f28.model_dump() if hasattr(f28, "model_dump") else dict(f28)
        f28_dict["amount_formatted"] = format_amount_with_words(amt, currency)
        f28_dict["amount_num_str"] = format_numeric_amount(amt)
        f28_dict["approved_num_str"] = format_numeric_amount(f28.approved_limit_vnd)
        
        if not f28.selected_sub_products:
            warnings.append("Mục 2.8: Chưa chọn sản phẩm con nào (Phái sinh ngoại hối hoặc Phái sinh lãi suất).")
        processed_facs["need_2_8"] = f28_dict

    grand_total = total_group_a + total_group_b + total_group_c + total_group_d

    totals = SectionBDerivedTotals(
        total_group_a=total_group_a,
        total_group_b=total_group_b,
        total_group_c=total_group_c,
        total_group_d=total_group_d,
        grand_total=grand_total,
        max_lending_limit=max_lending_limit,
        grand_total_str=format_numeric_amount(grand_total),
        max_lending_str=format_numeric_amount(max_lending_limit),
        grand_total_words=format_amount_with_words(grand_total, currency),
        max_lending_words=format_amount_with_words(max_lending_limit, currency)
    )

    report = SectionBValidationReport(
        is_valid=(len(blocking_errors) == 0),
        warnings=warnings,
        blocking_errors=blocking_errors
    )

    return totals, report, processed_facs
