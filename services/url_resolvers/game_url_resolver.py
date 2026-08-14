# services/url_resolvers/game_url_resolver.py

import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from config.runtime_config import resolve_headless
from shops.price_utils import extract_price
from urllib.parse import unquote_plus

BASE_URL = "https://www.game.es"

# The main buy box, and the only node on the page that identifies it. A product
# page carries exactly one `[data-quick-container]` but 9-11 `.buy--price`
# nodes — the rest belong to the "Productos relacionados" carousels. Scoping
# every read to this container is the same defence amazon.py's
# MAIN_PRICE_CONTAINERS provides: a product with no price of its own must return
# None, never a neighbouring product's price.
QUICK_CONTAINER = "[data-quick-container]"

# A pre-order page adds `buy-reserve` to that container. Its `.buy--price` then
# holds the RESERVATION DEPOSIT, not the price — 3'00 € for a game whose real
# web price is 39,99 €. This class is the only reliable discriminator: the
# "RESERVAR" label (`.buy--type`) also appears elsewhere on a released page.
RESERVE_CONTAINER = f"{QUICK_CONTAINER}.buy-reserve"

# Wait for the price to carry its text, not just for the node to exist
# (README § "Scraper Waits"). `:has-text` and NOT `:text-matches`: the amount is
# split across `.int` / `.decimal` / `.currency` children, and `:text-matches`
# only matches the *smallest* element holding the text, so it would never match
# the outer node and would silently burn the whole timeout.
PRICE_SELECTOR = f"{QUICK_CONTAINER} .buy--price:has-text('€')"

# On a reserve page the real price lives in `.buy--info` as "PVP WEB : 39.99 €".
# `.buy--info` exists on released pages too, holding "Llévate 420 puntos GAME" —
# so the PVP text is required, never the bare node, or a released product would
# report 420.
PVP_WEB_PATTERN = re.compile(r"PVP\s*WEB\s*:?\s*([\d.,]+)", re.IGNORECASE)

# `.int` nests a <small> with the crossed-out original price. Reading only the
# direct text nodes drops it without depending on how inner_text() happens to
# break lines, and without the IndexError an empty node would raise.
_OWN_TEXT_JS = """el => {
    let text = '';
    for (const node of el.childNodes) {
        if (node.nodeType === Node.TEXT_NODE) text += node.textContent;
    }
    return text.trim();
}"""

USED_KEYWORDS = {"segunda mano", "seminuevo", "usado", "reacondicionado", "segunda-mano"}
DIGITAL_KEYWORDS = {"prepago", "prepagos", "digital", "descarga"}

# Maps our internal platform names → the path segment game.es uses in product URLs
# e.g. /videojuegos/accion/playstation-5/007-first-light/246786
PLATFORM_SLUGS = {
    "ps5": "playstation-5",
    "ps4": "playstation-4",
    "ns2": "nintendo-switch-2",
    "switch 2": "nintendo-switch-2",
    "ns": "nintendo-switch",
    "switch": "nintendo-switch",
    "pc": "pc",
    "xbox series x": "xbox-series-x",
}


def _is_used(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in USED_KEYWORDS)


def _is_digital(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in DIGITAL_KEYWORDS)


def _words(text: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9\s]", " ", text.lower()).split())


def _matches_platform(href: str, slug: str) -> bool:
    """
    True when the href contains the platform slug as a full path segment.
    Segment (not substring) matching keeps "nintendo-switch" from matching
    "nintendo-switch-2" URLs.
    """
    return slug in [seg for seg in href.split("?")[0].split("/") if seg]


def _read_pvp_web(container) -> float | None:
    """The official web price from a pre-order page's `.buy--info` line."""
    info = container.locator(".buy--info")
    if info.count() == 0:
        return None

    # text_content(), not inner_text(): the container renders a second, hidden
    # copy of the buy box for narrow viewports, and inner_text() returns "" for
    # a hidden node. The pattern tolerates the raw node's newlines and padding.
    match = PVP_WEB_PATTERN.search(info.first.text_content(timeout=5000) or "")
    if not match:
        return None

    return extract_price(match.group(1))


def _read_buy_price(container) -> float | None:
    """The price from the `.buy--price` block of a normal, on-sale page."""
    buy_price = container.locator(".buy--price").first
    if buy_price.count() == 0:
        return None

    integer = buy_price.locator(".int")
    if integer.count() == 0:
        return None

    int_part = integer.first.evaluate(_OWN_TEXT_JS)
    if not int_part:
        return None

    decimal = buy_price.locator(".decimal")
    decimal_part = ""
    if decimal.count() > 0:
        # decimal_part is "'99" — strip the apostrophe separator. text_content()
        # for the same hidden-copy reason as above; dropping the decimals
        # silently would report 69 € for a 69,99 € game.
        decimal_part = (decimal.first.text_content(timeout=5000) or "").strip()
        decimal_part = decimal_part.lstrip("'").lstrip(",").lstrip(".").strip()

    price_str = f"{int_part}.{decimal_part}" if decimal_part else int_part

    return extract_price(price_str)


