import asyncio
import random

from playwright.async_api import async_playwright
from shops.price_utils import extract_price


def human_delay(min_seconds=1, max_seconds=3):
    delay = random.randint(
        min_seconds * 1000,
        max_seconds * 1000
    )
    return delay


async def _fetch_fnac_price(url):
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(
            url,
            timeout=60000,
            wait_until="domcontentloaded"
        )

        await page.wait_for_timeout(human_delay(3, 6))

        await page.mouse.move(
            random.randint(100, 500),
            random.randint(100, 500)
        )

        await page.wait_for_timeout(human_delay(1, 3))

        await page.mouse.wheel(0, random.randint(300, 1000))

        await page.wait_for_timeout(human_delay(2, 5))

        texts = await page.locator(".f-faPriceBox__price").all_inner_texts()

        price_text = None

        for text in texts:
            cleaned_text = text.strip()
            print(f"FNAC TEXT FOUND: {cleaned_text}")
            if "€" in cleaned_text:
                price_text = cleaned_text
                break

        await context.close()
        await browser.close()

        if not price_text:
            return None

        return extract_price(price_text)


def _run_async(coro_func, *args, **kwargs):
    try:
        return asyncio.run(coro_func(*args, **kwargs))
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" in str(e):
            import threading

            result = {}
            exc = {}

            def target():
                try:
                    result["value"] = asyncio.run(coro_func(*args, **kwargs))
                except Exception as inner_exc:
                    exc["value"] = inner_exc

            thread = threading.Thread(target=target)
            thread.start()
            thread.join()

            if exc:
                raise exc["value"]
            return result.get("value")
        raise


def get_fnac_price(url):
    try:
        return _run_async(_fetch_fnac_price, url)
    except Exception as e:
        print(f"Fnac scraper error: {e}")
        return None
