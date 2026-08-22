from application.shops.playwright_utils import chromium_page
from application.shops.price_utils import extract_price


def get_pccomponentes_price(url):

    try:
        with chromium_page(url) as page:
            # Wait for the price to render rather than sleeping blindly: this
            # continues as soon as it appears and still tolerates a slower page
            # than the old fixed wait did. On timeout we fall through and let
            # the extraction below fail exactly as it used to.
            # Wait for the price to render rather than sleeping blindly: this
            # continues as soon as it appears and still tolerates a slower page
            # than the old fixed wait did.
            #
            # `:has-text` and NOT `:text-matches`: the price is split across a
            # nested span —
            #     <span id=pdp-price-current-integer>57<span ...>,99€</span></span>
            # — and `:text-matches` only matches the *smallest* element holding
            # the text, so it never matched the outer node and burned the whole
            # timeout on every scrape. `:has-text` searches descendants too.
            try:
                page.wait_for_selector("#pdp-price-current-integer:has-text('€')",
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