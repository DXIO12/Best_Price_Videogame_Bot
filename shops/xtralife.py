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

            # Scope to the main product price component. `.tw-font-xtralife-bold`
            # is a generic Tailwind class also used by shipping notices
            # ("Recíbelo desde 2,99€") and recommendation cards, so searching the
            # whole page could return an unrelated product's price when this one
            # has none. The real price lives inside <product-pricing>.
            pricing = page.locator("product-pricing").first

            if pricing.count() == 0:
                return None

            elements = pricing.locator(".tw-font-xtralife-bold")

            count = elements.count()

            price_text = None

            for i in range(count):

                text = elements.nth(i).inner_text().strip()

                if "€" in text:
                    price_text = text
                    break

            if price_text is None:
                return None

            return extract_price(price_text)

    except Exception as e:
        print(f"Xtralife scraper error: {e}")
        return None