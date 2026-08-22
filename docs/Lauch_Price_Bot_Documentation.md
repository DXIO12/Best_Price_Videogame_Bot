# Launch Price Bot — Documentation

Two folders sit next to each other and are easy to confuse, so first the one-line rule:

> **`launcher/` runs the app from source on this machine. `packaging/` produces a
> distributable for machines that have no Python.**

| | `launcher/` | `packaging/` |
| --- | --- | --- |
| Does what | starts / stops processes | generates an artifact |
| Run when | every time you use the app | once per release |
| Needs | `venv/` and this checkout | `venv/` + PyInstaller |
| Produces | live processes | `dist/price_bot_gui/` |
| For whom | whoever has the repo | the end user, no Python |

The folder was called `build/` until this became a problem twice over: `build` is also
PyInstaller's own default working directory, so a build dropped its temporary tree on top of
the scripts, and `.gitignore` ignored the name — new files added there were invisible to git.

Every script changes to the **project root** before doing anything. That root is the import
root: all internal imports are absolute and `application.`-prefixed, so nothing ever descends
into `application/`.

---

## Scripts overview

### `launcher/`

| File | Platform | Purpose |
|------|----------|---------|
| `start_gui.sh` / `.bat` | Linux · macOS / Windows | Run the desktop GUI |
| `start_bot.sh` / `.bat` | Linux · macOS / Windows | Run the headless price-checking bot |
| `stop_bot.sh` / `.bat` | Linux · macOS / Windows | Stop the headless bot |
| `install_launcher.sh` | Linux | Add "Price Bot" to the application menu |
| `install_launcher.ps1` | Windows | Add "Price Bot" to the Start Menu |
| `price-bot.desktop.in` | Linux | Template the installer fills in — not run directly |

### `packaging/`

| File | Platform | Purpose |
|------|----------|---------|
| `build_exe.sh` | Linux · macOS | Build a standalone GUI executable with PyInstaller |
| `build_exe.bat` | Windows | Build a standalone GUI `.exe` |
| `make_icons.py` | any | Regenerate `assets/price-bot.png` and `.ico` from the SVG |

---

## First-time setup

### 1. Create and activate the virtual environment

```bash
python -m venv venv
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate.bat         # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

The second line is not optional: Playwright ships no browser of its own, and every scraper
and URL resolver needs Chromium.

### 3. Create the `.env` file

In the project root, with your Telegram credentials:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

Gitignored, and never to be committed. The launchers tighten its permissions on every start
(`chmod 600`, or `icacls` on Windows).

### 4. Initialise the database — optional

The launchers do this automatically. Run it by hand only to set up the database without
starting anything:

```bash
python -m application.database.init_db
```

It creates all tables and applies pending column migrations. Safe to run repeatedly.

---

## Recommended launch order

### Using the GUI (recommended)

```
1. launcher/start_gui.sh     ← opens the desktop app
2. Click "Settings Bot"      ← configure check interval, notifications, etc.
3. Click "Add Product"       ← add the products you want to track
4. Click "Update URLs"       ← auto-resolve shop URLs for new products
5. Click "Start Bot"         ← run a price check immediately
```

> Clicking **Start Bot** before configuring anything opens the **Settings Bot** dialog first,
> and starts the bot once you save.

### Headless bot only (no GUI)

For a server or a background machine. Products and settings **must already be configured**
through the GUI: the headless bot has no configuration interface and falls back to defaults.

```
1. launcher/start_gui.sh     ← configure products + settings (one time)
2. launcher/start_bot.sh     ← run the bot headlessly
3. launcher/stop_bot.sh      ← stop it
```

---

## `start_gui.sh` / `start_gui.bat`

Launches the **PyQt6 desktop application**. Automatically:

1. Changes to the project root and activates `venv/`
2. Restricts `.env` to the current user
3. Exports `PRICE_BOT_PROCESS=gui`, so the database step logs into the GUI's own log file
   rather than a stray `price_bot_app.log`
4. Runs `python -m application.database.init_db`
5. Opens the main window with `python -m application.gui.main_window`

Browsers follow the **debug_mode** setting (Settings → Application): visible in debug,
headless in release. Nothing is forced here.

```bash
./launcher/start_gui.sh          # Linux / macOS
launcher\start_gui.bat           # Windows
```

---

## `start_bot.sh` / `start_bot.bat`

Runs `application/bot/bot.py` — the headless price-checking bot — with no window. Same setup
as above, plus `PRICE_BOT_DEBUG=0` and `PRICE_BOT_HEADLESS=1`, which pin it to Release mode
regardless of the stored setting.

Configuration comes from the `settings` table (written by the GUI's Settings dialog). With no
settings row it falls back to:

| Setting | Default |
| ------- | ------- |
| Check interval | 30 min |
| Notify only best price | OFF |
| Repeat notifications | ON |
| Repeat after | 90 min |

---

## `stop_bot.sh` / `stop_bot.bat`

Stops the bot started by `start_bot`. Prints `Bot stopped.` or `Bot was not running.`

Both look up the process by command line, and both then **confirm the match is a python
process** before signalling it. That check is not decoration: a bare `pkill -f "bot.bot"`
tests its pattern against every command line on the machine, the shell running the script
included, and will happily kill its own caller and report success. The Windows version had the
same flaw through PowerShell's own command line.

The GUI's built-in Start/Stop buttons are unrelated to these scripts — they control a worker
thread inside the GUI process.

---

## Desktop launcher

Adds a normal application entry so the GUI opens with a double click, no terminal involved.

### Linux

```bash
./launcher/install_launcher.sh              # install
./launcher/install_launcher.sh --uninstall  # remove
```

Writes `~/.local/share/applications/price-bot.desktop`, installs the icon into the hicolor
theme, and refreshes the menu caches. **Price Bot** then appears in the application menu:

* **left click** — opens the GUI
* **right click** — *Start bot (headless)* and *Stop bot*

One entry rather than three, via `.desktop` actions.

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File launcher\install_launcher.ps1 -Desktop
powershell -ExecutionPolicy Bypass -File launcher\install_launcher.ps1 -Uninstall
```

