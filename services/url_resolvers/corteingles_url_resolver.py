# services/url_resolvers/corteingles_url_resolver.py

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from urllib.parse import unquote_plus

BASE_URL = "https://www.elcorteingles.es/search-nwx/"


def resolve_corteingles_product_url(search_url: str, platform: str | None = None):
    query = search_url.split("query=")[-1]
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
        page.wait_for_timeout(5000)

        # Accept cookies
        try:
            page.locator('button#onetrust-accept-btn-handler').click(timeout=8000)
            print("Cookies accepted.")
            page.wait_for_timeout(2000)
        except:
            print("Cookie button not found or already accepted.")

        # Type query in search input
        try:
            page.locator('input#search-bar__input').click(timeout=5000)
            page.locator('input#search-bar__input').fill(query)
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Search input error: {e}")
            browser.close()
            return None

        # Debug: check autocomplete dropdown
        try:
            print(f"Current URL: {page.url}")
            # Check for autocomplete suggestions
            suggestions = page.locator('[aria-controls="search-input-bar-typeahead-list"] ~ * li, ul#search-input-bar-typeahead-list li').all()
            print(f"Suggestions found: {len(suggestions)}")
            for s in suggestions[:5]:
                print(f"  text: {s.inner_text(timeout=2000).strip()[:100]}")
                print(f"  html: {s.inner_html(timeout=2000)[:200]}")
        except Exception as e:
            print(f"Suggestion debug error: {e}")

        browser.close()
        return None