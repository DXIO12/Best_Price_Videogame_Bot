from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_elcorteingles_price(url):

    try:
        with chromium_page(url) as page:

            page.wait_for_timeout(8000)

            price_text = page.locator(
                'span.price-unit--normal.product-detail-price'
            ).first.inner_text(timeout=5000)

            if not price_text or "€" not in price_text:
                return None

            return extract_price(price_text)

    except Exception as e:
        print(f"El Corte Inglés scraper error: {e}")
        return None