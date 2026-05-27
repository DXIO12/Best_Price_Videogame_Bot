from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_elcorteingles_price(url):

    try:
        with chromium_page(url) as page:
            page.wait_for_timeout(8000)

            # Accept cookies
            try:
                page.locator('button#onetrust-accept-btn-handler').click(timeout=3000)
                page.wait_for_timeout(1000)
            except Exception:
                pass

            # HTML structure:
            #   span.price-sale            → "49,90 €"  ← current sale price (we want)
            #   span.price-unit--original  → "79,90 €"  ← crossed-out original price
            #   span.price-discount        → "37%"
            SELECTORS = [
                'span.price-sale',
                '[aria-label="Precio de venta"]',
                '[class*="price-sale"]',
            ]

            price_text = None

            for selector in SELECTORS:
                try:
                    text = page.locator(selector).first.inner_text(timeout=5000)
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
        print(f"El Corte Inglés scraper error: {e}")
        return None