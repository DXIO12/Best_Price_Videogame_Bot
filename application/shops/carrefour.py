from application.shops.playwright_utils import chromium_page
from application.shops.price_utils import extract_price


# The buybox has two price spans:
#   .buybox__price--current    → 60,84 €   (sale price  ← we want this)
#   .buybox__price-strikethrough → 73,01 € (original price)
# Target the current price span directly.
SELECTORS = [
    '.buybox__price--current',       # sale/offer price (takes priority)
    '[class*="price--current"]',
    '[class*="current-price"]',
    '.buybox__price',                # regular price (no active offer)
]

# `:has-text` is deliberate — these nodes can be in the DOM before their text is
# filled in, so waiting for the bare element races the render on a busy machine.
PRICE_SELECTOR = ", ".join(f"{selector}:has-text('€')" for selector in SELECTORS)


def get_carrefour_price(url):

    try:
        with chromium_page(url) as page:
            # Wait for the price to render rather than sleeping blindly: this
            # continues as soon as it appears and still tolerates a slower page
            # than the old fixed wait did. On timeout we fall through to the
            # extraction loop, which fails the same way it used to.
            try:
                page.wait_for_selector(PRICE_SELECTOR, state="attached",
                                       timeout=12000)
            except Exception:
                pass

            # Accept cookies
            try:
                page.locator('button#onetrust-accept-btn-handler').click(timeout=8000)
                page.wait_for_timeout(2000)
            except:
                print("Cookie button not found or already accepted.")

            price_text = None

            for selector in SELECTORS:
                try:
                    text = page.locator(selector).first.inner_text(timeout=3000)
                    cleaned = text.strip()
                    if cleaned and "€" in cleaned:
                        price_text = cleaned
                        break
                except Exception:
                    continue

            if not price_text:
                return None

            return extract_price(price_text)

    except Exception as e:
        print(f"Carrefour scraper error: {e}")
        return None