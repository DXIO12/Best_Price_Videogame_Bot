import re


def extract_price(text):
    try:
        if text is None:
            return None

        cleaned = text.strip()
        cleaned = cleaned.replace("€", "")
        cleaned = cleaned.replace("\xa0", "")
        cleaned = cleaned.replace(" ", "")
        cleaned = cleaned.replace("\n", "")
        cleaned = cleaned.replace("'", ".")
        cleaned = cleaned.replace(",", ".")

        match = re.search(r"\d+(?:\.\d+)?", cleaned)

        if match:
            return float(match.group())

        return None

    except Exception as e:
        print(f"Price extraction error: {e}")
        return None
