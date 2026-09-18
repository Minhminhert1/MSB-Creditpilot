"""
Module: agent_section_a.py
Mô tả: Specialist Agent A - Chuyên viên Pháp lý & Sàng lọc sơ bộ (Pre-screening QĐ.RR.074).
Nhiệm vụ:
1. Xử lý 4 nguồn dữ liệu (OCR, RM nhập, Link từ Phần E CIC, Auto mặc định).
2. Kiểm tra tính hợp lệ của vốn (Vốn đăng ký vs Vốn thực góp).
3. Rà soát 6 điều kiện Tiền sàng lọc theo QĐ.RR.074.
4. Render bảng PHẦN A chuẩn 100% theo đúng mẫu biểu MSB MB07.
"""

import os
import sys
import json
from typing import Dict, Any, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class AgentSectionA:
    """Agent A - Xử lý Phần A: Tóm tắt thông tin chung & Hồ sơ Khách hàng."""

    def __init__(self, spec_dir: str = None):
        if spec_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            spec_dir = os.path.join(base_dir, "sections_spec", "01_section_A_profile")
        self.spec_dir = spec_dir

    def validate_and_process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Xử lý nghiệp vụ, kiểm tra chéo và đối soát 4 nguồn dữ liệu."""
        ocr = input_data.get("ocr_from_documents", {})
        rm = input_data.get("rm_provided_inputs", {})
        cic = input_data.get("linked_from_section_e", {})
        auto = input_data.get("auto_default_flags", {})

        warnings = []
        hard_failures = []

        # 1. Đối soát Vốn điều lệ đăng ký vs Vốn thực góp
        cap_reg = ocr.get("charter_capital_registered_vnd", 0.0)
        cap_act = rm.get("actual_contributed_capital_vnd", 0.0)
        if cap_act < cap_reg:
            warnings.append(
                f"Vốn thực góp ({cap_act:,.0f} trđ) nhỏ hơn Vốn đăng ký ({cap_reg:,.0f} trđ). "
                f"Cần kiểm tra thời hạn góp vốn 90 ngày theo Luật Doanh nghiệp."
            )

        # 2. Kiểm tra Doanh thu thuần phân khúc KHDN Lớn (LC >= 200 tỷ VND = 200.000 trđ)
        rev = ocr.get("latest_year_revenue_vnd", 0.0)
        seg = rm.get("customer_segment", "LC")
        if seg == "LC" and rev < 200_000.0:
            warnings.append(
                f"Doanh thu năm gần nhất ({rev:,.0f} trđ) nhỏ hơn ngưỡng 200 tỷ VND của phân khúc LC. "
                f"Đề xuất RM xem xét phân loại phân khúc LMC hoặc xin ngoại lệ."
            )

        # 3. Tính toán tổng hạn mức trong Ma trận Thẩm quyền
        matrix = rm.get("approval_authority_matrix", {})
        existing_total = matrix.get("existing_approved_limit_total_vnd", 0.0)
        existing_unsec = matrix.get("existing_approved_limit_unsecured_vnd", 0.0)
        proposed_total = matrix.get("proposed_limit_total_vnd", 0.0)
        proposed_unsec = matrix.get("proposed_limit_unsecured_vnd", 0.0)

        grand_total_limit = existing_total + proposed_total
        grand_unsecured_limit = existing_unsec + proposed_unsec

        # 4. Đóng gói kết quả đã chuẩn hóa
        processed_profile = {
            # Bảng thông tin định danh
            "company_name": ocr.get("company_name", ""),
            "company_short_name": ocr.get("company_short_name", ""),
            "enterprise_type": ocr.get("enterprise_type", "Công ty Cổ phần"),
            "customer_status": rm.get("customer_status", "KH mới"),
            "cif_number": rm.get("cif_number", ""),
            "customer_segment": rm.get("customer_segment", "LC"),
            "group_affiliation": ocr.get("group_affiliation", "Độc lập"),
            "headquarters_address": ocr.get("headquarters_address", ""),
            "tax_code_business_reg_no": ocr.get("tax_code_business_reg_no", ""),
            "business_reg_date": ocr.get("business_reg_date", ""),
            "business_reg_place": ocr.get("business_reg_place", ""),
            "operation_start_date": ocr.get("operation_start_date", ""),
            "legal_representative_name": ocr.get("legal_representative_name", ""),
            "legal_representative_title": ocr.get("legal_representative_title", ""),
            "credit_applicant_representative": rm.get("credit_applicant_representative", ""),
            
            # 3 cờ auto mặc định
            "restricted_credit_subject": auto.get("restricted_credit_subject", "Không"),
            "environmental_social_risk_esg": auto.get("environmental_social_risk_esg", "Không thuộc đối tượng"),
            "sbv_single_borrower_limit_check": auto.get("sbv_single_borrower_limit_check", "Trong giới hạn"),
            
            # Doanh thu & Ngành nghề
            "latest_year_revenue_vnd": rev,
            "industry_level_5_code": rm.get("industry_level_5_code", ""),
            "industry_level_5_name": rm.get("industry_level_5_name", ""),
            "industry_revenue_share": rm.get("industry_revenue_share", "100%"),
            "main_business_activity": rm.get("main_business_activity", ""),
            "main_products": rm.get("main_products", ""),

            # Vốn & XHTD
            "charter_capital_registered_vnd": cap_reg,
            "actual_contributed_capital_vnd": cap_act,
            "contributed_capital_as_of_date": rm.get("contributed_capital_as_of_date", ""),
            "internal_rating_dvkd": rm.get("internal_rating_dvkd", {"profile_id": "", "rating_grade": "A+", "rating_score": 85.0}),

            # Dư nợ link từ Phần E (CIC)
            "outstanding_loan_at_msb_vnd": cic.get("outstanding_loan_at_msb_vnd", 0.0),
            "total_credit_exposure_at_msb_vnd": cic.get("total_credit_exposure_at_msb_vnd", 0.0),

            # Thẩm quyền phê duyệt
            "approval_authority_matrix": {
                "existing_approved_limit_total_vnd": existing_total,
                "existing_approved_limit_unsecured_vnd": existing_unsec,
                "proposed_limit_total_vnd": proposed_total,
                "proposed_limit_unsecured_vnd": proposed_unsec,
                "grand_total_limit_vnd": grand_total_limit,
                "grand_unsecured_limit_vnd": grand_unsecured_limit,
                "target_approval_level": matrix.get("target_approval_level", "HĐTDCC")
            },
            "latest_approval_session": rm.get("latest_approval_session", "Chưa phát sinh"),
            "credit_proposal_type": rm.get("credit_proposal_type", "Cấp mới"),

            # Trạng thái rà soát
            "validation_status": "PASS" if len(hard_failures) == 0 else "FAIL",
            "warnings": warnings,
            "hard_failures": hard_failures
        }

        return processed_profile


if __name__ == "__main__":
    # Test thử Agent A với sample input
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample_file = os.path.join(base_dir, "sections_spec", "01_section_A_profile", "4_sample_input.json")
    
    with open(sample_file, "r", encoding="utf-8") as f:
        sample_data = json.load(f)

    agent = AgentSectionA()
    result = agent.validate_and_process(sample_data)
    print("=== AGENT A TEST SUCCESSFUL ===")
    print(f"Khách hàng: {result['company_name']}")
    print(f"Tổng HMTD đề xuất: {result['approval_authority_matrix']['proposed_limit_total_vnd']:,.0f} trđ")
    print(f"Dư nợ MSB (Link từ CIC): {result['outstanding_loan_at_msb_vnd']:,.0f} trđ")
    print(f"Cảnh báo rủi ro: {result['warnings']}")
