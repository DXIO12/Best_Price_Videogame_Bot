from application.shops.playwright_utils import chromium_page
from application.shops.price_utils import extract_price


# Only look for a price inside the main-product price region. Searching the whole
# page (e.g. `page.locator('.a-price')`) also matches recommendation carousels
# ("Productos relacionados", "Los clientes también compraron"), so an unavailable
# product with no buybox price would wrongly return a recommended product's price.
MAIN_PRICE_CONTAINERS = [
    '#corePriceDisplay_desktop_feature_div',
    '#corePrice_feature_div',
    '#apex_desktop',
    '#buybox',
    '#desktop_buybox',
    '#rightCol',
    '#priceblock_ourprice',
]

# Any price node inside the main-price region that already holds a price. Used
# to wait for the page to actually render instead of sleeping a fixed amount.
# The `:has-text` is deliberate: these nodes can be in the DOM before their text
# is filled in, and waiting for the bare element lets the extraction run against
# an empty node — a race that only shows up on a busy machine.
MAIN_PRICE_SELECTOR = ", ".join(
    f"{container} .a-price:has-text('€')" for container in MAIN_PRICE_CONTAINERS
)


def _extract_amazon_price_from_price_block(block) -> float | None:
    """Amazon commonly renders price as whole + decimal + fraction nodes."""
    try:
        whole = block.locator('.a-price-whole').first.inner_text(timeout=2000).strip()
        fraction = block.locator('.a-price-fraction').first.inner_text(timeout=2000).strip()
        decimal = block.locator('.a-price-decimal').first.inner_text(timeout=2000).strip()
    except Exception:
        try:
            html = block.inner_html()
            return extract_price(html)
        except Exception:
            return None

    if not whole and not fraction:
        return None

    if not fraction:
        return extract_price(whole)

    # Build the exact price from the Amazon structure: 54 + ',' + 99 => 54.99
    whole_digits = ''.join(ch for ch in whole if ch.isdigit())
    fraction_digits = ''.join(ch for ch in fraction if ch.isdigit())
    if not whole_digits or not fraction_digits:
        return None

    separator = ',' if decimal == ',' or ',' in whole or ',' in fraction else '.'
    price_text = f"{whole_digits}{separator}{fraction_digits}"
    return extract_price(price_text)


def get_amazon_price(url):

    try:
        with chromium_page(url) as page:
            # Wait for the price to render rather than sleeping blindly: this
            # continues as soon as it appears (typically well under a second)
            # and still tolerates a slower page than the old fixed wait did.
            # On timeout we fall through and let the extraction below decide,
            # exactly as it used to after the sleep expired.
            try:
                page.wait_for_selector(MAIN_PRICE_SELECTOR, state="attached",
                                       timeout=12000)
            except Exception:
                pass

            # Accept cookies if banner appears
            try:
                page.locator('input#sp-cc-accept').click(timeout=5000)
                page.wait_for_timeout(1500)
            except Exception:
                pass

            # Look for the price ONLY inside the main-product price region.
            # If none of these containers hold a price, the product has no
            # buybox price and is treated as not available (return None).
            for container_selector in MAIN_PRICE_CONTAINERS:
                try:
                    container = page.locator(container_selector).first
                    if container.count() == 0:
                        continue
                except Exception:
                    continue

                # Prefer the structured block: whole + decimal + fraction.
                try:
                    block = container.locator('.a-price').first
                    if block.count() > 0:
                        price = _extract_amazon_price_from_price_block(block)
                        if price is not None:
                            return price
                except Exception:
                    pass

                # Fallback to the hidden offscreen price text within the container.
                try:
                    offscreen = container.locator('.a-price .a-offscreen')
                    for text in offscreen.all_inner_texts():
                        price = extract_price(text)
                        if price is not None:
                            return price
                except Exception:
                    pass

            return None

    except Exception as e:
        print(f"Amazon scraper error: {e}")
        return None