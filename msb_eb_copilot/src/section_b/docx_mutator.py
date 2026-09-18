# -*- coding: utf-8 -*-
"""High-fidelity OOXML mutator for Section B (MB07 template).

Preserves 100% of the original Word document styling, fonts, margins, column widths,
merged cells, and form field checkboxes.
Deletes unselected 2.x blocks directly from XML body without leaving blank lines.
Deletes non-applicable rows from Table 0 (Mục 1) based on stable label/ECS matching.
"""

from typing import Dict, Any, List, Set, Optional
from lxml import etree
import docx
from docx.shared import Pt, RGBColor

from .enums import (
    CreditNeedId, ProposalType, IssuanceStructure, LoanTermType,
    TenorClassification, ProductTypeLC, ProductTypeDiscount,
    CounterpartySubProduct
)
from .config import CREDIT_NEEDS_CATALOG, SECTION_1_ROWS_SPEC
from .models import SectionBDerivedTotals

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_MAP = {"w": W_NS}


def update_form_field_checkbox(tc_elem, is_tai_cap: bool, is_cap_moi: bool):
    """Cập nhật trạng thái check của Word Form Field Checkbox trực tiếp trong OOXML.
    
    Checkbox 0 trong cell 4 của template là 'Tái cấp'.
    Checkbox 1 trong cell 4 của template là 'Cấp mới'.
    """
    ff_datas = tc_elem.xpath('.//w:ffData')
    if len(ff_datas) >= 2:
        # Checkbox 0: Tái cấp
        cb0 = ff_datas[0].find(f'.//{{{W_NS}}}checkBox')
        if cb0 is not None:
            for ex in cb0.findall(f'.//{{{W_NS}}}checked'):
                cb0.remove(ex)
            val0 = '1' if is_tai_cap else '0'
            ch0 = etree.Element(f'{{{W_NS}}}checked')
            ch0.set(f'{{{W_NS}}}val', val0)
            cb0.append(ch0)
            def0 = cb0.find(f'.//{{{W_NS}}}default')
            if def0 is not None:
                def0.set(f'{{{W_NS}}}val', val0)

        # Checkbox 1: Cấp mới
        cb1 = ff_datas[1].find(f'.//{{{W_NS}}}checkBox')
        if cb1 is not None:
            for ex in cb1.findall(f'.//{{{W_NS}}}checked'):
                cb1.remove(ex)
            val1 = '1' if is_cap_moi else '0'
            ch1 = etree.Element(f'{{{W_NS}}}checked')
            ch1.set(f'{{{W_NS}}}val', val1)
            cb1.append(ch1)
            def1 = cb1.find(f'.//{{{W_NS}}}default')
            if def1 is not None:
                def1.set(f'{{{W_NS}}}val', val1)


def find_section_b_summary_table(doc: docx.Document):
    """Tìm Bảng tổng hợp Mục 1 của Phần B (Table Cụ thể / Mã hạn mức) bất kể vị trí."""
    for t in doc.tables:
        if len(t.rows) > 0 and len(t.rows[0].cells) >= 4:
            c0 = t.rows[0].cells[0].text.strip().lower()
            c1 = t.rows[0].cells[1].text.strip().lower()
            if "cụ thể" in c0 and "mã hạn mức" in c1:
                return t
    return doc.tables[0]


from ..template_rendering.safe_mutation import SafeCellMutator


def set_cell_text_preserve_font(cell, text: str, bold: bool = False, italic: bool = False, font_size: float = 11.0):
    """Điền văn bản vào ô bảo toàn cấu trúc và chuẩn phong cách Times New Roman 11pt."""
    SafeCellMutator.set_cell_text(
        cell=cell,
        text=text,
        bold=bold if bold else None,
        font_name="Times New Roman",
        font_size_pt=font_size,
    )


def fill_cell_value(cell, value: Optional[str], default_font_size: float = 11.0):
    """Điền dữ liệu vào ô giá trị (cột 1 hoặc ô đích), nếu không có dữ liệu thì để TRỐNG hoàn toàn."""
    val_str = str(value).strip() if value is not None else ""
    set_cell_text_preserve_font(cell, val_str, bold=False, italic=False, font_size=default_font_size)


