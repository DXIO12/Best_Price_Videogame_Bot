"""Export and import the tracking list, and rename the database file.

**Why a JSON of products and not a copy of tracker.db.** The database carries
things that must not travel between two bots. ``Setting`` holds the Telegram bot
token and chat id — a bearer credential the Settings dialog deliberately masks
on screen, so writing it into a file meant for sharing would undo that. And
``ProductShop`` holds per-instance runtime state (``last_price``,
``last_notified``, ``retry_count``, ``next_retry_at``); an imported
``last_notified`` silences a notification the receiving instance should have
sent. What is actually worth moving is the tracking list: which products, on
which platforms, in which order, at which shops. That is what this module
writes, and a JSON of it is readable, diffable and safe to send.

Everything here reuses ``product_service``: ``create_product`` already knows how
to attach platforms and shops, and ``reorder_platform_priorities`` already owns
the priority column. Nothing in this module writes to the ORM directly.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from application.config.logger import get_logger
from application.database.db import (
    SessionLocal,
    database_path,
    db_dir,
    rebind,
    sanitize_db_name,
    write_pointer,
)
from application.database.models import Platform, Product
from application.services.product_service import (
    create_product,
    delete_products,
    get_platform_priorities,
    get_products_with_shops,
    reorder_platform_priorities,
    to_gui_names,
)

log = get_logger("product_io")

# Bumped only on a breaking change to the shape below; ``read_export_file``
# refuses a version it was not written for rather than guessing.
FORMAT = "price-bot-products"
VERSION = 1

# Placement choices offered when merging — how the imported rows are woven into
# the existing priority order.
PLACEMENT_END = "end"
PLACEMENT_START = "start"
PLACEMENT_MANUAL = "manual"


class ProductIOError(Exception):
    """A file could not be read, written or applied. Message is user-facing."""


# ---------------------------------------------------------------------------
# In-memory shapes
# ---------------------------------------------------------------------------

@dataclass
class ImportedProduct:
    """One product as it appears in an export file."""
    name: str
    target_price: float
    # DB platform names ("Switch 2"), in the priority order the file recorded.
    platforms: list[str] = field(default_factory=list)
    # (shop display name, url) — url may be "" for a row never resolved.
    shops: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ImportPreview:
    """What a file contains, judged against what is already tracked."""
    path: Path
    products: list[ImportedProduct]
    new: list[ImportedProduct]
    duplicates: list[ImportedProduct]
    current_count: int


@dataclass
class ImportResult:
    """What actually happened, for the status line and the log."""
    added: int = 0
    removed: int = 0
    skipped: int = 0
    unknown_platforms: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_products(path: Path) -> int:
    """Write every tracked product to ``path`` as JSON. Returns how many.

    Products are written in the order the table shows them, so an import that
    keeps the file order reproduces the list exactly."""
    priorities = get_platform_priorities()
    entries = []

    for product, shop_records in get_products_with_shops():
        # A product occupies one row per platform, each with its own priority.
        # Sort its platforms by that, and the product itself by its topmost row,
        # so the file reads top-to-bottom like the table does.
        platforms = sorted(
            product.platforms,
            key=lambda platform: priorities.get((product.id, platform.id), 0),
        )
        rank = min(
            (priorities.get((product.id, platform.id), 0) for platform in platforms),
            default=0,
        )
        entries.append((rank, {
            "name": product.name,
            "target_price": product.target_price,
            "platforms": [platform.name for platform in platforms],
            "shops": [
                {"shop": record.shop, "url": record.url or ""}
                for record in shop_records
            ],
        }))

    entries.sort(key=lambda entry: entry[0])
    payload = {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "products": [entry[1] for entry in entries],
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    except OSError as exc:
        raise ProductIOError(str(exc)) from exc

    log.info(f"Exported {len(entries)} product(s) to {path}")
    return len(entries)


def suggested_export_name() -> str:
    """Default file name offered by the save dialog."""
    return f"productos-price-bot-{datetime.now():%Y%m%d}.json"


# ---------------------------------------------------------------------------
# Read + validate
# ---------------------------------------------------------------------------

def read_export_file(path: Path) -> ImportPreview:
    """Parse and validate an export file, and compare it with what is tracked.

    Raises ProductIOError with a user-facing message on anything malformed —
    the caller shows it in a message box, so it must read as a sentence."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError as exc:
        raise ProductIOError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise ProductIOError(f"JSON: {exc}") from exc
    except OSError as exc:
        raise ProductIOError(str(exc)) from exc

    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise ProductIOError("format")
    if raw.get("version") != VERSION:
        raise ProductIOError(f"version {raw.get('version')}")

    entries = raw.get("products")
    if not isinstance(entries, list):
        raise ProductIOError("products")

    products: list[ImportedProduct] = []
    for entry in entries:
        product = _parse_product(entry)
        if product is not None:
            products.append(product)

    if not products:
        raise ProductIOError("empty")

    # Duplicate = same name, ignoring case and surrounding space. Platform is
    # deliberately not part of the identity: two rows of the same game are the
    # same product here, and merging must never create a second copy of it.
    existing_names = _tracked_names()
    new, duplicates = [], []
    for product in products:
        (duplicates if product.name.strip().lower() in existing_names else new).append(product)

    return ImportPreview(
        path=path,
        products=products,
        new=new,
        duplicates=duplicates,
        current_count=len(existing_names),
    )


