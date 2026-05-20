from shops.playwright_utils import chromium_page
from shops.price_utils import extract_price


def get_carrefour_price(url):

    try:
        with chromium_page(url) as page:

            # Esperar a que cargue la página
            page.wait_for_timeout(8000)

            # Obtener todos los posibles precios
            texts = page.locator(
                '[class*="price"]'
            ).all_inner_texts()

            price_text = None

            for text in texts:

                cleaned_text = text.strip()

                # Buscar un texto que contenga €
                if "€" in cleaned_text:
                    price_text = cleaned_text
                    break

            if not price_text:
                return None

            return extract_price(price_text)

    except Exception as e:
        print(f"Carrefour scraper error: {e}")
        return None