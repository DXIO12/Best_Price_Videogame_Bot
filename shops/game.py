from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_game_price(url):

    try:
        with chromium_page(url) as page:
            page.wait_for_timeout(8000)

            # Accept cookies if banner appears
            try:
                page.locator(
                    'button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll'
                ).click(timeout=3000)
                page.wait_for_timeout(1000)
            except Exception:
                pass

            # The price is split across three sibling spans:
            #   <span class="int">49 <small>...</small></span>
            #   <span class="decimal">'99</span>
            #   <span class="currency">€</span>
            # We read .int and .decimal separately and combine them,
            # ignoring the <small> crossed-out original price inside .int.

            buy_price = page.locator(".buy--price").first

            # .int contains the integer part BUT also a nested <small> with the
            # original price — evaluate only the direct text node to avoid it
            int_part = buy_price.locator(".int").evaluate(
                """el => {
                    // Collect only direct text nodes, skip child elements
                    let text = '';
                    for (const node of el.childNodes) {
                        if (node.nodeType === Node.TEXT_NODE) {
                            text += node.textContent;
                        }
                    }
                    return text.trim();
                }"""
            )

            decimal_part = buy_price.locator(".decimal").inner_text().strip()

            # decimal_part is "'99" — strip the apostrophe separator
            decimal_part = decimal_part.lstrip("'").lstrip(",").lstrip(".").strip()

            if not int_part:
                return None

            price_str = f"{int_part}.{decimal_part}" if decimal_part else int_part

            return extract_price(price_str)

    except Exception as e:
        print(f"Game scraper error: {e}")
        return None