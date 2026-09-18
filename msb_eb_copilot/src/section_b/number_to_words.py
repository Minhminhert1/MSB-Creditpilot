# -*- coding: utf-8 -*-
"""Pure-Python Vietnamese number-to-words currency formatting engine for MSB Credit Proposals."""

from typing import Optional


def read_three_digits(num: int, is_highest_group: bool = False) -> str:
    units = ["", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
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


def number_to_vietnamese_words(n: int) -> str:
    """Chuyển đổi số nguyên thành chuỗi chữ tiếng Việt chuẩn ngữ pháp tài chính ngân hàng Việt Nam.
    
    Hỗ trợ chuẩn xác các cấp số từ hàng đơn vị, triệu, tỷ, đến hàng nghìn tỷ đồng.
    Ví dụ:
        100_000_000_000   -> 'Một trăm tỷ đồng'
        2_200_000_000_000 -> 'Hai nghìn hai trăm tỷ đồng'
        1_000_000_000_000 -> 'Một nghìn tỷ đồng'
        20_000_000        -> 'Hai mươi triệu đồng'
        0                 -> 'Không đồng'
    """
    if n == 0:
        return "Không đồng"
    if n < 0:
        return "Âm " + number_to_vietnamese_words(abs(n)).lower()

    # Tách thành các block 9 chữ số (chu kỳ tỷ: 10^0, 10^9, 10^18)
    ty_blocks = []
    temp = n
    while temp > 0:
        ty_blocks.append(temp % 1_000_000_000)
        temp //= 1_000_000_000

    ty_scales = ["", "tỷ", "triệu tỷ", "tỷ tỷ"]

    words = []
    for ty_idx in range(len(ty_blocks) - 1, -1, -1):
        block_val = ty_blocks[ty_idx]
        if block_val > 0:
            groups = []
            b_temp = block_val
            while b_temp > 0:
                groups.append(b_temp % 1000)
                b_temp //= 1000

            sub_scales = ["", "nghìn", "triệu"]
            sub_words = []
            is_highest_of_all = (ty_idx == len(ty_blocks) - 1)
            for g_idx in range(len(groups) - 1, -1, -1):
                g = groups[g_idx]
                if g > 0:
                    text_g = read_three_digits(g, is_highest_group=(is_highest_of_all and g_idx == len(groups) - 1))
                    scale = sub_scales[g_idx]
                    if scale:
                        sub_words.append(f"{text_g} {scale}")
                    else:
                        sub_words.append(text_g)

            block_text = " ".join(sub_words).strip()
            scale_ty = ty_scales[ty_idx]
            if scale_ty:
                words.append(f"{block_text} {scale_ty}")
            else:
                words.append(block_text)

    result = " ".join(words).strip()
    result = result[0].upper() + result[1:] + " đồng"
    return result


def format_amount_with_words(amount_trieu: Optional[float], currency: str = "VND") -> str:
    """Format số tiền từ đơn vị triệu đồng thành chuỗi số và chữ chuẩn biểu mẫu MSB MB07."""
    if amount_trieu is None or amount_trieu <= 0:
        return ""
    
    full_amount = int(round(amount_trieu * 1_000_000))
    formatted_num = f"{full_amount:,.0f}".replace(",", ".")
    words = number_to_vietnamese_words(full_amount)
    return f"{formatted_num} {currency} ({words})"


def format_numeric_amount(amount_trieu: Optional[float]) -> str:
    """Format số tiền (triệu) thành chuỗi số có dấu phân cách hàng nghìn."""
    if amount_trieu is None or amount_trieu <= 0:
        return ""
    return f"{amount_trieu:,.0f}".replace(",", ".")
