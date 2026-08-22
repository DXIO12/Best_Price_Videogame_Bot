# services/url_resolvers/todoconsolas_url_resolver.py

import re
from urllib.parse import urlparse, parse_qs, unquote_plus

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from application.config.runtime_config import resolve_headless
from application.services.url_resolvers.resolution import (
    title_match_ratio,
    MIN_TITLE_MATCH_RATIO,
)

BASE_URL = "https://www.todoconsolas.com"

# TodoConsolas keeps the platform in the product URL category slug
# ("/juegos-ps5/203177-hollow_knight__silksong_ps5_sp_...html"), which is a far
# safer discriminator than the title: it never confuses "Switch" with
# "Switch 2". Internal platform name (lowercased) → category slug.
PLATFORM_SLUGS = {
    "ps5":           "juegos-ps5",
    "ps4":           "juegos-ps4",
    "switch 2":      "juegos-switch-2",
    "switch":        "juegos-switch",
    "xbox series x": "juegos-xbox-series",
    "pc":            "juegos-pc",
}

# Facet panels of the search overlay, addressed by their visible header, and the
# option we want inside each. The shop offers a filter only when it has matching
# stock, so a missing "Nuevo" means there is no new copy of that product.
REGION_FACET = "Regiones de juegos"
REGION_FILTER = "PAL/ES"
CONDITION_FACET = "Estado"
NEW_FILTER = "Nuevo"

# Region as printed at the end of a product title — "Hollow Knight PS4 (SP)".
# Used as a safety net once the PAL/ES facet is applied, and as the only region
# signal for the products that carry no region facet at all.
PAL_ES_REGIONS = {"SP", "ES", "EU", "PAL", "PAL/ES"}

# A parenthesised suffix that is not one of these is not a region marker at all
# (e.g. "Nintendo Switch OLED (Sin JoyCon)") and must not reject the card.
KNOWN_REGIONS = PAL_ES_REGIONS | {
    "UK", "USA", "US", "JP", "JAP", "DE", "FR", "IT", "PT", "NL",
    "ASIA", "KOR", "AUS", "CAN", "RU",
}

# The search overlay is a Vue app rendered inside a shadow root, so its markup
# is invisible to document.querySelectorAll — every read has to go through
# Playwright locators, which do pierce open shadow roots.
RESULT_SELECTOR = '[data-test="result"]'
RESULT_LINK_SELECTOR = '[data-test="result-link"]'
FACET_SELECTOR = '.x-mot-facet'
FILTER_SELECTOR = '[data-test="filter"]'


def _title_region(title: str) -> str | None:
    """Return the region code a title ends with, or None when it has no marker."""
    match = re.search(r"\(([^()]{1,10})\)\s*$", title.strip())
    if not match:
        return None

    region = match.group(1).strip().upper()
    return region if region in KNOWN_REGIONS else None


def _card_slug(href: str) -> str:
    """Category slug of a product URL: '.../juegos-ps5/203177-...html' → 'juegos-ps5'."""
    path = urlparse(href).path.strip("/")
    return path.split("/")[0] if path else ""


def _apply_filter(page, facet_label: str, option_label: str) -> bool:
    """
    Tick one option of a facet panel in the left-hand menu.

    Returns False when the shop does not offer that option for this search —
    it only renders filters it has stock for, so a missing option is an answer,
    not an error.
    """
    facet = page.locator(FACET_SELECTOR).filter(has_text=facet_label).first
    if not facet.count():
        print(f"[TodoConsolas] '{facet_label}' filter not offered for this search.")
        return False

    option = facet.locator(FILTER_SELECTOR).filter(has_text=option_label).first
    if not option.count():
        print(f"[TodoConsolas] '{facet_label} → {option_label}' not available.")
        return False

    try:
        option.click(timeout=8000)
        page.wait_for_timeout(3000)
        return True
    except Exception as e:
        print(f"[TodoConsolas] Could not tick '{option_label}': {e}")
        return False


