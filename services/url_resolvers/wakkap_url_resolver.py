from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from urllib.parse import unquote_plus

BASE_URL = "https://wakkap.com/search/filter/on-sale"

PLATFORM_MAP = {
    "ps5": "ps5",
    "ns2": "nsw2",
    "ns": "switch",
    "ps4": "ps4",
    "pc": "pc",
    "xbox series x": "xbox-series",
}


def resolve_wakkap_product_url(search_url: str, platform: str | None = None):
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
            page.locator('div.cmp-pop div.cmp-button-mini').click(timeout=8000)
            page.wait_for_timeout(1500)
        except:
            pass

        # Type in search box and press Enter
        try:
            page.locator('input.search-box').click(timeout=5000)
            page.locator('input.search-box').fill(query)
            page.locator('input.search-box').press("Enter")
            page.wait_for_timeout(3000)
        except PlaywrightTimeout:
            print(f"[Wakkap] Search input not found.")
            browser.close()
            return None

        # Click Filtrar button to open filters
        try:
            page.get_by_text("Filtrar").click(timeout=5000)
            page.wait_for_timeout(1000)
        except:
            pass

        # Select "Juegos" from product type dropdown
        try:
            page.locator('div.section-3 div.cmp-dropdown').first.click(timeout=5000)
            page.wait_for_timeout(1000)
            page.locator('div.select-items div.item[value="game"]').first.click(timeout=5000)
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"[Wakkap] Juegos filter error: {e}")

        # Apply platform filter
        if platform:
            platform_value = PLATFORM_MAP.get(platform.lower())
            if platform_value:
                try:
                    page.locator('div.section-3 div.cmp-dropdown').nth(1).click(timeout=5000)
                    page.wait_for_timeout(1000)
                    page.locator(
                        f'div.select-items div.item[value="{platform_value}"]'
                    ).first.click(timeout=5000)
                    page.wait_for_timeout(1000)
                except Exception as e:
                    print(f"[Wakkap] Platform filter error: {e}")

        # Ensure "Mostrar sólo disponibles" is checked
        try:
            checkbox = page.locator('input[type="checkbox"][name=""]').last
            if not checkbox.is_checked():
                checkbox.click()
            page.wait_for_timeout(1000)
        except:
            pass

        # Close filters
        try:
            page.locator('#close-filters').click(timeout=5000)
            page.wait_for_timeout(2000)
        except:
            pass

        # Click the first card and return the product URL
        try:
            page.wait_for_selector('div.cmp-thumbnail-card', timeout=10000)
            cards = page.locator('div.cmp-thumbnail-card').all()

            if not cards:
                print("[Wakkap] No product cards found.")
                browser.close()
                return None

            cards[0].click()
            page.wait_for_timeout(3000)
            href = page.url

        except PlaywrightTimeout:
            print("[Wakkap] No products found.")
            browser.close()
            return None

        browser.close()
        return href