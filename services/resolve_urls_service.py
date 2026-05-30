"""
resolve_urls_service.py
=======================
Resolves missing ProductShop URLs using the Playwright-based URL resolvers.
Only shops with an empty URL are processed — manual URLs are never overwritten.

Retry schedule (applied after each failed resolution attempt):
  attempt 1 fails → retry in 5 min
  attempt 2 fails → retry in 15 min
  attempt 3 fails → retry in 30 min
  attempt 4 fails → retry in 60 min
  attempt 5 fails → retry in 180 min (3 h)
  attempt 6 fails → retry in 360 min (6 h)
  attempt 7 fails → exhausted, user notified via ⚠ in the GUI
"""

from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from database.db import SessionLocal
from database.models import Product, ProductShop

from services.url_search_service import get_search_url

from services.url_resolvers.amazon_url_resolver import resolve_amazon_product_url
from services.url_resolvers.game_url_resolver import resolve_game_product_url
from services.url_resolvers.mediamarkt_url_resolver import resolve_mediamarkt_product_url
from services.url_resolvers.pccomponentes_url_resolver import resolve_pccomponentes_product_url
from services.url_resolvers.wakkap_url_resolver import resolve_wakkap_product_url
from services.url_resolvers.xtralife_url_resolver import resolve_xtralife_product_url


# Map shop name (lower) → resolver function
# Carrefour and Fnac are excluded (bot-detected)
RESOLVERS = {
    "amazon":        resolve_amazon_product_url,
    "game":          resolve_game_product_url,
    "mediamarkt":    resolve_mediamarkt_product_url,
    "pccomponentes": resolve_pccomponentes_product_url,
    "wakkap":        resolve_wakkap_product_url,
    "xtralife":      resolve_xtralife_product_url,
}

# Minutes to wait before each successive retry attempt
RETRY_INTERVALS_MINUTES = [5, 15, 30, 60, 180, 360]
MAX_RETRIES = len(RETRY_INTERVALS_MINUTES)  # 5 retries → 6 total attempts


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _schedule_retry(record: ProductShop) -> None:
    """After a failed resolution, schedule the next retry or mark as exhausted."""
    current = record.retry_count or 0
    if current < MAX_RETRIES:
        delay = RETRY_INTERVALS_MINUTES[current]
        record.retry_count = current + 1
        record.next_retry_at = datetime.utcnow() + timedelta(minutes=delay)
        print(f"[Resolver] {record.shop}: retry {current + 1}/{MAX_RETRIES} in {delay} min")
    else:
        record.retry_count = MAX_RETRIES + 1  # sentinel: all retries exhausted
        record.next_retry_at = None
        print(f"[Resolver] {record.shop}: all retries exhausted")


# ─────────────────────────────────────────────
# First-time resolution (called when product is added)
# ─────────────────────────────────────────────

def resolve_urls_for_product(
    product_id: int,
    on_progress=None,
) -> dict[str, str | None]:
    """
    Resolve missing URLs for all ProductShop rows of a given product.
    Shops that already have a URL (manual entry) are skipped.
    Shops whose resolution fails are scheduled for automatic retry.

    on_progress(product_id, shop_name, resolved_url_or_None) is called after
    each shop is processed so callers can update the UI incrementally.
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
            record.retry_count = 0
            record.next_retry_at = None
            print(f"[Resolver] {record.shop}: ✓ {resolved_url}")
        else:
            print(f"[Resolver] {record.shop}: ✗ could not resolve URL")
            _schedule_retry(record)

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


# ─────────────────────────────────────────────
# Scheduled retry (called periodically by the GUI timer)
# ─────────────────────────────────────────────

def retry_due_shops(on_progress=None) -> dict[int, dict[str, str | None]]:
    """
    Find all ProductShop rows whose retry is due and attempt resolution.
    Called periodically by the GUI timer.
    Returns {product_id: {shop_name: resolved_url_or_None}}.
    """
    db = SessionLocal()
    now = datetime.utcnow()

    pending_ids = [
        r.id for r in db.query(ProductShop).filter(
            or_(ProductShop.url == None, ProductShop.url == ""),
            ProductShop.retry_count > 0,
            ProductShop.retry_count <= MAX_RETRIES,
            ProductShop.next_retry_at.isnot(None),
            ProductShop.next_retry_at <= now,
        ).all()
    ]
    db.close()

    if not pending_ids:
        return {}

    all_results: dict[int, dict[str, str | None]] = {}
    for shop_id in pending_ids:
        result = _retry_single_shop(shop_id, on_progress)
        if result:
            product_id, shop_name, url = result
            all_results.setdefault(product_id, {})[shop_name] = url

    return all_results


def _retry_single_shop(shop_record_id: int, on_progress=None):
    """Attempt one retry for a single ProductShop row. Returns (product_id, shop, url) or None."""
    db = SessionLocal()

    record = db.query(ProductShop).filter(ProductShop.id == shop_record_id).first()
    if not record:
        db.close()
        return None

    product = db.query(Product).options(
        joinedload(Product.platforms)
    ).filter(Product.id == record.product_id).first()
    if not product:
        db.close()
        return None

    platform = product.platforms[0].name if product.platforms else None
    shop_key = record.shop.strip().lower()

    resolver = RESOLVERS.get(shop_key)
    if resolver is None:
        record.retry_count = MAX_RETRIES + 1
        record.next_retry_at = None
        db.commit()
        db.close()
        return (product.id, record.shop, None)

    search_url = get_search_url(shop_key, product.name, platform)
    if not search_url:
        db.commit()
        db.close()
        return (product.id, record.shop, None)

    print(f"[Retry] {record.shop} for '{product.name}' (attempt {record.retry_count + 1})...")
    try:
        resolved_url = resolver(search_url, platform)
    except Exception as e:
        print(f"[Retry] {record.shop}: error — {e}")
        resolved_url = None

    if resolved_url:
        record.url = resolved_url
        record.retry_count = 0
        record.next_retry_at = None
        print(f"[Retry] {record.shop}: ✓ {resolved_url}")
    else:
        print(f"[Retry] {record.shop}: ✗ still not resolved")
        _schedule_retry(record)

    product_id = product.id
    shop_name = record.shop
    db.commit()
    db.close()

    if on_progress:
        on_progress(product_id, shop_name, resolved_url)

    return (product_id, shop_name, resolved_url)
