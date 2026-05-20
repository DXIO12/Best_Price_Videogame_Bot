import json
import os
import time

from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import joinedload
from database.db import SessionLocal
from database.models import (
    Setting,
    Product,
    ProductShop
)

from notifier import send_telegram_message

from shops.amazon import get_amazon_price
from shops.carrefour import get_carrefour_price
from shops.game import get_game_price
from shops.pccomponentes import get_pccomponentes_price
from shops.xtralife import get_xtralife_price
from shops.wakkap import get_wakkap_price
from shops.fnac import get_fnac_price
from shops.mediamarkt import get_mediamarkt_price
from shops.playwright_utils import stop_browser


# =========================================================
# LOAD ENVIRONMENT VARIABLES
# =========================================================

load_dotenv()

CONFIG_JSON = "config.json"
LAST_PRICES_FILE = "last_prices.json"


# =========================================================
# LOAD CONFIG
# =========================================================

try:

    with open(CONFIG_JSON, "r", encoding="utf-8") as file:
        config = json.load(file)

except FileNotFoundError:

    config = {}

except json.JSONDecodeError:

    print(f"Invalid JSON in config file: {CONFIG_JSON}")
    config = {}


# =========================================================
# CONFIG OPTIONS
# =========================================================

notify_only_best_price = config.get(
    "notify_only_best_price",
    True
)

repeat_notifications = config.get(
    "repeat_notifications",
    True
)

repeat_notification_hours = config.get(
    "repeat_notification_hours",
    24
)


# =========================================================
# LOAD LAST PRICES
# =========================================================

def load_last_prices():

    try:

        with open(LAST_PRICES_FILE, "r") as file:
            return json.load(file)

    except:
        return {}


# =========================================================
# SAVE LAST PRICES
# =========================================================

def save_last_prices(data):

    with open(LAST_PRICES_FILE, "w") as file:
        json.dump(data, file, indent=4)


# =========================================================
# DATABASE PRODUCT HELPERS
# =========================================================

def get_products_from_db():
    db = SessionLocal()
    products = db.query(Product).options(joinedload(Product.platforms)).all()
    result = []

    for product in products:
        shop_rows = db.query(ProductShop).filter(
            ProductShop.product_id == product.id
        ).all()
        result.append({
            "name": product.name,
            "target_price": product.target_price,
            "shops": [
                {"shop": shop_row.shop, "url": shop_row.url}
                for shop_row in shop_rows
            ]
        })

    db.close()
    return result


# =========================================================
# SHOP SCRAPER FUNCTIONS
# =========================================================

SHOP_FUNCTIONS = {
    "amazon": get_amazon_price,
    "carrefour": get_carrefour_price,
    "game": get_game_price,
    "pccomponentes": get_pccomponentes_price,
    "xtralife": get_xtralife_price,
    "wakkap": get_wakkap_price,
    "fnac": get_fnac_price,
    "mediamarkt": get_mediamarkt_price
}


# =========================================================
# CHECK IF NOTIFICATION SHOULD BE SENT
# =========================================================

def should_notify(last_entry, current_price):

    if not last_entry:
        return True

    last_price = last_entry.get("price")
    last_notification = last_entry.get(
        "last_notification",
        0
    )

    current_time = time.time()

    # Notify if price changed
    if last_price != current_price:
        return True

    # Notify again after cooldown
    if repeat_notifications:

        hours_passed = (
            current_time - last_notification
        ) / 3600

        if hours_passed >= repeat_notification_hours:
            return True

    return False


# =========================================================
# SAVE NOTIFICATION
# =========================================================

def save_notification(last_prices, key, price):

    last_prices[key] = {
        "price": price,
        "last_notification": time.time()
    }


# =========================================================
# FETCH ALL SHOP PRICES
# =========================================================

def fetch_shop_prices(product, target_price):
    """
    Scrapes all shops for a product and returns list of prices.
    Only includes prices at or below target price.
    """
    prices_list = []
    name = product["name"]

    for shop_data in product["shops"]:

        try:

            shop = shop_data["shop"].lower()
            url = shop_data["url"]

            if not url:
                print(f"Skipping {name} on {shop}: no stored URL")
                continue

            print("===================================")
            print(f"Checking {name} on {shop}")

            scraper_function = SHOP_FUNCTIONS.get(shop)

            if scraper_function is None:
                print(f"No scraper found for {shop}")
                continue

            current_price = scraper_function(url)

            if current_price is None:
                print(
                    f"Could not retrieve price "
                    f"for {name} from {shop}"
                )
                continue

            print(f"{shop}: {current_price}€")

            # Only collect prices below or at target
            if current_price <= target_price:
                prices_list.append({
                    "shop": shop,
                    "price": current_price,
                    "url": url,
                    "product_key": f"{name}_{shop}"
                })

        except Exception as e:
            print(f"Error checking {name} on {shop}: {e}")

    return prices_list


