from application.config.logger import get_logger
from application.shops.playwright_utils import chromium_page
from application.shops.price_utils import extract_price

log = get_logger("shops.mediamarkt")


def get_mediamarkt_price(url):

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
            #
            # This only works because the node is a leaf (`<span ...>58,</span>`).
            # `:text-matches` matches the *smallest* element containing the text,
            # so if MediaMarkt ever nests the digits in a child span this stops
            # matching and silently burns the full timeout — the exact bug that
            # hit PCComponentes. test_wait_selectors.py guards against it.
            try:
                page.wait_for_selector(
                    '[data-test="branded-price-whole-value"]:text-matches("[0-9]")',
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
        log.error(f"MediaMarkt scraper error: {e}")
        return None