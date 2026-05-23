# services/url_resolvers/xtralife_url_resolver.py

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from urllib.parse import unquote_plus

BASE_URL = "https://www.xtralife.com"


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
        except:
            pass

        # Type in search box and press Enter
        try:
            page.locator('input[placeholder="Buscar"]').click(timeout=5000)
            page.locator('input[placeholder="Buscar"]').fill(query)
            page.locator('input[placeholder="Buscar"]').press("Enter")
            page.wait_for_timeout(3000)
        except PlaywrightTimeout:
            print("Search input not found.")
            browser.close()
            return None

        # Click "Juegos" quick filter using scroll_into_view
        try:
            juegos_filter = page.locator('quick-filter').filter(has_text="Juegos").first
            juegos_filter.scroll_into_view_if_needed(timeout=5000)
            juegos_filter.click(timeout=5000)
            print("Clicked Juegos filter.")
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Juegos filter error: {e}")

        # Apply platform filter if provided
        if platform:
            try:
                # Click the Plataforma dropdown to open it
                page.locator('filter-select').filter(has_text="Plataforma").first.click(timeout=5000)
                print("Clicked Plataforma dropdown.")
                page.wait_for_timeout(1000)

                # Find and click the matching platform option
                platform_options = page.locator('div.filter-select-list div.option div.label').all()
                print(f"Platform options found: {len(platform_options)}")
                for option in platform_options:
                    label = option.inner_text(timeout=2000).strip()
                    print(f"  Option: {label}")
                    if platform.lower() in label.lower():
                        option.click()
                        print(f"Selected: {label}")
                        page.wait_for_timeout(1000)
                        break

                # Click "Aplicar filtros" button
                page.locator('div.action-buttons div.tag').first.click(timeout=5000)
                print("Applied platform filter.")
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"Platform filter error: {e}")

        # Grab the cheapest product among the first 5 results
        try:
            page.wait_for_timeout(2000)
            page.wait_for_selector('a.flex.ng-star-inserted[href*="/producto/"]', timeout=10000)
            
            cards = page.locator('a.flex.ng-star-inserted[href*="/producto/"]').all()[:5]
            print(f"Cards found: {len(cards)}")

            best_href = None
            best_price = float('inf')

            for card in cards:
                try:
                    href = card.get_attribute("href", timeout=3000)
                    
                    # Target price specifically inside ctaWrapper
                    price_text = card.locator('div.ctaWrapper span.fontBold').first.inner_text(timeout=3000)
                    print(f"  Raw price text: {price_text}")
                    price = float(price_text.strip().replace(',', '.').replace('€', '').strip())
                    print(f"  Product: {href} — Price: {price}€")

                    if price < best_price:
                        best_price = price
                        best_href = href
                except Exception as e:
                    print(f"  Error reading card: {e}")
                    continue

            print(f"Cheapest product: {best_href} at {best_price}€")

        except PlaywrightTimeout:
            print("No products found.")
            browser.close()
            return None

        browser.close()

        if not best_href:
            return None

        return best_href if best_href.startswith("http") else f"{BASE_URL}{best_href}"