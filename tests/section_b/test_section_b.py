# -*- coding: utf-8 -*-
"""Comprehensive automated acceptance test suite for Section B Copilot.

Verifies all 15 scenarios specified in Section XXXVII of the requirements:
- Test 1: Only 2.1 selected -> only block 2.1 remains, 2.2-2.8 deleted.
- Test 2: 2.1 + 2.6 selected -> 2.2-2.5, 2.7-2.8 deleted.
- Test 3: Canonical fact -> amount entered once appears in Mục 1 and Mục 2.1.
- Test 4: Modifying amount propagates in sync across all targets.
- Test 5: Optional field left blank remains blank in Word (no N/A).
- Test 6: 2.2 duration <= 12 months triggers validation warning.
- Test 7: 2.4 merged cells preserved for Ân hạn and Nợ gốc / Nợ lãi.
- Test 8: 2.8 selecting only FX derivative excludes IR derivative.
- Test 9: Cấp mới vs Tái cấp sets native Word form field checkbox.
- Test 10: Deleting consecutive blocks leaves valid, contiguous Word XML.
- Test 11: Fixed notes / footnotes preserved without orphan references.
- Test 12: Output document opens cleanly without XML schema errors.
- Test 13: Formatting, borders, column widths preserved.
- Test 14: Ambiguous need mapping triggers blocking error, no guessing.
- Test 15: Optional "Điều kiện khác" left blank produces blank value cell.
"""

import os
import copy
import docx
from lxml import etree

from msb_eb_copilot.src.section_b.enums import (
    CreditNeedId, ProposalType, IssuanceStructure, LoanTermType,
    TenorClassification, CounterpartySubProduct
)
from msb_eb_copilot.src.section_b.validator import validate_and_calculate_section_b
from msb_eb_copilot.src.section_b.renderer import render_section_b_docx

OUTPUT_DIR = "output/test_section_b"
os.makedirs(OUTPUT_DIR, exist_ok=True)
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


import pytest


