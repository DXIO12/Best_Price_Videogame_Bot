# services/url_resolvers/game_url_resolver.py

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from urllib.parse import unquote_plus

BASE_URL = "https://www.game.es"


def resolve_game_product_url(search_url: str, platform: str | None = None):
    # Extract the search query from the URL
    query = search_url.split("text=")[-1]
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

        # Accept cookies
        try:
            page.locator('button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll').click(timeout=8000)
            page.wait_for_timeout(2000)
        except:
            pass

        # Type in the search box to trigger autocomplete
        try:
            page.locator('input#searchinput').click(timeout=5000)
            page.locator('input#searchinput').fill(query)
            page.wait_for_timeout(2000)  # Wait for autocomplete to populate
        except PlaywrightTimeout:
            print("Search input not found.")
            browser.close()
            return None

        # Wait for autocomplete results
        try:
            page.wait_for_selector('li.ui-search-menu-item a', timeout=10000)
        except PlaywrightTimeout:
            print("Autocomplete results did not appear.")
            browser.close()
            return None
        
        # Always take the first result
        try:
            first_item = page.locator('li.ui-search-menu-item a').first
            href = first_item.get_attribute("href", timeout=3000)
        except:
            href = None

        browser.close()

        if not href:
            print(f"No matching product found for platform: {platform}")
            return None

        return href if href.startswith("http") else f"{BASE_URL}{href}"