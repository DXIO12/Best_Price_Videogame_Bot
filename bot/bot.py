import os
import queue
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler

from bot.notifier import send_telegram_message

from shops.amazon import get_amazon_price
from shops.game import get_game_price
from shops.pccomponentes import get_pccomponentes_price
from shops.xtralife import get_xtralife_price
from shops.wakkap import get_wakkap_price
from shops.mediamarkt import get_mediamarkt_price
from shops.corteingles import get_elcorteingles_price
from shops.carrefour import get_carrefour_price
from shops.playwright_utils import stop_browser

from config.runtime_config import get_debug_mode

from sqlalchemy import func

from database.db import SessionLocal
from database.models import Product, ProductShop, Setting, product_platforms


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


# Threads used when allow_parallel_scraping is on and the DB has no explicit
# value. Every worker launches its own browser, so this trades RAM for wall
# time. Benchmarked (see README): 4 workers is the last step that still pays —
# it buys 35 s per extra GB, against only 8 s/GB for a fifth worker.
DEFAULT_PARALLEL_WORKERS = 4


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
            "repeat_notification_minutes": setting.repeat_notification_minutes or 90,
            "allow_parallel_scraping": setting.allow_parallel_scraping if setting.allow_parallel_scraping is not None else False,
            "max_parallel_workers": setting.max_parallel_workers or DEFAULT_PARALLEL_WORKERS,
            "debug_mode": get_debug_mode(),
        }

    # Defaults when no settings row exists
    return {
        "check_interval_minutes": 30,
        "notify_only_best_price": False,
        "repeat_notifications": True,
        "repeat_notification_minutes": 90,
        "allow_parallel_scraping": False,
        "max_parallel_workers": DEFAULT_PARALLEL_WORKERS,
        "debug_mode": get_debug_mode(),
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
        minutes_passed = (now - last_notified).total_seconds() / 60
        if minutes_passed >= settings["repeat_notification_minutes"]:
            return True

    return False


# =========================================================
# PERSIST PRICE + NOTIFICATION TIMESTAMP TO DB
# =========================================================

def save_shop_record(db, shop_record: ProductShop, price: float, notified: bool):
    """Update last_price and optionally last_notified on the ProductShop row."""
    shop_record.last_price = price
    shop_record.available = True
    if notified:
        shop_record.last_notified = datetime.now(timezone.utc)
    db.commit()


def mark_unavailable(db, shop_record: ProductShop):
    """Flag a shop as having no price in the most recent check.

    The URL exists but the scraper returned no price (product out of stock /
    no buybox). We keep the historical last_price but record that the product is
    currently unavailable so the GUI can show it instead of a stale price."""
    shop_record.available = False
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

def check_prices(stop_event=None):
    print("===================================")
    print("Checking product prices...")

    settings = load_settings()
    db = SessionLocal()

    try:
        # Products are searched in ascending priority order — a product's
        # priority is the best (lowest) priority among its platform rows,
        # since the same product can rank differently per platform in the UI.
        products = (
            db.query(Product)
            .outerjoin(product_platforms, product_platforms.c.product_id == Product.id)
            .group_by(Product.id)
            .order_by(func.coalesce(func.min(product_platforms.c.priority), 0))
            .all()
        )

        if not products:
            print("No products in database.")
            return

        records_by_product = {
            product.id: db.query(ProductShop).filter(
                ProductShop.product_id == product.id
            ).all()
            for product in products
        }

        # In parallel mode every price is fetched up front, then the loop below
        # reads them from this dict instead of scraping inline. Notifications and
        # DB writes stay on this thread and keep running in priority order.
        prices = None
        if settings["allow_parallel_scraping"]:
            prices = _scrape_parallel(
                records_by_product,
                {product.id: product.name for product in products},
                settings["max_parallel_workers"],
                stop_event,
            )

        for product in products:
            if stop_event is not None and stop_event.is_set():
                print("Stop requested — halting price check.")
                break

            name = product.name
            target_price = product.target_price
            shop_records = records_by_product[product.id]

            if not shop_records:
                print(f"No shops configured for {name}, skipping.")
                continue

            print(f"\nProduct: {name} | Target: {target_price}€")

            if settings["notify_only_best_price"]:
                _check_best_price(db, name, target_price, shop_records, settings,
                                  stop_event, prices)
            else:
                _check_all_shops(db, name, target_price, shop_records, settings,
                                 stop_event, prices)

    finally:
        db.close()
        stop_browser()

    print("===================================")
    print("Price check complete.")


# =========================================================
# STRATEGY A — notify only the single best price
# =========================================================

def _check_best_price(db, product_name: str, target_price: float,
                      shop_records: list, settings: dict, stop_event=None,
                      prices: dict | None = None):
    """Scrape all shops, then send one notification for the cheapest hit."""
    hits = []

    for record in shop_records:
        if stop_event is not None and stop_event.is_set():
            break

        price = _scrape(record, prices)
        if price is not None:
            save_shop_record(db, record, price, notified=False)
            if price <= target_price:
                hits.append((price, record))
        elif record.url and record.url.strip():
            mark_unavailable(db, record)

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
                     shop_records: list, settings: dict, stop_event=None,
                     prices: dict | None = None):
    """Scrape each shop and notify individually for every hit."""
    for record in shop_records:
        if stop_event is not None and stop_event.is_set():
            break

        price = _scrape(record, prices)

        if price is None:
            if record.url and record.url.strip():
                mark_unavailable(db, record)
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

