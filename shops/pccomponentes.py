from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_pccomponentes_price(url):

    try:
        with chromium_page(url) as page:
            # Wait for the price to render rather than sleeping blindly: this
            # continues as soon as it appears and still tolerates a slower page
            # than the old fixed wait did. On timeout we fall through and let
            # the extraction below fail exactly as it used to.
            # `:text-matches` is deliberate — this node holds digits (no "€")
            # and can be in the DOM before they are filled in, so waiting for
            # the bare element races the render on a busy machine. "[0-9]" and
            # not "\d": Playwright unescapes backslashes inside the selector
            # string, so "\d" silently becomes a literal "d" and never matches.
            try:
                page.wait_for_selector(
                    '#pdp-price-current-integer:text-matches("[0-9]")',
                    state="attached", timeout=10000)
            except Exception:
                pass

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