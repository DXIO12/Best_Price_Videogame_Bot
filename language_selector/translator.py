"""Application translations.

Every user-facing string lives in a JSON catalog under ``languages/``, one file
per language, addressed with a dotted key::

    tr("main.btn_add_product")            ->  "Add Product"
    tr("main.status_resolving", count=3)  ->  "Resolving URLs for 3 product(s)..."

Adding a language is dropping a new ``<code>.json`` next to the existing ones —
there is no code to change. The catalog names itself through its ``_meta.name``
entry, which is what the Settings combo box shows.

Source of truth for the active language is the DB ``Setting.language`` column;
it is mirrored to ``config.json`` like the other settings. Resolution
precedence (first wins) deliberately mirrors ``runtime_config.get_debug_mode``:

    PRICE_BOT_LANG env  →  DB Setting.language  →  config.json ["language"]  →
    system locale (only when a catalog for it exists)  →  "en"

Lookups fall back active catalog → English → the key itself, so a missing or
malformed entry shows up as visible-but-harmless text instead of raising inside
a Qt slot (where PyQt turns an exception into an uncatchable ``qFatal``).

Console/log output is deliberately NOT translated: it is diagnostic, and log
files are easier to compare and search when they read the same everywhere.
"""

import json
import os
from pathlib import Path

from config.runtime_config import base_dir, read_config_json


DEFAULT_LANGUAGE = "en"

# Catalogs already read from disk, keyed by language code.
_catalogs: dict[str, dict] = {}

# None until something resolves the language; get_language() does it on demand,
# so the standalone bot works without an explicit init_language() call.
_active_code: str | None = None

# Keys already reported as missing, so one looked up on every table rebuild is
# only printed once instead of flooding the log.
_reported_missing: set[str] = set()


# ---------------------------------------------------------------------------
# Catalog files
# ---------------------------------------------------------------------------

def _language_dirs() -> list[Path]:
    """Where catalogs are looked for, highest priority first.

    The external directory comes first so a user can drop a ``fr.json`` next to
    the executable — or override a bundled translation — without a rebuild. The
    bundled one sits beside this module, which resolves correctly both from a
    source checkout and from inside a PyInstaller bundle."""
    return [
        base_dir() / "languages",
        Path(__file__).resolve().parent / "languages",
    ]


def _catalog_path(code: str) -> Path | None:
    for directory in _language_dirs():
        path = directory / f"{code}.json"
        if path.is_file():
            return path
    return None


def _catalog(code: str) -> dict:
    """Read and cache one catalog. Returns {} when it cannot be read, which the
    fallback chain in tr() then handles."""
    if code in _catalogs:
        return _catalogs[code]

    data: dict = {}
    path = _catalog_path(code)
    if path is not None:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[lang] Could not read {path}: {exc}")

    _catalogs[code] = data
    return data


def available_languages() -> list[tuple[str, str]]:
    """Every catalog found on disk, as ``(code, display name)`` sorted by name.

    The display name is the catalog's own ``_meta.name``, so a new language
    appears in the Settings dropdown with nothing here to edit."""

    found: dict[str, str] = {}
    for directory in _language_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            code = path.stem
            if code in found:
                continue  # an earlier (higher priority) directory already won
            meta = _catalog(code).get("_meta") or {}
            found[code] = meta.get("name") or code.upper()
    return sorted(found.items(), key=lambda item: item[1].lower())


# ---------------------------------------------------------------------------
# Language resolution
# ---------------------------------------------------------------------------

def _system_language() -> str | None:
    """The OS locale's language code, but only when we ship a catalog for it.

    Qt is imported lazily so the standalone CLI bot never pulls in QtCore just
    to answer this."""
    try:
        from PyQt6.QtCore import QLocale

        code = QLocale.system().name().split("_")[0]
    except Exception:
        return None
    return code if _catalog_path(code) else None


def resolve_language() -> str:
    """Resolve the effective language code (see module docstring for order)."""
    # 1. Explicit env override (launcher scripts / tests).
    env = (os.environ.get("PRICE_BOT_LANG") or "").strip()
    if env and _catalog_path(env):
        return env

    # 2. DB Setting (source of truth). Guarded like get_debug_mode(): a
    #    tracker.db from before this feature has no "language" column, and an
    #    unguarded query would raise "no such column" and abort startup.
    try:
        from database.db import SessionLocal
        from database.models import Setting

        db = SessionLocal()
        try:
            setting = db.query(Setting).first()
        finally:
            db.close()
        if setting is not None and setting.language:
            return setting.language
    except Exception:
        pass

    # 3. config.json mirror (external tooling / pre-seeding).
    cfg = read_config_json()
    language = cfg.get("language")
    if isinstance(language, str) and language:
        return language

    # 4. System locale, when it is one we actually ship.
    system = _system_language()
    if system:
        return system

    # 5. English.
    return DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    """Make ``code`` the active language.

    An unknown code is accepted rather than rejected: every lookup then falls
    back to English, and the stored preference survives a catalog file being
    temporarily missing."""
    global _active_code
    _active_code = code
    _catalog(code)  # warm the cache, and surface a read error once, here
    _reported_missing.clear()


def get_language() -> str:
    """The active language code, resolving it on first use if needed."""
    if _active_code is None:
        init_language()
    return _active_code


def init_language() -> str:
    """Resolve and activate the language at startup. Returns the code."""
    code = resolve_language()
    set_language(code)
    print(f"[lang] Language: {code}")
    return code


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def _lookup(catalog: dict, key: str) -> str | None:
    """Walk a dotted key through a nested catalog. None when it is absent or
    does not bottom out in a string."""
    node = catalog
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def tr(key: str, **kwargs) -> str:
    """Translate ``key`` into the active language.

    ``kwargs`` are substituted with ``str.format``. They are named rather than
    positional so a translation can reorder them freely."""
    code = get_language()

    text = _lookup(_catalog(code), key)
    if text is None:
        text = _lookup(_catalog(DEFAULT_LANGUAGE), key)
        if text is None:
            if key not in _reported_missing:
                _reported_missing.add(key)
                print(f"[lang] Missing translation key: {key}")
            return key

    if not kwargs:
        return text

    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        # The translation names a placeholder the caller did not pass. Use the
        # English text rather than letting the format error escape into the GUI.
        english = _lookup(_catalog(DEFAULT_LANGUAGE), key)
        if english is not None and english != text:
            try:
                return english.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                pass
        print(f"[lang] Bad placeholders in '{key}' for language '{code}'.")
        return text
