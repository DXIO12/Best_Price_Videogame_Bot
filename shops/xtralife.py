from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_xtralife_price(url):

    try:
        with chromium_page(url) as page:
            page.wait_for_timeout(5000)

            # Accept cookies
            try:
                page.get_by_text("Permitir todo").click(timeout=8000)
                page.wait_for_timeout(2000)
            except:
                pass

            elements = page.locator(".tw-font-xtralife-bold")

            count = elements.count()

            price_text = None

            for i in range(count):

                text = elements.nth(i).inner_text().strip()

                if "€" in text:
                    price_text = text
                    break

            return extract_price(price_text)

    except Exception as e:
        print(f"Xtralife scraper error: {e}")
        return None