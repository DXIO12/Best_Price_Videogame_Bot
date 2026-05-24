from urllib.parse import quote_plus

from sqlalchemy.orm import joinedload

from database.db import SessionLocal
from database.models import Product, ProductShop

SHOP_SEARCH_PATTERNS = {
    "amazon": "https://www.amazon.es/s?k={query}",
    "game": "https://www.game.es/buscar?text={query}",
    "pccomponentes": "https://www.pccomponentes.com/search/?query={query}",
    "xtralife": "https://www.xtralife.com/buscar?q={query}",
    "wakkap": "https://wakkap.com/search/filter/on-sale?q={query}",
    "fnac": "https://www.fnac.es/SearchResult/Results.aspx?SCat=0%211&Search={query}",
    "corteingles": "https://www.elcorteingles.es/search/?query={query}",
    "mediamarkt": "https://www.mediamarkt.es/es/search.html?query={query}"
}


def normalize_shop_name(shop_name: str) -> str:
    if not shop_name:
        return ""
    return shop_name.strip().lower()


def build_search_query(product_name: str, platform: str | None = None) -> str:
    if not product_name:
        return ""

    product_name = product_name.strip()
    if platform:
        platform = platform.strip()
        if platform and platform.lower() not in product_name.lower():
            product_name = f"{product_name} {platform}"

    return quote_plus(product_name)


def get_search_url(shop_name: str, product_name: str, platform: str | None = None) -> str:
    key = normalize_shop_name(shop_name)
    pattern = SHOP_SEARCH_PATTERNS.get(key)
    if not pattern:
        return ""

    query = build_search_query(product_name, platform)
    if not query:
        return ""

    return pattern.format(query=query)


def get_product_search_urls(product_id: int) -> list[dict]:
    """Return search URLs for every shop and platform linked to a product."""
    db = SessionLocal()
    product = db.query(Product).options(joinedload(Product.platforms)).filter(Product.id == product_id).first()
    if not product:
        db.close()
        return []

    platform_names = [platform.name for platform in product.platforms] or [None]
    shops = db.query(ProductShop).filter(ProductShop.product_id == product_id).all()
    db.close()

    urls = []
    for shop_record in shops:
        for platform_name in platform_names:
            generated_url = get_search_url(
                shop_record.shop,
                product.name,
                platform_name
            )
            urls.append({
                "product_id": product.id,
                "product_name": product.name,
                "platform": platform_name,
                "shop": shop_record.shop,
                "stored_url": shop_record.url,
                "search_url": shop_record.url.strip() or generated_url,
                "generated_search_url": generated_url
            })

    return urls


def get_all_product_search_urls() -> list[dict]:
    """Return search URLs for every product/shop/platform combination in the database."""
    db = SessionLocal()
    products = db.query(Product).options(joinedload(Product.platforms)).all()
    urls = []

    for product in products:
        platform_names = [platform.name for platform in product.platforms] or [None]
        shop_rows = db.query(ProductShop).filter(ProductShop.product_id == product.id).all()

        for shop_row in shop_rows:
            for platform_name in platform_names:
                generated_url = get_search_url(
                    shop_row.shop,
                    product.name,
                    platform_name
                )
                urls.append({
                    "product_id": product.id,
                    "product_name": product.name,
                    "platform": platform_name,
                    "shop": shop_row.shop,
                    "stored_url": shop_row.url,
                    "search_url": shop_row.url.strip() or generated_url,
                    "generated_search_url": generated_url
                })

    db.close()
    return urls
