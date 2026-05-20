import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


def clean_amazon_url(href: str) -> str | None:
    """Extract the clean /dp/ASIN url, dropping query params and fragments."""
    match = re.search(r'(/dp/[A-Z0-9]+)', href)
    if match:
        base = href.split('/dp/')[0]
        asin = match.group(1)
        return f"https://www.amazon.es{asin}" if not href.startswith("http") else f"{base}{asin}"
    return None


def resolve_amazon_product_url(search_url):
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

        try:
            page.locator('#sp-cc-accept').click(timeout=5000)
            page.wait_for_timeout(1500)
        except:
            pass

        try:
            page.wait_for_selector(
                '[data-component-type="s-search-result"]',
                timeout=15000
            )
        except PlaywrightTimeout:
            print("Timed out waiting for Amazon results.")
            browser.close()
            return None

        selectors = [
            '[data-component-type="s-search-result"] h2 a.a-link-normal',
            '[data-component-type="s-search-result"] a.a-link-normal.s-underline-text',
            '[data-component-type="s-search-result"] h2 a',
        ]

        href = None
        for selector in selectors:
            try:
                href = page.locator(selector).first.get_attribute("href", timeout=5000)
                if href:
                    break
            except:
                continue

        browser.close()

        if not href:
            return None

        full_url = href if href.startswith("http") else f"https://www.amazon.es{href}"
        return clean_amazon_url(full_url)