import sys
import os
import traceback

sys.path.insert(0, ".")
sys.path.insert(0, "msb_eb_copilot")
sys.stdout.reconfigure(encoding='utf-8')

from tests.section_b import test_section_b

test_functions = [
    ("TEST 01: Chỉ chọn 2.1 (Xóa 2.2-2.8)", test_section_b.test_01_only_2_1_selected, True),
    ("TEST 02: Chọn 2.1 + 2.6 (Xóa 2.2-2.5, 2.7-2.8)", test_section_b.test_02_select_2_1_and_2_6, False),
    ("TEST 03: 1 Business Fact = 1 Input (Mục 1 + Mục 2)", test_section_b.test_03_single_canonical_amount, True),
    ("TEST 04: Sửa số tiền tự động cập nhật đồng bộ", test_section_b.test_04_modifying_amount_syncs_everywhere, True),
    ("TEST 05: Trường optional để blank (Không ra N/A)", test_section_b.test_05_optional_field_blank_remains_blank, True),
    ("TEST 06: Cảnh báo thời hạn 2.2 <= 12 tháng", test_section_b.test_06_validation_warning_for_2_2_duration, False),
    ("TEST 07: Bảo toàn Merged Cells Mục 2.4 (Ân hạn, Nợ gốc/lãi)", test_section_b.test_07_merged_cells_preserved_for_2_4, False),
    ("TEST 08: Progressive Disclosure Mục 2.8 (Ẩn sản phẩm không chọn)", test_section_b.test_08_progressive_disclosure_for_2_8, False),
    ("TEST 09: Bảo toàn Word Native Form Field Checkbox (Cấp mới/Tái cấp)", test_section_b.test_09_checkbox_native_ooxml_updated, False),
    ("TEST 10: Xóa nhiều block liên tiếp layout không bị vỡ", test_section_b.test_10_deleting_consecutive_blocks_leaves_valid_xml, False),
    ("TEST 11: Bảo toàn Fixed Notes & Footnotes của template", test_section_b.test_11_fixed_notes_preserved, False),
    ("TEST 12: DOCX cuối mở sạch sẽ không lỗi XML schema", test_section_b.test_12_docx_opens_cleanly_without_error, True),
    ("TEST 13: Bảo toàn Font Times New Roman và độ rộng bảng", test_section_b.test_13_formatting_and_column_widths_preserved, True),
    ("TEST 14: Subtype không rõ ràng báo Blocking, không đoán mò", test_section_b.test_14_ambiguous_subtype_triggers_blocking, False),
    ("TEST 15: Điều kiện khác để blank -> Word blank", test_section_b.test_15_optional_other_conditions_blank, False),
]

passed = 0
failed = 0

print("=" * 70)
print("BẮT ĐẦU CHẠY BỘ KIỂM THỬ 15 ACCEPTANCE TESTS CHO PHẦN B")
print("=" * 70)

for name, func, needs_fixture in test_functions:
    try:
        if needs_fixture:
            fix = {
                "selected_needs": ["2.1_vay_vld_han_muc"],
                "currency": "VND",
                "facilities_data": {
                    "need_2_1": {
                        "proposal_type": "Cấp mới",
                        "approved_limit_vnd": None,
                        "proposed_limit_vnd": 50000.0,
                        "purpose": "Bổ sung vốn lưu động",
                        "duration_months": 12,
                        "effective_date_rule": "Kể từ ngày ký Hợp đồng tín dụng",
                        "max_promissory_note_duration_months": 6,
                        "lending_interest_rate": "Theo quy định MSB",
                        "disbursement_method": "Chuyển khoản",
                        "repayment_period": "Gốc trả cuối kỳ, lãi hàng tháng",
                        "other_conditions": ""
                    }
                }
            }
            func(fix)
        else:
            func()
        print(f"  ✅ PASS: {name}")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAIL: {name}")
        traceback.print_exc()
        failed += 1

print("=" * 70)
print(f"KẾT QUẢ: {passed}/{len(test_functions)} TESTS ĐẠT ({passed/len(test_functions)*100:.1f}%)")
print("=" * 70)

if failed > 0:
    sys.exit(1)
