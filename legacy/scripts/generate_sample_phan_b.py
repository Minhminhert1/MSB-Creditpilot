# -*- coding: utf-8 -*-
"""Generate authoritative sample output for Section B (Demo: 2.1 + 2.6)."""

import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "msb_eb_copilot")
sys.stdout.reconfigure(encoding='utf-8')

from msb_eb_copilot.src.section_b.renderer import render_section_b_docx

def generate_demo():
    payload = {
        "selected_needs": ["2.1_vay_vld_han_muc", "2.6_bao_lanh"],
        "currency": "VND",
        "facilities_data": {
            "need_2_1": {
                "proposal_type": "Tái cấp",
                "approved_limit_vnd": 80000.0,
                "proposed_limit_vnd": 100000.0,
                "note": "Tái cấp tăng hạn mức năm 2026",
                "purpose": "Bổ sung vốn lưu động phục vụ sản xuất kinh doanh phôi thép và thép xây dựng",
                "duration_months": 12,
                "effective_date_rule": "Kể từ ngày ký Hợp đồng tín dụng",
                "max_promissory_note_duration_months": 6,
                "lending_interest_rate": "Theo quy định MSB tại thời điểm giải ngân từng KƯNN",
                "disbursement_method": "Chuyển khoản trực tiếp vào tài khoản bên thụ hưởng",
                "repayment_period": "Gốc trả cuối kỳ mỗi KƯNN; Lãi trả định kỳ hàng tháng",
                "other_conditions": ""
            },
            "need_2_6": {
                "issuance_structure": "Hạn mức",
                "term_classification": "Ngắn hạn",
                "proposal_type": "Cấp mới",
                "approved_limit_vnd": None,
                "proposed_limit_vnd": 20000.0,
                "note": "Cấp mới bảo lãnh năm 2026",
                "purpose": "Phát hành bảo lãnh thực hiện hợp đồng, bảo lãnh thanh toán tiền điện cho EVN",
                "guarantee_types": "Bảo lãnh thực hiện hợp đồng, Bảo lãnh thanh toán",
                "facility_duration_months": 12,
                "effective_date_rule": "Kể từ ngày ký Hợp đồng tín dụng",
                "single_guarantee_duration": "Tối đa 12 tháng kể từ ngày phát hành",
                "min_margin_cash_percentage": "0%",
                "other_conditions": ""
            }
        }
    }

    out_file = "output/TO_TRINH_MB07_PHAN_B_DEMO.docx"
    print("Generating sample Phần B output...")
    res_path, totals, report = render_section_b_docx(payload, out_file)
    print(f"✅ Generated successfully: {res_path}")
    print(f"Tổng hạn mức cấp tín dụng đề xuất: {totals.grand_total_str} triệu VND")
    print(f"Mức cho vay tối đa: {totals.max_lending_str} triệu VND")
    print(f"Bằng chữ: {totals.grand_total_words}")
    print(f"Warnings ({len(report.warnings)}): {report.warnings}")
    print(f"Blocking errors ({len(report.blocking_errors)}): {report.blocking_errors}")
    return res_path

if __name__ == "__main__":
    generate_demo()
