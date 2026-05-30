import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler

from notifier import send_telegram_message

from shops.amazon import get_amazon_price
from shops.game import get_game_price
from shops.pccomponentes import get_pccomponentes_price
from shops.xtralife import get_xtralife_price
from shops.wakkap import get_wakkap_price
from shops.mediamarkt import get_mediamarkt_price
from shops.corteingles import get_elcorteingles_price
from shops.carrefour import get_carrefour_price
from shops.playwright_utils import stop_browser

from database.db import SessionLocal
from database.models import Product, ProductShop, Setting


# =========================================================
# LOAD ENVIRONMENT VARIABLES
# =========================================================

load_dotenv()


# =========================================================
# SHOP SCRAPER FUNCTIONS
# =========================================================

SHOP_FUNCTIONS = {
    "amazon": get_amazon_price,
    "game": get_game_price,
    "pccomponentes": get_pccomponentes_price,
    "xtralife": get_xtralife_price,
    "wakkap": get_wakkap_price,
    "mediamarkt": get_mediamarkt_price,
    "corteingles": get_elcorteingles_price,
    "carrefour": get_carrefour_price
}


# =========================================================
# LOAD SETTINGS FROM DB
# =========================================================

def load_settings() -> dict:
    """Read bot settings from the DB Settings table.
    Falls back to safe defaults if no row exists yet."""
    db = SessionLocal()
    setting = db.query(Setting).first()
    db.close()

    if setting:
        return {
            "check_interval_minutes": setting.check_interval_minutes or 30,
            "notify_only_best_price": setting.notify_only_best_price if setting.notify_only_best_price is not None else False,
            "repeat_notifications": setting.repeat_notifications if setting.repeat_notifications is not None else True,
            "repeat_notification_hours": setting.repeat_notification_hours or 3,
        }

    # Defaults when no settings row exists
    return {
        "check_interval_minutes": 30,
        "notify_only_best_price": False,
        "repeat_notifications": True,
        "repeat_notification_hours": 3,
    }


# =========================================================
# NOTIFICATION COOLDOWN CHECK
# =========================================================

def should_notify(shop_record: ProductShop, current_price: float, settings: dict) -> bool:
    """Return True if a Telegram notification should be sent for this shop record."""

    last_price = shop_record.last_price
    last_notified = shop_record.last_notified  # datetime or None

    # Always notify if we have never notified before
    if last_notified is None:
        return True

    # Notify if the price has dropped since last notification
    if last_price is None or current_price < last_price:
        return True

    # Notify again after cooldown if repeat_notifications is enabled
    if settings["repeat_notifications"]:
        now = datetime.now(timezone.utc)
        # last_notified may be naive (SQLite stores without tz); normalise it
        if last_notified.tzinfo is None:
            last_notified = last_notified.replace(tzinfo=timezone.utc)
        hours_passed = (now - last_notified).total_seconds() / 3600
        if hours_passed >= settings["repeat_notification_hours"]:
            return True

    return False


# =========================================================
# PERSIST PRICE + NOTIFICATION TIMESTAMP TO DB
# =========================================================

def save_shop_record(db, shop_record: ProductShop, price: float, notified: bool):
    """Update last_price and optionally last_notified on the ProductShop row."""
    shop_record.last_price = price
    if notified:
        shop_record.last_notified = datetime.now(timezone.utc)
    db.commit()


# =========================================================
# SEND TELEGRAM NOTIFICATION
# =========================================================

def send_notification(product_name: str, shop: str, current_price: float,
                      target_price: float, url: str):
    message = (
        f"PRICE ALERT!\n\n"
        f"Product: {product_name}\n"
        f"Shop: {shop}\n"
        f"Current price: {current_price}€\n"
        f"Target price: {target_price}€\n\n"
        f"URL:\n{url}"
    )
    send_telegram_message(
        os.getenv("TELEGRAM_BOT_TOKEN"),
        os.getenv("TELEGRAM_CHAT_ID"),
        message
    )


