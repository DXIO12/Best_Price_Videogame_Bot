"""SQLAlchemy engine, session factory and declarative base.

The database file name is no longer fixed. It defaults to ``tracker.db`` but can
be renamed from Settings → Data, and the chosen name is remembered in
``config.json`` — the same mirror the rest of the app already uses. Everything
here goes through :func:`database_path` so a rename only has to update that one
key and call :func:`rebind`.
"""

import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DEFAULT_DB_NAME = "tracker.db"


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


def database_name() -> str:
    """Configured database file name, falling back to ``tracker.db``.

    ``runtime_config`` is imported lazily: it reaches back into this module from
    ``get_debug_mode()``, and a module-level import here would close that loop."""
    from application.config.runtime_config import read_config_json

    return sanitize_db_name(read_config_json().get("database_name")) or DEFAULT_DB_NAME


def database_path() -> Path:
    """Full path of the database file currently in use."""
    return db_dir() / database_name()


DATABASE_URL = f"sqlite:///{database_path()}"

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
