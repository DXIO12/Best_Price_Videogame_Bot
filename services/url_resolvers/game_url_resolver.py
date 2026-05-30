# services/url_resolvers/game_url_resolver.py

import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from urllib.parse import unquote_plus

BASE_URL = "https://www.game.es"

USED_KEYWORDS = {"segunda mano", "seminuevo", "usado", "reacondicionado", "segunda-mano"}


def _is_used(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in USED_KEYWORDS)


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

    query_words = set(re.sub(r"[^a-z0-9\s]", "", query.lower()).split())
    if platform:
        query_words |= set(re.sub(r"[^a-z0-9\s]", "", platform.lower()).split())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
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

        # Step 1 — score all non-used candidates
        candidates = []  # (score, href, title)
        first_href = None

        for item in items:
            try:
                title = item.inner_text(timeout=2000).strip()
                href = item.get_attribute("href", timeout=2000)
                if not href:
                    continue

                if first_href is None:
                    first_href = href

                if _is_used(title):
                    continue

                title_words = set(re.sub(r"[^a-z0-9\s]", "", title.lower()).split())
                score = len(query_words & title_words)
                candidates.append((score, href, title))

            except Exception:
                continue

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
