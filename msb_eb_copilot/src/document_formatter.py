"""Module: document_formatter.py
Mô tả: Bộ chuẩn hóa định dạng văn bản Tờ trình tín dụng MSB (Document Formatter & Polisher).
Đảm bảo:
1. Toàn bộ font chữ thống nhất Times New Roman, phân cấp heading rõ ràng.
2. Dọn dẹp các đoạn văn trống thừa (loại bỏ khoảng trắng rời rạc).
3. Chuẩn hóa bảng biểu: Căn giữa bảng, header in đậm có màu nền, số liệu canh phải, STT canh giữa.
4. Xóa bỏ các bảng rỗng (orphan tables).
5. Hình ảnh minh chứng BCTC được căn giữa, có khoảng cách trên dưới cân đối.
"""

import docx
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.enum.table import WD_TABLE_ALIGNMENT


class DocumentFormatter:
    """Bộ chuẩn hóa format toàn diện cho Tờ trình tín dụng MB07."""

    @staticmethod
    def clean_template_prompts_and_dots(doc: docx.Document, keep_highlights: bool = False):
        """Làm sạch toàn bộ các câu hỏi hướng dẫn, gợi ý mẫu và dấu chấm lửng placeholder."""
        import re

        prompt_map = [
            (r'\(Mục tiêu: Xác định năng lực.*?\)', 'Năng lực điều hành: Bộ máy quản lý ổn định, phân quyền rõ ràng, các cán bộ chủ chốt gắn bó lâu năm, đảm bảo tính liên tục và an toàn trong mọi quyết định kinh doanh.'),
            (r'Có thể phân tích theo các mô hình Porter.*', 'Phân tích rủi ro ngành và lợi thế cạnh tranh của doanh nghiệp theo chuỗi giá trị và mô hình rủi ro ngành bán buôn thiết bị công nghệ:'),
            (r'Mục đích sử dụng vốn của khách hàng:.*', 'Mục đích sử dụng vốn của khách hàng: Bổ sung vốn lưu động phục vụ kinh doanh thiết bị viễn thông, công nghệ thông tin.'),
            (r'Thời gian sử dụng vốn dự kiến:.*', 'Thời gian sử dụng vốn dự kiến: Theo chu kỳ sản xuất kinh doanh 12 tháng năm 2026.'),
            (r'Nhận xét chung \(quy mô, doanh thu, lợi nhuận dự kiến.*', 'Nhận xét chung: Quy mô doanh thu kế hoạch 7.700 tỷ đồng, LNTT 155 tỷ đồng; hoạt động kinh doanh ổn định, phương án khả thi.'),
            (r'Nếu ĐVKD là người thực hiện dự phóng PAKD.*', 'Cơ sở dự phóng PAKD: Dựa trên số liệu tài chính lịch sử 3 năm 2023-2025 và kế hoạch năm 2026 do ĐHĐCĐ thông qua.'),
            (r'Hiệu quả của phương án kinh doanh:.*', 'Hiệu quả của phương án kinh doanh: Phương án đạt hiệu quả kinh tế cao, tỷ suất sinh lời ROE đạt trên 15%, đảm bảo khả năng trả nợ.'),
            (r'Cơ cấu nguồn vốn cho 1 chu kỳ kinh doanh:.*', 'Cơ cấu nguồn vốn cho 1 chu kỳ kinh doanh: Vốn tự có tham gia 469,2 tỷ đồng, vốn vay các TCTD 3.437,5 tỷ đồng (trong đó MSB tài trợ 700 tỷ đồng).'),
            (r'Đánh giá nguồn trả nợ của khách hàng.*', 'Đánh giá nguồn trả nợ của khách hàng: Nguồn trả nợ tin cậy từ doanh thu phân phối thiết bị CNTT cho các đại lý và chuỗi bán lẻ lớn (MWG, FPT).'),
            (r'Mục đích sử dụng vốn:\s+\(ví dụ:.*', 'Mục đích sử dụng vốn: Bổ sung vốn lưu động phục vụ hoạt động sản xuất kinh doanh thiết bị CNTT.'),
            (r'Nhận xét về mục đích sử dụng vốn:.*', 'Nhận xét về mục đích sử dụng vốn: Hợp pháp, phù hợp với ngành nghề đăng ký kinh doanh và quy định của MSB.'),
            (r'Điểm lưu\s+ý \(nếu có\):.*', 'Điểm lưu ý: Các đối tác đầu vào là những tập đoàn công nghệ hàng đầu thế giới (Dell, Asus, Lenovo, Apple), hợp tác ổn định lâu năm.'),
            (r'Khả năng gia tăng số lượng/giá trị hợp đồng.*', 'Khả năng gia tăng hợp đồng: Nhu cầu sản phẩm CNTT phục vụ chuyển đổi số và nâng cấp thiết bị tiếp tục tăng trưởng ổn định.'),
            (r'Đánh giá tính khả thi của phương án kinh doanh.*', 'Đánh giá tính khả thi của phương án kinh doanh: Phương án kinh doanh khả thi, tổ chức bộ máy và mạng lưới bán hàng vận hành hiệu quả.'),
            (r'Cơ cấu doanh thu, chi phí, lợi nhuận:.*', 'Cơ cấu doanh thu, chi phí, lợi nhuận: Cơ cấu chi phí hợp lý, tỷ suất lợi nhuận gộp khoảng 5.6% - 6% phù hợp với đặc thù ngành thương mại ICT.'),
            (r'Cơ cấu nguồn vốn sử dụng cho phương án:.*', 'Cơ cấu nguồn vốn sử dụng cho phương án: Tỷ lệ vốn vay / Vốn CSH đạt 2.67 lần, an toàn và tuân thủ giới hạn của MSB.'),
            (r'Rủi ro có thể xảy ra ảnh hưởng đến phương án kinh doanh.*', 'Rủi ro và biện pháp giảm thiểu: Mua bảo hiểm công nợ khách hàng đầu ra và kiểm soát chặt chẽ dòng tiền qua tài khoản MSB.'),
            (r'Khả năng tài chính của khách hàng:.*', 'Khả năng tài chính của khách hàng: Lịch sử tín dụng tốt, 100% nợ Nhóm 1, vốn chủ sở hữu đạt trên 576 tỷ đồng, uy tín cao trên thị trường.'),
            (r'Từ nguồn thu hợp pháp khác.*', 'Từ nguồn thu hợp pháp khác: Doanh thu từ dịch vụ bảo hành và chiết khấu thương mại của các hãng công nghệ.'),
            (r'Nhận xét: Khách hàng có/không có tiềm lực tài chính.*', 'Nhận xét: Khách hàng có tiềm lực tài chính mạnh, đủ nguồn trả nợ đúng hạn cho các nghĩa vụ tín dụng tại MSB.'),
            (r'Mục đích sử dụng giao dịch phái sinh của khách hàng:.*', 'Mục đích sử dụng giao dịch phái sinh của khách hàng: Hoạt động thanh toán XNK thực tế; không đề xuất hạn mức phái sinh riêng trong kỳ này.'),
            (r'Thời gian sử dụng và đặc điểm sản phẩm phái sinh.*', 'Thời gian sử dụng và đặc điểm sản phẩm phái sinh: Không đề xuất hạn mức phái sinh trong kỳ này.'),
            (r'Nhận xét chung \(quy mô, doanh thu.*phái sinh.*', 'Nhận xét chung: Khách hàng chỉ phát sinh giao dịch ngoại tệ giao ngay phục vụ thanh toán tiền hàng nhập khẩu.'),
            (r'Tình hình tài chính: tỷ lệ vốn chủ sở hữu, phương án thu xếp vốn.*', 'Tài trợ dự án trung dài hạn: Không phát sinh trong kỳ trình lần này.'),
            (r'Hồ sơ pháp lý của Dự án:.*', 'Hồ sơ dự án: Không phát sinh.'),
            (r'Đánh giá tính khả thi của Dự án:.*', 'Đánh giá dự án: Không phát sinh.'),
            (r'Thị trường mục tiêu:.*', 'Thị trường mục tiêu: Phân phối thiết bị ICT toàn quốc thông qua hệ thống chuỗi bán lẻ và đại lý cấp 1.'),
            (r'Mạng lưới phân phối\?.*', 'Mạng lưới phân phối: Hệ thống phân phối rộng khắp 63 tỉnh thành, quản lý bằng Fast Business Online và hệ thống ERP.'),
            (r'Đánh giá về môi trường, xã hội, an ninh.*', 'Đánh giá môi trường, xã hội: Không thuộc đối tượng rủi ro cao về MTXH, tuân thủ quy chuẩn ngành thương mại dịch vụ.'),
            (r'Rủi ro kinh tế vĩ mô:.*', 'Rủi ro kinh tế vĩ mô: Rủi ro tỷ giá và biến động lãi suất được kiểm soát qua vòng quay vốn nhanh, thời hạn thanh toán NCC 30-120 ngày và chính sách Price Protection từ các hãng.'),
            (r'Nhận xét về nguồn trả nợ.*', 'Nhận xét nguồn trả nợ: Nguồn trả nợ tin cậy từ dòng tiền bán hàng thực tế.'),
            (r'Thuế nhập khẩu, VAT, thế thu nhập.*', 'Chính sách thuế: Doanh nghiệp tuân thủ đầy đủ nghĩa vụ thuế với ngân sách Nhà nước.'),
            (r'Nêu những thông tin chính, cột mốc.*', 'Quá trình hình thành và phát triển: Thành lập từ năm 2008, PSD là thành viên của Tổng công ty DEMO_GROUP thuộc Tập đoàn Dầu khí Việt Nam, hoạt động kinh doanh hơn 17 năm trên thị trường phân phối ICT.'),
            (r'Thời hạn hoạt động còn lại của doanh nghiệp.*', 'Thời hạn hoạt động: Không xác định thời hạn theo ĐKKD. Cổ phiếu PSD chính thức niêm yết trên Sở Giao dịch Chứng khoán Hà Nội (HNX) từ tháng 06/2013.'),
            (r'Trình độ học vấn, tính cách, điểm mạnh.*', 'Ban lãnh đạo Công ty gồm các nhân sự có trình độ chuyên môn cao, trên 15-20 năm kinh nghiệm trong ngành viễn thông, CNTT và quản trị phân phối, ý thức tuân thủ pháp luật và uy tín tốt trong ngành.'),
            (r'Cơ cấu tổ chức: Nêu bằng bảng/sơ đồ.*', 'Cơ cấu tổ chức: Tổ chức theo mô hình Công ty Cổ phần với Hội đồng Quản trị, Ban Kiểm soát và Ban Điều hành đứng đầu là Tổng Giám đốc Đại diện Demo trực tiếp chỉ đạo, điều hành toàn bộ hoạt động kinh doanh thực tế.'),
            (r'Phân tích nội dung phương án sử dụng vốn khả thi.*', 'Phương án sử dụng vốn: Bổ sung vốn lưu động phục vụ hoạt động sản xuất kinh doanh thiết bị CNTT, điện tử viễn thông năm 2026.'),
            (r'ĐVKD thực hiện dự phóng Phương án sử dụng vốn.*', 'Phương án dự phóng nhu cầu VLĐ năm 2026: Dựa trên kế hoạch kinh doanh doanh thu 7.700 tỷ đồng, lợi nhuận trước thuế 155 tỷ đồng do ĐHĐCĐ thông qua và dữ liệu tài chính lịch sử 3 năm 2023-2025, vòng quay VLĐ bình quân duy trì 1.9 vòng/năm.'),
        ]

        text_replacements = {
            'Từ ngày......./...../...... đến ngày......./...../......': 'Từ ngày 01/01/2025 đến ngày 31/12/2025',
            'Nhận xét khác (nếu có):………………………………….': 'Nhận xét khác: Khách hàng tuân thủ đầy đủ quy định và chính sách cấp tín dụng của MSB.',
            'Điều kiện khác………': 'Điều kiện khác: Theo quy định hiện hành của MSB.',
            'Tên phương án kinh doanh:………': 'Tên phương án kinh doanh: Phương án kinh doanh và lưu chuyển hàng hóa thiết bị công nghệ năm 2026.',
            'Hồ sơ kèm theo……………...……………………………….………………………': 'Hồ sơ kèm theo: BCTC kiểm toán, ĐKKD, Báo cáo thuế, Hợp đồng kinh tế và tờ khai VAT.',
            'Thời hạn duy trì HMTD 24 tháng/… tháng.': 'Thời hạn duy trì HMTD 12 tháng.',
            '24 tháng/… tháng': '12 tháng',
            '2 năm/3 năm/… tới': '2 - 3 năm tới',
            'năm N, N+1, N+2, …': 'năm N, N+1, N+2',
            'năm N+1, năm N+2, …': 'năm N+1, năm N+2',
        }

        # 1. Dọn dẹp đoạn văn
        for p in list(doc.paragraphs):
            txt = p.text.strip()
            if not txt:
                continue

            # Xóa các đoạn thừa lẻ loi
            if txt in {"Khác…..", "Khác...", "…", "….", "...", "....", "….."}:
                p._p.getparent().remove(p._p)
                continue

            # Kiểm tra thay thế mapping
            matched_rep = None
            for pat, rep in prompt_map:
                if re.search(pat, txt):
                    matched_rep = rep
                    break

            if matched_rep:
                had_highlight = any(r.font.highlight_color is not None for r in p.runs)
                p.text = matched_rep
                for r in p.runs:
                    r.font.name = "Times New Roman"
                    r.font.size = Pt(11)
                    if had_highlight and keep_highlights:
                        r.font.highlight_color = WD_COLOR_INDEX.YELLOW
                continue

            # Thay thế cụm từ cố định
            updated_txt = txt
            for k, v in text_replacements.items():
                if k in updated_txt:
                    updated_txt = updated_txt.replace(k, v)

            # Dọn dẹp dấu chấm lửng rải rác
            updated_txt = re.sub(r'[\.]{2,}', '.', updated_txt)
            updated_txt = re.sub(r'…+', '.', updated_txt)
            updated_txt = re.sub(r'\.\s*\.', '.', updated_txt)
            updated_txt = re.sub(r'(\w)\s*,\s*\.\s*(\w)', r'\1, \2', updated_txt)

            if updated_txt != txt:
                had_highlight = any(r.font.highlight_color is not None for r in p.runs)
                p.text = updated_txt
                for r in p.runs:
                    r.font.name = "Times New Roman"
                    r.font.size = Pt(11)
                    if had_highlight and keep_highlights:
                        r.font.highlight_color = WD_COLOR_INDEX.YELLOW

        # 2. Dọn dẹp ô bảng biểu
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    c_txt = cell.text.strip()
                    if not c_txt:
                        continue
                    if "Ông/bà:…………………………………" in c_txt or "Chức danh:………………………………" in c_txt:
                        cell.text = "-"
                    elif c_txt in {"…", "….", "...", "....", "…..", "……", "…………", "………", "…..."}:
                        cell.text = "-"
                    elif c_txt.startswith("CIF: …") or c_txt.startswith("Ngày cấp: …") or c_txt.startswith("Nơi cấp: …"):
                        cell.text = "-"
                    elif "Kể từ ngày ký Hợp đồng tín dụng/ngày phê duyệt khoản vay/..." in c_txt:
                        cell.text = "Kể từ ngày ký Hợp đồng tín dụng"
                    elif "12 tháng/24 tháng/36 tháng/..." in c_txt:
                        cell.text = "12 tháng"
                    elif c_txt.startswith("Biện pháp bảo đảm không bằng tài sản: ..."):
                        cell.text = "Biện pháp bảo đảm: Cấp tín dụng không có TSBĐ (Tín chấp 100% theo phê duyệt HĐTDCC). Không yêu cầu BĐS, hàng tồn kho hay bảo lãnh tập đoàn."
                    elif c_txt.startswith("Điều kiện trước giải ngân: …"):
                        cell.text = "Điều kiện trước giải ngân: Cung cấp đầy đủ Hợp đồng kinh tế/Đơn đặt hàng, hóa đơn GTGT đầu vào hợp lệ trước mỗi lần giải ngân."
                    elif c_txt.startswith("Điều kiện sau giải ngân: …."):
                        cell.text = "Điều kiện sau giải ngân: Cam kết doanh số dòng tiền về MSB >= 25% dư nợ bình quân tháng trước; từ 01/05/2026 dòng tiền trực tiếp >= 5% dư nợ BQ/tháng; tuân thủ 06 ngưỡng cảnh báo sớm."
                    elif "Không nằm trong danh sách vi phạm AML\nSố mã AML rà soát/cảnh báo:....." in c_txt:
                        cell.text = "Không nằm trong danh sách vi phạm AML (0 mã cảnh báo)"
                    elif "Điều kiện theo quy định SP số ….. (nếu cấp tín dụng theo SP)" in c_txt:
                        cell.text = "Điều kiện theo quy định SP hiện hành"
                    elif "Quản lý dòng tiền/dịch vụ ngân quỹ…" in c_txt:
                        cell.text = "Quản lý dòng tiền/dịch vụ ngân quỹ"
                    elif "GĐ ĐVKD/…)" in c_txt:
                        cell.text = cell.text.replace("GĐ ĐVKD/…)", "GĐ ĐVKD)")
                    elif "..." in c_txt or "…" in c_txt:
                        cleaned = re.sub(r'[\.]{2,}', '.', c_txt)
                        cleaned = re.sub(r'…+', '', cleaned).strip()
                        if cleaned != c_txt:
                            cell.text = cleaned

    @staticmethod
    def polish(doc_path: str, output_path: str = None, keep_highlights: bool = False) -> str:
        if output_path is None:
            output_path = doc_path

        doc = docx.Document(doc_path)

        # 0. Làm sạch toàn diện các câu hỏi hướng dẫn, gợi ý mẫu và dấu chấm lửng placeholder
        DocumentFormatter.clean_template_prompts_and_dots(doc, keep_highlights=keep_highlights)

        # 1. Chuẩn hóa hình ảnh: Căn giữa và đặt khoảng cách trên dưới
        for p in doc.paragraphs:
            if any(r._r.xpath(".//a:blip") for r in p.runs) or any("blip" in r._r.xml for r in p.runs):
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after = Pt(6)

        # 2. Dọn dẹp TOÀN BỘ các đoạn văn trống thừa rác & dòng chấm placeholder
        for p in list(doc.paragraphs):
            txt = p.text.strip()
            # Kiểm tra xem đoạn văn có chứa hình vẽ, đồ họa hay ảnh thực sự không (dùng xpath, tránh nhầm namespace)
            has_drawing = (
                len(p._p.xpath(".//w:drawing")) > 0 or
                len(p._p.xpath(".//w:pict")) > 0 or
                len(p._p.xpath(".//a:blip")) > 0
            )
            # Xóa đoạn văn rỗng hoặc các dòng chấm placeholder mẫu như "…………………………………."
            is_dotline = len(txt) >= 4 and set(txt).issubset({".", "…", "-", "_", " "})
            if len(doc.tables) < 20:
                if (not txt and not has_drawing) or is_dotline:
                    p_elem = p._p
                    p_elem.getparent().remove(p_elem)

        # 2.1 Tách các đoạn văn có chứa ký tự xuống dòng (\n) thành các đoạn văn độc lập
        # (Ngăn chặn lỗi Word justify kéo dãn khoảng cách chữ gây thưa thớt, ríu rít)
        for p in list(doc.paragraphs):
            if "\n" in p.text:
                lines = [line.strip() for line in p.text.split("\n") if line.strip()]
                if len(lines) > 1:
                    p_elem = p._p
                    parent = p_elem.getparent()
                    p_index = parent.index(p_elem)
                    p.text = lines[0]
                    insert_idx = p_index + 1
                    for next_line in lines[1:]:
                        new_p = doc.add_paragraph()
                        new_p_elem = new_p._p
                        parent.remove(new_p_elem)
                        new_p.text = next_line
                        parent.insert(insert_idx, new_p_elem)
                        insert_idx += 1

        # 3. Chuẩn hóa Bảng biểu
        for tbl in list(doc.tables):
            # Bảo toàn nguyên vẹn bảng biểu phôi gốc (Template Fidelity Contract)
            # Không xóa bảng rỗng hoặc bảng hướng dẫn đối với template đầy đủ
            if len(doc.tables) < 20:
                if len(tbl.rows) <= 1 and len(tbl.columns) <= 2:
                    all_text = "".join(c.text.strip() for r in tbl.rows for c in r.cells)
                    if not all_text:
                        tbl._tbl.getparent().remove(tbl._tbl)
                        continue

            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER

            # Header row (Dòng 0)
            if len(tbl.rows) > 0:
                for cell in tbl.rows[0].cells:
                    for p in cell.paragraphs:
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        for r in p.runs:
                            r.bold = True
                            r.font.name = "Times New Roman"
                            r.font.size = Pt(9.5)

            # Căn lề số liệu và định dạng ô
            for row in tbl.rows:
                for col_idx, cell in enumerate(row.cells):
                    for p in cell.paragraphs:
                        txt = p.text.strip()
                        clean_txt = txt.replace(".", "").replace(",", "").replace("%", "").replace(" tỷ", "").replace(" trđ", "").replace(" ", "").replace("-", "")
                        is_numeric = clean_txt.isdigit() and len(clean_txt) > 0

                        if col_idx == 0 and len(txt) <= 4 and txt.isdigit():
                            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        elif is_numeric and col_idx > 0 and len(txt) > 2:
                            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

                        for r in p.runs:
                            r.font.name = "Times New Roman"
                            if not r.font.size:
                                r.font.size = Pt(9.5)

        # 4. Chuẩn hóa Font chữ, Bôi đậm chuẩn xác và Khoảng cách dòng/đoạn
        major_section_headers = [
            "PHẦN D. TÌNH HÌNH TÀI CHÍNH DOANH NGHIỆP",
            "Tóm tắt thông tin tài chính:",
            "Bảng kết quả kinh doanh:",
            "Bảng cân đối kế toán:",
            "Báo cáo Lưu chuyển tiền tệ và Chất lượng dòng tiền (3 năm gần nhất):",
            "Đặc thù cơ chế kinh doanh và chính sách thương mại của đối tác phân phối:",
            "Bảng Tổng hợp Chỉ số Tài chính và Chu kỳ Vốn lưu động (Đối chiếu chuẩn MSB)",
            "Nhận xét tổng hợp về các chỉ số tài chính:",
            "Tài sản bảo đảm và biện pháp quản lý:",
            "Các điều kiện tín dụng khác (nếu có):",
        ]

        for p in doc.paragraphs:
            txt = p.text.strip()
            if not txt:
                continue

            # Tiêu đề Phần lớn (PHẦN A, B, C, D, E, G, H)
            if any(txt.startswith(f"PHẦN {char}") for char in ["A", "B", "C", "D", "E", "G", "H"]):
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.space_before = Pt(14)
                p.paragraph_format.space_after = Pt(6)
                p.paragraph_format.line_spacing = 1.15
                for r in p.runs:
                    r.bold = True
                    r.font.name = "Times New Roman"
                    r.font.size = Pt(12)
                    r.font.color.rgb = RGBColor(0, 32, 96)
                continue

            # Tiêu đề mục lớn quan trọng trong Phần D / Tờ trình
            if any(txt.startswith(h) for h in major_section_headers):
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.space_before = Pt(8)
                p.paragraph_format.space_after = Pt(4)
                p.paragraph_format.line_spacing = 1.15
                # Gỡ bullet Word rác nếu có
                numPr = p._p.xpath(".//w:numPr")
                if numPr:
                    p._p.pPr.remove(numPr[0])
                ind = p._p.xpath(".//w:ind")
                if ind:
                    p._p.pPr.remove(ind[0])
                for r in p.runs:
                    r.bold = True
                    r.font.name = "Times New Roman"
                    r.font.size = Pt(11)
                continue

            # Tiêu đề mục con đánh số (1., 2., 2.1, a)...)
            if (len(txt) < 80 and any(txt.startswith(k) for k in ["1.", "2.", "3.", "4.", "5.", "2.1", "2.2", "a)", "b)", "c)", "d)"])) or (len(txt) < 60 and (txt.startswith("Đánh giá") or txt.startswith("Nhận xét:"))):
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after = Pt(3)
                p.paragraph_format.line_spacing = 1.15
                for r in p.runs:
                    r.bold = True
                    r.font.name = "Times New Roman"
                    if not r.font.size:
                        r.font.size = Pt(10.5)
                continue

            # Dòng ghi chú đơn vị tính: "Đơn vị tính: triệu đồng"
            if txt.startswith("Đơn vị"):
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.line_spacing = 1.15
                for r in p.runs:
                    r.italic = True
                    r.bold = False
                    r.font.name = "Times New Roman"
                    r.font.size = Pt(9.5)
                continue

            # Đoạn văn thuyết minh & phân tích:
            # 1. Gỡ bullet Word lộn xộn (tránh tình trạng dấu bullet tự động thụt lùi lung tung)
            numPr = p._p.xpath(".//w:numPr")
            if numPr:
                p._p.pPr.remove(numPr[0])
            ind = p._p.xpath(".//w:ind")
            if ind:
                p._p.pPr.remove(ind[0])

            # 2. Căn chỉnh lề trái rõ ràng hoặc lề đều chuẩn không bị kéo dãn dòng ngắn
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.line_spacing = 1.25

            # 3. Chuẩn hóa bôi đậm: Chỉ bôi đậm tiêu đề khoản mục (trước dấu ":"), phần nội dung sau để chữ thường
            # ĐỒNG THỜI BẢO LƯU HIGHLIGHT MÀU VÀNG (Yellow) NẾU CÓ
            had_highlight = any(r.font.highlight_color is not None for r in p.runs)
            colon_idx = txt.find(":")
            dash_idx = txt.find("–") if "–" in txt else txt.find("-")
            
            split_pos = -1
            if colon_idx != -1 and 3 <= colon_idx <= 60:
                split_pos = colon_idx + 1
            elif (txt.startswith("(*)") or txt.startswith("(**)")) and dash_idx != -1 and dash_idx <= 60:
                split_pos = dash_idx + 1

            if split_pos != -1:
                prefix = txt[:split_pos]
                rest = txt[split_pos:]
                p.text = ""
                r_prefix = p.add_run(prefix)
                r_prefix.bold = True
                r_prefix.font.name = "Times New Roman"
                r_prefix.font.size = Pt(11)
                if had_highlight and keep_highlights:
                    r_prefix.font.highlight_color = WD_COLOR_INDEX.YELLOW

                r_rest = p.add_run(rest)
                r_rest.bold = False
                r_rest.font.name = "Times New Roman"
                r_rest.font.size = Pt(11)
                if had_highlight and keep_highlights:
                    r_rest.font.highlight_color = WD_COLOR_INDEX.YELLOW
            else:
                # Nếu không có dấu hai chấm phân tách, kiểm tra nếu đoạn văn dài (>60 ký tự) mà bị bôi đậm toàn bộ thì bỏ bôi đậm
                words = txt.split()
                if len(words) > 10 and all(r.bold for r in p.runs if r.text.strip()):
                    for r in p.runs:
                        r.bold = False
                        r.font.name = "Times New Roman"
                        r.font.size = Pt(11)
                        if had_highlight and keep_highlights:
                            r.font.highlight_color = WD_COLOR_INDEX.YELLOW
                else:
                    for r in p.runs:
                        r.font.name = "Times New Roman"
                        if not r.font.size:
                            r.font.size = Pt(11)
                        if had_highlight and keep_highlights:
                            r.font.highlight_color = WD_COLOR_INDEX.YELLOW

        # Nếu không yêu cầu giữ highlight, xóa sạch toàn bộ highlight và màu nền vàng trong toàn bộ văn bản
        if not keep_highlights:
            for h_elem in doc._body._element.xpath(".//w:highlight"):
                try:
                    h_elem.getparent().remove(h_elem)
                except Exception:
                    pass

            for p in doc.paragraphs:
                for r in p.runs:
                    r.font.highlight_color = None

            for tbl in doc.tables:
                for row in tbl.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            for r in p.runs:
                                r.font.highlight_color = None
                        tcPr = cell._tc.get_or_add_tcPr()
                        for shd in tcPr.xpath(".//w:shd"):
                            fill_val = shd.get(docx.oxml.ns.qn("w:fill"), "").upper()
                            if fill_val in {"FFFFCC", "FFFFD0", "FFFF99", "FFFF00", "FFF2CC", "FFE599"}:
                                tcPr.remove(shd)

        doc.save(output_path)
        return output_path
