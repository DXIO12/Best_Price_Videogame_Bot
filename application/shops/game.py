from application.shops.playwright_utils import chromium_page

# The DOM knowledge for game.es lives with the URL resolver, which has to read a
# price from every candidate listing before it can pick one. Re-exported here so
# the scraper and the resolver can never drift apart: they used to keep separate
# copies, and only one of them ever learned that a pre-order page shows the
# reservation deposit instead of the price.
from application.services.url_resolvers.game_url_resolver import (  # noqa: F401
    PRICE_SELECTOR,
    read_game_price,
)


def get_game_price(url):

    try:
        with chromium_page(url) as page:
            # Accept cookies if banner appears
            try:
                page.locator(
                    'button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll'
                ).click(timeout=5000)
                page.wait_for_timeout(1000)
            except Exception:
                pass

            try:
                page.wait_for_selector(PRICE_SELECTOR, state="attached", timeout=20000)
            except Exception:
                pass

            return read_game_price(page)

    except Exception as e:
        print(f"Game scraper error: {e}")
        return None
