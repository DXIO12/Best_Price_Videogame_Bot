# services/url_resolvers/amazon_url_resolver.py

import re
from urllib.parse import parse_qs, unquote_plus, urlencode, urlparse, urlunparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from application.config.logger import get_logger
from application.config.runtime_config import resolve_headless
from application.services.url_resolvers.resolution import (
    is_digital,
    is_used,
    is_bundle,
    not_found,
    only_used,
    mentions_any_platform,
    platform_matches_title,
    resolved,
    search_failed,
    ranking_score,
    title_match_ratio,
    best_relevance,
    is_best_available_match,
    MIN_TITLE_MATCH_RATIO,
)

log = get_logger("resolver.amazon")

BASE_URL = "https://www.amazon.es"

# One search-result tile. Amazon marks sponsored tiles with the same attribute,
# which is exactly why the relevance and platform tests below cannot be skipped:
# this resolver used to take `.first` unconditionally, so whatever Amazon chose
# to put at position one became the tracked URL.
RESULT_SELECTOR = '[data-component-type="s-search-result"]'

# The tile's own title. `h2` carries the full, un-truncated product name — the
# same string a shopper reads — so it is what gets scored.
TITLE_SELECTOR = "h2"

# Amazon has renamed the results anchor repeatedly; each of these has been the
# working one at some point. The `/dp/<ASIN>` shape inside the href is the part
# that never changes, and `_clean_url` is what depends on it.
LINK_SELECTORS = (
    "h2 a.a-link-normal",
    "a.a-link-normal.s-underline-text",
    "h2 a",
    'a.s-line-clamp-2',
    '[data-cy="title-recipe"] a',
)

# Amazon serves the English storefront under a `/-/en/` path prefix, and a
# headless context lands there often enough to matter. Storing that URL means
# every later scrape reads the English page instead of the Spanish one, so the
# prefix is stripped and the canonical es-ES path kept.
_LOCALE_PREFIX = re.compile(r"^/-/[a-z]{2}/")

_ASIN = re.compile(r"/dp/([A-Z0-9]{10})")

# Amazon's search rejects a percent-encoded colon outright: `?k=Onimusha%3A+Way
# +of+the+Sword+PS5` renders "Lo sentimos. Se ha producido un error al intentar
# procesar tu solicitud" with zero result tiles, while the identical query
# without the colon returns 24. Every product whose name carries one — three of
# them in the current catalogue ("Onimusha: Way of the Sword", "Tomodachi Life:
# Una vida de ensueño", "MARVEL Tōkon: Fighting Souls") — therefore looked like
# a dead search page and burned the whole retry ladder for nothing.
#
# Stripped here rather than in url_search_service.build_search_query: that
# builder feeds every shop, and the others handle the colon fine (game.es
# slugifies it away, the rest pass it through their own search boxes).
_QUERY_NOISE = re.compile(r"[:;]+")


def _sanitise_search_url(search_url: str) -> tuple[str, str]:
    """(url, query) with the characters Amazon's search chokes on removed."""
    parts = urlparse(search_url)
    params = parse_qs(parts.query)

    raw = params.get("k", [""])[0]
    cleaned = re.sub(r"\s+", " ", _QUERY_NOISE.sub(" ", raw)).strip()
    if not cleaned:
        return search_url, raw

    params["k"] = [cleaned]
    return urlunparse(parts._replace(query=urlencode(params, doseq=True))), cleaned


def clean_amazon_url(href: str) -> str | None:
    """Reduce a search-result href to a stable `<slug>/dp/<ASIN>` product URL.

    The slug is kept rather than reduced to a bare `/dp/<ASIN>`: it is what
    makes a stored URL auditable at a glance (and by the word-overlap scan that
    found the two wrong rows this work started from).
    """
    match = _ASIN.search(href)
    if not match:
        return None

    path = urlparse(href).path if href.startswith("http") else href.split("?")[0]
    slug = _LOCALE_PREFIX.sub("/", path).split("/dp/")[0].strip("/")

    asin = match.group(1)
    return f"{BASE_URL}/{slug}/dp/{asin}" if slug else f"{BASE_URL}/dp/{asin}"


