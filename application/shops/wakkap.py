from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_wakkap_price(url):

    try:
        with chromium_page(url) as page:
            # Wait for the price to render rather than sleeping blindly: this
            # continues as soon as it appears and still tolerates a slower page
            # than the old fixed wait did. Scoped to the product summary for the
            # same reason the extraction below is. On timeout we fall through
            # and let that extraction fail exactly as it used to.
            # `:has-text` is deliberate — the node can be in the DOM before its
            # text is filled in, so waiting for the bare element races the
            # render on a busy machine.
            try:
                page.wait_for_selector(".cmp-item-summary .price-value:has-text('€')",
                                       state="attached", timeout=10000)
            except Exception:
                pass

            # Accept cookies
            try:
                page.locator('div.cmp-pop div.cmp-button-mini').click(timeout=8000)
                page.wait_for_timeout(1500)
            except:
                pass

            # Scope to the main product summary so we never read a price from a
            # recommendation card if this product has none.
            summary = page.locator(".cmp-item-summary").first
            if summary.count() == 0:
                return None

            # Try offer price first, fall back to regular price
            offer = summary.locator(".price-value.offer")
            if offer.count() > 0:
                price_text = offer.first.evaluate("(el) => el.childNodes[1].textContent")
            else:
                regular = summary.locator(".price-value")
                if regular.count() == 0:
                    return None
                price_text = regular.first.inner_text(timeout=5000)

            return extract_price(price_text)

    except Exception as e:
        print(f"Wakkap scraper error: {e}")
        return None