def _scrape(record: ProductShop, prices: dict | None = None) -> float | None:
    """Price for a ProductShop record, scraped now or read from a parallel pass.

    When ``prices`` is given (parallel mode) the value was already fetched by a
    worker thread, so nothing is scraped here. Records missing from it are the
    ones the parallel pass skipped for the very same reasons checked below — no
    scraper or no URL — so both modes end up treating them identically."""
    if prices is not None:
        return prices.get(record.id)

    shop_key = record.shop.strip().lower()
    scraper = SHOP_FUNCTIONS.get(shop_key)

    if scraper is None:
        print(f"  No scraper for shop '{record.shop}' — skipping.")
        return None

    if not record.url or not record.url.strip():
        print(f"  No URL set for {record.shop} — skipping.")
        return None

    return _scrape_url(scraper, record.shop, record.url)


def _run_scraper(scraper, url: str) -> tuple:
    """Call a scraper without printing anything. Returns (price, error_message).

    Silent so each mode can narrate the result its own way: the sequential path
    tells a running story, the parallel one emits a single self-contained line."""
    try:
        return scraper(url), None
    except Exception as e:
        return None, str(e)


def _scrape_url(scraper, shop_name: str, url: str) -> float | None:
    """Sequential path: scrape one URL, narrating it as it goes.

    Takes plain values rather than a ProductShop so the shop name can be used
    for the log lines without touching the ORM."""
    print(f"  Scraping {shop_name}...")
    price, error = _run_scraper(scraper, url)

    if error is not None:
        print(f"  Error scraping {shop_name}: {error}")
        return None

    print(f"  {shop_name}: {price}€" if price is not None
          else f"  {shop_name}: could not retrieve price.")
    return price


# =========================================================
# PARALLEL SCRAPING
# =========================================================

def _parallel_line(done: int, total: int, shop_name: str, product_name: str,
                   price: float | None, error: str | None, shop_width: int) -> str:
    """One self-contained log line for a finished parallel scrape.

    Workers finish in unpredictable order, so a line may not name its product
    anywhere else — unlike the sequential log, which prints a product header and
    then narrates its shops underneath. Everything needed to read the line is
    therefore on the line itself, and it is emitted as a single string so it can
    be written atomically."""
    if error is not None:
        status = "ERROR"
        # Playwright errors are multi-line essays; the first line is the useful bit.
        suffix = f"  ({error.splitlines()[0][:70]})"
    elif price is None:
        status = "no price"
        suffix = ""
    else:
        status = f"{price:.2f}€"
        suffix = ""

    counter = f"{done:>{len(str(total))}}/{total}"
    return f"  [{counter}] {shop_name:<{shop_width}}  {status:>9}  {product_name}{suffix}"


