from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_pccomponentes_price(url):

    try:
        with chromium_page(url) as page:
            page.wait_for_timeout(5000)

            # Accept cookies
            try:
                page.locator('button#cookiesAcceptAll').click(timeout=5000)
                page.wait_for_timeout(1500)
            except:
                pass

            full_price = page.locator(
                "#pdp-price-current-integer"
            ).first.inner_text()

            return extract_price(full_price)

    except Exception as e:
        print(f"PcComponentes scraper error: {e}")
        return None