def remove_unselected_blocks(doc: docx.Document, selected_needs: List[str]):
    """Xóa các block 2.x không được chọn khỏi template standalone Section B."""
    unselected_prefixes = []
    for need in CREDIT_NEEDS_CATALOG:
        nid = need["id"]
        ncode = need["code"]
        if nid not in selected_needs and ncode not in selected_needs:
            unselected_prefixes.append(need["heading_pattern"])

    body = doc._body._element
    children = list(body)
    to_delete = []

    for prefix in unselected_prefixes:
        for i, child in enumerate(children):
            text = "".join(child.itertext()).strip()
            if prefix in text:
                to_delete.append(child)
                if i + 1 < len(children) and etree.QName(children[i + 1]).localname == "tbl":
                    to_delete.append(children[i + 1])

    for elem in to_delete:
        if elem in body:
            body.remove(elem)


def is_row_applicable(
    spec: Dict[str, Any],
    selected_needs: List[str],
    fac_data: Dict[str, Any]
) -> bool:
    """Xác định một dòng trong Bảng Mục 1 (Table 0) có áp dụng hay không dựa trên need và subtype."""
    if spec.get("is_group_header") or spec.get("is_subtotal"):
        return True  # handled separately in group retention logic
    
    need_id = spec.get("need_id")
    if not need_id:
        return False

    need_active = (need_id in selected_needs or need_id.split("_")[0] in selected_needs)
    if not need_active:
        return False

    # Check subtype conditions
    # Find matching facility data
    fac_key = None
    clean_nid = need_id.replace(".", "_")
    code_under = clean_nid.split("_")[0] + "_" + clean_nid.split("_")[1] # e.g. '2_1'
    code_dot = code_under.replace("_", ".") # e.g. '2.1'
    for k in fac_data:
        if k in (need_id, code_dot, code_under) or code_under in k or code_dot in k:
            fac_key = k
            break

    fac_info = fac_data.get(fac_key, {}) if fac_key else {}

    # Check condition_structure (Hạn mức vs Từng lần)
    cond_struct = spec.get("condition_structure")
    if cond_struct:
        actual_struct = fac_info.get("issuance_structure")
        val_struct = actual_struct.value if hasattr(actual_struct, "value") else str(actual_struct) if actual_struct else ""
        if val_struct and val_struct not in cond_struct:
            return False

    # Check condition_tenor
    cond_tenor = spec.get("condition_tenor")
    if cond_tenor:
        actual_tenor = fac_info.get("term_classification")
        val_tenor = actual_tenor.value if hasattr(actual_tenor, "value") else str(actual_tenor) if actual_tenor else ""
        if val_tenor and val_tenor not in cond_tenor:
            return False

    # Check condition_loan_type (Trung hạn vs Dài hạn)
    cond_lt = spec.get("condition_loan_type")
    if cond_lt:
        actual_lt = fac_info.get("loan_term_type")
        val_lt = actual_lt.value if hasattr(actual_lt, "value") else str(actual_lt) if actual_lt else ""
        if val_lt and val_lt not in cond_lt:
            return False

    return True