def _parse_product(entry) -> ImportedProduct | None:
    """One products[] element, or None when it is unusable.

    A single bad row is skipped rather than failing the whole file: a file that
    is 95% good is still worth importing, and the count shown to the user comes
    from what survived this."""
    if not isinstance(entry, dict):
        return None

    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    try:
        target_price = float(entry.get("target_price"))
    except (TypeError, ValueError):
        return None

    platforms = [
        value.strip()
        for value in entry.get("platforms", [])
        if isinstance(value, str) and value.strip()
    ]

    shops: list[tuple[str, str]] = []
    for record in entry.get("shops", []):
        if not isinstance(record, dict):
            continue
        shop = record.get("shop")
        if not isinstance(shop, str) or not shop.strip():
            continue
        url = record.get("url")
        shops.append((shop.strip(), url.strip() if isinstance(url, str) else ""))

    return ImportedProduct(
        name=name.strip(),
        target_price=target_price,
        platforms=platforms,
        shops=shops,
    )


def _tracked_names() -> set[str]:
    db = SessionLocal()
    try:
        return {name.strip().lower() for (name,) in db.query(Product.name).all()}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_merge(preview: ImportPreview, placement: str,
                manual_order: list[tuple] | None = None) -> ImportResult:
    """Add the file's new products, leaving the existing ones untouched.

    ``placement`` is one of the PLACEMENT_* constants. For PLACEMENT_MANUAL,
    ``manual_order`` is the token order returned by the ordering dialog — see
    :func:`merge_order_tokens` for what a token is."""
    result = ImportResult(skipped=len(preview.duplicates))
    if not preview.new:
        log.info("Import (merge): nothing new in the file")
        return result

    before = _ordered_keys()
    created = _create_all(preview.new, result)

    if placement == PLACEMENT_MANUAL and manual_order:
        final = _resolve_tokens(manual_order, created, before)
    elif placement == PLACEMENT_START:
        final = _flatten(created) + before
    else:
        final = before + _flatten(created)

    reorder_platform_priorities(final)
    log.info(f"Import (merge): +{result.added} product(s), "
             f"{result.skipped} already tracked, placement={placement}")
    return result


def apply_replace(preview: ImportPreview) -> ImportResult:
    """Drop everything currently tracked, then import the file wholesale."""
    db = SessionLocal()
    try:
        existing_ids = [product_id for (product_id,) in db.query(Product.id).all()]
    finally:
        db.close()

    result = ImportResult(removed=len(existing_ids))
    delete_products(existing_ids)

    created = _create_all(preview.products, result)
    reorder_platform_priorities(_flatten(created))

    log.info(f"Import (replace): -{result.removed} product(s), +{result.added}")
    return result


def _create_all(products: list[ImportedProduct],
                result: ImportResult) -> list[list[tuple[int, int]]]:
    """Create every product, returning its (product_id, platform_id) keys.

    One list per product, in file order, so a caller can weave them into an
    existing order without another database round trip."""
    known = _known_platforms()
    created: list[list[tuple[int, int]]] = []

    for product in products:
        usable = [name for name in product.platforms if name in known]
        result.unknown_platforms.update(set(product.platforms) - set(usable))

        shops = [shop for shop, _ in product.shops]
        shop_urls = {shop.lower(): url for shop, url in product.shops if url}

        product_id = create_product(
            name=product.name,
            # create_product speaks GUI labels ("NS2"); the file stores DB names.
            platforms=to_gui_names(usable),
            target_price=product.target_price,
            shops=shops,
            shop_urls=shop_urls,
        )
        result.added += 1
        created.append([(product_id, known[name]) for name in usable])

    if result.unknown_platforms:
        log.warning(f"Import: unknown platform(s) skipped: "
                    f"{', '.join(sorted(result.unknown_platforms))}")
    return created


