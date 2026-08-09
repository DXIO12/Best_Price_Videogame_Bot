"""Runtime execution-mode helpers (Task 2 — debug vs release mode).

Central place that resolves the app's ``debug_mode`` flag and applies its two
runtime effects:

* **Browsers**: visible (debug) vs headless (release) — see ``resolve_headless``.
* **Console/logs**: a real terminal + teed log file (debug) vs a silent
  background process that still writes a log file (release) — see
  ``init_runtime_mode``.

Source of truth is the DB ``Setting.debug_mode`` column; it is mirrored to
``config.json`` for external tooling. Resolution precedence (first wins):

    PRICE_BOT_DEBUG env (``1``/``0``)  →  DB Setting.debug_mode  →
    config.json ["debug_mode"]  →  frozen default (dev=True, exe=False)

This module only depends on the stdlib and the ``database`` package, so it can
be imported from anywhere (GUI, bot, shops, resolvers) without import cycles.
"""

import json
import os
import sys
import traceback
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _base_dir() -> Path:
    """Writable base directory: next to the executable when frozen, else the
    repo root.

    This module lives in ``<repo>/config/runtime_config.py``, so the repo root
    is two levels up from this file."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_json_path() -> Path:
    """Location of the mirrored ``config.json``.

    Dev keeps the existing ``bot/config.json``; a frozen build writes next to
    the executable (the bundled ``bot/`` dir is read-only)."""
    if getattr(sys, "frozen", False):
        return _base_dir() / "config.json"
    return _base_dir() / "bot" / "config.json"


def log_file_path() -> Path:
    """Log file location: ``<base>/logs/price_bot.log`` (repo root in dev, next
    to the executable when frozen). The ``logs`` dir is created on demand by
    ``init_runtime_mode``."""
    return _base_dir() / "logs" / "price_bot.log"


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
        print(f"[runtime_config] Could not write config.json mirror: {exc}")


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
        from database.db import SessionLocal
        from database.models import Setting

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

class _Tee:
    """Minimal write-only stream that fans out to several underlying streams.

    Tolerates a ``None`` primary stream (a windowed exe has no stdout), so
    output still reaches the log file in release mode."""

    # Python's traceback printer skips a stderr replacement that has no
    # ``encoding`` attribute — without these, an unhandled exception in a Qt
    # slot aborts the process with no traceback anywhere (neither console nor
    # log), which makes such crashes almost impossible to diagnose.
    encoding = "utf-8"
    errors = "replace"

    def __init__(self, *streams):
        self._streams = [s for s in streams if s is not None]

    def write(self, data):
        for stream in self._streams:
            try:
                stream.write(data)
                stream.flush()
            except Exception:
                pass
        return len(data)

    def flush(self):
        for stream in self._streams:
            try:
                stream.flush()
            except Exception:
                pass

    def isatty(self):
        return False


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


def _install_excepthook() -> None:
    """Log unhandled exceptions instead of letting Qt abort the process.

    When an exception escapes a Qt slot and ``sys.excepthook`` is still the
    default one, PyQt calls ``qFatal()``: the process dies with a bare
    "Unhandled Python exception" / "Aborted (core dumped)" and the traceback
    goes straight to the C-level stderr, so nothing reaches the log file — the
    crash is effectively undiagnosable. Installing our own hook makes PyQt hand
    the exception to us instead, so the traceback is teed to the log and the
    GUI survives."""
    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        print("[error] Unhandled exception:", file=sys.stderr)
        traceback.print_exception(exc_type, exc, tb, file=sys.stderr)

    sys.excepthook = hook


_initialised = False


def init_runtime_mode() -> bool:
    """Apply the execution mode at process startup. Idempotent.

    Returns the resolved debug flag. Attaches a Windows console when needed and
    tees stdout/stderr to ``logs/price_bot.log`` so release mode is never
    silent. Creates the ``logs`` directory on demand (works for both a fresh
    source checkout and next to a packaged executable)."""
    global _initialised
    debug = get_debug_mode()
    if _initialised:
        return debug
    _initialised = True

    _attach_windows_console(debug)

    try:
        log_path = log_file_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
        sys.stdout = _Tee(sys.stdout, log_fh)
        sys.stderr = _Tee(sys.stderr, log_fh)
    except Exception:
        pass

    _install_excepthook()

    mode = "DEBUG (visible browsers, console + logs)" if debug \
        else "RELEASE (headless, background)"
    print(f"[runtime_config] Execution mode: {mode}")
    return debug