def mutate_section_1_table(
    doc: docx.Document,
    selected_needs: List[str],
    fac_data: Dict[str, Any],
    totals: SectionBDerivedTotals
):
    """Xóa các dòng không áp dụng và điền số liệu, cập nhật checkbox trong Bảng Mục 1."""
    table = find_section_b_summary_table(doc)
    tbl_elem = table._tbl
    rows = list(table.rows)

    # 1. Map each row to spec
    rows_to_delete = []
    
    # We will identify which facility rows are active
    active_facility_row_ids = set()
    for spec in SECTION_1_ROWS_SPEC:
        if spec.get("is_facility") and is_row_applicable(spec, selected_needs, fac_data):
            active_facility_row_ids.add(spec["row_id"])

    # Determine which groups have at least one active facility
    active_groups = set()
    for spec in SECTION_1_ROWS_SPEC:
        if spec.get("is_facility") and spec["row_id"] in active_facility_row_ids:
            active_groups.add(spec["group"])

    # Traverse rows
    current_group = 'A'
    for row_idx, row in enumerate(rows):
        if row_idx == 0:
            continue  # table header: keep
        
        c0_text = row.cells[0].text.strip()
        c1_text = row.cells[1].text.strip() if len(row.cells) > 1 else ""

        # Determine current group context
        if c0_text.startswith("A.") or "Tín dụng hạn mức ngắn hạn" in c0_text:
            current_group = "A"
        elif c0_text.startswith("B.") or "Rủi ro tín dụng đối tác" in c0_text and "ECS9100" not in c1_text:
            current_group = "B"
        elif "Tổng tín dụng hạn mức" in c0_text:
            current_group = "SUBTOTAL_AB"
        elif c0_text.startswith("C.") or "Hạn mức tài trợ VLĐ trên 12 tháng" in c0_text:
            current_group = "C"
        elif c0_text.startswith("D.") or "Tín dụng từng lần" in c0_text:
            current_group = "D"
        elif "Tổng tín dụng từng lần" in c0_text:
            current_group = "SUBTOTAL_D"
        elif c0_text.startswith("E.") or "Khác" in c0_text:
            current_group = "E"

        # Find matching spec within current group
        matched_spec = None
        for spec in SECTION_1_ROWS_SPEC:
            if spec["group"] == current_group:
                if spec["label_pattern"].lower() in c0_text.lower():
                    if not spec.get("ecs_code") or spec["ecs_code"].lower() in c1_text.lower() or not c1_text:
                        matched_spec = spec
                        break

        if not matched_spec:
            # Row not in spec (e.g. Row 27 '....') -> delete
            rows_to_delete.append(row)
            continue

        # Check if group header:
        if matched_spec.get("is_group_header"):
            grp = matched_spec["group"]
            if grp not in active_groups:
                # Group has no active facilities -> delete group header
                rows_to_delete.append(row)
            else:
                # Group active -> if Group A, update group total
                if grp == "A":
                    set_cell_text_preserve_font(row.cells[3], f"{totals.total_group_a:,.0f}".replace(",", "."), bold=True)
                elif grp == "C":
                    set_cell_text_preserve_font(row.cells[3], f"{totals.total_group_c:,.0f}".replace(",", "."), bold=True)
            continue

        # Check if subtotal:
        if matched_spec.get("is_subtotal"):
            sub_grp = matched_spec["group"]
            if sub_grp == "SUBTOTAL_AB":
                if "A" not in active_groups and "B" not in active_groups:
                    rows_to_delete.append(row)
                else:
                    sub_ab = totals.total_group_a + totals.total_group_b
                    set_cell_text_preserve_font(row.cells[3], f"{sub_ab:,.0f}".replace(",", "."), bold=True)
            elif sub_grp == "SUBTOTAL_D":
                if "D" not in active_groups:
                    rows_to_delete.append(row)
                else:
                    set_cell_text_preserve_font(row.cells[3], f"{totals.total_group_d:,.0f}".replace(",", "."), bold=True)
            continue

        # Check if facility row:
        if matched_spec.get("is_facility"):
            if matched_spec["row_id"] not in active_facility_row_ids:
                rows_to_delete.append(row)
            else:
                # POPULATE DATA FOR ACTIVE FACILITY ROW
                # Find the facility data
                need_id = matched_spec["need_id"]
                fac_key = None
                code_under = need_id[:3].replace(".", "_")
                code_dot = need_id[:3]
                for k in fac_data:
                    if code_under in k or code_dot in k:
                        fac_key = k
                        break
                f_info = fac_data.get(fac_key, {}) if fac_key else {}

                appr_str = f_info.get("approved_num_str", "")
                prop_str = f_info.get("amount_num_str", "")
                prop_type = f_info.get("proposal_type", ProposalType.CAP_MOI.value)
                note_str = f_info.get("note", "")

                # Cell 2: Approved limit
                if len(row.cells) > 2:
                    set_cell_text_preserve_font(row.cells[2], appr_str)
                # Cell 3: Proposed limit
                if len(row.cells) > 3:
                    set_cell_text_preserve_font(row.cells[3], prop_str, bold=True)
                # Cell 4: Checkbox / Note
                if len(row.cells) > 4:
                    tc_elem = row.cells[4]._tc
                    is_tai_cap = (prop_type == ProposalType.TAI_CAP.value or prop_type == "Tái cấp")
                    is_cap_moi = (prop_type == ProposalType.CAP_MOI.value or prop_type == "Cấp mới")
                    
                    ff_datas = tc_elem.xpath(".//w:ffData")
                    if ff_datas:
                        update_form_field_checkbox(tc_elem, is_tai_cap=is_tai_cap, is_cap_moi=is_cap_moi)
                    else:
                        # If row didn't have checkboxes in template, add note if provided
                        if note_str:
                            set_cell_text_preserve_font(row.cells[4], note_str)
            continue

        # Any other row: delete
        rows_to_delete.append(row)

    # Delete marked rows from table XML directly
    for row in rows_to_delete:
        if row._tr in tbl_elem:
            tbl_elem.remove(row._tr)