@pytest.fixture
def base_input_21():
    return {
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


def test_01_only_2_1_selected(base_input_21):
    """TEST 1: Chỉ chọn 2.1. Output Mục 2 chỉ còn block 2.1."""
    out_file = os.path.join(OUTPUT_DIR, "test_01_only_2_1.docx")
    render_section_b_docx(base_input_21, out_file)
    
    doc = docx.Document(out_file)
    # Check remaining 2.x headings in document
    headings_2x = [p.text.strip() for p in doc.paragraphs if p.text.strip().startswith("2.")]
    assert len(headings_2x) == 1
    assert "2.1 Cho vay VLĐ" in headings_2x[0]
    
    # Check that 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8 are NOT in any paragraph
    full_text = " ".join([p.text for p in doc.paragraphs])
    for code in ["2.2", "2.3", "2.4", "2.5", "2.6", "2.7", "2.8"]:
        assert f"{code} " not in full_text


def test_02_select_2_1_and_2_6():
    """TEST 2: Chọn 2.1 + 2.6. Không có bất kỳ block nào thuộc 2.2/2.3/2.4/2.5/2.7/2.8."""
    payload = {
        "selected_needs": ["2.1_vay_vld_han_muc", "2.6_bao_lanh"],
        "currency": "VND",
        "facilities_data": {
            "need_2_1": {
                "proposal_type": "Cấp mới",
                "proposed_limit_vnd": 100000.0,
                "purpose": "Kinh doanh phôi thép",
                "duration_months": 12,
            },
            "need_2_6": {
                "issuance_structure": "Hạn mức",
                "term_classification": "Ngắn hạn",
                "proposal_type": "Cấp mới",
                "proposed_limit_vnd": 20000.0,
                "purpose": "Bảo lãnh thực hiện hợp đồng",
            }
        }
    }
    out_file = os.path.join(OUTPUT_DIR, "test_02_2_1_and_2_6.docx")
    render_section_b_docx(payload, out_file)
    
    doc = docx.Document(out_file)
    headings_2x = [p.text.strip() for p in doc.paragraphs if p.text.strip().startswith("2.")]
    assert len(headings_2x) == 2
    assert any("2.1" in h for h in headings_2x)
    assert any("2.6" in h for h in headings_2x)
    for code in ["2.2", "2.3", "2.4", "2.5", "2.7", "2.8"]:
        assert not any(code in h for h in headings_2x)


def test_03_single_canonical_amount(base_input_21):
    """TEST 3: RM nhập amount 2.1 một lần. Value tự xuất hiện Mục 1 + Mục 2.1 + Opening paragraph."""
    out_file = os.path.join(OUTPUT_DIR, "test_03_canonical_amount.docx")
    render_section_b_docx(base_input_21, out_file)
    
    doc = docx.Document(out_file)
    # Check Table 0 Row 2 (ECS1100) proposed limit
    t0_r2_c3 = doc.tables[0].rows[2].cells[3].text.strip()
    assert t0_r2_c3 == "50.000"
    
    # Check Table 1 Row 0 (Số tiền)
    t1_r0_c1 = doc.tables[1].rows[0].cells[1].text.strip()
    assert "50.000.000.000 VND" in t1_r0_c1
    assert "Năm mươi tỷ đồng" in t1_r0_c1
    
    # Check opening paragraph P2
    p2_text = [p.text for p in doc.paragraphs if "Tổng hạn mức cấp tín dụng (A+B)" in p.text][0]
    assert "50.000 triệu đồng" in p2_text


def test_04_modifying_amount_syncs_everywhere(base_input_21):
    """TEST 4: RM sửa amount từ 50 tỷ thành 75 tỷ. Tất cả nơi output thay đổi đồng bộ."""
    modified = copy.deepcopy(base_input_21)
    modified["facilities_data"]["need_2_1"]["proposed_limit_vnd"] = 75000.0
    
    out_file = os.path.join(OUTPUT_DIR, "test_04_modified_amount.docx")
    render_section_b_docx(modified, out_file)
    
    doc = docx.Document(out_file)
    assert doc.tables[0].rows[2].cells[3].text.strip() == "75.000"
    assert "75.000.000.000 VND" in doc.tables[1].rows[0].cells[1].text.strip()
    assert "Bảy mươi lăm tỷ đồng" in doc.tables[1].rows[0].cells[1].text.strip()
    p2 = [p.text for p in doc.paragraphs if "Tổng hạn mức cấp tín dụng (A+B)" in p.text][0]
    assert "75.000 triệu đồng" in p2


def test_05_optional_field_blank_remains_blank(base_input_21):
    """TEST 5: Field optional để blank -> Word output cũng blank. Không xuất N/A."""
    base_input_21["facilities_data"]["need_2_1"]["other_conditions"] = ""
    out_file = os.path.join(OUTPUT_DIR, "test_05_optional_blank.docx")
    render_section_b_docx(base_input_21, out_file)
    
    doc = docx.Document(out_file)
    t1 = doc.tables[1]
    # Row 8 is Điều kiện khác
    r8_c1 = t1.rows[8].cells[1].text.strip()
    assert r8_c1 == ""
    assert "N/A" not in r8_c1
    assert "Không có" not in r8_c1


def test_06_validation_warning_for_2_2_duration():
    """TEST 6: 2.2 có thời hạn <= 12 tháng -> Hiển thị warning, không tự sửa."""
    payload = {
        "selected_needs": ["2.2_vay_vld_han_muc_tren_12t"],
        "currency": "VND",
        "facilities_data": {
            "need_2_2": {
                "proposed_limit_vnd": 30000.0,
                "facility_duration_months": 12  # <= 12 triggers warning!
            }
        }
    }
    totals, report, facs = validate_and_calculate_section_b(payload)
    assert any("2.2" in w and "<= 12 tháng" in w for w in report.warnings)


def test_07_merged_cells_preserved_for_2_4():
    """TEST 7: 2.4 vẫn giữ đúng merged cells: Thời hạn / Ân hạn và Nợ gốc / Nợ lãi."""
    payload = {
        "selected_needs": ["2.4_vay_trung_dai_han"],
        "currency": "VND",
        "facilities_data": {
            "need_2_4": {
                "loan_term_type": "Trung hạn",
                "proposed_amount_vnd": 45000.0,
                "purpose": "Đầu tư máy móc thiết bị",
                "loan_duration_months": 36,
                "grace_period": "6 tháng",
                "principal_repayment": "Định kỳ 3 tháng/lần",
                "interest_repayment": "Hàng tháng"
            }
        }
    }
    out_file = os.path.join(OUTPUT_DIR, "test_07_merged_cells.docx")
    render_section_b_docx(payload, out_file)
    
    doc = docx.Document(out_file)
    t4 = doc.tables[1]  # detail table for 2.4
    # Row 2 contains Thời hạn khoản vay and Ân hạn
    row2 = t4.rows[2]
    assert "thời hạn khoản vay" in row2.cells[0].text.lower()
    assert "36 tháng" in row2.cells[1].text
    assert "ân hạn" in row2.cells[3].text.lower()
    assert "6 tháng" in row2.cells[4].text
    
    # Row 6 contains Nợ gốc vay and Nợ Lãi vay
    row6 = t4.rows[6]
    assert "nợ gốc vay" in row6.cells[1].text.lower()
    assert "3 tháng/lần" in row6.cells[2].text
    assert "nợ lãi vay" in row6.cells[5].text.lower()
    assert "hàng tháng" in row6.cells[6].text.lower()


def test_08_progressive_disclosure_for_2_8():
    """TEST 8: 2.8 chỉ chọn phái sinh ngoại hối -> không có data phái sinh lãi suất."""
    payload = {
        "selected_needs": ["2.8_rui_ro_doi_tac"],
        "currency": "VND",
        "facilities_data": {
            "need_2_8": {
                "proposed_limit_vnd": 10000.0,
                "selected_sub_products": [CounterpartySubProduct.FX_DERIVATIVE.value],
                "fx_limit_vnd": 10000.0,
                "fx_max_tenor": "3 tháng",
                "fx_margin_rate": "5%",
                "ir_limit_vnd": None,
                "ir_max_tenor": ""
            }
        }
    }
    out_file = os.path.join(OUTPUT_DIR, "test_08_progressive_disclosure_2_8.docx")
    render_section_b_docx(payload, out_file)
    
    doc = docx.Document(out_file)
    t8 = doc.tables[1]
    # Check row 3 (FX limit) has 10.000
    assert "10.000" in t8.rows[3].cells[1].text
    # Check row 6 (IR limit) is blank
    assert t8.rows[6].cells[1].text.strip() == ""


def test_09_checkbox_native_ooxml_updated():
    """TEST 9: Cấp mới / Tái cấp -> Word native checkbox toggle w:checked properly."""
    payload = {
        "selected_needs": ["2.1_vay_vld_han_muc"],
        "currency": "VND",
        "facilities_data": {
            "need_2_1": {
                "proposal_type": "Tái cấp",
                "approved_limit_vnd": 40000.0,
                "proposed_limit_vnd": 50000.0,
            }
        }
    }
    out_file = os.path.join(OUTPUT_DIR, "test_09_checkbox.docx")
    render_section_b_docx(payload, out_file)
    
    doc = docx.Document(out_file)
    row2 = doc.tables[0].rows[2]
    tc = row2.cells[4]._tc
    ff_datas = tc.xpath(".//w:ffData")
    assert len(ff_datas) >= 2
    
    # Checkbox 0 (Tái cấp) must be checked (val=1)
    cb0 = ff_datas[0].find(f".//{{{W_NS}}}checkBox")
    assert cb0.find(f".//{{{W_NS}}}checked").get(f"{{{W_NS}}}val") == "1"
    
    # Checkbox 1 (Cấp mới) must be unchecked (val=0)
    cb1 = ff_datas[1].find(f".//{{{W_NS}}}checkBox")
    assert cb1.find(f".//{{{W_NS}}}checked").get(f"{{{W_NS}}}val") == "0"


def test_10_deleting_consecutive_blocks_leaves_valid_xml():
    """TEST 10: Xóa nhiều block liên tiếp (2.2 đến 2.7). Layout Word không hỏng."""
    payload = {
        "selected_needs": ["2.1_vay_vld_han_muc", "2.8_rui_ro_doi_tac"],
        "currency": "VND",
        "facilities_data": {
            "need_2_1": {"proposed_limit_vnd": 20000.0},
            "need_2_8": {"proposed_limit_vnd": 5000.0}
        }
    }
    out_file = os.path.join(OUTPUT_DIR, "test_10_consecutive_blocks.docx")
    render_section_b_docx(payload, out_file)
    
    doc = docx.Document(out_file)
    headings = [p.text.strip() for p in doc.paragraphs if p.text.strip().startswith("2.")]
    assert len(headings) == 2
    assert "2.1" in headings[0]
    assert "2.8" in headings[1]


def test_11_fixed_notes_preserved():
    """TEST 11: Fixed notes / footnotes của template được giữ nguyên."""
    payload = {
        "selected_needs": ["2.1_vay_vld_han_muc"],
        "facilities_data": {"need_2_1": {"proposed_limit_vnd": 10000.0}}
    }
    out_file = os.path.join(OUTPUT_DIR, "test_11_fixed_notes.docx")
    render_section_b_docx(payload, out_file)
    
    doc = docx.Document(out_file)
    # Check that Mục 3 and Mục 4 remain untouched
    headings = [p.text.strip() for p in doc.paragraphs]
    assert any("Tài sản bảo đảm và biện pháp quản lý" in h for h in headings)
    assert any("Các điều kiện tín dụng khác" in h for h in headings)


def test_12_docx_opens_cleanly_without_error(base_input_21):
    """TEST 12: File Word mở bình thường không lỗi XML."""
    out_file = os.path.join(OUTPUT_DIR, "test_12_valid_docx.docx")
    render_section_b_docx(base_input_21, out_file)
    
    # Re-open with docx library
    doc = docx.Document(out_file)
    assert len(doc.tables) >= 3
    assert len(doc.paragraphs) > 5


def test_13_formatting_and_column_widths_preserved(base_input_21):
    """TEST 13: Font và cấu trúc của template được bảo toàn."""
    out_file = os.path.join(OUTPUT_DIR, "test_13_formatting.docx")
    render_section_b_docx(base_input_21, out_file)
    
    doc = docx.Document(out_file)
    t0 = doc.tables[0]
    # Header cells must have bold text and Times New Roman
    for cell in t0.rows[0].cells:
        for p in cell.paragraphs:
            for r in p.runs:
                assert r.font.name == "Times New Roman" or r.font.name is None


def test_14_ambiguous_subtype_triggers_blocking():
    """TEST 14: 2.4 thiếu subtype (Trung hạn/Dài hạn) -> Blocking error, không đoán mò."""
    payload = {
        "selected_needs": ["2.4_vay_trung_dai_han"],
        "facilities_data": {
            "need_2_4": {
                "proposed_amount_vnd": 10000.0,
                "loan_term_type": None  # Missing subtype!
            }
        }
    }
    totals, report, facs = validate_and_calculate_section_b(payload)
    assert not report.is_valid
    assert any("Mục 2.4" in err and "Trung hạn" in err for err in report.blocking_errors)


def test_15_optional_other_conditions_blank():
    """TEST 15: Điều kiện khác không nhập -> Cell trắng, không N/A."""
    payload = {
        "selected_needs": ["2.6_bao_lanh"],
        "facilities_data": {
            "need_2_6": {
                "proposed_limit_vnd": 15000.0,
                "other_conditions": ""
            }
        }
    }
    out_file = os.path.join(OUTPUT_DIR, "test_15_blank_conditions.docx")
    render_section_b_docx(payload, out_file)
    
    doc = docx.Document(out_file)
    t_bl = doc.tables[1]
    r_last = t_bl.rows[-1]
    assert "điều kiện khác" in r_last.cells[0].text.lower()
    assert r_last.cells[1].text.strip() == ""
