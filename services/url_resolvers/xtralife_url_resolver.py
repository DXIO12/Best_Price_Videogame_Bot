# services/url_resolvers/xtralife_url_resolver.py

import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from urllib.parse import unquote_plus

BASE_URL = "https://www.xtralife.com"

# Maps our internal platform names → exact label Xtralife shows (before the count)
# Labels look like "Switch (2)", "Switch 2 (181)", "PS5 (1)", etc.
PLATFORM_MAP = {
    "ps5":           "PS5",
    "ps4":           "PS4",
    "ns2":           "Switch 2",
    "ns":            "Switch",
    "pc":            "PC",
    "xbox series x": "Xbox Series",
}


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


def resolve_xtralife_product_url(search_url: str, platform: str | None = None):
    query = search_url.split("q=")[-1]
    query = unquote_plus(query)

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
        page.wait_for_timeout(3000)

        # Accept cookies
        try:
            page.get_by_text("Permitir todo").click(timeout=8000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        # Search
        try:
            page.locator('input[placeholder="Buscar"]').click(timeout=5000)
            page.locator('input[placeholder="Buscar"]').fill(query)
            page.locator('input[placeholder="Buscar"]').press("Enter")
            page.wait_for_timeout(3000)
        except PlaywrightTimeout:
            print("[Xtralife] Search input not found.")
            browser.close()
            return None

        # Click "Juegos" quick filter
        try:
            juegos_filter = page.locator('quick-filter').filter(has_text="Juegos").first
            juegos_filter.scroll_into_view_if_needed(timeout=5000)
            juegos_filter.click(timeout=5000)
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[Xtralife] Juegos filter error: {e}")

        # Platform filter
        if platform:
            keyword = PLATFORM_MAP.get(platform.strip().lower())

            if keyword:
                try:
                    page.locator('filter-select').filter(
                        has_text="Plataforma"
                    ).first.click(timeout=5000)
                    page.wait_for_timeout(1000)

                    options = page.locator(
                        'div.filter-select-list div.scroll div.option div.label'
                    ).all()
                    matched = False
                    for option in options:
                        try:
                            raw_label = option.inner_text(timeout=1500).strip()
                            # Strip trailing count: "Switch (1)" → "Switch"
                            label_clean = re.sub(r'\s*\(\d+\)\s*$', '', raw_label).strip()
                            # Exact match after stripping count
                            if label_clean.lower() == keyword.lower():
                                option.click()
                                matched = True
                                page.wait_for_timeout(500)
                                break
                        except Exception:
                            continue

                    if matched:
                        try:
                            page.locator(
                                'div.filter-select-list div.action-buttons div.tag'
                            ).first.click(timeout=5000)
                            page.wait_for_timeout(3000)
                        except Exception as e:
                            print(f"[Xtralife] Apply filter error: {e}")
                    else:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)

                except Exception as e:
                    print(f"[Xtralife] Platform filter error: {e}")

        # Grab product cards
        try:
            page.wait_for_timeout(2000)
            page.wait_for_selector(
                'a.flex.ng-star-inserted[href*="/producto/"]', timeout=10000
            )
            cards = page.locator(
                'a.flex.ng-star-inserted[href*="/producto/"]'
            ).all()[:5]
        except PlaywrightTimeout:
            print("[Xtralife] No product cards found.")
            browser.close()
            return None

        # Score each card by how many words from the product name appear in the card title
        query_words = set(re.sub(r"[^a-z0-9\s]", "", query.lower()).split())

        best_href = None
        best_score = -1
        first_href = None

        for i, card in enumerate(cards):
            try:
                href = card.get_attribute("href", timeout=2000)
                if not href:
                    continue
                if first_href is None:
                    first_href = href

                # Read the card title from titleWrapper
                try:
                    title_raw = card.locator(
                        "div.titleWrapper span.fontBold"
                    ).first.inner_text(timeout=2000).strip()
                except Exception:
                    title_raw = ""

                title_words = set(re.sub(r"[^a-z0-9\s]", "", title_raw.lower()).split())
                score = len(query_words & title_words)

                if score > best_score:
                    best_score = score
                    best_href = href

            except Exception:
                pass
        browser.close()

        result_href = best_href or first_href
        if not result_href:
            print("[Xtralife] No valid product URL found.")
            return None

        result = (
            result_href if result_href.startswith("http")
            else f"{BASE_URL}{result_href}"
        )
        return result