# Dependencies

All packages are listed in `requirements.txt` at the project root.
Install with:

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Runtime dependencies

Six, and the list is exact: these are every third-party top-level import under
`application/`. `requirements.txt` is hand-kept rather than `pip freeze`d, because a working
venv also accumulates packages nothing in the project imports.

| Package | Version | Used in | Purpose |
| ------- | ------- | ------- | ------- |
| `PyQt6` | 6.11.0 | `application/gui/` | Desktop GUI framework. All windows, dialogs, tables, and background workers. Also renders the launcher icon assets in `packaging/make_icons.py`, via the `QtSvg` module it ships with. |
| `SQLAlchemy` | 2.0.49 | `application/database/` | ORM for SQLite. Manages all DB models, sessions, and queries. |
| `playwright` | 1.59.0 | `application/shops/`, `application/services/url_resolvers/` | Browser automation for scraping shop prices and resolving product URLs. Requires `playwright install chromium` after install. |
| `requests` | 2.33.1 | `application/notifications/telegram.py` | HTTP client for sending Telegram notifications. |
| `APScheduler` | 3.11.2 | `application/bot/bot.py` | Scheduler for running price checks on a fixed interval when the bot runs headlessly. |
| `python-dotenv` | 1.2.2 | `application/bot/bot.py` | Loads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from the `.env` file at startup. |

## Build-only

| Package | Used in | Purpose |
| ------- | ------- | ------- |
| `pyinstaller` | `packaging/build_exe.sh` / `.bat` | Produces `dist/price_bot_gui/`. Not in `requirements.txt`: the build scripts install it on demand, so running the app never needs it. |

---

## Post-install step

Playwright downloads browser binaries separately. After `pip install -r requirements.txt`, run:

```bash
playwright install chromium
```

Once per environment. On a distributed executable it must also be run on the target machine —
the browsers are ~150 MB and are not bundled.

---

## A note on `python-dotenv` and frozen builds

`load_dotenv()` finds the `.env` differently depending on how the app was started:

* **From source** — it walks up from the directory of the calling module, so the repo-root
  `.env` is found from any working directory.
* **From a PyInstaller build** — `find_dotenv()` sees `sys.frozen` and uses `os.getcwd()`
  instead.

So a distributed `dist/price_bot_gui/` needs its own `.env` next to the executable, and must be
launched from that folder. There is no error when it is missing; notifications simply never
arrive.
