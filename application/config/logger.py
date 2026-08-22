"""Application logging — one rotating file per process, plus the console.

Every module logs through ``get_logger("<area>")``; the handlers live on the
shared ``price_bot`` parent, so there is exactly **one** writer per destination.

Two formats on purpose:

* **console** — the message and nothing else, so a terminal session reads
  exactly like the ``print()``-based output this replaced (indentation and all).
* **file** — timestamp, level and logger name, so a log read days later says
  *when* something happened and *who* said it.

Levels:

* ``DEBUG``   per-shop narration (``Scraping Amazon…``, ``54.9€ — above target.``)
* ``INFO``    the story worth keeping: alerts, resolved URLs, user actions
* ``WARNING`` the user should know, but nothing failed (no URL set, no scraper)
* ``ERROR``   failures and unhandled exceptions

**The console always shows everything; the file is what ``debug_mode`` filters.**
A terminal is open to watch a pass run, so it gets the narration either way. In
the file that same narration is ~70% of the volume and worthless a day later, so
a release run writes only ``INFO`` and above there. A debug run keeps everything
in both.

Nothing here imports the rest of the app: ``setup_logging`` is handed the path it
should write to. That keeps ``config.runtime_config`` (which owns paths and the
debug flag) free to import this module without a cycle.
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path


LOGGER_ROOT = "price_bot"

FILE_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
CONSOLE_FORMAT = "%(message)s"

# 1 MiB × 3 backups = 4 MiB hard ceiling per process, whatever happens.
MAX_BYTES = 1_048_576
BACKUP_COUNT = 3

RULE_WIDTH = 35


# ---------------------------------------------------------------------------
# Loggers
# ---------------------------------------------------------------------------

class _AppLogger(logging.Logger):
    """Adds the two console-only helpers the old output relied on.

    Separators and blank lines are what made the terminal narration readable,
    but in a timestamped file they are pure noise — every line already carries
    its own boundary. Both go out at INFO so the console still shows them, and
    ``_ConsoleOnlyFilter`` keeps them out of the file."""

    def rule(self, char: str = "=", width: int = RULE_WIDTH) -> None:
        self.info(char * width, extra={"console_only": True})

    def blank(self) -> None:
        self.info("", extra={"console_only": True})


class _ConsoleOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "console_only", False)


def get_logger(name: str) -> _AppLogger:
    """Return the ``price_bot.<name>`` logger. Safe to call at import time —
    it only creates the object; ``setup_logging`` attaches the handlers later.

    The logger class is swapped only for the duration of the call, so the extra
    methods land on our loggers without leaving a global override in place for
    every third-party library that creates one afterwards."""
    previous = logging.getLoggerClass()
    logging.setLoggerClass(_AppLogger)
    try:
        return logging.getLogger(f"{LOGGER_ROOT}.{name}")
    finally:
        logging.setLoggerClass(previous)


# ---------------------------------------------------------------------------
# stdout / stderr capture
# ---------------------------------------------------------------------------

class _StreamToLogger:
    """Write-only stream that funnels whatever is written to it into a logger.

    Third-party output (Playwright, Qt, APScheduler) and any stray ``print``
    still has to reach the log file, and this is what gets it there without
    giving the file a second writer.

    ``encoding``, ``errors`` and ``isatty`` are not decoration. Python's
    traceback printer skips a ``sys.stderr`` replacement that has no
    ``encoding``, and without them an exception escaping a Qt slot aborts the
    process with the traceback going nowhere at all — not the console, not the
    log. That was learned the hard way; do not drop them."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, logger: logging.Logger, level: int):
        self._logger = logger
        self._level = level
        self._buffer = ""

    def write(self, data) -> int:
        if not data:
            return 0
        text = data if isinstance(data, str) else str(data)
        self._buffer += text
        # print() writes the text and the newline separately, so only complete
        # lines are emitted; the tail waits for its newline (or a flush).
        *lines, self._buffer = self._buffer.split("\n")
        for line in lines:
            if line.strip():
                self._logger.log(self._level, line)
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self._logger.log(self._level, self._buffer)
        self._buffer = ""

    def isatty(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_logging(process: str, debug: bool, log_path: Path) -> None:
    """Attach the file and console handlers and start capturing the streams.

    ``process`` ("gui", "bot", …) only names the session header — the file it
    goes to is already decided by ``log_path``. Idempotent: a second call just
    re-applies the levels.

    **The level lives on the handlers, not on the logger**, because the console
    and the file want different things. Watching a pass run — "Scraping Game…",
    each price as it lands, the parallel progress counter — is the whole point of
    having a terminal open, and that is true whether or not the run is a debug
    one. Keeping every record in the *file* is a different question: there the
    same narration is 70% of the volume and says nothing once the pass is over.
    Putting the level on the logger tied the two together, and since ``debug``
    also decides whether the browsers are visible, a readable terminal meant four
    Chromium windows on screen."""
    app = logging.getLogger(LOGGER_ROOT)
    app.setLevel(logging.DEBUG)  # handlers below decide what survives

    if app.handlers:
        for handler in app.handlers:
            if isinstance(handler, logging.handlers.RotatingFileHandler):
                handler.setLevel(logging.DEBUG if debug else logging.INFO)
        return

    # Records reach the file through this logger's own handler. Without this,
    # the root handler added below would write every one of them a second time.
    app.propagate = False

    file_handler = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
            errors="replace",
        )
        file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT, DATE_FORMAT))
        file_handler.addFilter(_ConsoleOnlyFilter())
        app.addHandler(file_handler)
    except OSError:
        # A read-only or missing directory must never stop the app from running.
        file_handler = None

    # Grab the real stdout *before* redirecting it, or the console handler would
    # write into the logger it is serving.
    console_stream = sys.stdout
    if console_stream is not None:  # a --windowed exe has no stdout at all
        console = logging.StreamHandler(console_stream)
        # Always DEBUG: a terminal is open precisely to watch the run happen.
        console.setLevel(logging.DEBUG)
        console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
        app.addHandler(console)

    # Third-party warnings (Playwright, SQLAlchemy, APScheduler) land in the same
    # file. WARNING, not DEBUG: their debug output would drown ours.
    if file_handler is not None:
        root = logging.getLogger()
        root.setLevel(logging.WARNING)
        root.addHandler(file_handler)

    sys.stdout = _StreamToLogger(get_logger("stdout"), logging.INFO)
    sys.stderr = _StreamToLogger(get_logger("stderr"), logging.ERROR)

    mode = "DEBUG" if debug else "RELEASE"
    get_logger("runtime").info(
        f"=== price-bot {process} | {mode} | pid {os.getpid()} ==="
    )


def install_excepthook() -> None:
    """Log unhandled exceptions instead of letting Qt abort the process.

    When an exception escapes a Qt slot and ``sys.excepthook`` is still the
    default one, PyQt calls ``qFatal()``: the process dies with a bare
    "Unhandled Python exception" and the traceback goes to the C-level stderr,
    so nothing reaches the log. Installing our own hook makes PyQt hand the
    exception over instead, so it is logged and the GUI survives."""
    log = get_logger("runtime")

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.error("Unhandled exception:", exc_info=(exc_type, exc, tb))

    sys.excepthook = hook
