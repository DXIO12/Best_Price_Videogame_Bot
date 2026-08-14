from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_mediamarkt_price(url):

    try:
        with chromium_page(url) as page:
            # Wait for the price to render rather than sleeping blindly: this
            # continues as soon as it appears and still tolerates a slower page
            # than the old fixed wait did. On timeout we fall through and let
            # the extraction below fail exactly as it used to.
            try:
                page.wait_for_selector('[data-test="branded-price-whole-value"]',
                                       state="attached", timeout=10000)
            except Exception:
                pass

            # Accept cookies
            try:
                page.locator('button#pwa-consent-layer-accept-all-button').click(timeout=8000)
                page.wait_for_timeout(2000)
            except:
                pass

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