def populate_detail_tables(
    doc: docx.Document,
    selected_needs: List[str],
    fac_data: Dict[str, Any],
    currency: str = "VND"
):
    """Điền dữ liệu vào các Bảng chi tiết Mục 2 còn lại trong document."""
    # Find active tables by scanning document paragraphs for 2.x headings
    for need in CREDIT_NEEDS_CATALOG:
        nid = need["id"]
        ncode = need["code"]
        if nid not in selected_needs and ncode not in selected_needs:
            continue

        # Find facility data
        fac_key = None
        code_under = ncode.replace(".", "_")
        for k in fac_data:
            if ncode in k or code_under in k:
                fac_key = k
                break
        if not fac_key:
            continue
        data = fac_data[fac_key]

        # Find the table in doc that follows the heading
        target_table = None
        for i, p in enumerate(doc.paragraphs):
            if need["heading_pattern"] in p.text:
                # The table is the next table in body
                p_elem = p._p
                # find following sibling tbl
                curr = p_elem.getnext()
                while curr is not None:
                    if etree.QName(curr).localname == "tbl":
                        for t in doc.tables:
                            if t._tbl == curr:
                                target_table = t
                                break
                        break
                    curr = curr.getnext()
                break

        if not target_table:
            continue

        # Populate target table
        if ncode == "2.1":
            _populate_table_2_1(target_table, data)
        elif ncode == "2.2":
            _populate_table_2_2(target_table, data)
        elif ncode == "2.3":
            _populate_table_2_3(target_table, data)
        elif ncode == "2.4":
            _populate_table_2_4(target_table, data)
        elif ncode == "2.5":
            _populate_table_2_5(target_table, data)
        elif ncode == "2.6":
            _populate_table_2_6(target_table, data)
        elif ncode == "2.7":
            _populate_table_2_7(target_table, data)
        elif ncode == "2.8":
            _populate_table_2_8(target_table, data)


def _populate_table_2_1(table, data: Dict[str, Any]):
    """Điền Bảng 2.1: Cho vay VLĐ theo hạn mức."""
    dur = data.get("duration_months")
    dur_str = f"{dur} tháng" if dur else ""
    note_dur = data.get("max_promissory_note_duration_months")
    note_dur_str = f"{note_dur} tháng" if note_dur else ""

    mapping = {
        "số tiền": data.get("amount_formatted", ""),
        "mục đích": data.get("purpose", ""),
        "thời hạn duy trì hạn mức": dur_str,
        "ngày hiệu lực của hạn mức": data.get("effective_date_rule", "") or data.get("effective_date_custom", ""),
        "thời hạn tối đa mỗi khế ước": note_dur_str,
        "lãi suất cho vay": data.get("lending_interest_rate", ""),
        "hình thức giải ngân": data.get("disbursement_method", ""),
        "kỳ hạn trả nợ": data.get("repayment_period", ""),
        "điều kiện khác": data.get("other_conditions", ""),
    }
    _fill_table_by_label_dict(table, mapping)


def _populate_table_2_2(table, data: Dict[str, Any]):
    """Điền Bảng 2.2: Cho vay VLĐ hạn mức trên 12 tháng."""
    dur = data.get("facility_duration_months")
    dur_str = f"{dur} tháng" if dur else ""
    note_dur = data.get("max_promissory_note_duration_months")
    note_dur_str = f"{note_dur} tháng" if note_dur else ""

    mapping = {
        "số tiền": data.get("amount_formatted", ""),
        "mục đích": data.get("purpose", ""),
        "thời hạn của hạn mức": dur_str,
        "ngày hiệu lực của hạn mức": data.get("effective_date_rule", "") or data.get("effective_date_custom", ""),
        "thời hạn tối đa mỗi khế ước": note_dur_str,
        "lãi suất cho vay": data.get("lending_interest_rate", ""),
        "hình thức giải ngân": data.get("disbursement_method", ""),
        "kỳ hạn trả nợ": data.get("repayment_period", ""),
        "điều kiện khác": data.get("other_conditions", ""),
    }
    _fill_table_by_label_dict(table, mapping)


