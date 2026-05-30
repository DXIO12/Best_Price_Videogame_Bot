from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


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

            # Wait for the price container to be attached to the DOM.
            # state="attached" avoids the "visible" check which fails when the
            # element exists but Playwright considers it off-screen or zero-size.
            page.wait_for_selector(".buy--price", state="attached", timeout=20000)
            page.wait_for_timeout(2000)  # let JS fill in the price text

            buy_price = page.locator(".buy--price").first

            # inner_text() may include a nested <small> original price on a new line
            # — splitlines()[0] safely gives just the integer part in both cases
            int_raw = buy_price.locator(".int").inner_text(timeout=10000).strip()
            int_part = int_raw.splitlines()[0].strip()

            decimal_part = buy_price.locator(".decimal").inner_text(timeout=5000).strip()

            # decimal_part is "'99" — strip the apostrophe separator
            decimal_part = decimal_part.lstrip("'").lstrip(",").lstrip(".").strip()

            if not int_part:
                return None

            price_str = f"{int_part}.{decimal_part}" if decimal_part else int_part

            return extract_price(price_str)

    except Exception as e:
        print(f"Game scraper error: {e}")
        return None