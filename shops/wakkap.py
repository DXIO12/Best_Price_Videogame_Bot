from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_wakkap_price(url):

    try:
        with chromium_page(url) as page:
            page.wait_for_timeout(5000)

            # Accept cookies
            try:
                page.locator('div.cmp-pop div.cmp-button-mini').click(timeout=8000)
                page.wait_for_timeout(1500)
            except:
                pass

            # Try offer price first, fall back to regular price
            offer = page.locator(".price-value.offer")
            if offer.count() > 0:
                price_text = offer.evaluate("(el) => el.childNodes[1].textContent")
            else:
                price_text = page.locator(".price-value").first.inner_text(timeout=5000)

            return extract_price(price_text)

    except Exception as e:
        print(f"Wakkap scraper error: {e}")
        return None