# =========================================================
# MAIN PRICE CHECKER
# =========================================================

def check_prices():
    print("===================================")
    print("Checking product prices...")

    settings = load_settings()
    db = SessionLocal()

    try:
        products = db.query(Product).all()

        if not products:
            print("No products in database.")
            return

        for product in products:
            name = product.name
            target_price = product.target_price
            shop_records = db.query(ProductShop).filter(
                ProductShop.product_id == product.id
            ).all()

            if not shop_records:
                print(f"No shops configured for {name}, skipping.")
                continue

            print(f"\nProduct: {name} | Target: {target_price}€")

            if settings["notify_only_best_price"]:
                _check_best_price(db, name, target_price, shop_records, settings)
            else:
                _check_all_shops(db, name, target_price, shop_records, settings)

    finally:
        db.close()
        stop_browser()

    print("===================================")
    print("Price check complete.")


# =========================================================
# STRATEGY A — notify only the single best price
# =========================================================

def _check_best_price(db, product_name: str, target_price: float,
                      shop_records: list, settings: dict):
    """Scrape all shops, then send one notification for the cheapest hit."""
    hits = []

    for record in shop_records:
        price = _scrape(record)
        if price is not None:
            save_shop_record(db, record, price, notified=False)
            if price <= target_price:
                hits.append((price, record))

    if not hits:
        print(f"  No prices at or below target for {product_name}.")
        return

    best_price, best_record = min(hits, key=lambda x: x[0])

    if should_notify(best_record, best_price, settings):
        print(f"  BEST PRICE: {best_price}€ at {best_record.shop}")
        send_notification(product_name, best_record.shop,
                          best_price, target_price, best_record.url)
        save_shop_record(db, best_record, best_price, notified=True)
    else:
        print(f"  Best price {best_price}€ already notified recently.")


# =========================================================
# STRATEGY B — notify every shop that beats the target
# =========================================================

def _check_all_shops(db, product_name: str, target_price: float,
                     shop_records: list, settings: dict):
    """Scrape each shop and notify individually for every hit."""
    for record in shop_records:
        price = _scrape(record)

        if price is None:
            continue

        # Always persist the latest price
        notified = False

        if price <= target_price:
            if should_notify(record, price, settings):
                print(f"  ALERT: {record.shop} → {price}€")
                send_notification(product_name, record.shop,
                                  price, target_price, record.url)
                notified = True
            else:
                print(f"  {record.shop}: {price}€ — already notified recently.")
        else:
            print(f"  {record.shop}: {price}€ — above target.")

        save_shop_record(db, record, price, notified=notified)


# =========================================================
# SCRAPE HELPER
# =========================================================

def _scrape(record: ProductShop) -> float | None:
    """Call the right scraper for a ProductShop record. Returns price or None."""
    shop_key = record.shop.strip().lower()
    scraper = SHOP_FUNCTIONS.get(shop_key)

    if scraper is None:
        print(f"  No scraper for shop '{record.shop}' — skipping.")
        return None

    if not record.url or not record.url.strip():
        print(f"  No URL set for {record.shop} — skipping.")
        return None

    try:
        print(f"  Scraping {record.shop}...")
        price = scraper(record.url)
        print(f"  {record.shop}: {price}€" if price is not None
              else f"  {record.shop}: could not retrieve price.")
        return price
    except Exception as e:
        print(f"  Error scraping {record.shop}: {e}")
        return None


# =========================================================
# STANDALONE ENTRY POINT (runs scheduler)
# =========================================================

if __name__ == "__main__":
    settings = load_settings()
    interval = settings["check_interval_minutes"]

    scheduler = BlockingScheduler()
    scheduler.add_job(check_prices, "interval", minutes=interval)

    print("===================================")
    print("Price tracker bot started.")
    print(f"Checking every {interval} minutes.")
    print("Press CTRL+C to stop.")
    print("===================================")

    # Run once immediately, then let the scheduler take over
    check_prices()
    scheduler.start()