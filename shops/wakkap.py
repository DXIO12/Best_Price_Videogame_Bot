from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_wakkap_price(url):

    try:
        with chromium_page(url) as page:
            page.wait_for_timeout(5000)

            price_text = page.locator(
                ".price-value.offer"
            ).evaluate("(el) => el.childNodes[1].textContent")

            return extract_price(price_text)

    except Exception as e:
        print(f"Wakkap scraper error: {e}")
        return None