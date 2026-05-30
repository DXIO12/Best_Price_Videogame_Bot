# Project Structure - Price Bot

```
price-bot/
│
├── bot/
│   ├── __init__.py
│   ├── bot.py
│   ├── config.json
│   └── notifier.py
│
├── database/
│   ├── __init__.py
│   ├── db.py
│   ├── init_db.py
│   ├── models.py
│   └── seed_platforms.py
│
├── docs/
│   ├── Lauch_Price_Bot_Documentation.md
│   └── project_structure.md
│
├── gui/
│   ├── __init__.py
│   ├── add_product_dialog.py
│   ├── bot_worker.py
│   ├── delete_product_dialog.py
│   ├── main_window.py
│   └── modify_product_dialog.py
│
├── launcher/
│   ├── build_exe.bat
│   ├── build_exe.sh
│   ├── start_bot.bat
│   ├── start_bot.sh
│   ├── start_gui.bat
│   └── start_gui.sh
│
├── services/
│   ├── product_service.py
│   ├── resolve_urls_service.py
│   ├── resolver_worker.py
│   ├── url_search_service.py
│   └── url_resolvers/
│       ├── amazon_url_resolver.py
│       ├── game_url_resolver.py
│       ├── mediamarkt_url_resolver.py
│       ├── pccomponentes_url_resolver.py
│       ├── wakkap_url_resolver.py
│       └── xtralife_url_resolver.py
│
├── shops/
│   ├── amazon.py
│   ├── carrefour.py
│   ├── corteingles.py
│   ├── game.py
│   ├── mediamarkt.py
│   ├── pccomponentes.py
│   ├── playwright_utils.py
│   ├── price_utils.py
│   ├── wakkap.py
│   └── xtralife.py
│
├── README.md
└── requirements.txt
```

---

## File Descriptions

### `bot/`

The headless bot package. Runs independently of the GUI on a schedule.