def _populate_table_2_3(table, data: Dict[str, Any]):
    """Điền Bảng 2.3: Vay ngắn hạn từng lần."""
    dur = data.get("loan_duration_months")
    dur_str = f"{dur} tháng" if dur else ""

    mapping = {
        "số tiền": data.get("amount_formatted", ""),
        "mục đích": data.get("purpose", ""),
        "thời hạn khoản vay": dur_str,
        "ngày hiệu lực của khoản vay": data.get("effective_date_rule", ""),
        "lãi suất cho vay": data.get("lending_interest_rate", ""),
        "hình thức giải ngân": data.get("disbursement_method", ""),
        "kỳ hạn trả nợ": data.get("repayment_period", ""),
        "điều kiện khác": data.get("other_conditions", ""),
    }
    _fill_table_by_label_dict(table, mapping)


def _populate_table_2_4(table, data: Dict[str, Any]):
    """Điền Bảng 2.4: Vay trung/dài hạn (chú ý cấu trúc merged cells tại row 2 và row 6)."""
    dur = data.get("loan_duration_months")
    dur_str = f"{dur} tháng" if dur else ""

    for row in table.rows:
        c0 = row.cells[0].text.strip().lower()
        if "số tiền" in c0:
            fill_cell_value(row.cells[1], data.get("amount_formatted", ""))
        elif "mục đích" in c0:
            fill_cell_value(row.cells[1], data.get("purpose", ""))
        elif "thời hạn khoản vay" in c0:
            # Row 2 has 2 parts: Thời hạn khoản vay (c1) & Ân hạn (c4)
            fill_cell_value(row.cells[1], dur_str)
            if len(row.cells) > 4:
                fill_cell_value(row.cells[4], data.get("grace_period", ""))
        elif "thời hạn rút vốn" in c0:
            fill_cell_value(row.cells[1], data.get("drawdown_period", ""))
        elif "lãi suất cho vay" in c0:
            fill_cell_value(row.cells[1], data.get("lending_interest_rate", ""))
        elif "hình thức giải ngân" in c0:
            fill_cell_value(row.cells[1], data.get("disbursement_method", ""))
        elif "kỳ hạn trả nợ" in c0:
            # Row 6 has 2 parts: Nợ gốc vay (c2) & Nợ Lãi vay (c6)
            if len(row.cells) > 2:
                fill_cell_value(row.cells[2], data.get("principal_repayment", ""))
            if len(row.cells) > 6:
                fill_cell_value(row.cells[6], data.get("interest_repayment", ""))
        elif "điều kiện khác" in c0:
            fill_cell_value(row.cells[1], data.get("other_conditions", ""))


def _populate_table_2_5(table, data: Dict[str, Any]):
    """Điền Bảng 2.5: Hạn mức / từng lần phát hành L/C / Nhờ thu."""
    dur = data.get("facility_duration_months")
    dur_str = f"{dur} tháng" if dur else ""

    mapping = {
        "số tiền": data.get("amount_formatted", ""),
        "mục đích": data.get("purpose", ""),
        "thời hạn của hạn mức": dur_str,
        "ngày hiệu lực của hạn mức": data.get("effective_date_rule", ""),
        "loại l/c": data.get("lc_collection_type", ""),
        "tỷ lệ ký quỹ tối thiểu": data.get("min_margin_cash_percentage", ""),
        "mức cho vay/giá trị l/c": data.get("financing_rate_per_lc_value", ""),
        "phí l/c": data.get("lc_fee", ""),
        "điều kiện khác": data.get("other_conditions", ""),
    }
    _fill_table_by_label_dict(table, mapping)


def _populate_table_2_6(table, data: Dict[str, Any]):
    """Điền Bảng 2.6: Hạn mức / từng lần Bảo lãnh."""
    dur = data.get("facility_duration_months")
    dur_str = f"{dur} tháng" if dur else ""

    mapping = {
        "số tiền": data.get("amount_formatted", ""),
        "mục đích": data.get("purpose", ""),
        "loại bảo lãnh": data.get("guarantee_types", ""),
        "thời hạn của hạn mức": dur_str,
        "ngày hiệu lực của hạn mức": data.get("effective_date_rule", ""),
        "thời hạn từng món bl": data.get("single_guarantee_duration", ""),
        "tỷ lệ ký quỹ tối thiểu": data.get("min_margin_cash_percentage", ""),
        "điều kiện khác": data.get("other_conditions", ""),
    }
    _fill_table_by_label_dict(table, mapping)


