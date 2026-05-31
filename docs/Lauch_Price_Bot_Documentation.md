# Launch Price Bot — Documentation

This document describes the launcher scripts available in `launcher/` and the correct order to follow for first-time setup and daily use.
All scripts automatically change to the **project root directory** before executing.

---

## Scripts overview

| File | Platform | Purpose |
|------|----------|---------|
| `start_gui.sh` | Linux / macOS | Run the desktop GUI |
| `start_gui.bat` | Windows | Run the desktop GUI |
| `start_bot.sh` | Linux / macOS | Run the headless price-checking bot (no GUI) |
| `start_bot.bat` | Windows | Run the headless price-checking bot (no GUI) |
| `build_exe.sh` | Linux / macOS | Build a standalone GUI executable with PyInstaller |
| `build_exe.bat` | Windows | Build a standalone GUI `.exe` with PyInstaller |

---

## First-time setup

Before using any launcher, complete these steps once:

### 1. Create and activate the virtual environment

```bash
python -m venv venv
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate.bat         # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create the `.env` file

Create a file named `.env` in the project root with your Telegram credentials:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

This file is required by the bot to send price alert notifications. It is gitignored and should never be committed.

### 4. Initialise the database (optional — launchers do this automatically)

The launchers run `python -m database.init_db` automatically before starting. You only need to run it manually if you want to set up the database without launching anything else:

```bash
python -m database.init_db
```

This creates all tables and applies any pending column migrations. It is safe to run multiple times.

---

## Recommended launch order

### Using the GUI (recommended)

The GUI is the primary way to manage products and start the bot.

```
1. launcher/start_gui.sh     ← opens the desktop app
2. Click "Settings Bot"      ← configure check interval, notifications, etc.
3. Click "Add Product"       ← add the products you want to track
4. Click "Update URLs"       ← auto-resolve shop URLs for new products
5. Click "Start Bot"         ← run a price check immediately
```

> If you click **Start Bot** without having configured settings first, the app will automatically open the **Settings Bot** dialog and launch the bot once you save.

### Headless bot only (no GUI)

Use this when you want the bot to run on a server or in the background, without a desktop.
Products and settings **must already be configured** via the GUI beforehand, since the headless bot has no configuration interface of its own and falls back to safe defaults if settings are missing.

```
1. launcher/start_gui.sh     ← configure products + settings (one time)
2. launcher/start_bot.sh     ← run the bot headlessly on any machine
```

---

## start_gui.sh / start_gui.bat

Launches the **PyQt6 desktop application**.

Steps performed automatically:

1. Activates the virtual environment (`venv/`)
2. Runs `python -m database.init_db` (creates tables + applies migrations)
3. Opens the main window

From the GUI you can:

- **Add / Delete / Modify** tracked products
- **Update URLs** — auto-resolve missing shop URLs for all products
- **Settings Bot** — configure how often the bot runs, notification behaviour, and repeat cooldowns
- **Start Bot** — trigger an immediate price check and Telegram notification if a target is hit

```bash
# Linux / macOS
./launcher/start_gui.sh

# Windows (double-click or run from cmd)
launcher\start_gui.bat
```

---

## start_bot.sh / start_bot.bat

Launches `bot/bot.py` — the **headless price-checking bot** — without opening any window.

Steps performed automatically:

1. Activates the virtual environment (`venv/`)
2. Runs `python -m database.init_db` (creates tables + applies migrations)
3. Starts the APScheduler-based bot

The bot reads its configuration from the `settings` table in the database (populated via the **Settings Bot** dialog in the GUI). If no settings row exists, it falls back to these defaults:

| Setting | Default |
| ------- | ------- |
| Check interval | 30 min |
| Notify only best price | OFF |
| Repeat notifications | ON |
| Repeat after | 90 min |

```bash
# Linux / macOS
./launcher/start_bot.sh

# Windows (double-click or run from cmd)
launcher\start_bot.bat
```

---

## build_exe.sh / build_exe.bat

Builds a **standalone distributable** of the GUI using [PyInstaller](https://pyinstaller.org/).

Steps performed:

1. Activates the virtual environment
2. Installs PyInstaller if not already present
3. Packages the GUI, bot, database, shops, and services into `dist/price_bot_gui/`

The resulting folder can be copied to another machine without needing Python or the virtual environment installed.

```bash
# Linux / macOS
./launcher/build_exe.sh

# Windows (double-click or run from cmd)
launcher\build_exe.bat
```

### Output

```
dist/
└── price_bot_gui/
    ├── price_bot_gui        ← executable (Linux) or price_bot_gui.exe (Windows)
    ├── _internal/           ← bundled Python runtime and dependencies
    └── ...
```

### Important: Playwright browsers are not bundled

Playwright browser binaries (~150 MB each) cannot be included inside the PyInstaller bundle.
After copying `dist/price_bot_gui/` to a new machine, run the following command **once** before launching the app:

```bash
playwright install chromium
```

Without this step, URL resolution and price scraping will fail on the target machine.

---

## Requirements

- Python 3.11+ with a virtual environment at `venv/` (created via `python -m venv venv`)
- All dependencies installed: `pip install -r requirements.txt`
- A `.env` file in the project root containing `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
