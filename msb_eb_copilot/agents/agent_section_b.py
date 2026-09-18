# -*- coding: utf-8 -*-
"""
Module: agent_section_b.py
Mô tả: Specialist Agent B - Quản lý & Sinh Đề xuất Cấp Tín dụng (Phần B: Mục 1 & Mục 2.1 - 2.8).
Tuân thủ nghiêm ngặt các quy tắc:
1. 1 Business Fact = 1 Input = N Output Bindings.
2. In-Place DOCX Editing: Xóa block không chọn, xóa dòng không áp dụng trên file Word template gốc.
3. Không tự điền N/A, ô trống để blank.
4. Chuyển đổi số tiền thành chữ tiếng Việt chính xác 100%.
5. Map ô bằng Label text giúp độ tin cậy và chính xác tuyệt đối.
"""

import os
import sys
import json
import copy
from typing import Dict, Any, List, Tuple
import docx
from docx.shared import Pt, RGBColor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def number_to_vietnamese_words(n: int) -> str:
    """Chuyển đổi số nguyên thành chuỗi chữ tiếng Việt chuẩn ngữ pháp tài chính."""
    if n == 0:
        return "Không đồng"
    
    units = ["", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
    scales = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ", "triệu tỷ", "nghìn triệu tỷ", "tỷ tỷ"]

    def read_three_digits(num: int, is_highest_group: bool = False) -> str:
        h = num // 100
        t = (num % 100) // 10
        u = num % 10
        res = []

        if h > 0:
            res.append(f"{units[h]} trăm")
        elif not is_highest_group and (t > 0 or u > 0):
            res.append("không trăm")

        if t > 1:
            res.append(f"{units[t]} mươi")
            if u == 1:
                res.append("mốt")
            elif u == 4:
                res.append("tư")
            elif u == 5:
                res.append("lăm")
            elif u > 0:
                res.append(units[u])
        elif t == 1:
            res.append("mười")
            if u == 5:
                res.append("lăm")
            elif u > 0:
                res.append(units[u])
        elif t == 0:
            if u > 0:
                if not is_highest_group or h > 0:
                    res.append(f"lẻ {units[u]}")
                else:
                    res.append(units[u])
        return " ".join(res).strip()

    groups = []
    temp = n
    while temp > 0:
        groups.append(temp % 1000)
        temp //= 1000

    words = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g > 0:
            text_g = read_three_digits(g, is_highest_group=(i == len(groups) - 1))
            scale_text = scales[i]
            if scale_text:
                words.append(f"{text_g} {scale_text}")
            else:
                words.append(text_g)

    result = " ".join(words).strip()
    result = result[0].upper() + result[1:] + " đồng"
    return result


def format_amount_with_words(amount_trieu: float, currency: str = "VND") -> str:
    """Format số tiền triệu VND thành chuỗi số và chữ chuẩn MSB."""
    if amount_trieu is None or amount_trieu == 0:
        return ""
    if amount_trieu >= 100_000_000:
        full_amount = int(round(amount_trieu))
    else:
        full_amount = int(round(amount_trieu * 1_000_000))
    formatted_num = f"{full_amount:,.0f}".replace(",", ".")
    words = number_to_vietnamese_words(full_amount)
    return f"{formatted_num} {currency} ({words})"



def fill_table_by_labels(table, mapping_dict: Dict[str, str]):
    """Điền dữ liệu vào table dựa trên label khớp ở cột 0, bảo toàn ô trống nếu không có dữ liệu."""
    for row in table.rows:
        label = row.cells[0].text.strip().lower()
        for key_pattern, val in mapping_dict.items():
            if key_pattern.lower() in label:
                val_str = str(val).strip() if val is not None else ""
                row.cells[1].text = val_str
                break


class AgentSectionB:
    """Agent B - Chuyên viên Thiết kế Gói Hạn mức & Điều kiện Tín dụng."""

    def __init__(self, template_path: str = None):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if template_path is None:
            template_path = os.path.join(base_dir, "templates", "PHAN_B_TEMPLATE.docx")
        self.template_path = template_path

    def validate_and_calculate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Tính toán các tổng, format số tiền, và kiểm tra các điều kiện logic."""
        selected_needs = input_data.get("selected_needs", [])
        fac_data = input_data.get("facilities_data", {})
        currency = input_data.get("general_facility_summary", {}).get("currency", "VND")

        warnings = []
        blocking_errors = []

        total_group_a = 0.0
        total_group_b = 0.0
        total_group_c = 0.0
        total_group_d = 0.0
        max_lending_limit = 0.0

        # Rà soát từng Need
        # 2.1 Cho vay VLĐ theo hạn mức
        if "2.1_vay_vld_han_muc" in selected_needs:
            n21 = fac_data.get("need_2_1", {})
            amt = n21.get("proposed_limit_vnd", 0.0) or 0.0
            total_group_a += amt
            max_lending_limit += amt
            n21["amount_formatted"] = format_amount_with_words(amt, currency)

        # 2.2 Cho vay VLĐ hạn mức trên 12 tháng
        if "2.2_vay_vld_han_muc_tren_12t" in selected_needs:
            n22 = fac_data.get("need_2_2", {})
            amt = n22.get("proposed_limit_vnd", 0.0) or 0.0
            dur = n22.get("facility_duration_months", 0) or 0
            if dur <= 12 and dur > 0:
                warnings.append(f"Mục 2.2 là Hạn mức VLĐ trên 12 tháng nhưng thời hạn hiện nhập là {dur} tháng.")
            total_group_c += amt
            max_lending_limit += amt
            n22["amount_formatted"] = format_amount_with_words(amt, currency)

        # 2.3 Vay ngắn hạn từng lần
        if "2.3_vay_ngan_han_tung_lan" in selected_needs:
            n23 = fac_data.get("need_2_3", {})
            amt = n23.get("proposed_amount_vnd", 0.0) or 0.0
            total_group_d += amt
            max_lending_limit += amt
            n23["amount_formatted"] = format_amount_with_words(amt, currency)

        # 2.4 Vay trung/dài hạn
        if "2.4_vay_trung_dai_han" in selected_needs:
            n24 = fac_data.get("need_2_4", {})
            amt = n24.get("proposed_amount_vnd", 0.0) or 0.0
            ltype = n24.get("loan_type", "")
            if not ltype:
                blocking_errors.append("Mục 2.4 cần chọn phân loại 'Trung hạn' hoặc 'Dài hạn'.")
            total_group_d += amt
            max_lending_limit += amt
            n24["amount_formatted"] = format_amount_with_words(amt, currency)

        # 2.5 L/C & Nhờ thu
        if "2.5_lc_nho_thu" in selected_needs:
            n25 = fac_data.get("need_2_5", {})
            amt = n25.get("proposed_limit_vnd", 0.0) or 0.0
            total_group_a += amt
            n25["amount_formatted"] = format_amount_with_words(amt, currency)

        # 2.6 Bảo lãnh
        if "2.6_bao_lanh" in selected_needs:
            n26 = fac_data.get("need_2_6", {})
            amt = n26.get("proposed_limit_vnd", 0.0) or 0.0
            total_group_a += amt
            n26["amount_formatted"] = format_amount_with_words(amt, currency)

        # 2.7 Chiết khấu BCT / BTT
        if "2.7_chiet_khau_bao_thanh_toan" in selected_needs:
            n27 = fac_data.get("need_2_7", {})
            amt = n27.get("proposed_amount_vnd", 0.0) or 0.0
            total_group_a += amt
            n27["amount_formatted"] = format_amount_with_words(amt, currency)

        # 2.8 Rủi ro đối tác
        if "2.8_rui_ro_doi_tac" in selected_needs:
            n28 = fac_data.get("need_2_8", {})
            amt = n28.get("proposed_limit_vnd", 0.0) or 0.0
            total_group_b += amt
            n28["amount_formatted"] = format_amount_with_words(amt, currency)

        grand_total = total_group_a + total_group_b + total_group_c + total_group_d

        return {
            "selected_needs": selected_needs,
            "facilities_data": fac_data,
            "totals": {
                "total_group_a": total_group_a,
                "total_group_b": total_group_b,
                "total_group_c": total_group_c,
                "total_group_d": total_group_d,
                "grand_total": grand_total,
                "max_lending_limit": max_lending_limit,
                "grand_total_str": f"{grand_total:,.0f}".replace(",", "."),
                "max_lending_str": f"{max_lending_limit:,.0f}".replace(",", ".")
            },
            "warnings": warnings,
            "blocking_errors": blocking_errors
        }

    def generate_docx(self, processed_data: Dict[str, Any], output_path: str) -> str:
        """Thực hiện In-Place DOCX Rendering trực tiếp trên template gốc."""
        doc = docx.Document(self.template_path)
        selected_needs = processed_data["selected_needs"]
        fac_data = processed_data["facilities_data"]
        totals = processed_data["totals"]

        # 1. Cập nhật đoạn mở đầu Phần B (Tổng HMTD đề xuất)
        for p in doc.paragraphs:
            if "Tổng hạn mức cấp tín dụng (A+B)" in p.text:
                p.text = (
                    f"Tổng hạn mức cấp tín dụng (A+B) ĐVKD đề xuất : {totals['grand_total_str']} triệu đồng "
                    f"hoặc ngoại tệ tương đương, trong đó mức cho vay tối đa là {totals['max_lending_str']} triệu đồng "
                    f"hoặc ngoại tệ tương đương."
                )
                for run in p.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(11)

        # 2. Điền dữ liệu vào các Bảng chi tiết được chọn theo Label
        # Bảng 1: 2.1 Vay VLĐ hạn mức
        if "2.1_vay_vld_han_muc" in selected_needs:
            n = fac_data.get("need_2_1", {})
            fill_table_by_labels(doc.tables[1], {
                "số tiền": n.get("amount_formatted", ""),
                "mục đích": n.get("purpose", ""),
                "thời hạn duy trì": f"{n.get('duration_months', 12)} tháng",
                "ngày hiệu lực": n.get("effective_date_rule", ""),
                "thời hạn tối đa mỗi khế ước": f"{n.get('max_promissory_note_duration_months', 6)} tháng kể từ ngày giải ngân",
                "lãi suất": n.get("lending_interest_rate", ""),
                "hình thức giải ngân": n.get("disbursement_method", ""),
                "kỳ hạn trả nợ": n.get("repayment_period", ""),
                "điều kiện khác": n.get("other_conditions", "")
            })

        # Bảng 5: 2.5 L/C & Nhờ thu
        if "2.5_lc_nho_thu" in selected_needs:
            n = fac_data.get("need_2_5", {})
            fill_table_by_labels(doc.tables[5], {
                "số tiền": n.get("amount_formatted", ""),
                "mục đích": n.get("purpose", ""),
                "thời hạn của hạn mức": f"{n.get('facility_duration_months', 12)} tháng",
                "ngày hiệu lực": n.get("effective_date_rule", ""),
                "loại l/c": n.get("lc_collection_type", ""),
                "tỷ lệ ký quỹ": n.get("min_margin_cash_percentage", ""),
                "mức cho vay/giá trị l/c": n.get("financing_rate_per_lc_value", ""),
                "phí l/c": n.get("lc_fee", ""),
                "điều kiện khác": n.get("other_conditions", "")
            })

        # Bảng 6: 2.6 Bảo lãnh
        if "2.6_bao_lanh" in selected_needs:
            n = fac_data.get("need_2_6", {})
            fill_table_by_labels(doc.tables[6], {
                "số tiền": n.get("amount_formatted", ""),
                "mục đích": n.get("purpose", ""),
                "loại bảo lãnh": n.get("guarantee_types", ""),
                "thời hạn của hạn mức": f"{n.get('facility_duration_months', 12)} tháng",
                "ngày hiệu lực": n.get("effective_date_rule", ""),
                "thời hạn từng món": n.get("single_guarantee_duration", ""),
                "tỷ lệ ký quỹ": n.get("min_margin_cash_percentage", ""),
                "điều kiện khác": n.get("other_conditions", "")
            })

        # 3. Điền dữ liệu vào Bảng Mục 1 (Table 0)
        t1 = doc.tables[0]
        # Hàng Tổng Nhóm A
        t1.rows[1].cells[3].text = f"{totals['total_group_a']:,.0f}".replace(",", ".")
        # Dòng ECS1100 (Cho vay ngắn hạn)
        if "2.1_vay_vld_han_muc" in selected_needs:
            amt = fac_data.get("need_2_1", {}).get("proposed_limit_vnd", 0.0)
            t1.rows[2].cells[3].text = f"{amt:,.0f}".replace(",", ".")
            t1.rows[2].cells[4].text = "☑ Cấp mới      ☐ Tái cấp"
        # Dòng ECS1200 (Bảo lãnh)
        if "2.6_bao_lanh" in selected_needs:
            amt = fac_data.get("need_2_6", {}).get("proposed_limit_vnd", 0.0)
            t1.rows[3].cells[3].text = f"{amt:,.0f}".replace(",", ".")
            t1.rows[3].cells[4].text = "☑ Cấp mới      ☐ Tái cấp"
        # Dòng ECS1300 (L/C)
        if "2.5_lc_nho_thu" in selected_needs:
            amt = fac_data.get("need_2_5", {}).get("proposed_limit_vnd", 0.0)
            t1.rows[4].cells[3].text = f"{amt:,.0f}".replace(",", ".")
            t1.rows[4].cells[4].text = "☑ Cấp mới      ☐ Tái cấp"

        # 4. Xóa các Block 2.x không được chọn trực tiếp khỏi body element
        need_patterns = {
            "2.1_vay_vld_han_muc": "2.1 Cho vay VLĐ",
            "2.2_vay_vld_han_muc_tren_12t": "2.2 Cho vay VLĐ hạn mức trên",
            "2.3_vay_ngan_han_tung_lan": "2.3 Vay ngắn hạn",
            "2.4_vay_trung_dai_han": "2.4 Vay trung/dài hạn",
            "2.5_lc_nho_thu": "2.5 Hạn mức/ từng lần phát hành L/C",
            "2.6_bao_lanh": "2.6 Hạn mức/từng lần Bảo lãnh",
            "2.7_chiet_khau_bao_thanh_toan": "2.7 Hạn mức/ từng lần chiết khấu",
            "2.8_rui_ro_doi_tac": "2.8 Hạn mức rủi ro"
        }

        body = doc._body._element
        children = list(body)
        to_delete = []

        for need_key, pat in need_patterns.items():
            if need_key not in selected_needs:
                for i, child in enumerate(children):
                    text = ''.join(child.itertext()).strip()
                    if pat in text:
                        to_delete.append(child)
                        if i + 1 < len(children) and children[i+1].tag.endswith('tbl'):
                            to_delete.append(children[i+1])

        for elem in to_delete:
            if elem in body:
                body.remove(elem)

        # 5. Xóa các dòng không áp dụng trong Bảng Mục 1 (Table 0)
        keep_indices = set([0, 1, 8])  # Header, Nhóm A header, Tổng tín dụng hạn mức
        if "2.1_vay_vld_han_muc" in selected_needs:
            keep_indices.add(2)
        if "2.6_bao_lanh" in selected_needs:
            keep_indices.add(3)
        if "2.5_lc_nho_thu" in selected_needs:
            keep_indices.add(4)
        if "2.7_chiet_khau_bao_thanh_toan" in selected_needs:
            keep_indices.add(5)
        if "2.8_rui_ro_doi_tac" in selected_needs:
            keep_indices.update([6, 7])
        if "2.2_vay_vld_han_muc_tren_12t" in selected_needs:
            keep_indices.update([9, 10])
        if "2.3_vay_ngan_han_tung_lan" in selected_needs:
            keep_indices.update([14, 15, 25])
        if "2.4_vay_trung_dai_han" in selected_needs:
            keep_indices.update([14, 16, 25])

        t1_elem = doc.tables[0]._tbl
        rows_list = list(doc.tables[0].rows)
        for idx, row in enumerate(rows_list):
            if idx not in keep_indices:
                if row._tr in t1_elem:
                    t1_elem.remove(row._tr)

        # Cập nhật giá trị vào dòng Tổng tín dụng hạn mức (dòng cuối của Table 0)
        doc.tables[0].rows[-1].cells[3].text = f"{totals['grand_total_str']}"

        # 6. Format lại toàn bộ font chữ Times New Roman 9.5pt trong tất cả các bảng
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        for run in para.runs:
                            run.font.name = "Times New Roman"
                            run.font.size = Pt(9.5)
                            run.font.color.rgb = RGBColor(0, 0, 0)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        doc.save(output_path)
        return output_path


if __name__ == "__main__":
    # Chạy kiểm thử tự động với dữ liệu mẫu
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample_file = os.path.join(base_dir, "sections_spec", "02_section_B_facility", "4_sample_input.json")
    out_file = os.path.join(base_dir, "output", "TO_TRINH_MB07_PHAN_B_DEMO.docx")

    with open(sample_file, "r", encoding="utf-8") as f:
        sample_data = json.load(f)

    agent = AgentSectionB()
    processed = agent.validate_and_calculate(sample_data)
    print("=== PROCESSED DATA PHẦN B ===")
    print(f"Selected Needs: {processed['selected_needs']}")
    print(f"Tổng HMTD đề xuất: {processed['totals']['grand_total_str']} triệu đồng")
    print(f"Mức cho vay tối đa: {processed['totals']['max_lending_str']} triệu đồng")
    print(f"Warnings: {processed['warnings']}")
    print(f"Blocking Errors: {processed['blocking_errors']}")

    res_path = agent.generate_docx(processed, out_file)
    print(f"✅ ĐÃ XUẤT THÀNH CÔNG BẢN WORD PHẦN B: {res_path}")