def _populate_table_2_7(table, data: Dict[str, Any]):
    """Điền Bảng 2.7: Hạn mức / từng lần chiết khấu BCT / Bao thanh toán."""
    dur = data.get("facility_duration_months")
    dur_str = f"{dur} tháng" if dur else ""
    disc_limit = data.get("discount_limit_vnd")
    disc_limit_str = f"{disc_limit:,.0f}".replace(",", ".") if disc_limit else ""

    mapping = {
        "số tiền": data.get("amount_formatted", ""),
        "hạn mức ck/btt": disc_limit_str,
        "thời hạn của hạn mức": dur_str,
        "ngày hiệu lực của hạn mức": data.get("effective_date_rule", ""),
        "thời hạn ck/btt": data.get("discount_tenor", ""),
        "mức ck/btt": data.get("discount_rate_percentage", ""),
        "lãi suất": data.get("interest_rate", ""),
        "điều kiện khác": data.get("other_conditions", ""),
    }
    _fill_table_by_label_dict(table, mapping)


def _populate_table_2_8(table, data: Dict[str, Any]):
    """Điền Bảng 2.8: Hạn mức rủi ro tín dụng đối tác (Progressive Disclosure)."""
    dur = data.get("facility_duration_months")
    dur_str = f"{dur} tháng" if dur else ""
    subs = data.get("selected_sub_products", [])
    has_fx = any("ngoại hối" in str(s).lower() or "fx" in str(s).lower() for s in subs)
    has_ir = any("lãi suất" in str(s).lower() or "ir" in str(s).lower() for s in subs)

    fx_limit = data.get("fx_limit_vnd")
    fx_limit_str = f"{fx_limit:,.0f}".replace(",", ".") if fx_limit else ""
    ir_limit = data.get("ir_limit_vnd")
    ir_limit_str = f"{ir_limit:,.0f}".replace(",", ".") if ir_limit else ""

    for row in table.rows:
        c0 = row.cells[0].text.strip().lower()
        if "hạn mức" == c0:
            fill_cell_value(row.cells[1], data.get("amount_formatted", ""))
        elif "thời hạn của hạn mức" in c0:
            fill_cell_value(row.cells[1], dur_str)
        elif "ngày hiệu lực của hạn mức" in c0:
            fill_cell_value(row.cells[1], data.get("effective_date_rule", ""))
        elif "1. hm đối với sp phái sinh ngoại hối" in c0:
            fill_cell_value(row.cells[1], fx_limit_str if has_fx else "")
        elif "kỳ hạn tối đa từng giao dịch" in c0 and "ngoại hối" in row.cells[0].text.lower():
            fill_cell_value(row.cells[1], data.get("fx_max_tenor", "") if has_fx else "")
        elif "ký quỹ" == c0 and not has_ir:
            fill_cell_value(row.cells[1], data.get("fx_margin_rate", "") if has_fx else "")
        elif "2. hạn mức đối với các sản phẩm phái sinh lãi suất" in c0:
            fill_cell_value(row.cells[1], ir_limit_str if has_ir else "")
        elif "điều kiện khác" in c0:
            fill_cell_value(row.cells[1], data.get("other_conditions", ""))


def _fill_table_by_label_dict(table, mapping: Dict[str, str]):
    """Điền dữ liệu vào table dựa trên label khớp ở cột 0, xóa bỏ placeholder và giữ ô trắng nếu không có dữ liệu."""
    for row in table.rows:
        c0 = row.cells[0].text.strip().lower()
        for key, val in mapping.items():
            if key in c0:
                fill_cell_value(row.cells[1], val)
                break


def update_opening_paragraph(doc: docx.Document, totals: SectionBDerivedTotals):
    """Cập nhật đoạn mở đầu Phần B với tổng hạn mức và mức cho vay tối đa."""
    for p in doc.paragraphs:
        if "Tổng hạn mức cấp tín dụng (A+B)" in p.text:
            p.text = (
                f"Tổng hạn mức cấp tín dụng (A+B) ĐVKD đề xuất : {totals.grand_total_str} triệu đồng "
                f"hoặc ngoại tệ tương đương, trong đó mức cho vay tối đa là {totals.max_lending_str} triệu đồng "
                f"hoặc ngoại tệ tương đương."
            )
            for r in p.runs:
                r.font.name = "Times New Roman"
                r.font.size = Pt(11)
            break