def _scrape_parallel(records_by_product: dict, product_names: dict,
                     max_workers: int, stop_event=None) -> dict:
    """Scrape every product×shop pair concurrently. Returns {shop_record_id: price}.

    Jobs are bucketed **by shop** and each bucket is handled start-to-finish by a
    single thread, so a given site never receives two simultaneous requests — the
    shops here are already anti-bot sensitive. Effective parallelism is therefore
    the number of distinct shops, capped at ``max_workers``.

    Each worker owns its own Playwright driver and browser (the sync API is bound
    to the creating thread) and closes them before exiting. Only plain values
    cross the thread boundary: the SQLAlchemy session stays with the caller.

    A record absent from the returned dict was never attempted — either it was
    filtered out below, or ``stop_event`` fired first."""
    buckets = defaultdict(list)
    skipped = []

    for product_id, shop_records in records_by_product.items():
        product_name = product_names.get(product_id, "?")

        for record in shop_records:
            shop_key = record.shop.strip().lower()

            if shop_key not in SHOP_FUNCTIONS:
                skipped.append(f"  Skipped {record.shop} for {product_name}: no scraper.")
                continue

            if not record.url or not record.url.strip():
                skipped.append(f"  Skipped {record.shop} for {product_name}: no URL set.")
                continue

            buckets[shop_key].append((record.id, record.shop, product_name, record.url))

    if not buckets:
        for line in skipped:
            print(line)
        return {}

    pending = queue.Queue()
    for shop_key, jobs in buckets.items():
        pending.put((shop_key, jobs))

    total = sum(len(jobs) for jobs in buckets.values())
    shop_width = max(len(shop) for jobs in buckets.values() for _, shop, _, _ in jobs)
    results = {}
    results_lock = threading.Lock()
    worker_count = max(1, min(max_workers, len(buckets)))

    def worker():
        try:
            while stop_event is None or not stop_event.is_set():
                try:
                    shop_key, jobs = pending.get_nowait()
                except queue.Empty:
                    break

                scraper = SHOP_FUNCTIONS[shop_key]
                for record_id, shop_name, product_name, url in jobs:
                    if stop_event is not None and stop_event.is_set():
                        break

                    price, error = _run_scraper(scraper, url)

                    # Recording and logging share the lock: it keeps the progress
                    # counter consistent with the line it appears on, and stops
                    # two workers from interleaving halves of the same line.
                    with results_lock:
                        results[record_id] = price
                        print(_parallel_line(len(results), total, shop_name,
                                             product_name, price, error, shop_width))
        finally:
            # Closes this worker's own browsers; a driver cannot be shut down
            # from another thread.
            stop_browser()

    print(f"==============================================="
          f"\nScraping {total} page(s) across {len(buckets)} shop(s) "
          f"with {worker_count} worker(s)..."
          f"\nTemporal log. Lines may appear out of product order due to parallelism.\n"
          f"===============================================")
    for line in skipped:
        print(line)

    started = time.monotonic()
    threads = [
        threading.Thread(target=worker, name=f"scraper-{index}", daemon=True)
        for index in range(worker_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    priced = sum(1 for price in results.values() if price is not None)
    print(f"Scraped {priced}/{total} price(s) in {time.monotonic() - started:.1f}s.")

    return results


# =========================================================
# STANDALONE ENTRY POINT (runs scheduler)
# =========================================================

if __name__ == "__main__":
    from config.runtime_config import init_runtime_mode

    # Console/log setup + headless resolution before scraping starts.
    init_runtime_mode()

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