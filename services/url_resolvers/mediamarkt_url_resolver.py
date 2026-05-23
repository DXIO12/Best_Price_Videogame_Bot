# services/url_resolvers/mediamarkt_url_resolver.py

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from urllib.parse import unquote_plus

BASE_URL = "https://www.mediamarkt.es"


def resolve_mediamarkt_product_url(search_url: str, platform: str | None = None):
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
        page.wait_for_timeout(3000)

        # Accept cookies
        try:
            page.locator('button#pwa-consent-layer-accept-all-button').click(timeout=8000)
            page.wait_for_timeout(2000)
        except:
            pass

        # Type in the search box
        try:
            page.locator('input#search-form').click(timeout=5000)
            page.locator('input#search-form').fill(query)
            page.wait_for_timeout(1000)
        except PlaywrightTimeout:
            print("Search input not found.")
            browser.close()
            return None

        # Submit the search by pressing Enter
        page.locator('input#search-form').press("Enter")

        # Wait for search results page to load
        try:
            page.wait_for_selector(
                'a[data-test="mms-router-link-product-list-item-link"]',
                timeout=15000
            )
        except PlaywrightTimeout:
            print("Search results did not appear.")
            browser.close()
            return None

        # Wait a bit more for all cards to render
        page.wait_for_timeout(2000)

        # Grab all product result links
        items = page.locator('a[data-test="mms-router-link-product-list-item-link"]').all()

        href = None
        for item in items:
            try:
                title = item.locator('p[data-test="product-title"]').inner_text(timeout=3000).strip().lower()
                print(f"Found: {title}")

                if platform and platform.lower() not in title:
                    continue

                href = item.get_attribute("href", timeout=3000)
                if href:
                    break
            except:
                continue

        browser.close()

        if not href:
            print(f"No matching product found for platform: {platform}")
            return None

        return href if href.startswith("http") else f"{BASE_URL}{href}"