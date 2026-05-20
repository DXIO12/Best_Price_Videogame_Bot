from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_game_price(url):

    try:
        with chromium_page(url) as page:
            # Let the page fully render
            page.wait_for_timeout(8000)

            # Get ALL matching elements
            texts = page.locator(".buy--price").all_inner_texts()

            price_text = None

            for text in texts:

                cleaned_text = text.strip()

                if "€" in cleaned_text:
                    price_text = cleaned_text
                    break

            if not price_text:
                return None

            return extract_price(price_text)

    except Exception as e:
        print(f"Game scraper error: {e}")
        return None