def _card_href(card) -> str | None:
    for selector in LINK_SELECTORS:
        link = card.locator(selector).first
        if not link.count():
            continue
        try:
            href = link.get_attribute("href", timeout=2000)
        except Exception:
            continue
        if href:
            return href
    return None


def resolve_amazon_product_url(search_url: str, platform: str | None = None):
    search_url, query = _sanitise_search_url(search_url)
    query = unquote_plus(query)

    with sync_playwright() as p:
        # channel="chromium": the full browser, not the headless shell, which
        # renders partial DOM on shop pages and would make a stocked product
        # read as absent — now a terminal verdict (see the 2026-08-21 session).
        browser = p.chromium.launch(headless=resolve_headless(), channel="chromium")
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.goto(search_url, wait_until="domcontentloaded")

        try:
            page.locator("#sp-cc-accept").click(timeout=5000)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        try:
            # state="attached": tiles below the fold are not "visible", and the
            # default would time out on a page that rendered perfectly well.
            page.wait_for_selector(RESULT_SELECTOR, state="attached", timeout=15000)
        except PlaywrightTimeout:
            log.warning("Search results did not render.")
            browser.close()
            return search_failed()

        cards = page.locator(RESULT_SELECTOR).all()[:20]

        # Pass 1 — read every tile. The platform is deliberately not applied
        # yet: `is_best_available_match` needs to know how well the *whole*
        # page matches the name before any of it is filtered away.
        rows = []  # (title, href)
        for card in cards:
            try:
                if not (card.get_attribute("data-asin", timeout=2000) or "").strip():
                    continue  # not a product tile

                title_node = card.locator(TITLE_SELECTOR).first
                if not title_node.count():
                    continue
                title = (title_node.inner_text(timeout=2000) or "").strip()
                href = _card_href(card)
                if title and href:
                    rows.append((title, href))
            except Exception:
                continue

        browser.close()

    best_ratio = best_relevance(query, [title for title, _ in rows])

    # Pass 2 — keep the new, physical, on-platform tiles that match the name
    # as well as anything on the page.
    candidates = []    # (score, href, title)
    used_matches = []  # right product and platform, but second-hand

    for title, href in rows:
        ratio = title_match_ratio(query, title)
        # Explicit match, or a title that names no console at all. The second
        # case is common on Amazon and must not be discarded — see
        # mentions_any_platform.
        explicit = platform_matches_title(platform, title)
        on_platform = explicit or not mentions_any_platform(title)
        relevant = (
            ratio >= MIN_TITLE_MATCH_RATIO
            and is_best_available_match(ratio, best_ratio)
        )

        if is_used(title):
            # "Amazon has it, but only used" is a different answer to the user
            # than "Amazon does not have it".
            if relevant and on_platform:
                used_matches.append(title)
            continue

        # Amazon lists download codes beside the physical game at a different
        # price; the scraper would then track the wrong one.
        if is_digital(title):
            continue

        # A pack or a console bundle contains the game but is not the game.
        if is_bundle(title):
            continue

        if not on_platform or not relevant:
            continue

        # Explicit platform first, so a listing that says "PS5" outranks one
        # that merely fails to contradict it.
        candidates.append((1 if explicit else 0, ranking_score(query, title), href, title))

    if not candidates:
        if used_matches:
            log.debug(f"Only second-hand copies: {used_matches[0]}")
            return only_used()
        # The grid rendered and every tile was read — Amazon has been heard
        # from, and none of what it offered is this product on this platform.
        log.debug(f"No new {platform} copy matching '{query}'.")
        return not_found()

    best = max(candidates)
    href, title = best[2], best[3]
    url = clean_amazon_url(href if href.startswith("http") else f"{BASE_URL}{href}")
    if not url:
        # A top-scoring card whose href carries no ASIN is a broken read, not
        # an answer about the product.
        log.warning(f"No ASIN in the winning href: {href[:120]}")
        return search_failed()

    log.debug(f"Resolved: {url} ({title})")
    return resolved(url)
