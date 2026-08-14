from database.db import SessionLocal
from sqlalchemy.orm import joinedload
from database.models import (Product, ProductShop, Platform, product_platforms)

# Maps GUI display labels → DB-stored names (and reverse).
# Update this dict whenever a platform is renamed in the DB.
_PLATFORM_GUI_TO_DB = {
    "NS2": "Switch 2",
    "NS":  "Switch",
}
_PLATFORM_DB_TO_GUI = {v: k for k, v in _PLATFORM_GUI_TO_DB.items()}


def _to_db_names(gui_names: list[str]) -> list[str]:
    return [_PLATFORM_GUI_TO_DB.get(n, n) for n in gui_names]


def to_gui_names(db_names: list[str]) -> list[str]:
    """Translate DB-stored platform names back to GUI display labels."""
    return [_PLATFORM_DB_TO_GUI.get(n, n) for n in db_names]

def create_product(name, platforms, target_price, shops=None, shop_urls=None, priority_position=None):

    db = SessionLocal()

    platform_objects = db.query(
        Platform
    ).filter(
        Platform.name.in_(_to_db_names(platforms))
    ).all()

    product = Product(name=name, target_price=target_price)
    product.platforms = platform_objects

    db.add(product)
    db.flush()

    # Build the full set of shops to track:
    # - All shops selected in the dropdown
    # - Plus any shop the user provided a manual URL for (even if not in dropdown)
    # Manual URL always wins over resolver for the same shop.
    shop_urls = shop_urls or {}

    # Normalised map: lower-case shop name → original-case name (prefer dropdown casing)
    merged: dict[str, str] = {}  # lower → display name

    for shop in (shops or []):
        if shop:
            merged[shop.lower()] = shop

    for shop_key in shop_urls:
        # shop_urls keys are already lower-case (set in ManualUrlDialog)
        if shop_key and shop_key not in merged:
            merged[shop_key] = shop_key.capitalize()

    for shop_lower, shop_display in merged.items():
        url = shop_urls.get(shop_lower, "")
        product_shop = ProductShop(
            product_id=product.id,
            shop=shop_display,
            url=url,
        )
        db.add(product_shop)

    db.commit()
    product_id = product.id
    new_platform_ids = [platform.id for platform in platform_objects]
    db.close()

    # Place the new product's rows at the requested table position (default:
    # first). Priority lives per (product, platform), so a product with several
    # platforms occupies several consecutive rows.
    _place_product_at_position(product_id, new_platform_ids, priority_position)
    return product_id


def _place_product_at_position(product_id, platform_ids, position):
    """Insert a newly created product's (product_id, platform_id) rows at a
    1-based position among the existing priority-ordered rows, then renumber
    everything. position None or < 1 places the product first (top)."""
    if not platform_ids:
        return

    new_keys = [(product_id, platform_id) for platform_id in platform_ids]

    priorities = get_platform_priorities()  # already includes the new rows
    new_key_set = set(new_keys)
    existing = sorted(
        (key for key in priorities if key not in new_key_set),
        key=lambda key: priorities[key],
    )

    if position is None or position < 1:
        index = 0
    else:
        index = min(position - 1, len(existing))

    ordered = existing[:index] + new_keys + existing[index:]
    reorder_platform_priorities(ordered)


def get_products():

    db = SessionLocal()

    products = db.query(Product).options(
        joinedload(Product.platforms)
    ).all()

    db.close()

    return products


def get_products_with_shops():

    db = SessionLocal()

    products = db.query(Product).options(
        joinedload(Product.platforms)
    ).all()

    if not products:
        db.close()
        return []

    # Deduplicate products (joinedload can cause duplicates with many-to-many)
    seen_ids = set()
    unique_products = []
    for product in products:
        if product.id not in seen_ids:
            seen_ids.add(product.id)
            unique_products.append(product)

    product_ids = [product.id for product in unique_products]
    product_shops = db.query(ProductShop).filter(ProductShop.product_id.in_(product_ids)).all()

    shops_by_product: dict[int, list[ProductShop]] = {}
    for product_shop in product_shops:
        shops_by_product.setdefault(product_shop.product_id, []).append(product_shop)

    db.close()

    return [(product, shops_by_product.get(product.id, []))
        for product in unique_products
    ]