# =========================================================
# NOTIFY BEST PRICE IMMEDIATELY
# =========================================================

def send_best_price_notification(prices_list, last_prices, product_name, target_price):

    if prices_list:
        best_price_info = min(prices_list, key=lambda x: x["price"])
        lowest_price_key = f"{product_name}_lowest"
        last_entry = last_prices.get(lowest_price_key)

        if should_notify(last_entry, best_price_info["price"]):

            print("===================================")
            print("BEST PRICE FOUND!")
            print(f"PRODUCT: {product_name}")
            print(f"SHOP: {best_price_info['shop']}")
            print(f"CURRENT PRICE: {best_price_info['price']}€")
            print(f"TARGET PRICE: {target_price}€")
            print("===================================")

            message = (
                f"PRICE ALERT!\n\n"
                f"Product: {product_name}\n"
                f"Shop: {best_price_info['shop']}\n"
                f"Current price: {best_price_info['price']}€\n"
                f"Target price: {target_price}€\n\n"
                f"URL:\n{best_price_info['url']}"
            )

            send_telegram_message(
                os.getenv("TELEGRAM_BOT_TOKEN"),
                os.getenv("TELEGRAM_CHAT_ID"),
                message
            )

            save_notification(
                last_prices,
                lowest_price_key,
                best_price_info["price"]
            )

        else:
            print("Best price already notified recently.")

    return last_prices


# =========================================================
# NOTIFY ALL SHOPS IMMEDIATELY
# =========================================================

def notify_all_shops(product, target_price, last_prices):
    name = product["name"]

    for shop_data in product["shops"]:

        try:
            shop = shop_data["shop"].lower()
            url = shop_data["url"]

            print("===================================")
            print(f"Checking {name} on {shop}")

            scraper_function = SHOP_FUNCTIONS.get(shop)

            if scraper_function is None:
                print(f"No scraper found for {shop}")
                continue

            current_price = scraper_function(url)

            if current_price is None:
                print(
                    f"Could not retrieve price "
                    f"for {name} from {shop}"
                )
                continue

            print(f"{shop}: {current_price}€")

            if current_price <= target_price:
                product_key = f"{name}_{shop}"
                last_entry = last_prices.get(product_key)

                if should_notify(last_entry, current_price):
                    print("===================================")
                    print(f"PRODUCT: {name}")
                    print(f"SHOP: {shop}")
                    print(f"CURRENT PRICE: {current_price}€")
                    print(f"TARGET PRICE: {target_price}€")
                    print("===================================")

                    message = (
                        f"PRICE ALERT!\n\n"
                        f"Product: {name}\n"
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

                    save_notification(
                        last_prices,
                        product_key,
                        current_price
                    )
                    save_last_prices(last_prices)
                else:
                    print(f"{shop} already notified recently.")

        except Exception as e:
            print(f"Error checking {name} on {shop}: {e}")

    return last_prices


# =========================================================
# MAIN PRICE CHECKER
# =========================================================

def check_prices():

    print("Checking product prices...")

    last_prices = load_last_prices()

    for product in get_products_from_db():

        name = product["name"]
        target_price = product["target_price"]

        if notify_only_best_price:
            # Scrape all shops once and send one best-price notification
            prices_list = fetch_shop_prices(product, target_price)

            last_prices = send_best_price_notification(
                prices_list,
                last_prices,
                name,
                target_price
            )

            save_last_prices(last_prices)
        else:
            # Scrape and notify each shop immediately
            last_prices = notify_all_shops(
                product,
                target_price,
                last_prices
            )

    # Clean up browser instances after each check cycle
    stop_browser()


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    scheduler = BlockingScheduler()

    scheduler.add_job(
        check_prices,
        'interval',
        minutes=config["check_interval_minutes"]
    )

    print("===================================")
    print("Price tracker bot started.")

    print(
        f"Checking every "
        f"{config['check_interval_minutes']} minutes."
    )

    print("Press CTRL+C to stop the bot.")
    print("===================================")

    # First execution
    check_prices()

    # Scheduler loop
    scheduler.start()