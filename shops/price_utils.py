import re


def extract_price(text: str) -> float | None:
    """
    Robustly extract a Euro price from a raw string.

    Handles:
    - Spanish locale: "49,99 €"  → 49.99
    - Thousands separator: "1.299,00 €" → 1299.00
    - Multiple numbers in string (e.g. old price + new price): takes the LAST match
    - Extra whitespace, newlines, non-breaking spaces
    """
    try:
        if text is None:
            return None

        cleaned = text.strip()
        cleaned = cleaned.replace("€", "")
        cleaned = cleaned.replace("\xa0", " ")   # non-breaking space → space
        cleaned = cleaned.replace("\n", " ")
        cleaned = cleaned.replace("\t", " ")

        # Normalise European number format to plain decimal
        # Pattern: optional thousands (dots or spaces) + comma decimal
        # e.g. "1.299,00" → "1299.00"  |  "49,99" → "49.99"  |  "49.99" → "49.99"
        def normalise_number(raw: str) -> str:
            raw = raw.strip()
            # If it contains a comma: comma is the decimal separator
            if "," in raw:
                # Remove dots (thousands separators) then replace comma with dot
                raw = raw.replace(".", "").replace(",", ".")
            # else: dot is already the decimal separator (or no decimal at all)
            return raw

        # Find all candidate price tokens: digits with optional separators
        # Matches things like "49,99"  "1.299,00"  "49.99"  "60,84"
        candidates = re.findall(r"\d[\d.,]*\d|\d", cleaned)

        if not candidates:
            return None

        # Take the LAST candidate — pages often show "original price  →  sale price"
        # and we want the sale (final) price
        price_str = normalise_number(candidates[-1])

        match = re.fullmatch(r"\d+(?:\.\d+)?", price_str)
        if match:
            return float(match.group())

        return None

    except Exception as e:
        print(f"Price extraction error: {e}")
        return None