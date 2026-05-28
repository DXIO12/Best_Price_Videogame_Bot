from database.db import SessionLocal
from sqlalchemy.orm import joinedload
from database.models import (Product, ProductShop, Platform)

def create_product(name, platforms, target_price, shops=None, shop_urls=None):

    db = SessionLocal()

    platform_objects = db.query(
        Platform
    ).filter(
        Platform.name.in_(platforms)
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
    db.close()
    return product_id


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
        platform_objects = db.query(Platform).filter(Platform.name.in_(cleaned)).all()
        product.platforms = platform_objects

    # Update name if provided
    if new_name is not None:
        product.name = new_name

    # Update target_price if provided
    if new_target_price is not None:
        product.target_price = new_target_price

    db.commit()
    db.close()