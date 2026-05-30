# Launch Price Bot — Documentation

This document describes the launcher and build scripts available in the project root.
All scripts must be run from the **project root directory** (where `bot.py` lives).

---

## Scripts overview

| File | Platform | Purpose |
|------|----------|---------|
| `start_bot.sh` | Linux / macOS | Run the headless price-checking bot |
| `start_gui.sh` | Linux / macOS | Run the desktop GUI |
| `start_bot.bat` | Windows | Run the headless price-checking bot |
| `start_gui.bat` | Windows | Run the desktop GUI |
| `build_exe.sh` | Linux / macOS | Build a standalone GUI executable with PyInstaller |
| `build_exe.bat` | Windows | Build a standalone GUI `.exe` with PyInstaller |

---

## start_bot.sh / start_bot.bat

Launches `bot.py` — the **headless price-checking bot** — without opening any window.

- Activates the project virtual environment (`venv/`).
- Runs the APScheduler-based bot that checks prices on a fixed interval and sends Telegram notifications when a product drops below its target price.
- Use this when you want the bot to run in the background or on a server without a desktop.

```bash
# Linux / macOS
./start_bot.sh

# Windows (double-click or run from cmd)
start_bot.bat
```

---

## start_gui.sh / start_gui.bat

Launches `gui/main_window.py` — the **PyQt6 desktop application**.

- Activates the project virtual environment (`venv/`).
- Opens the graphical interface where you can add, modify, and delete tracked products, view current prices, and start the bot manually via the "Start Bot" button.
- URL resolution and automatic retries run inside the GUI via background workers.

```bash
# Linux / macOS
./start_gui.sh

# Windows (double-click or run from cmd)
start_gui.bat
```

---

## build_exe.sh / build_exe.bat

Builds a **standalone distributable** of the GUI using [PyInstaller](https://pyinstaller.org/).

- Installs PyInstaller into the virtual environment if not already present.
- Packages the GUI and all Python dependencies into a self-contained folder at `dist/price_bot_gui/`.
- The resulting folder can be copied to another machine without needing Python or the virtual environment installed.

```bash
# Linux / macOS
./build_exe.sh

# Windows (double-click or run from cmd)
build_exe.bat
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

- Python 3.11+ with a virtual environment at `venv/` (created via `python -m venv venv`).
- All dependencies installed: `pip install -r requirements.txt`.
- A `.env` file in the project root containing `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (required by the bot; not needed for the GUI alone if the bot is not started).
