# services/url_resolvers/pccomponentes_url_resolver.py

from urllib.parse import urlparse, parse_qs, unquote_plus

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

BASE_URL = "https://www.pccomponentes.com"

# Result cards. `data-product-name` mirrors the visible title, which saves a
# locator round-trip per card.
CARD_SELECTOR = 'a[data-testid="normal-link"]'


def resolve_pccomponentes_product_url(search_url: str, platform: str | None = None):
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
        page.goto(search_url, wait_until="domcontentloaded")

        # Accept cookies
        try:
            page.locator('button#cookiesAcceptAll').click(timeout=5000)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        # Wait for the JS-rendered cards rather than sleeping a fixed 5 s: a
        # slow render used to look identical to an empty result set.
        # state="attached" and not the default "visible": the first card in DOM
        # order sits inside a collapsed panel, so waiting for visibility times
        # out on a page that has in fact rendered every one of its results.
        try:
            page.wait_for_selector(CARD_SELECTOR, state="attached", timeout=15000)
        except PlaywrightTimeout:
            # A search with no hits and a search page that never rendered look
            # the same from here, so this stays retryable (see resolution.py).
            print("[PCComponentes] No product cards rendered.")
            browser.close()
            return search_failed()

        cards = page.locator(CARD_SELECTOR).all()

        href = None
        used_matches = []

        for card in cards:
            try:
                product_name = card.get_attribute("data-product-name", timeout=3000)
                if not product_name:
                    continue

                # The name test is what this resolver was missing entirely. It
                # only ever checked that the platform appeared in the title, so
                # "Naruto x Boruto Ultimate Ninja Storm Connections Nintendo
                # Switch" satisfied a search for Ninja Gaiden Ragebound and its
                # URL was saved and scraped from then on.
                if title_match_ratio(query, product_name) < MIN_TITLE_MATCH_RATIO:
                    continue

                if not platform_matches_title(platform, product_name):
                    continue

                if is_used(product_name):
                    used_matches.append(product_name)
                    continue

                href = card.get_attribute("href", timeout=3000)
                if href:
                    break
            except Exception:
                continue

        browser.close()

        if not href:
            if used_matches:
                print(f"[PCComponentes] Only second-hand copies: {used_matches[0]}")
                return only_used()
            # Cards rendered and none of them is the product: the shop has
            # answered, and the answer is that it does not sell it.
            print(f"[PCComponentes] '{query}' not sold for {platform}.")
            return not_found()

        return resolved(href if href.startswith("http") else f"{BASE_URL}{href}")
