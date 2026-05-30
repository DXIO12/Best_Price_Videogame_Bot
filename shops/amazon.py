from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price
    
def get_amazon_price(url):

    try:
        with chromium_page(url) as page:
            # Let the page fully render
            page.wait_for_timeout(8000)

            # Accept cookies if banner appears
            try:
                page.locator('input#sp-cc-accept').click(timeout=5000)
                page.wait_for_timeout(1500)
            except Exception:
                pass

            # Get ALL matching elements
            texts = page.locator(".a-price .a-offscreen").all_inner_texts()

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
        print(f"Amazon scraper error: {e}")
        return None