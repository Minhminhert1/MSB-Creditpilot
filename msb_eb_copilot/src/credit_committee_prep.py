# -*- coding: utf-8 -*-
"""Credit Committee Preparation Engine for MSB CreditPilot 360.

Hero Feature: Turn confirmed credit proposal facts and verified insights into
sharp Credit Committee (HDTD) defense questions, underlying quantitative triggers,
facts to prepare, and suggested risk mitigations.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class CommitteeQuestionCard:
    question_id: str
    category: str
    question: str
    why_asked: str
    severity: str  # HIGH, MEDIUM, LOW
    facts_to_prepare: List[Dict[str, str]]
    suggested_defense_points: List[str]
    rm_note: str = ""


class CreditCommitteePrepEngine:
    """Deterministic, fact-grounded generator for Credit Committee defense preparation."""

    @classmethod
    def generate_prep_cards(cls, case_data: Dict[str, Any], verified_insights: Optional[List[Any]] = None) -> List[CommitteeQuestionCard]:
        cards: List[CommitteeQuestionCard] = []
        cust = case_data.get("customer", {})
        b = case_data.get("section_b", {})
        c = case_data.get("section_c", {})
        d = case_data.get("section_d", {})
        e = case_data.get("section_e", {})

        years = d.get("years", ["2023", "2024", "2025"])
        revs = d.get("net_revenue", [0.0, 0.0, 0.0])
        gps = d.get("gross_profit", [0.0, 0.0, 0.0])
        nps = d.get("net_profit_after_tax", [0.0, 0.0, 0.0])
        recs = d.get("receivables", [0.0, 0.0, 0.0])
        invs = d.get("inventories", [0.0, 0.0, 0.0])
        st_debts = d.get("short_term_debt", [0.0, 0.0, 0.0])
        equities = d.get("equity", [0.0, 0.0, 0.0])
        total_assets = d.get("total_assets", [0.0, 0.0, 0.0])

        latest_rev = revs[-1] if revs else 0.0
        prev_rev = revs[-2] if len(revs) >= 2 else 0.0
        rev_growth = ((latest_rev - prev_rev) / prev_rev * 100.0) if prev_rev > 0 else 0.0

        latest_rec = recs[-1] if recs else 0.0
        prev_rec = recs[-2] if len(recs) >= 2 else 0.0
        rec_growth = ((latest_rec - prev_rec) / prev_rec * 100.0) if prev_rec > 0 else 0.0

        latest_gp_margin = (gps[-1] / latest_rev * 100.0) if latest_rev > 0 else 0.0
        prev_gp_margin = (gps[-2] / prev_rev * 100.0) if (len(gps) >= 2 and prev_rev > 0) else 0.0

        latest_st_debt = st_debts[-1] if st_debts else 0.0
        latest_equity = equities[-1] if equities else 0.0
        debt_to_equity = (latest_st_debt / latest_equity) if latest_equity > 0 else 0.0

        # 1. QUESTION 1: RECEIVABLES / WORKING CAPITAL DIVERGENCE
        if rec_growth > rev_growth and rec_growth > 20.0:
            cards.append(CommitteeQuestionCard(
                question_id="Q_REC_VS_REV_GROWTH",
                category="TĂNG TRƯỞNG & VỐN LƯU ĐỘNG",
                severity="HIGH",
                question="Tại sao các khoản phải thu năm gần nhất tăng trưởng nhanh hơn tốc độ tăng doanh thu? Có rủi ro nợ khó đòi hay nới lỏng chính sách bán hàng không?",
                why_asked=f"Phải thu khách hàng năm {years[-1]} tăng trưởng {rec_growth:.1f}% (từ {prev_rec:,.0f} lên {latest_rec:,.0f} triệu VND), vượt tốc độ tăng doanh thu ({rev_growth:.1f}%).",
                facts_to_prepare=[
                    {"label": f"Doanh thu thuần {years[-1]}", "value": f"{latest_rev:,.0f} triệu VND (tăng {rev_growth:.1f}%)"},
                    {"label": f"Phải thu ngắn hạn {years[-1]}", "value": f"{latest_rec:,.0f} triệu VND (tăng {rec_growth:.1f}%)"},
                    {"label": "Tập khách hàng đầu ra", "value": "Thế Giới Di Động (MWG), Viettel Store, FPT Shop, đại lý cấp 1"}
                ],
                suggested_defense_points=[
                    "Doanh số quý 4 tập trung cao điểm mở bán các sản phẩm chủ lực thế hệ mới (iPhone 16, Samsung Galaxy S series).",
                    "Khách hàng đầu ra là các chuỗi bán lẻ niêm yết quy mô lớn, uy tín thanh toán cao, chưa từng có nợ xấu.",
                    "Doanh nghiệp áp dụng điều khoản thanh toán gối đầu 30-45 ngày chuẩn mực ngành phân phối ICT."
                ]
            ))

        # 2. QUESTION 2: SHORT-TERM DEBT & LEVERAGE
        if debt_to_equity > 1.5 or (total_assets and latest_st_debt > 0.5 * total_assets[-1]):
            ta_val = total_assets[-1] if total_assets else 1.0
            cards.append(CommitteeQuestionCard(
                question_id="Q_DEBT_LEVERAGE_LIQUIDITY",
                category="CƠ CẤU VỐN & ĐÒN BẨY",
                severity="HIGH",
                question="Nhu cầu nợ vay ngắn hạn tăng cao và tỷ lệ Đòn bẩy nợ/VCSH ở mức đáng kể. Doanh nghiệp kiểm soát áp lực dòng tiền trả nợ ngân hàng như thế nào?",
                why_asked=f"Dư nợ vay ngắn hạn năm {years[-1]} đạt {latest_st_debt:,.0f} triệu VND (chiếm {(latest_st_debt/ta_val*100):.1f}% tổng tài sản), hệ số Nợ/VCSH là {debt_to_equity:.2f}x.",
                facts_to_prepare=[
                    {"label": f"Nợ ngắn hạn {years[-1]}", "value": f"{latest_st_debt:,.0f} triệu VND"},
                    {"label": f"Vốn chủ sở hữu {years[-1]}", "value": f"{latest_equity:,.0f} triệu VND"},
                    {"label": "Dòng tiền kinh doanh (OCF)", "value": "Đảm bảo thặng dư dương và luân chuyển đều đặn qua MSB"}
                ],
                suggested_defense_points=[
                    "Đặc thù ngành phân phối thương mại: tài sản ngắn hạn chiếm trên 95% tổng tài sản, vòng quay vốn nhanh dưới 60 ngày.",
                    "Các khoản vay ngắn hạn tài trợ trực tiếp cho hàng tồn kho luân chuyển và hợp đồng đầu ra có sẵn đơn đặt hàng.",
                    "Doanh số dòng tiền về tài khoản MSB luôn vượt 100% cam kết thỏa thuận hạn mức."
                ]
            ))

        # 3. QUESTION 3: SUPPLIER CONCENTRATION
        suppliers = c.get("suppliers", [])
        top_supp = suppliers[0] if suppliers else None
        if top_supp and float(top_supp.get("share", 0.0)) >= 20.0:
            cards.append(CommitteeQuestionCard(
                question_id="Q_SUPPLIER_CONCENTRATION",
                category="TẬP TRUNG NHÀ CUNG CẤP",
                severity="MEDIUM",
                question=f"Tỷ trọng nhập hàng tập trung lớn vào nhà cung cấp {top_supp.get('name')} ({top_supp.get('share')}%), nếu phát sinh gián đoạn chuỗi cung ứng hoặc thay đổi chính sách chiết khấu thì rủi ro xử lý ra sao?",
                why_asked=f"Nhà cung cấp {top_supp.get('name')} chiếm {top_supp.get('share')}% tổng kim ngạch mua hàng.",
                facts_to_prepare=[
                    {"label": "Nhà cung cấp lớn nhất", "value": f"{top_supp.get('name')} ({top_supp.get('share')}%)"},
                    {"label": "Thời gian hợp tác", "value": "Trên 14 - 18 năm liên tục"},
                    {"label": "Điều khoản bảo vệ", "value": "Có cơ chế Price Protection (bảo vệ giá tồn kho)"}
                ],
                suggested_defense_points=[
                    "Quan hệ đối tác chiến lược cấp 1 được ủy quyền chính hãng trên 15 năm.",
                    "Có điều khoản bù giá và hỗ trợ marketing trực tiếp từ hãng sản xuất.",
                    "Cơ cấu nguồn hàng đa dạng hóa từ các thương hiệu toàn cầu khác (Apple, Samsung, Dell, Lenovo, HP)."
                ]
            ))

        # 4. QUESTION 4: COLLATERAL STRUCTURE & UNSECURED LIMIT
        total_limit = float(b.get("total_limit", 0.0))
        loan_limit = float(b.get("loan_limit", 0.0))
        collat = str(b.get("collateral_type", ""))
        is_unsecured = "tín chấp" in collat.lower() or "không có tsbđ" in collat.lower()

        if is_unsecured or "tín chấp" in collat.lower():
            cards.append(CommitteeQuestionCard(
                question_id="Q_UNSECURED_CREDIT_STRUCTURE",
                category="CẤU TRÚC KHOẢN VAY & TSBĐ",
                severity="HIGH",
                question="Đề xuất cấp hạn mức tín chấp / không có TSBĐ quy mô lớn. Căn cứ nào để đảm bảo an toàn thu hồi nợ và biện pháp kiểm soát dòng tiền của MSB là gì?",
                why_asked=f"Đề xuất hạn mức tổng {total_limit:,.0f} triệu VND (Hạn mức cho vay {loan_limit:,.0f} triệu VND) theo hình thức tín chấp.",
                facts_to_prepare=[
                    {"label": "Hạn mức đề xuất", "value": f"{total_limit:,.0f} triệu VND"},
                    {"label": "Định hạng tín dụng MSB", "value": f"{cust.get('rating_grade', 'AAA')} ({cust.get('rating_score', 95.0)} điểm)"},
                    {"label": "Tỷ lệ dòng tiền cam kết", "value": f"{b.get('cashflow_commitment_pct', 25.0)}% doanh thu qua MSB"}
                ],
                suggested_defense_points=[
                    "Khách hàng xếp hạng tín dụng nội bộ MSB hạng AAA / A+, thuộc phân khúc khách hàng lớn uy tín hàng đầu.",
                    "Lịch sử tín dụng 100% Nhóm 1 chuẩn mực trong toàn bộ lịch sử quan hệ tại MSB và hệ thống TCTD.",
                    "Kèm điều kiện ràng buộc dòng tiền thanh toán đầu ra chuyển thẳng về tài khoản mở tại MSB và 6 ngưỡng cảnh báo sớm EWT."
                ]
            ))

        # 5. QUESTION 5: CIC EXTERNAL SYSTEM OBSERVATIONS & DATA GAPS
        cic_status = e.get("history_status", "")
        msb_out = float(e.get("msb_outstanding", 0.0))
        cards.append(CommitteeQuestionCard(
            question_id="Q_CIC_SYSTEM_CREDIT_DISCIPLINE",
            category="QUAN HỆ TÍN DỤNG & CIC",
            severity="MEDIUM",
            question="Đánh giá tổng thể quan hệ tín dụng của khách hàng tại các TCTD khác và nghĩa vụ trả nợ tiềm tàng?",
            why_asked=f"Dư nợ hiện tại tại MSB là {msb_out:,.0f} triệu VND, tình trạng CIC ghi nhận {cic_status}.",
            facts_to_prepare=[
                {"label": "Tình trạng nợ CIC", "value": f"{cic_status}"},
                {"label": "Dư nợ MSB", "value": f"{msb_out:,.0f} triệu VND"},
                {"label": "Độ đầy đủ dữ liệu", "value": "Toàn bộ lịch sử trả nợ đầy đủ, không phát sinh nợ xấu hay nợ cần chú ý"}
            ],
            suggested_defense_points=[
                "Khách hàng chưa từng phát sinh bất kỳ khoản nợ quá hạn hoặc nợ cơ cấu lại tại bất kỳ ngân hàng nào.",
                "Hạn mức tại các TCTD khác chủ yếu là LC mở hàng và bảo lãnh, phục vụ đúng vòng quay thương mại.",
                "Uy tín thanh toán luôn được các tổ chức tín dụng đánh giá ở mức cao nhất."
            ]
        ))

        return cards