def read_game_price(page) -> float | None:
    """Read the current price from an already-loaded game.es product page.

    Shared with shops/game.py so the resolver's cheapest-wins tie-break compares
    the same number the scraper will later store — it used to read the
    reservation deposit, which undercuts every real price and made pre-order
    listings win the tie-break outright.
    """
    container = page.locator(QUICK_CONTAINER).first
    if container.count() == 0:
        return None

    if page.locator(RESERVE_CONTAINER).count() > 0:
        # `.buy--price` is the deposit here, so a reserve page with no readable
        # PVP WEB has no price to report. Returning None (product shows as
        # unavailable) beats reporting a 3 € deposit as if it were the price.
        return _read_pvp_web(container)

    return _read_buy_price(container)


def resolve_game_product_url(search_url: str, platform: str | None = None):
    query = search_url.split("text=")[-1]
    query = unquote_plus(query)

    query_words = _words(query)

    # game.es titles say "PLAYSTATION 5", never "PS5", so the platform can't be
    # scored as plain text — it's used as a hard filter on the URL slug instead.
    platform_slug = PLATFORM_SLUGS.get(platform.lower().strip()) if platform else None
    if platform and not platform_slug:
        query_words |= _words(platform)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=resolve_headless())
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.goto(BASE_URL, wait_until="domcontentloaded")

        # Accept cookies
        try:
            page.locator('button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll').click(timeout=8000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        # Type in the search box to trigger autocomplete
        try:
            page.locator('input#searchinput').click(timeout=5000)
            page.locator('input#searchinput').fill(query)
            page.wait_for_timeout(2000)
        except PlaywrightTimeout:
            print("[Game] Search input not found.")
            browser.close()
            return None

        # Wait for autocomplete results
        try:
            page.wait_for_selector('a.ui-search-menu-item-wrapper', timeout=10000)
        except PlaywrightTimeout:
            print("[Game] Autocomplete results did not appear.")
            browser.close()
            return None

        items = page.locator('a.ui-search-menu-item-wrapper').all()[:10]

        # Step 1 — score all non-used candidates of the requested platform
        candidates = []  # (score, href, title)
        first_href = None
        off_platform = 0

        for item in items:
            try:
                title = item.inner_text(timeout=2000).strip()
                href = item.get_attribute("href", timeout=2000)
                if not href:
                    continue

                if first_href is None:
                    first_href = href

                if _is_used(title) or _is_digital(title):
                    continue

                if platform_slug and not _matches_platform(href, platform_slug):
                    off_platform += 1
                    continue

                # Titles are "<name> - <PLATFORM>"; score only the name part so the
                # platform label doesn't inflate the score of every candidate.
                title_words = _words(title.split(" - ")[0])
                matched = len(query_words & title_words)
                extra = len(title_words - query_words)
                # Extra words are a penalty: it keeps "Edición Coleccionista" and
                # "Legacy Edition" from tying with the plain edition we asked for.
                candidates.append((matched - extra, href, title))

            except Exception:
                continue

        if not candidates and off_platform:
            browser.close()
            print(f"[Game] No {platform} results among the autocomplete items.")
            return None

        if not candidates:
            browser.close()
            result = (first_href if first_href.startswith("http") else f"{BASE_URL}{first_href}") if first_href else None
            print(f"[Game] No scored candidates — fallback: {result}")
            return result

        # Step 2 — keep only the top-scoring candidates
        max_score = max(c[0] for c in candidates)
        top_candidates = [c for c in candidates if c[0] == max_score]

        if len(top_candidates) == 1:
            browser.close()
            href = top_candidates[0][1]
            result = href if href.startswith("http") else f"{BASE_URL}{href}"
            print(f"[Game] Resolved (single top): {result}")
            return result

        # Step 3 — visit each top candidate and read its price; pick cheapest.
        # This only works because read_game_price() reports a pre-order page's
        # real PVP WEB rather than its reservation deposit: a 3,00 € deposit
        # undercuts every genuine price, so reserve listings used to win the
        # tie-break outright (see the 007 First Light bug in docs/AI/handoff.md).
        best_href = None
        best_price = float("inf")

        for _, href, title in top_candidates:
            full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
            try:
                page.goto(full_url, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector(PRICE_SELECTOR, state="attached", timeout=10000)
                except PlaywrightTimeout:
                    pass
                price = read_game_price(page)
                if price is not None and price < best_price:
                    best_price = price
                    best_href = full_url
            except Exception as e:
                print(f"[Game]   Price read error for {full_url}: {e}")

        browser.close()

        result = best_href or (
            top_candidates[0][1] if top_candidates[0][1].startswith("http")
            else f"{BASE_URL}{top_candidates[0][1]}"
        )
        return result