def _known_platforms() -> dict[str, int]:
    db = SessionLocal()
    try:
        return {platform.name: platform.id for platform in db.query(Platform).all()}
    finally:
        db.close()


def _ordered_keys() -> list[tuple[int, int]]:
    """Every tracked (product_id, platform_id), in current priority order."""
    priorities = get_platform_priorities()
    return sorted(priorities, key=lambda key: priorities[key])


def _flatten(created: list[list[tuple[int, int]]]) -> list[tuple[int, int]]:
    return [key for keys in created for key in keys]


# ---------------------------------------------------------------------------
# Manual ordering tokens
# ---------------------------------------------------------------------------
#
# The ordering dialog runs *before* anything is written, so the imported rows
# have no database id yet and cannot be identified by a (product_id,
# platform_id) key like the existing ones. Each row is therefore an opaque
# token, resolved to a real key only after the products exist:
#
#     ("db",   product_id, platform_id)   a row already tracked
#     ("file", index,      platform_name) row ``index`` of preview.new

def merge_order_tokens(preview: ImportPreview) -> list[tuple[tuple, str, str, bool]]:
    """Rows to show in the ordering dialog: (token, product, platform, is_new).

    Existing rows first, in priority order, then the file's new ones — the same
    starting point as the "at the end of my list" placement, so the dialog opens
    on the default rather than on some third order."""
    rows: list[tuple[tuple, str, str, bool]] = []

    db = SessionLocal()
    try:
        names = {product.id: product.name for product in db.query(Product).all()}
        platforms = {platform.id: platform.name for platform in db.query(Platform).all()}
    finally:
        db.close()

    for product_id, platform_id in _ordered_keys():
        rows.append((
            ("db", product_id, platform_id),
            names.get(product_id, ""),
            to_gui_names([platforms.get(platform_id, "")])[0],
            False,
        ))

    for index, product in enumerate(preview.new):
        for platform_name in product.platforms:
            rows.append((
                ("file", index, platform_name),
                product.name,
                to_gui_names([platform_name])[0],
                True,
            ))

    return rows


def _resolve_tokens(tokens: list[tuple],
                    created: list[list[tuple[int, int]]],
                    before: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Turn the dialog's token order into real (product_id, platform_id) keys.

    Tokens naming a row that no longer resolves are dropped, and anything the
    dialog never saw is appended — so a key can never be lost from the priority
    order, whatever the dialog returned."""
    names = {platform_id: name for name, platform_id in _known_platforms().items()}

    by_token: dict[tuple, tuple[int, int]] = {}
    for index, keys in enumerate(created):
        for product_id, platform_id in keys:
            by_token[("file", index, names.get(platform_id, ""))] = (product_id, platform_id)
    for key in before:
        by_token[("db", key[0], key[1])] = key

    ordered: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for token in tokens:
        key = by_token.get(tuple(token))
        if key is not None and key not in seen:
            seen.add(key)
            ordered.append(key)

    for key in before + _flatten(created):
        if key not in seen:
            seen.add(key)
            ordered.append(key)

    return ordered



# ---------------------------------------------------------------------------
# Rename the database file
# ---------------------------------------------------------------------------

def rename_database(new_name: str) -> Path:
    """Rename the database file on disk and remember the new name.

    The engine is disposed before the file moves and rebuilt after: SQLAlchemy
    hands out a fresh connection per session, and one opened against a path that
    no longer exists would silently create a second, empty database instead of
    failing. The pointer is written last, so a failed move leaves nothing to
    undo."""
    cleaned = sanitize_db_name(new_name)
    if cleaned is None:
        raise ProductIOError("invalid")

    current = database_path()
    target = db_dir() / cleaned

    if target == current:
        return current
    if target.exists():
        raise ProductIOError("exists")

    from application.database.db import engine

    engine.dispose()
    try:
        os.replace(current, target)
    except OSError as exc:
        # The engine is disposed, not dismantled: the next session reopens the
        # untouched original, so nothing is lost by the failed move.
        raise ProductIOError(str(exc)) from exc

    # Pointer, not config.json — see the db module docstring for why.
    write_pointer(cleaned)
    rebind(target)

    log.info(f"Database renamed: {current.name} -> {cleaned}")
    return target
