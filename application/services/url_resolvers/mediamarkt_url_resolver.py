# services/url_resolvers/mediamarkt_url_resolver.py

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from config.runtime_config import resolve_headless
from services.url_resolvers.resolution import (
    is_used,
    not_found,
    only_used,
    platform_matches_title,
    resolved,
    search_failed,
    title_match_ratio,
    MIN_TITLE_MATCH_RATIO,
)
from urllib.parse import urlparse, parse_qs, unquote_plus

BASE_URL = "https://www.mediamarkt.es"

# The search results grid. Its presence is what separates "the shop answered
# and has nothing" from "the page never rendered" — the two outcomes this
# resolver has to report differently.
RESULTS_SELECTOR = '[data-test="mms-search-srp-productlist"]'

# One result card. The old selector,
# `a[data-test="mms-router-link-product-list-item-link"]`, no longer exists in
# MediaMarkt's markup: every search timed out waiting for a node that is never
# emitted, burned all six retries and reported the product as unresolvable even
# though the search page itself loaded fine and the product was right there.
# Anchoring on the card and reading the link out of it survives a renamed
# anchor, because the product URL shape is the stable part.
CARD_SELECTOR = 'article[data-test="mms-product-card"]'
CARD_LINK_SELECTOR = 'a[href*="/product/"]'
CARD_TITLE_SELECTOR = '[data-test="product-title"]'


def resolve_mediamarkt_product_url(search_url: str, platform: str | None = None):
    query = parse_qs(urlparse(search_url).query).get("query", [""])[0]
    if not query:
        query = unquote_plus(search_url.split("query=")[-1])

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

        # Straight to the search URL instead of loading the home page, clicking
        # the search box, typing and pressing Enter. Four fewer things to break,
        # and get_search_url() already built the exact URL that flow produced.
        page.goto(search_url, wait_until="domcontentloaded")

        # Accept cookies — while the consent layer is up it swallows clicks and
        # holds back the grid.
        try:
            page.locator('button#pwa-consent-layer-accept-all-button').click(timeout=8000)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        try:
            page.wait_for_selector(RESULTS_SELECTOR, state="attached", timeout=20000)
        except PlaywrightTimeout:
            print("[MediaMarkt] Search results grid did not render.")
            browser.close()
            return search_failed()

        # The grid appears before its cards are hydrated.
        try:
            page.wait_for_selector(CARD_SELECTOR, state="attached", timeout=10000)
        except PlaywrightTimeout:
            # Grid rendered with no cards in it — that is the shop's answer.
            print(f"[MediaMarkt] No results for '{query}'.")
            browser.close()
            return not_found()

        href = None
        used_matches = []

        for card in page.locator(CARD_SELECTOR).all():
            try:
                title = card.locator(CARD_TITLE_SELECTOR).first.inner_text(
                    timeout=3000
                ).strip()
            except Exception:
                continue

            # Titles read "Juego Nintendo Switch Ninja Gaiden Ragebound,
            # Acción", so the platform is only ever part of a longer sentence —
            # matching on it alone (the previous behaviour) accepts every game
            # for that console.
            if title_match_ratio(query, title) < MIN_TITLE_MATCH_RATIO:
                continue

            if not platform_matches_title(platform, title):
                continue

            if is_used(title):
                used_matches.append(title)
                continue

            try:
                href = card.locator(CARD_LINK_SELECTOR).first.get_attribute(
                    "href", timeout=3000
                )
            except Exception:
                continue

            if href:
                break

        browser.close()

        if not href:
            if used_matches:
                print(f"[MediaMarkt] Only second-hand copies: {used_matches[0]}")
                return only_used()
            print(f"[MediaMarkt] '{query}' not sold for {platform}.")
            return not_found()

        return resolved(href if href.startswith("http") else f"{BASE_URL}{href}")