Creates a Start Menu shortcut (`-Desktop` adds one on the desktop too). The shortcut targets
`venv\Scripts\pythonw.exe` rather than `start_gui.bat`, because a `.bat` opens a console
window on every launch. Debug mode still gets a real console — the app allocates one itself
when none is attached.

Because it bypasses `start_gui.bat`, the installer does that script's two setup steps once, at
install time: initialising the database and restricting `.env`.

---

## `packaging/build_exe.sh` / `.bat`

Builds a standalone distributable of the GUI with [PyInstaller](https://pyinstaller.org/):

1. Activates the virtual environment and installs PyInstaller if missing
2. Regenerates the icon assets from `assets/price-bot.svg`
3. Stages a copy of `application/` with the database files stripped out
4. Packages everything into `dist/price_bot_gui/`

```bash
./packaging/build_exe.sh         # Linux / macOS
packaging\build_exe.bat          # Windows
```

### Output

```
dist/
└── price_bot_gui/
    ├── price_bot_gui        ← executable (price_bot_gui.exe on Windows)
    ├── _internal/           ← bundled Python runtime and dependencies
    ├── tracker.db           ← created on first run, next to the executable
    └── logs/                ← created on first run
```

### Why the source tree is bundled as data

The `--add-data "application:application"` entry looks redundant beside PyInstaller's import
analysis, but it is load-bearing. Two places read the tree off disk at runtime and would find
nothing without it:

* `gui/add_product_dialog.py` builds the shop dropdown by listing `shops/*.py` — inside a
  bundle those files exist only because they were copied in.
* `language_selector/translator.py` globs `languages/*.json` for the language dropdown.

The copy is *staged* first, with `*.db` removed, so no database ships. An earlier version of
this script instead deleted `database/tracker.db` before building — which, once the
`application/` refactor moved the file, would have meant deleting the live database on every
build.

### The distribution is self-contained

Chromium ships inside it. The build downloads it straight into
`dist/price_bot_gui/browsers/` by pointing `PLAYWRIGHT_BROWSERS_PATH` at that folder while
running Playwright's own installer, and `runtime_config.use_bundled_browsers()` repoints
Playwright there at startup.

That matters more than it looks. Without it, the target machine hits Playwright's own error —
*"Please run: playwright install"* — which is a **Python** command, on a machine that by
definition has no Python. There is no way for the recipient to act on it.

Only the full Chromium build ships, not the "headless shell": every launch in the codebase
passes `channel="chromium"`, so the shell would be 257 MB that never runs. Keep it that way —
a launch without that argument fails in the distribution with a missing-executable error, even
though it works fine from a source checkout where the shell is in the local cache.

**Telegram credentials come from the Settings dialog**, not from a `.env`. Someone running a
distributed copy has no source tree to drop one into, and on Windows a file named `.env` is
genuinely hard to create in Explorer. `notifier.get_telegram_credentials()` reads the database
first and falls back to the environment, so a developer checkout with a `.env` keeps working
unchanged.

If you *do* put a `.env` next to a frozen executable, note that it is resolved from the
**working directory** rather than by walking up from the source file — that is what
`find_dotenv()` does when `sys.frozen` is set.

---

## Releasing to other people

```bash
./packaging/build_exe.sh          # build + download Chromium into the distribution
./packaging/make_release.sh       # zip it, with the end-user guide inside
```

`make_release.sh` refuses to package a build containing a `*.db` or a `.env` — both are things
that accumulate in `dist/` from running the build output, and either one would hand a tester
someone else's data or a live bot token. It also refuses if `browsers/` is missing.

The zip is ~300 MB (~670 MB unpacked). The recipient unzips it, opens the executable, and
pastes a Telegram token into Settings; `packaging/DISTRIBUTION_README.md` travels inside the
zip as `LEEME.md` and walks them through it.

### Windows builds

**PyInstaller does not cross-compile.** A Windows `.exe` can only be produced on Windows.
`.github/workflows/build-distribution.yml` builds both platforms on GitHub's runners — trigger
it from the Actions tab, or push a `v*` tag, and download the two artifacts from the run.

The CI build is functionally identical to a local one despite three gitignored files being
absent from the runner (`shops/fnac.py` and the Carrefour / Corte Inglés URL resolvers):
nothing imports them, and `fnac.py` is on the shop dropdown's exclusion list either way.

---

## Requirements

- Python 3.11+ with a virtual environment at `venv/`
- `pip install -r requirements.txt`, then `playwright install chromium`
- A `.env` in the project root with `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
