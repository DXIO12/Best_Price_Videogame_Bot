# services/url_resolvers/xtralife_url_resolver.py

import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from application.config.logger import get_logger
from application.config.runtime_config import resolve_headless
from application.services.url_resolvers.resolution import (
    is_used,
    is_bundle,
    not_found,
    only_used,
    platform_matches_title,
    resolved,
    search_failed,
    slug_as_text,
    ranking_score,
    title_match_ratio,
    best_relevance,
    is_best_available_match,
    MIN_TITLE_MATCH_RATIO,
)
from urllib.parse import unquote_plus

log = get_logger("resolver.xtralife")

BASE_URL = "https://www.xtralife.com"

CARD_SELECTOR = 'a.flex.ng-star-inserted[href*="/producto/"]'

# The card's text block: a bold span with the product name, then a second span
# with the platform and edition ("Switch 2 Edición Estándar").
TITLE_WRAPPER_SELECTOR = "div.titleWrapper"
TITLE_SELECTOR = "div.titleWrapper span.fontBold"

# Xtralife lists the download code beside the boxed copy, at a different price
# and under the same name — "Hollow Knight Silksong / Xbox Series Edición
# Estándar, 19,99 €" is the digital one. The badge is the only thing that tells
# them apart, since neither the title nor the URL says "digital".
DIGITAL_FLAG_SELECTOR = "div.digitalFlag"

# The second span also names the department, so a search for a game that has
# tie-in merchandise ("Hollow Knight: El Libro Hueco — Libros Edición Estándar",
# "Figura Skull Knight Berserk Figma — Figuras Edición Estándar") can be kept
# out without depending on the "Juegos" quick filter having taken effect.
NON_GAME_CATEGORIES = ("libros", "figuras", "merchandising", "ropa", "comics", "cómics")

def _read_card_price(card) -> float | None:
    """
    Extract price from a product card.
    HTML: div.ctaWrapper > div.content > span.fontBold ("56,95") + span ("€")
    € is a sibling span so we read the whole div.content text.
    """
    try:
        text = card.locator('div.ctaWrapper div.content').first.inner_text(timeout=2000).strip()
        match = re.search(r'\d+[,.]\d+', text)
        if match:
            return float(match.group().replace(",", "."))
    except Exception:
        pass
    return None


def _read_card(card) -> tuple[str, str, str, bool] | None:
    """(href, title, subtitle, is_digital) for one card, or None if unreadable.

    The subtitle is whatever `div.titleWrapper` holds beyond the bold title —
    that is where the platform and the department live.
    """
    try:
        href = card.get_attribute("href", timeout=2000)
        if not href:
            return None

        title_node = card.locator(TITLE_SELECTOR).first
        if not title_node.count():
            return None
        title = (title_node.inner_text(timeout=2000) or "").strip()
        if not title:
            return None

        wrapper = card.locator(TITLE_WRAPPER_SELECTOR).first
        whole = (wrapper.inner_text(timeout=2000) or "").strip() if wrapper.count() else title
        subtitle = whole.replace(title, "", 1).strip()

        digital = card.locator(DIGITAL_FLAG_SELECTOR).count() > 0

        return href, title, subtitle, digital
    except Exception:
        return None


def resolve_xtralife_product_url(search_url: str, platform: str | None = None):
    query = unquote_plus(search_url.split("q=")[-1])

    with sync_playwright() as p:
        # channel="chromium" — full browser, not the headless shell (2026-08-21).
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
        page.wait_for_timeout(3000)

        # Accept cookies
        try:
            page.get_by_text("Permitir todo").click(timeout=8000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        # Search
        try:
            search_box = page.locator('input[placeholder="Buscar"]')
            search_box.click(timeout=5000)
            search_box.fill(query)
            search_box.press("Enter")
            page.wait_for_timeout(3000)
        except PlaywrightTimeout:
            log.warning("Search input not found.")
            browser.close()
            return search_failed()

        # Click "Juegos" quick filter
        try:
            juegos_filter = page.locator('quick-filter').filter(has_text="Juegos").first
            juegos_filter.scroll_into_view_if_needed(timeout=5000)
            juegos_filter.click(timeout=5000)
            page.wait_for_timeout(2000)
        except Exception as e:
            log.debug(f"Juegos filter not applied: {e}")

        # The shop's Plataforma facet is deliberately NOT applied. Letting
        # Xtralife pre-filter blinds the name check below: with only Switch
        # cards on the page, a search for "Hollow Knight Silksong" sees plain
        # "Hollow Knight" as the best match available and takes it, while the
        # Silksong cards it should have lost to sit one facet away, unread.
        # Every card states its own platform in the subtitle, so filtering here
        # loses nothing and removes a flaky UI interaction.

        # Grab product cards
        try:
            page.wait_for_timeout(2000)
            page.wait_for_selector(CARD_SELECTOR, state="attached", timeout=10000)
            cards = page.locator(CARD_SELECTOR).all()[:40]
        except PlaywrightTimeout:
            # Nothing rendered. Xtralife shows no empty state this resolver can
            # read, so the honest answer is "we do not know" — retry.
            log.warning(f"No result cards for '{query}'.")
            browser.close()
            return search_failed()

        # Pass 1 — read every card before any filtering, so the name match
        # can be judged against the whole page (see is_best_available_match).
        rows = []
        for card in cards:
            read = _read_card(card)
            if read:
                rows.append(read)

        browser.close()

    best_ratio = best_relevance(query, [title for _, title, _, _ in rows])

    # Pass 2 — physical, on-platform, and as good a name match as any card here.
    candidates = []    # (score, href, title)
    used_matches = []

    for href, title, subtitle, digital in rows:
        if digital:
            continue

        # A pack or a console bundle contains the game but is not the game.
        if is_bundle(title):
            continue

        lowered_subtitle = subtitle.lower()
        if any(category in lowered_subtitle for category in NON_GAME_CATEGORIES):
            continue

        # The platform is in the subtitle; the URL slug repeats it, and is used
        # when the subtitle could not be read. Both go through the shared
        # matcher so "switch 2" never answers a "switch" search.
        platform_text = subtitle if subtitle else slug_as_text(href)
        on_platform = platform_matches_title(platform, platform_text)
        ratio = title_match_ratio(query, title)
        relevant = (
            ratio >= MIN_TITLE_MATCH_RATIO
            and is_best_available_match(ratio, best_ratio)
        )

        if is_used(f"{title} {subtitle}"):
            if relevant and on_platform:
                used_matches.append(title)
            continue

        if not on_platform or not relevant:
            continue

        # The old code took `best_href or first_href` starting from
        # `best_score = -1`, so a card sharing zero words with the query still
        # won. The floor above stops that; the page-wide gate is what stops
        # plain "Hollow Knight" answering a search for "Hollow Knight Silksong".
        candidates.append((ranking_score(query, title), href, title))

    if not candidates:
        if used_matches:
            log.debug(f"Only second-hand copies: {used_matches[0]}")
            return only_used()
        log.debug(f"No {platform} copy matching '{query}'.")
        return not_found()

    best = max(candidates)
    href = best[1]
    url = href if href.startswith("http") else f"{BASE_URL}{href}"
    log.debug(f"Resolved: {url} ({best[2]})")
    return resolved(url)
