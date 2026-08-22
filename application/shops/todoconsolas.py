from application.config.logger import get_logger
from application.shops.playwright_utils import chromium_page
from application.shops.price_utils import extract_price

log = get_logger("shops.todoconsolas")


# The product page shows the current price and, right below it, the "PVPR"
# recommended one ("51,95 € / PVPR 59,95 €"). Both live inside
# <div class="current-price">, so the selector has to reach the itemprop span:
# reading the whole block would hand extract_price two numbers and it keeps the
# last one — the PVPR — which is never what we track.
PRICE_SELECTOR = 'div.current-price span[itemprop="price"]'


def get_todoconsolas_price(url):

    try:
        with chromium_page(url) as page:
            # Server-rendered price, so it is in the markup as soon as the
            # document arrives; the wait only covers a slow response.
            try:
                page.wait_for_selector(PRICE_SELECTOR, state="attached", timeout=10000)
            except Exception:
                pass

            price = page.locator(PRICE_SELECTOR).first

            if price.count() == 0:
                return None

            # The clean decimal is mirrored in the content attribute
            # ("51.95"); the visible text ("51,95 €") is the fallback for
            # pages that omit it.
            price_text = price.get_attribute("content") or price.inner_text()

            return extract_price(price_text)

    except Exception as e:
        log.error(f"TodoConsolas scraper error: {e}")
        return None
