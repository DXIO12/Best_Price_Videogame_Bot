# services/url_resolvers/wakkap_url_resolver.py

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from application.config.logger import get_logger
from application.config.runtime_config import resolve_headless
from application.services.url_resolvers.resolution import (
    is_digital,
    is_used,
    is_bundle,
    not_found,
    only_used,
    platform_matches_title,
    resolved,
    search_failed,
    ranking_score,
    title_match_ratio,
    best_relevance,
    is_best_available_match,
    MIN_TITLE_MATCH_RATIO,
)
from urllib.parse import unquote_plus

log = get_logger("resolver.wakkap")

BASE_URL = "https://wakkap.com/search/filter/on-sale"

# A result tile. It is a plain <div>, not an anchor — the card carries no href
# at all and the shop navigates on click — so the product URL can only be read
# from `page.url` after clicking the one card we chose.
CARD_SELECTOR = "div.cmp-thumbnail-card"

# Every card labels its own platform in a coloured badge ("Switch", "NSW2",
# "PS5", "Xbox Series"). That badge is the shop's own explicit statement and is
# what this resolver filters on. It replaces the platform dropdown as the
# authority: the dropdown was keyed on the GUI's platform names ("ns", "ns2")
# while resolvers are handed the DB's ("Switch", "Switch 2"), so for every
# Nintendo product the lookup missed, no filter was applied, and the blind
# `cards[0].click()` below it returned whatever came first — an Xbox Series
# listing for a Switch search.
CARD_PLATFORM_SELECTOR = "div.tag-name"
CARD_TITLE_SELECTOR = "div.card-info div.title"

# A resolved product lives at /item/<slug>; anything else means the click did
# not land on a product page.
PRODUCT_PATH = "/item/"

# The shop's own platform dropdown is deliberately NOT used. It was keyed on
# the GUI's platform names ("ns", "ns2") while resolvers are handed the DB's
# ("Switch", "Switch 2"), so for every Nintendo product the lookup missed and
# no filter was applied at all — which, with the blind `cards[0].click()` this
# file used to end in, returned an Xbox Series listing for a Switch search.
#
# Fixing the keys is not the right repair. Letting the shop pre-filter by
# platform blinds the name check below: with only Switch cards left on the
# page, a search for "Hollow Knight Silksong" sees plain "Hollow Knight" as the
# best match available and takes it, while the Silksong cards it should have
# been compared against sit one facet away, unread. Reading every platform and
# filtering on the badge keeps that comparison possible, and removes a flaky UI
# interaction at the same time.


def _read_card(card) -> tuple[str, str] | None:
    """(title, platform badge) for one result tile, or None when unreadable."""
    try:
        title_node = card.locator(CARD_TITLE_SELECTOR).first
        if not title_node.count():
            return None
        title = (title_node.inner_text(timeout=2000) or "").strip()
        if not title:
            return None

        badge_node = card.locator(CARD_PLATFORM_SELECTOR).first
        badge = ""
        if badge_node.count():
            badge = (badge_node.inner_text(timeout=2000) or "").strip()

        return title, badge
    except Exception:
        return None


def resolve_wakkap_product_url(search_url: str, platform: str | None = None):
    query = unquote_plus(search_url.split("q=")[-1])

    with sync_playwright() as p:
        # channel="chromium" for the same reason as the other resolvers: the
        # headless shell renders partial DOM, and a card read as empty now
        # produces a terminal NOT_FOUND rather than a harmless retry.
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

        try:
            page.locator("div.cmp-pop div.cmp-button-mini").click(timeout=8000)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        try:
            search_box = page.locator("input.search-box")
            search_box.click(timeout=5000)
            search_box.fill(query)
            search_box.press("Enter")
            page.wait_for_timeout(3000)
        except PlaywrightTimeout:
            log.warning("Search input not found.")
            browser.close()
            return search_failed()

        try:
            page.get_by_text("Filtrar").click(timeout=5000)
            page.wait_for_timeout(1000)
        except Exception:
            pass

        # Narrow to games (drops consoles and accessories).
        try:
            page.locator("div.section-3 div.cmp-dropdown").first.click(timeout=5000)
            page.wait_for_timeout(1000)
            page.locator('div.select-items div.item[value="game"]').first.click(timeout=5000)
            page.wait_for_timeout(1000)
        except Exception as e:
            log.debug(f"Juegos filter not applied: {e}")

        # "Mostrar sólo disponibles"
        try:
            checkbox = page.locator('input[type="checkbox"][name=""]').last
            if not checkbox.is_checked():
                checkbox.click()
            page.wait_for_timeout(1000)
        except Exception:
            pass

        try:
            page.locator("#close-filters").click(timeout=5000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        try:
            page.wait_for_selector(CARD_SELECTOR, state="attached", timeout=10000)
        except PlaywrightTimeout:
            # No grid at all. Wakkap renders no empty-state element we can rely
            # on, so this stays ambiguous and must retry rather than report a
            # terminal "not sold here".
            log.warning(f"No result grid for '{query}'.")
            browser.close()
            return search_failed()

        cards = page.locator(CARD_SELECTOR).all()[:40]

        # Pass 1 — read every tile, platform included but not yet applied.
        rows = []  # (index, title, badge)
        for index, card in enumerate(cards):
            read = _read_card(card)
            if read:
                rows.append((index, read[0], read[1]))

        best_ratio = best_relevance(query, [title for _, title, _ in rows])

        # Pass 2 — the platform badge decides, but only among the cards that
        # match the product name as well as anything else Wakkap returned.
        best = None  # (score, index, title)
        used_matches = []

        for index, title, badge in rows:
            # The badge is the platform; the title is only the product name, so
            # the two are tested separately rather than as one string.
            on_platform = platform_matches_title(platform, badge) if badge else not platform
            ratio = title_match_ratio(query, title)
            relevant = (
                ratio >= MIN_TITLE_MATCH_RATIO
                and is_best_available_match(ratio, best_ratio)
            )

            if is_used(title):
                if relevant and on_platform:
                    used_matches.append(title)
                continue

            if is_digital(title):
                continue

            # A pack or a console bundle contains the game but is not the game:
            # Wakkap lists "Pack Hollow Knight + Silksong" (82,90 €) beside the
            # standalone game (42,90 €), and it matches every query word.
            if is_bundle(title):
                continue

            if not on_platform or not relevant:
                continue

            score = ranking_score(query, title)

            if best is None or score > best[0]:
                best = (score, index, title)

        if best is None:
            browser.close()
            if used_matches:
                log.debug(f"Only second-hand copies: {used_matches[0]}")
                return only_used()
            log.debug(f"No {platform} copy matching '{query}'.")
            return not_found()

        # Only now is a card clicked, and only the winning one — the URL exists
        # nowhere else on the results page.
        try:
            cards[best[1]].click()
            page.wait_for_timeout(3000)
            href = page.url
        except Exception as e:
            log.error(f"Could not open the winning card: {e}")
            browser.close()
            return search_failed()

        browser.close()

    if PRODUCT_PATH not in href:
        log.warning(f"Click did not land on a product page: {href}")
        return search_failed()

    log.debug(f"Resolved: {href} ({best[2]})")
    return resolved(href)
