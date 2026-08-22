from application.config.logger import get_logger
import html as html_lib
import re

log = get_logger("shops.price_utils")


def extract_price(text: str) -> float | None:
    """
    Robustly extract a Euro price from a raw string or HTML fragment.

    Handles:
    - Spanish locale: "49,99 €"  → 49.99
    - Thousands separator: "1.299,00 €" → 1299.00
    - HTML fragments from Amazon: "<span>54<span>,</span></span><span>99</span>€" → 54.99
    - Multiple numbers in string (e.g. old price + new price): takes the LAST match
    - Extra whitespace, newlines, non-breaking spaces
    """
    try:
        if text is None:
            return None

        cleaned = html_lib.unescape(str(text)).strip()
        cleaned = cleaned.replace("&nbsp;", " ")
        cleaned = cleaned.replace("\xa0", " ")
        cleaned = cleaned.replace("€", "")
        cleaned = cleaned.replace("\n", " ")
        cleaned = cleaned.replace("\t", " ")
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        # Amazon can split a price like "54 , 99" across HTML tags/spaces.
        # Rejoin decimal separators while keeping thousand separators valid.
        cleaned = re.sub(r"(?<=\d)\s*[,\.]\s*(?=\d{1,2}(?:\D|$))", ".", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Normalise European number format to plain decimal
        # Pattern: optional thousands (dots or spaces) + comma decimal
        # e.g. "1.299,00" → "1299.00"  |  "49,99" → "49.99"  |  "49.99" → "49.99"
        def normalise_number(raw: str) -> str:
            raw = raw.strip().replace(" ", "")
            # If it contains a comma: comma is the decimal separator
            if "," in raw and "." in raw:
                if raw.rfind(",") > raw.rfind("."):
                    raw = raw.replace(".", "").replace(",", ".")
                else:
                    raw = raw.replace(",", "")
            elif "," in raw:
                raw = raw.replace(".", "").replace(",", ".")
            elif "." in raw and raw.count(".") > 1:
                # Handles "1.299.00" where the last dot is the decimal separator.
                if len(raw.rsplit(".", 1)[1]) <= 2:
                    integer_part, decimal_part = raw.rsplit(".", 1)
                    raw = integer_part.replace(".", "") + "." + decimal_part
                else:
                    raw = raw.replace(".", "")
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
        log.error(f"Price extraction error: {e}")
        return None