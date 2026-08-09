# services/url_resolvers/game_url_resolver.py

import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from config.runtime_config import resolve_headless
from urllib.parse import unquote_plus

BASE_URL = "https://www.game.es"

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


def _read_game_price(page) -> float | None:
    """Read the new price from a game.es product page."""
    try:
        buy_price = page.locator(".buy--price").first
        int_part = buy_price.locator(".int").evaluate(
            """el => {
                let text = '';
                for (const node of el.childNodes) {
                    if (node.nodeType === Node.TEXT_NODE) text += node.textContent;
                }
                return text.trim();
            }"""
        )
        decimal_part = buy_price.locator(".decimal").inner_text().strip()
        decimal_part = decimal_part.lstrip("'").lstrip(",").lstrip(".").strip()
        if not int_part:
            return None
        price_str = f"{int_part}.{decimal_part}" if decimal_part else int_part
        return float(price_str.replace(",", "."))
    except Exception:
        return None


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

        # Step 3 — visit each top candidate and read its price; pick cheapest
        best_href = None
        best_price = float("inf")

        for _, href, title in top_candidates:
            full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
            try:
                page.goto(full_url, wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
                price = _read_game_price(page)
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
