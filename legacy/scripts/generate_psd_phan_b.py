# -*- coding: utf-8 -*-
"""Generate Section B Word document for customer PSD (CTCP Dịch vụ Phân phối Tổng hợp Dầu khí)."""

import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "msb_eb_copilot")
sys.stdout.reconfigure(encoding='utf-8')

from msb_eb_copilot.src.section_b.renderer import render_section_b_docx

def generate_psd():
    payload = {
        "selected_needs": ["2.1_vay_vld_han_muc"],
        "currency": "VND",
        "facilities_data": {
            "need_2_1": {
                "proposal_type": "Cấp mới",
                "approved_limit_vnd": None,
                "proposed_limit_vnd": 2200000.0,
                "note": "Cấp mới hạn mức năm 2026",
                "purpose": "Tài trợ góp vốn vào các công ty: Công ty TNHH Hạ tầng Gelex Tây Thành Phố, Công ty TNHH Hạ tầng Gelex Bắc Sài Gòn 1 và Công ty TNHH Hạ tầng Gelex Bắc Sài Gòn 2.",
                "duration_months": 12,
                "effective_date_rule": "Kể từ ngày ký Hợp đồng tín dụng",
                "max_promissory_note_duration_months": 6,
                "lending_interest_rate": "3%",
                "disbursement_method": "Chuyển khoản",
                "repayment_period": "Lãi trả định kì hàng tháng",
                "other_conditions": ""
            }
        }
    }

    out_file = "output/TO_TRINH_MB07_PHAN_B_PSD.docx"
    print("=" * 70)
    print("BẮT ĐẦU SINH TỜ TRÌNH PHẦN B CHO KHÁCH HÀNG PSD")
    print("=" * 70)
    res_path, totals, report = render_section_b_docx(payload, out_file)
    print(f"✅ ĐÃ XUẤT THÀNH CÔNG: {res_path}")
    print(f"Tổng HMTD đề xuất: {totals.grand_total_str} triệu VND")
    print(f"Mức cho vay tối đa: {totals.max_lending_str} triệu VND")
    print(f"Bằng chữ: {totals.grand_total_words}")
    print(f"Warnings ({len(report.warnings)}): {report.warnings}")
    print(f"Blocking Errors ({len(report.blocking_errors)}): {report.blocking_errors}")
    return res_path, totals, report

if __name__ == "__main__":
    generate_psd()