| File | Description |
| ------ | ----------- |
| `__init__.py` | Marks `bot/` as a Python package so it can be imported as `bot.bot`, `bot.notifier`, etc. |
| `bot.py` | Main bot entry point. Loads settings from the DB, scrapes all product URLs on a schedule (APScheduler), compares prices against targets, and sends Telegram notifications. Contains `check_prices()`, `_scrape()`, `should_notify()`, and `save_shop_record()`. |
| `config.json` | Static configuration (shop names, default settings). Read by `bot.py` at startup. |
| `notifier.py` | Sends Telegram messages via the Bot API using `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from `.env`. |

---

### `database/`

SQLAlchemy models and DB utilities.

| File | Description |
| ------ | ----------- |
| `__init__.py` | Package marker. |
| `db.py` | Creates the SQLAlchemy engine and `SessionLocal` factory for SQLite. |
| `init_db.py` | Creates all tables on first run and runs any `ALTER TABLE` migrations (e.g. adding `retry_count`, `next_retry_at` columns). |
| `models.py` | ORM models: `Product` (name, target price), `Platform` (PS5, Switch, etc.), `ProductShop` (URL, last price, retry state, notification timestamp), `Setting` (bot config). |
| `seed_platforms.py` | One-off script that inserts the default platform list into the DB. |

---

### `docs/`

Project documentation.

| File | Description |
| ------ | ----------- |
| `Lauch_Price_Bot_Documentation.md` | User-facing guide explaining each launcher script (`.sh`, `.bat`, build scripts) and how to run or build the project. |
| `project_structure.md` | This file. |

---

### `gui/`

PyQt6 desktop application.

| File | Description |
| ------ | ----------- |
| `__init__.py` | Package marker. |
| `main_window.py` | Main application window. Renders the product table (Product, Platform, Target Price, Shops, Best Price), handles toolbar actions (Add, Delete, Modify, Start/Stop Bot, Resolve URLs), drives the retry timer (`QTimer` every 5 min), and updates Shops cells incrementally as URLs resolve. |
| `add_product_dialog.py` | Dialog to add a new product. Lets the user pick platforms, set a target price, and either auto-resolve shop URLs or enter them manually via `ManualUrlDialog`. Prints a summary to the terminal on save. |
| `delete_product_dialog.py` | Dialog to select and delete a product and all its associated `ProductShop` rows. Prints deleted product/platform info to the terminal. |
| `modify_product_dialog.py` | Dialog to edit an existing product's name, platforms, or target price. Only prints the attributes that actually changed (before → after). |
| `bot_worker.py` | `QRunnable` that calls `check_prices()` from `bot.bot` in a background thread. Emits `started`, `finished`, and `error` signals to keep the GUI responsive. |

---

### `launcher/`

Scripts to start or build the project without needing to know the Python environment details.

| File | Description |
| ------ | ----------- |
| `start_bot.sh` | Linux/macOS — activates `venv/` and runs the headless bot (`bot/bot.py`). |
| `start_bot.bat` | Windows equivalent of `start_bot.sh`. |
| `start_gui.sh` | Linux/macOS — activates `venv/` and launches the PyQt6 GUI (`python -m gui.main_window`). |
| `start_gui.bat` | Windows equivalent of `start_gui.sh`. |
| `build_exe.sh` | Linux/macOS — uses PyInstaller to build a standalone `dist/price_bot_gui/` directory. Note: `playwright install chromium` must be run on the target machine separately. |
| `build_exe.bat` | Windows equivalent of `build_exe.sh`. |

---

### `services/`

Business logic that sits between the GUI and the scrapers/resolvers.

| File | Description |
| ------ | ----------- |
| `product_service.py` | CRUD helpers for `Product` and `ProductShop` DB rows (create, read, update, delete). |
| `resolve_urls_service.py` | Orchestrates URL resolution for a product: iterates available shops, calls the right resolver, writes the URL to `ProductShop`, and schedules retries on failure (`retry_count`, `next_retry_at`). Also exposes `retry_due_shops()` for the periodic retry timer. |
| `resolver_worker.py` | Two `QRunnable` workers: `ResolverWorker` (first-time resolution, emits `progress` signals per shop) and `RetryWorker` (re-runs failed shops whose `next_retry_at` is due). |
| `url_search_service.py` | Takes a product name + platform and returns a ranked list of candidate URLs across all shops. Used by `add_product_dialog.py` for search-based URL suggestions. |

#### `services/url_resolvers/`

One resolver per shop. Each takes a product name and platform string, navigates the shop's search UI with Playwright, scores candidates by word overlap, and returns the best product URL (or `None`).

| File | Description |
| ------ | ----------- |
| `amazon_url_resolver.py` | Searches Amazon.es, extracts `/dp/` product links, returns first match. (Improvement pending: scoring + used-listing filter.) |
| `game_url_resolver.py` | Types into Game.es autocomplete, reads up to 10 results, scores by word overlap, filters second-hand listings, visits tied pages to pick the cheapest. |
| `mediamarkt_url_resolver.py` | Searches MediaMarkt.es, presses Enter to get results page, scores product cards by name overlap. |
| `pccomponentes_url_resolver.py` | Searches PCComponentes.com without platform in query, matches `data-product-name` attribute. |
| `wakkap_url_resolver.py` | Searches Wakkap.com and returns the best-matching product link. |
| `xtralife_url_resolver.py` | Navigates Xtralife.es, applies platform filter via `PLATFORM_MAP`, scores top-5 cards by word overlap. |

---

### `shops/`

Playwright scrapers — one per shop. Each exposes a single `get_<shop>_price(url)` function that returns a `float` or `None`.

| File | Description |
| ------ | ----------- |
| `amazon.py` | Scrapes the Amazon.es product page buybox price. |
| `carrefour.py` | Scrapes Carrefour.es. Tries offer-price selectors first (`.buybox__price--current`), falls back to `.buybox__price` for regular price. Manual URL only (Cloudflare blocks the resolver). |
| `corteingles.py` | Scrapes El Corte Inglés product pages. |
| `game.py` | Scrapes Game.es. Uses `state="attached"` wait + 2 s pause to handle the JS-rendered `.buy--price` element. |
| `mediamarkt.py` | Scrapes MediaMarkt.es product pages. |
| `pccomponentes.py` | Scrapes PCComponentes.com product pages. |
| `playwright_utils.py` | Shared Playwright helpers: `chromium_page(url)` context manager that opens a browser page with a realistic user-agent; `stop_browser()` to close the shared browser instance. |
| `price_utils.py` | `extract_price(text)` — strips currency symbols, normalises decimal separators (`,` → `.`), and returns a `float`. |
| `wakkap.py` | Scrapes Wakkap.com. Tries `.price-value.offer` (sale price) first, falls back to `.price-value` for regular price. |
| `xtralife.py` | Scrapes Xtralife.es product pages. |

---

### Root files

| File | Description |
| ------ | ----------- |
| `README.md` | Project overview and quick-start instructions. |
| `requirements.txt` | Python dependencies (PyQt6, Playwright, SQLAlchemy, APScheduler, python-dotenv, etc.). |
