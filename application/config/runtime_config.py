"""Runtime execution-mode helpers (Task 2 — debug vs release mode).

Central place that resolves the app's ``debug_mode`` flag and applies its two
runtime effects:

* **Browsers**: visible (debug) vs headless (release) — see ``resolve_headless``.
* **Console/logs**: a real terminal plus a log file (debug) vs a silent
  background process that still writes one (release) — see ``init_runtime_mode``.
  The mode also picks the log level: DEBUG keeps the per-shop narration, RELEASE
  logs only what is worth reading later. The handlers themselves live in
  ``application.config.logger``; this module owns *where* the file goes.

Source of truth is the DB ``Setting.debug_mode`` column; it is mirrored to
``config.json`` for external tooling. Resolution precedence (first wins):

    PRICE_BOT_DEBUG env (``1``/``0``)  →  DB Setting.debug_mode  →
    config.json ["debug_mode"]  →  frozen default (dev=True, exe=False)

This module only depends on the stdlib and the ``application.database``
package, so it can be imported from anywhere (GUI, bot, shops, resolvers)
without import cycles.
"""

import json
import os
import sys
from pathlib import Path

from application.config.logger import get_logger, install_excepthook, setup_logging

_log = get_logger("runtime")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def base_dir() -> Path:
    """Writable base directory: next to the executable when frozen, else the
    repo root.

    This module lives in ``<repo>/application/config/runtime_config.py``, so the
    repo root is three levels up from this file. Public because
    ``language_selector.translator`` also needs it, to find user-dropped
    language catalogs."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def config_json_path() -> Path:
    """Location of the mirrored ``config.json``.

    Dev keeps the existing ``application/bot/config.json``; a frozen build writes
    next to the executable (the bundled ``bot/`` dir is read-only)."""
    if getattr(sys, "frozen", False):
        return base_dir() / "config.json"
    return base_dir() / "application" / "bot" / "config.json"


def process_name(process: str | None = None) -> str:
    """Which process this is — "gui", "bot", … — used to name its log file.

    An explicit argument wins; otherwise ``PRICE_BOT_PROCESS`` (exported by the
    launcher scripts, so the one-shot helpers they run land in the same file as
    the app they are about to start); otherwise a neutral default."""
    if process:
        return process
    return os.environ.get("PRICE_BOT_PROCESS", "").strip() or "app"


def log_dir() -> Path:
    """Where log files go: ``<base>/logs`` (repo root in dev, next to the
    executable when frozen).

    ``PRICE_BOT_LOG_DIR`` overrides it outright. That is what keeps a test
    harness out of the real log: importing ``application.gui.main_window`` runs
    ``init_runtime_mode`` at module level, and without the override its output
    is written straight into the log the running app uses."""
    override = os.environ.get("PRICE_BOT_LOG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return base_dir() / "logs"


def log_file_path(process: str | None = None) -> Path:
    """Log file for one process: ``<log_dir>/price_bot_<process>.log``.

    One file per process, not one shared file. The GUI and the background bot
    can run at the same time, and a rotating file handler is not safe across
    processes — two of them rolling the same file over can truncate each other's
    output. Separate files also stop the two narrations from interleaving."""
    return log_dir() / f"price_bot_{process_name(process)}.log"


def browsers_dir() -> Path:
    """Where a packaged build keeps its Playwright browsers: ``<base>/browsers``."""
    return base_dir() / "browsers"


def use_bundled_browsers() -> bool:
    """Point Playwright at the browsers shipped beside the executable.

    A distributed copy has no Python, so the ``playwright install chromium``
    that Playwright's own error message tells the user to run is not a command
    they can execute. The build therefore downloads Chromium straight into
    ``<dist>/browsers``, and this repoints Playwright at it.

    ``PLAYWRIGHT_BROWSERS_PATH`` set by hand always wins, so a developer can
    still override it. Returns whether the redirect was applied."""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return False

    path = browsers_dir()
    if not path.is_dir():
        return False

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
    return True


# ---------------------------------------------------------------------------
# config.json mirror (read-merge-write, preserves unrelated keys)
# ---------------------------------------------------------------------------

def read_config_json() -> dict:
    path = config_json_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_config_settings(values: dict) -> None:
    """Merge ``values`` into config.json without dropping existing keys."""
    data = read_config_json()
    data.update(values)
    path = config_json_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except OSError as exc:  # pragma: no cover - best effort mirror
        _log.error(f"Could not write config.json mirror: {exc}")


# ---------------------------------------------------------------------------
# debug_mode resolution
# ---------------------------------------------------------------------------

def _frozen_default() -> bool:
    """Dev (source) defaults to debug=True; the packaged exe to False."""
    return not getattr(sys, "frozen", False)


def get_debug_mode() -> bool:
    """Resolve the effective debug_mode flag (see module docstring for order)."""
    # 1. Explicit env override (used by launcher scripts / tests).
    env = os.environ.get("PRICE_BOT_DEBUG")
    if env is not None:
        return env.strip() == "1"

    # 2. DB Setting (source of truth). Guarded: the table may not exist yet.
    try:
        from application.database.db import SessionLocal
        from application.database.models import Setting

        db = SessionLocal()
        try:
            setting = db.query(Setting).first()
        finally:
            db.close()
        if setting is not None and setting.debug_mode is not None:
            return bool(setting.debug_mode)
    except Exception:
        pass

    # 3. config.json mirror (external tooling / pre-seeding).
    cfg = read_config_json()
    if isinstance(cfg.get("debug_mode"), bool):
        return cfg["debug_mode"]

    # 4. Frozen default.
    return _frozen_default()


def resolve_headless() -> bool:
    """Whether Playwright browsers should launch headless.

    ``PRICE_BOT_HEADLESS=1`` forces headless regardless of debug_mode (kept for
    the background-bot launchers). Otherwise headless == not debug_mode."""
    if os.environ.get("PRICE_BOT_HEADLESS") == "1":
        return True
    return not get_debug_mode()


# ---------------------------------------------------------------------------
# Console + log setup
# ---------------------------------------------------------------------------

def _attach_windows_console(debug: bool) -> None:
    """On Windows, allocate a real console when debug is on and none exists.

    No-op on other platforms, when not in debug mode, or when a console is
    already attached (e.g. launched from a terminal)."""
    if not debug or sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        if kernel32.GetConsoleWindow() != 0:
            return  # a console is already attached
        if not kernel32.AllocConsole():
            return
        # Rebind the standard streams to the freshly allocated console.
        sys.stdout = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
        sys.stderr = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
        sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
    except Exception:
        pass


_initialised = False


def init_runtime_mode(process: str | None = None) -> bool:
    """Apply the execution mode at process startup. Idempotent.

    Returns the resolved debug flag. Attaches a Windows console when needed and
    sets up logging: a rotating file for this process plus the console, at DEBUG
    or INFO depending on the mode. Creates the ``logs`` directory on demand
    (works for both a fresh source checkout and next to a packaged executable).

    ``process`` names the log file — pass "gui" or "bot" from the entry points."""
    global _initialised
    debug = get_debug_mode()
    if _initialised:
        return debug
    _initialised = True

    # Before setup_logging, which captures whatever sys.stdout is by then: on
    # Windows this is what creates the console the handler will write to.
    _attach_windows_console(debug)

    name = process_name(process)
    setup_logging(name, debug, log_file_path(name))
    install_excepthook()

    # Before any scraper runs. Only ever finds anything in a packaged build,
    # where the browsers ship next to the executable.
    if use_bundled_browsers():
        _log.info(f"Using bundled browsers: {browsers_dir()}")

    mode = "DEBUG (visible browsers, console + logs)" if debug \
        else "RELEASE (headless, background)"
    _log.info(f"Execution mode: {mode}")
    return debug
