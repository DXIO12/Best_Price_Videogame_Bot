from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_carrefour_price(url):

    try:
        with chromium_page(url) as page:
            page.wait_for_timeout(8000)

            # Accept cookies
            try:
                page.locator('button#onetrust-accept-btn-handler').click(timeout=8000)
                print("Cookies accepted.")
                page.wait_for_timeout(2000)
            except:
                print("Cookie button not found or already accepted.")

            # The buybox has two price spans:
            #   .buybox__price--current    → 60,84 €   (sale price  ← we want this)
            #   .buybox__price-strikethrough → 73,01 € (original price)
            # Target the current price span directly.
            SELECTORS = [
                '.buybox__price--current',
                '[class*="price--current"]',
                '[class*="current-price"]',
            ]

            price_text = None

            for selector in SELECTORS:
                try:
                    text = page.locator(selector).first.inner_text(timeout=3000)
                    cleaned = text.strip()
                    if cleaned and "€" in cleaned:
                        price_text = cleaned
                        break
                except Exception:
                    continue

            if not price_text:
                return None

            return extract_price(price_text)

    except Exception as e:
        print(f"Carrefour scraper error: {e}")
        return None