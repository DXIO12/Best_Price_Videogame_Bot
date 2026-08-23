"""SQLAlchemy engine, session factory and declarative base.

The database file name is no longer fixed. It defaults to ``tracker.db`` but can
be renamed from Settings → Data, and the chosen name is remembered in a pointer
file sitting next to the database itself.

**Not in config.json.** That was the first attempt and it was wrong: config.json
is tracked by git, so a branch switch reverted the pointer, the app looked for a
database that was no longer there, SQLite created an empty one without a word,
and every product appeared to have vanished. The pointer belongs beside the data
it names, outside version control — hence ``active_db.txt`` and the .gitignore
entry for it.
"""

import os
import sys
from pathlib import Path

from application.config.logger import get_logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

_log = get_logger("database")

DEFAULT_DB_NAME = "tracker.db"

# One line of text holding the database file name in use. Gitignored, and kept
# in the same directory as the database so the two travel together.
POINTER_NAME = "active_db.txt"


def db_dir() -> Path:
    """Directory holding the database file.

    Running as a PyInstaller bundle: next to the executable, so the DB lives
    outside the read-only ``_internal/`` directory. From source: beside this
    module, where it has always been."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def sanitize_db_name(name) -> str | None:
    """Return ``name`` as a usable database file name, or None if it is not one.

    Rejects anything that is not a bare file name — a value carrying ``/``,
    ``\\`` or ``..`` would let a config.json edit point the engine anywhere on
    disk. ``.db`` is appended when missing, so "juegos" and "juegos.db" both
    work from the rename dialog."""
    if not isinstance(name, str):
        return None
    cleaned = name.strip()
    if not cleaned or cleaned != Path(cleaned).name or cleaned in (".", ".."):
        return None
    if not cleaned.lower().endswith(".db"):
        cleaned += ".db"
    return cleaned


def pointer_path() -> Path:
    """The file recording which database is in use."""
    return db_dir() / POINTER_NAME


def write_pointer(name: str) -> None:
    """Record ``name`` as the database to open from now on."""
    pointer_path().write_text(name + "\n", encoding="utf-8")


def database_name() -> str:
    """Which database file to open: env override, then pointer, then default.

    ``PRICE_BOT_DB`` wins outright, matching how PRICE_BOT_DEBUG, PRICE_BOT_LANG
    and PRICE_BOT_LOG_DIR already work — it is what lets a test point somewhere
    harmless without touching the pointer."""
    override = sanitize_db_name(os.environ.get("PRICE_BOT_DB", ""))
    if override:
        return override

    try:
        stored = pointer_path().read_text(encoding="utf-8").strip()
    except OSError:
        stored = ""
    return sanitize_db_name(stored) or DEFAULT_DB_NAME


def database_path() -> Path:
    """Full path of the database file currently in use."""
    return db_dir() / database_name()


def warn_if_missing(path: Path) -> None:
    """Say something before conjuring a database out of nothing.

    A missing file is normal exactly once, on a first run. Every other time it
    means the app is pointed at the wrong place — and SQLite's habit of creating
    an empty database rather than failing turns that into "all my products are
    gone". Naming the neighbours makes it a two-second fix instead of a scare."""
    if path.exists():
        return

    siblings = sorted(
        sibling.name for sibling in path.parent.glob("*.db")
        if sibling.name != path.name
    )
    if siblings:
        _log.warning(
            f"{path.name} does not exist: an EMPTY database is about to be created. "
            f"Other databases in {path.parent}: {', '.join(siblings)}. "
            f"If your products live in one of those, put its name in "
            f"{POINTER_NAME} (or set PRICE_BOT_DB) and restart."
        )


DATABASE_URL = f"sqlite:///{database_path()}"

warn_if_missing(database_path())

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def active_path() -> Path:
    """The file the engine is bound to *right now*.

    Not the same question as :func:`database_path`, which answers "what does
    config.json ask for". The two agree in normal use — a rename writes the
    config and rebinds together — but only this one is the truth about which
    file queries are landing in, so it is what the Data tab reports."""
    return Path(engine.url.database)

def rebind(path: Path) -> None:
    """Point the engine — and every session handed out so far — at ``path``.

    Callers all hold the same ``SessionLocal`` object imported at module load,
    so reassigning the global would not reach them; ``sessionmaker.configure``
    mutates that shared object in place, which does. The old engine is disposed
    last, after the new one exists, so a failure to build it leaves the app
    still pointed at a working database."""
    global DATABASE_URL, engine

    previous = engine
    DATABASE_URL = f"sqlite:///{path}"
    engine = create_engine(DATABASE_URL, echo=False)
    SessionLocal.configure(bind=engine)
    previous.dispose()
