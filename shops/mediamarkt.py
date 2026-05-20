from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_mediamarkt_price(url):

    try:
        with chromium_page(url) as page:
            page.wait_for_timeout(5000)

            whole = page.locator(
                '[data-test="branded-price-whole-value"]'
            ).first.inner_text()

            decimal = page.locator(
                '[data-test="branded-price-decimal-value"]'
            ).first.inner_text()

            price_text = whole + decimal

            return extract_price(price_text)

    except Exception as e:
        print(f"MediaMarkt scraper error: {e}")
        return None