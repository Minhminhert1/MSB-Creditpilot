"""Deterministic normalization helpers for Section A fact values."""

from decimal import Decimal, InvalidOperation
import re


def normalize_identifier(raw: str) -> str:
    """Normalize enterprise registration numbers / tax codes.

    Preserves leading zeros and removes spaces, dots, and hyphens.
    """
    if not isinstance(raw, str):
        raise TypeError(f"Identifier must be a string, got {type(raw)}.")
    cleaned = re.sub(r"[\s.\-_]", "", raw.strip())
    if not cleaned:
        raise ValueError("Identifier cannot be empty.")
    return cleaned


def normalize_date(raw: str) -> str:
    """Normalize various date expressions into ISO YYYY-MM-DD or YYYY format."""
    if not isinstance(raw, str):
        raise TypeError(f"Date must be a string, got {type(raw)}.")
    cleaned = raw.strip()

    # Pattern: ngày DD tháng MM năm YYYY
    vn_match = re.search(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", cleaned, re.IGNORECASE)
    if vn_match:
        d, m, y = vn_match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

    # Pattern: DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    dmy_match = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$", cleaned)
    if dmy_match:
        d, m, y = dmy_match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

    # Pattern: YYYY-MM-DD
    iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", cleaned)
    if iso_match:
        return cleaned

    # Pattern: Year only YYYY
    year_match = re.match(r"^(\d{4})$", cleaned)
    if year_match:
        return cleaned

    # Fallback to stripped string if unparsed
    return cleaned


def normalize_monetary_to_million_vnd(
    raw_amount: str | int | float | Decimal,
    source_unit: str = "VND",
) -> Decimal:
    """Normalize a monetary amount into Decimal with target unit 'triệu đồng'.

    Args:
        raw_amount: Numeric value or formatted currency string.
        source_unit: Unit of the input amount: 'VND', 'đồng', 'triệu đồng', 'tỷ đồng'.

    Returns:
        Decimal amount scaled to 'triệu đồng'.
    """
    if isinstance(raw_amount, (int, float, Decimal)):
        val = Decimal(str(raw_amount))
    elif isinstance(raw_amount, str):
        cleaned = raw_amount.strip()
        # Remove currency words and symbols
        cleaned = re.sub(r"(?i)\s*(đồng|vnd|đ|tỷ|triệu)\s*", "", cleaned)
        # Handle Vietnamese formatting where '.' is thousands separator and ',' is decimal
        if "." in cleaned and "," in cleaned:
            # E.g. "6.162.331,83" -> "6162331.83"
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "." in cleaned and cleaned.count(".") > 1:
            # E.g. "900.000.000.000" -> "900000000000"
            cleaned = cleaned.replace(".", "")
        elif "," in cleaned and cleaned.count(",") > 1:
            # E.g. "900,000,000,000" -> "900000000000"
            cleaned = cleaned.replace(",", "")
        elif "." in cleaned:
            # Vietnamese notation: if exactly 3 digits follow '.', e.g. '1.500' -> 1500
            if re.search(r"^\d+\.\d{3}$", cleaned):
                cleaned = cleaned.replace(".", "")
        elif "," in cleaned:
            # Decimal comma "123,45"
            cleaned = cleaned.replace(",", ".")


        try:
            val = Decimal(cleaned)
        except InvalidOperation as e:
            raise ValueError(f"Could not parse monetary amount from '{raw_amount}'.") from e
    else:
        raise TypeError(f"Amount must be str, int, float or Decimal, got {type(raw_amount)}.")

    unit_lower = source_unit.strip().lower()
    if unit_lower in ("vnd", "đồng", "dong"):
        # 1 triệu đồng = 1,000,000 VND
        return val / Decimal("1000000")
    elif unit_lower in ("tỷ", "tỷ đồng", "ty"):
        # 1 tỷ đồng = 1,000 triệu đồng
        return val * Decimal("1000")
    elif unit_lower in ("triệu", "triệu đồng", "trieu"):
        return val

    # Default assumed VND if unrecognized
    return val / Decimal("1000000")
