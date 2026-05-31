# Dependencies

All packages are listed in `requirements.txt` at the project root.
Install with:

```bash
pip install -r requirements.txt
```

---

## Runtime dependencies

| Package | Version | Used in | Purpose |
| ------- | ------- | ------- | ------- |
| `PyQt6` | latest | `gui/` | Desktop GUI framework. All windows, dialogs, tables, and background workers. |
| `SQLAlchemy` | latest | `database/` | ORM for SQLite. Manages all DB models, sessions, and queries. |
| `playwright` | latest | `shops/`, `services/url_resolvers/` | Browser automation for scraping shop prices and resolving product URLs. Requires `playwright install chromium` after install. |
| `requests` | latest | `bot/notifier.py` | HTTP client for sending Telegram notifications. |
| `APScheduler` | latest | `bot/bot.py` | Scheduler for running price checks on a fixed interval when the bot runs headlessly. |
| `python-dotenv` | latest | `bot/bot.py` | Loads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from the `.env` file at startup. |

---

## Post-install step

Playwright downloads browser binaries separately. After `pip install -r requirements.txt`, run:

```bash
playwright install chromium
```

This only needs to be done once per environment. On a distributed executable (`build_exe.sh`), it must also be run on the target machine.
