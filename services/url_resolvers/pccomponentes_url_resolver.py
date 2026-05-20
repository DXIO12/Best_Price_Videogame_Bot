from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BASE_URL = "https://www.pccomponentes.com"


def resolve_pccomponentes_product_url(search_url: str, platform: str | None = None):
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
        page.goto(search_url, wait_until="domcontentloaded")

        # Accept cookies
        try:
            page.locator('button#cookiesAcceptAll').click(timeout=5000)
            page.wait_for_timeout(1500)
        except:
            pass

        # Wait for JS to render the product cards
        page.wait_for_timeout(5000)

        cards = page.locator('a[data-testid="normal-link"]').all()

        if not cards:
            print("No product cards found.")
            browser.close()
            return None

        href = None
        for card in cards:
            try:
                product_name = card.get_attribute("data-product-name", timeout=3000)
                if not product_name:
                    continue

                if platform and platform.lower() not in product_name.lower():
                    continue

                href = card.get_attribute("href", timeout=3000)
                if href:
                    break
            except:
                continue

        browser.close()

        if not href:
            print(f"No matching product found for platform: {platform}")
            return None

        return href if href.startswith("http") else f"{BASE_URL}{href}"