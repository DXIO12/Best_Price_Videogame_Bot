# services/url_resolvers/carrefour_url_resolver.py

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from urllib.parse import unquote_plus

BASE_URL = "https://www.carrefour.es"


def resolve_carrefour_product_url(search_url: str, platform: str | None = None):
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
            page.locator('button#onetrust-accept-btn-handler').click(timeout=8000)
            print("Cookies accepted.")
            page.wait_for_timeout(2000)
        except:
            print("Cookie button not found or already accepted.")

        # Navigate directly to search URL
        page.goto(search_url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        # Debug: check current URL and page title
        print(f"Current URL: {page.url}")
        print(f"Page title: {page.title()}")

        # Debug: check what product cards look like
        try:
            cards = page.locator('article').all()
            print(f"Articles found: {len(cards)}")
            if cards:
                print("\nFIRST ARTICLE HTML:")
                print(cards[0].inner_html())
        except Exception as e:
            print(f"Card debug error: {e}")

        browser.close()
        return None