def _read_cards(page) -> list[dict]:
    """Read title + URL off every result card currently rendered."""
    cards = []
    for card in page.locator(RESULT_SELECTOR).all():
        try:
            # The title is mirrored into data-wysiwyg-title, which saves a
            # second locator round-trip per card.
            title = card.get_attribute("data-wysiwyg-title", timeout=2000) or ""
            href = card.locator(RESULT_LINK_SELECTOR).first.get_attribute(
                "href", timeout=2000
            ) or ""
        except Exception:
            continue

        if href and title:
            cards.append({"title": title.strip(), "href": href})

    return cards


def _pick_best_card(cards: list[dict], query: str, platform: str | None) -> str | None:
    """
    Choose the product URL that best matches the request.

    The facets already narrowed the list to PAL/ES (and to new copies when the
    shop had any), so this mostly enforces the platform — there is no platform
    facet, and a "hollow knight" search returns PS4/PS5/Switch/Switch 2 side by
    side. Cards are discarded when the URL category is not the requested
    platform's, when the title advertises a non-PAL/ES region, or when the title
    shares too few words with the product name.

    What survives is ranked by explicit PAL/ES first, then title similarity,
    then the shop's own relevance order.
    """
    wanted_slug = PLATFORM_SLUGS.get(platform.strip().lower()) if platform else None

    scored = []
    for position, card in enumerate(cards):
        href, title = card["href"], card["title"]

        if wanted_slug and _card_slug(href) != wanted_slug:
            continue

        region = _title_region(title)
        if region is not None and region not in PAL_ES_REGIONS:
            continue

        ratio = title_match_ratio(query, title)
        if ratio < MIN_TITLE_MATCH_RATIO:
            continue

        scored.append((1 if region in PAL_ES_REGIONS else 0, ratio, -position, href))

    if not scored:
        return None

    return max(scored)[3]


def resolve_todoconsolas_product_url(search_url: str, platform: str | None = None):
    query = parse_qs(urlparse(search_url).query).get("mot_q", [""])[0]
    if not query:
        query = unquote_plus(search_url.split("mot_q=")[-1])

    with sync_playwright() as p:
        # Same reason as BrowserManager: the lightweight "headless shell" does
        # not reliably boot the shop's shadow-DOM search app.
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

        # Accept cookies — the banner is intermittent, but while it is up its
        # overlay swallows every click on the filters.
        try:
            page.locator('.cookiesplus-accept').first.click(timeout=6000)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        # Type the product name + platform in the header search box; Enter opens
        # the search overlay at /?mot_q=<query>.
        try:
            search_box = page.locator('input.spr-query').first
            search_box.click(timeout=8000)
            search_box.fill(query)
            search_box.press("Enter")
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"[TodoConsolas] Search box not usable ({e}), opening the search URL.")
            try:
                page.goto(search_url, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
            except Exception as goto_error:
                print(f"[TodoConsolas] Could not open the search page: {goto_error}")
                browser.close()
                return None

        try:
            page.wait_for_selector(RESULT_SELECTOR, timeout=20000)
        except PlaywrightTimeout:
            print(f"[TodoConsolas] No results for '{query}'.")
            browser.close()
            return None

        # Restrict to the Spanish edition, then to new copies. Second-hand is
        # only accepted when the shop offers no new one.
        if not _apply_filter(page, REGION_FACET, REGION_FILTER):
            print(f"[TodoConsolas] No PAL/ES stock for '{query}'.")
            browser.close()
            return None

        if not _apply_filter(page, CONDITION_FACET, NEW_FILTER):
            print("[TodoConsolas] No new copy, falling back to second-hand.")

        cards = _read_cards(page)
        browser.close()

    href = _pick_best_card(cards, query, platform)
    if not href:
        print(f"[TodoConsolas] No match for '{query}' on {platform}.")
        return None

    return href if href.startswith("http") else f"{BASE_URL}{href}"