def get_platform_priorities() -> dict[tuple[int, int], int]:
    """Return {(product_id, platform_id): priority} for every product+platform row."""

    db = SessionLocal()
    rows = db.execute(
        product_platforms.select().with_only_columns(
            product_platforms.c.product_id,
            product_platforms.c.platform_id,
            product_platforms.c.priority,
        )
    ).all()
    db.close()

    return {(row.product_id, row.platform_id): row.priority for row in rows}


def reorder_platform_priorities(ordered_keys: list[tuple[int, int]]):
    """Persist a new priority order for (product_id, platform_id) pairs.

    ordered_keys is the desired top-to-bottom order; each pair gets its
    index as the new priority value.
    """

    if not ordered_keys:
        return

    db = SessionLocal()
    for priority, (product_id, platform_id) in enumerate(ordered_keys):
        db.execute(
            product_platforms.update()
            .where(product_platforms.c.product_id == product_id)
            .where(product_platforms.c.platform_id == platform_id)
            .values(priority=priority)
        )
    db.commit()
    db.close()


def delete_products(product_ids):

    if not product_ids:
        return

    db = SessionLocal()

    # DELETE PRODUCT SHOPS FIRST
    db.query(ProductShop).filter(
        ProductShop.product_id.in_(product_ids)
    ).delete(synchronize_session=False)

    # DELETE PRODUCTS
    db.query(Product).filter(
        Product.id.in_(product_ids)
    ).delete(synchronize_session=False)

    db.commit()
    db.close()


def delete_product_platforms(product_id, platforms_to_remove):
    """
    Remove specific platform entries from a product's relational platforms list.
    If no platforms remain after removal, delete the product and its ProductShop rows.
    """
    if not product_id or not platforms_to_remove:
        return

    db = SessionLocal()

    product = db.query(Product).options(joinedload(Product.platforms)).filter(Product.id == product_id).first()
    if not product:
        db.close()
        return

    remaining_platforms = [platform for platform in product.platforms if platform.name not in platforms_to_remove]

    if not remaining_platforms:
        # Delete product shops and the product itself
        db.query(ProductShop).filter(ProductShop.product_id == product_id).delete(synchronize_session=False)
        db.delete(product)
    else:
        product.platforms = remaining_platforms

    db.commit()
    db.close()


def modify_product(product_id, new_platforms, new_name=None, new_target_price=None):
    """
    Update a product's platforms, name, and/or target_price.
    """
    if not product_id:
        return

    db = SessionLocal()

    product = db.query(Product).options(joinedload(Product.platforms)).filter(Product.id == product_id).first()
    if not product:
        db.close()
        return

    # Update platform relationships
    if new_platforms:
        cleaned = [p.strip() for p in new_platforms if p.strip()]
        platform_objects = db.query(Platform).filter(Platform.name.in_(_to_db_names(cleaned))).all()
        product.platforms = platform_objects

    # Update name if provided
    if new_name is not None:
        product.name = new_name

    # Update target_price if provided
    if new_target_price is not None:
        product.target_price = new_target_price

    db.commit()
    db.close()


def apply_shop_changes(product_id, to_add, to_remove, to_update):
    """
    Persist the shop edits made in the Manage Shops dialog for one product.

    to_add:    [{"shop": str, "url": str}]        — new shops to track
    to_remove: [(product_shop_id, shop_name)]     — shops to stop tracking
    to_update: [(product_shop_id, new_url)]       — URL changes ("" = auto-resolve again)
    """
    db = SessionLocal()

    for record_id, shop in to_remove:
        record = db.query(ProductShop).filter(ProductShop.id == record_id).first()
        if record:
            db.delete(record)
            print(f"[Shops] Removed '{shop}' from product {product_id}")

    for record_id, new_url in to_update:
        record = db.query(ProductShop).filter(ProductShop.id == record_id).first()
        if record:
            record.url = new_url
            # The retry schedule belongs to the old URL, so it starts over.
            record.retry_count = 0
            record.next_retry_at = None
            status = "manual URL set" if new_url else "URL cleared (will auto-resolve)"
            print(f"[Shops] '{record.shop}' on product {product_id}: {status}")

    for shop_info in to_add:
        db.add(ProductShop(
            product_id=product_id,
            shop=shop_info["shop"],
            url=shop_info["url"],
            retry_count=0,
        ))
        print(f"[Shops] Added '{shop_info['shop']}' to product {product_id}"
              + (" with manual URL" if shop_info["url"] else " (will auto-resolve)"))

    db.commit()
    db.close()