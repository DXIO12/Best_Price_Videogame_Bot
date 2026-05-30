"""
resolve_urls_service.py
=======================
Resolves missing ProductShop URLs using the Playwright-based URL resolvers.
Only shops with an empty URL are processed — manual URLs are never overwritten.

Usage:
    from services.resolve_urls_service import resolve_urls_for_product
    resolve_urls_for_product(product_id)   # resolves missing URLs for one product
"""

from database.db import SessionLocal
from database.models import Product, ProductShop
from sqlalchemy.orm import joinedload

from services.url_search_service import get_search_url

from services.url_resolvers.amazon_url_resolver import resolve_amazon_product_url
from services.url_resolvers.game_url_resolver import resolve_game_product_url
from services.url_resolvers.mediamarkt_url_resolver import resolve_mediamarkt_product_url
from services.url_resolvers.pccomponentes_url_resolver import resolve_pccomponentes_product_url
from services.url_resolvers.wakkap_url_resolver import resolve_wakkap_product_url
from services.url_resolvers.xtralife_url_resolver import resolve_xtralife_product_url


# Map shop name (lower) → resolver function
# Carrefour and Fnac are excluded (bot-detected)
# Corteingles has no resolver yet
RESOLVERS = {
    "amazon":        resolve_amazon_product_url,
    "game":          resolve_game_product_url,
    "mediamarkt":    resolve_mediamarkt_product_url,
    "pccomponentes": resolve_pccomponentes_product_url,
    "wakkap":        resolve_wakkap_product_url,
    "xtralife":      resolve_xtralife_product_url,
}


def resolve_urls_for_product(
    product_id: int,
    on_progress=None,
) -> dict[str, str | None]:
    """
    Resolve missing URLs for all ProductShop rows of a given product.
    Shops that already have a URL (manual entry) are skipped.

    on_progress(product_id, shop_name, resolved_url_or_None) is called after
    each shop is processed so callers can update the UI incrementally.

    Returns a dict of {shop_name: resolved_url_or_None} for every shop processed.
    """
    db = SessionLocal()

    product = db.query(Product).options(
        joinedload(Product.platforms)
    ).filter(Product.id == product_id).first()

    if not product:
        db.close()
        print(f"[Resolver] Product {product_id} not found.")
        return {}

    platform_names = [p.name for p in product.platforms] if product.platforms else [None]
    # Use the first platform for the search query
    platform = platform_names[0] if platform_names else None

    shop_records = db.query(ProductShop).filter(
        ProductShop.product_id == product_id
    ).all()

    results: dict[str, str | None] = {}

    for record in shop_records:
        shop_key = record.shop.strip().lower()

        # Skip if a URL is already set (manual URL — never overwrite)
        if record.url and record.url.strip():
            print(f"[Resolver] {record.shop}: already has URL, skipping.")
            continue

        resolver = RESOLVERS.get(shop_key)
        if resolver is None:
            print(f"[Resolver] {record.shop}: no resolver available, skipping.")
            results[record.shop] = None
            continue

        # Build the search URL from the product name + platform
        search_url = get_search_url(shop_key, product.name, platform)
        if not search_url:
            print(f"[Resolver] {record.shop}: could not build search URL, skipping.")
            results[record.shop] = None
            continue

        try:
            resolved_url = resolver(search_url, platform)
        except Exception as e:
            print(f"[Resolver] {record.shop}: resolver error — {e}")
            resolved_url = None

        if resolved_url:
            record.url = resolved_url
            print(f"[Resolver] {record.shop}: ✓ {resolved_url}")
        else:
            print(f"[Resolver] {record.shop}: ✗ could not resolve URL")

        results[record.shop] = resolved_url

        if on_progress:
            on_progress(product_id, record.shop, resolved_url)

    db.commit()
    db.close()
    return results


def resolve_urls_for_products(
    product_ids: list[int],
    on_progress=None,
) -> dict[int, dict[str, str | None]]:
    """Resolve URLs for multiple products. Returns {product_id: {shop: url}} mapping."""
    all_results = {}
    for pid in product_ids:
        all_results[pid] = resolve_urls_for_product(pid, on_progress=on_progress)
    return all_results