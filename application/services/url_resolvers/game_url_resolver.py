# services/url_resolvers/game_url_resolver.py

import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from application.config.runtime_config import resolve_headless
from application.services.url_resolvers.resolution import (
    is_digital,
    is_used,
    normalize_words,
    not_found,
    only_used,
    resolved,
    search_failed,
    title_match_ratio,
    MIN_TITLE_MATCH_RATIO,
)
from application.shops.price_utils import extract_price
from urllib.parse import quote, unquote_plus

BASE_URL = "https://www.game.es"

# The full search results page — NOT the header autocomplete this resolver used
# to read. Three reasons the dropdown had to go:
#   * it pads short result lists with unrelated best-sellers, which is how a
#     search for Ninja Gaiden Ragebound came back with Minecraft;
#   * it hides second-hand listings, so "GAME only has it seminuevo" was
#     indistinguishable from "GAME does not have it";
#   * it is capped at ~10 suggestions, so a real match can simply fall off.
# `/buscar?q=` (redirects to `/buscar/<slug>`) is the page a shopper actually
# sees. Note the shape: `/buscar?text=`, which url_search_service builds for
# display, silently renders the home page instead.
RESULTS_URL = f"{BASE_URL}/buscar?q={{slug}}"

# The grid, then one result card. The grid also renders for a search with no
# hits — game.es fills it with ~8 loosely related products rather than showing
# an empty state — so its presence proves the page loaded, never that the
# product was found. Only the relevance floor can tell those apart.
# `search-completed` is the class game.es adds once the list has finished
# hydrating. Waiting on the bare `div.search-list` returns while the grid still
# holds a single empty skeleton card, so every attribute read comes back None
# and a stocked product reads as absent (README § "Scraper Waits").
RESULTS_SELECTOR = "div.search-list.search-completed"
CARD_SELECTOR = "div.search-item"

# Second guard on the same race: a card whose link already carries its href.
CARD_READY_SELECTOR = f"{CARD_SELECTOR} a.figure[href]"

# Carries the product URL plus a clean, un-truncated title in
# `data-list-item-name` — the rendered <h3> is subject to CSS ellipsis.
CARD_LINK_SELECTOR = "a.figure"

# game.es slugs the query with hyphens; spaces resolve to an empty result page.
_SLUG_SEPARATORS = re.compile(r"[^\w]+", re.UNICODE)

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


def _slugify(text: str) -> str:
    """'Ninja Gaiden Ragebound' → 'ninja-gaiden-ragebound'.

    `\\w` rather than `[a-z0-9]` so accented letters survive: game.es keeps them
    in its own slugs ('.../tomodachi-life-una-vida-de-ensueño/256491').
    """
    return _SLUG_SEPARATORS.sub("-", text.lower()).strip("-")


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

    query_words = normalize_words(query)

    # game.es titles say "PLAYSTATION 5", never "PS5", so the platform can't be
    # scored as plain text — it's used as a hard filter on the URL slug instead.
    platform_slug = PLATFORM_SLUGS.get(platform.lower().strip()) if platform else None
    if platform and not platform_slug:
        query_words |= normalize_words(platform)

    with sync_playwright() as p:
        # channel="chromium": the full browser, not the lightweight "headless
        # shell" Playwright launches by default for headless=True. Same defect
        # BrowserManager works around for El Corte Inglés — the shell renders
        # this search page with a single, attribute-less card, so a product
        # that is plainly there reads as absent. That matters more here than in
        # a scraper: a false "not found" is now terminal, and would stop the
        # shop being tracked at all.
        browser = p.chromium.launch(headless=resolve_headless(), channel="chromium")
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.goto(BASE_URL, wait_until="domcontentloaded")

        # Accept cookies on the home page before searching: the consent overlay
        # covers the results grid, and the choice then rides on the context.
        try:
            page.locator('button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll').click(timeout=8000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        try:
            page.goto(RESULTS_URL.format(slug=quote(_slugify(query))),
                      wait_until="domcontentloaded")
            # state="attached": the first card can sit outside the viewport, and
            # the default "visible" would time out on a page that rendered fine.
            page.wait_for_selector(RESULTS_SELECTOR, state="attached", timeout=20000)
            page.wait_for_selector(CARD_READY_SELECTOR, state="attached", timeout=10000)
        except PlaywrightTimeout:
            print("[Game] Search results did not render.")
            browser.close()
            return search_failed()

        items = page.locator(CARD_SELECTOR).all()[:20]

        # Step 1 — score all new, physical candidates of the requested platform
        candidates = []  # (score, href, title)
        used_matches = []  # titles of the right product, but second-hand

        for item in items:
            try:
                link = item.locator(CARD_LINK_SELECTOR).first
                href = link.get_attribute("href", timeout=2000)
                title = (link.get_attribute("data-list-item-name", timeout=2000) or "").strip()
                if not href or not title:
                    continue

                # Unlike the autocomplete, results-page titles carry no platform
                # suffix — what follows the dash is an edition ("- Seminuevo",
                # "- Edición Coleccionista"). So the whole title is scored, and
                # the `extra` penalty below keeps those editions from tying with
                # the plain one that was asked for.
                on_platform = not platform_slug or _matches_platform(href, platform_slug)
                relevant = title_match_ratio(query, title) >= MIN_TITLE_MATCH_RATIO

                if is_used(title):
                    # Remembered rather than dropped: when these are the *only*
                    # matches, the honest answer is "GAME has it, but only
                    # second-hand" — not "not found", and certainly not the
                    # URL of whatever unrelated game the autocomplete padded
                    # the list with.
                    if relevant and on_platform:
                        used_matches.append(title)
                    continue

                if is_digital(title):
                    continue

                if not on_platform or not relevant:
                    continue

                title_words = normalize_words(title)
                matched = len(query_words & title_words)
                extra = len(title_words - query_words)
                # Extra words are a penalty: it keeps "Edición Coleccionista" and
                # "Legacy Edition" from tying with the plain edition we asked for.
                candidates.append((matched - extra, href, title))

            except Exception:
                continue

        if not candidates:
            browser.close()
            if used_matches:
                print(f"[Game] Only second-hand copies: {used_matches[0]}")
                return only_used()
            # The autocomplete answered, so the shop has been heard from: it
            # pads short result lists with loosely related games, and none of
            # them cleared the relevance floor.
            print(f"[Game] No new {platform} copy matching '{query}'.")
            return not_found()

        # Step 2 — keep only the top-scoring candidates
        max_score = max(c[0] for c in candidates)
        top_candidates = [c for c in candidates if c[0] == max_score]

        if len(top_candidates) == 1:
            browser.close()
            href = top_candidates[0][1]
            result = href if href.startswith("http") else f"{BASE_URL}{href}"
            print(f"[Game] Resolved (single top): {result}")
            return resolved(result)

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

        # Every fallback here is still one of the top-scoring candidates, so
        # it has already cleared the relevance floor — this only decides which
        # of several equally good matches wins when no price could be read.
        result = best_href or (
            top_candidates[0][1] if top_candidates[0][1].startswith("http")
            else f"{BASE_URL}{top_candidates[0][1]}"
        )
        return resolved(result)
