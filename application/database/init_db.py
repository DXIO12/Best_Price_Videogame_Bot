from sqlalchemy import text
from database.db import engine, SessionLocal
from database.models import Base, Platform, product_platforms

Base.metadata.create_all(bind=engine)

# Migrate: add columns that may not exist in older DBs
with engine.connect() as conn:
    added_priority_column = False
    for stmt in [
        "ALTER TABLE product_shops ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE product_shops ADD COLUMN next_retry_at DATETIME",
        "ALTER TABLE product_shops ADD COLUMN available BOOLEAN",
        "ALTER TABLE settings ADD COLUMN repeat_notification_minutes INTEGER",
        "ALTER TABLE settings ADD COLUMN debug_mode BOOLEAN",
        "ALTER TABLE settings ADD COLUMN allow_parallel_scraping BOOLEAN",
        "ALTER TABLE settings ADD COLUMN max_parallel_workers INTEGER",
        "ALTER TABLE settings ADD COLUMN language TEXT",
        "ALTER TABLE product_platforms ADD COLUMN priority INTEGER NOT NULL DEFAULT 0",
    ]:
        try:
            conn.execute(text(stmt))
            conn.commit()
            if "product_platforms" in stmt:
                added_priority_column = True
        except Exception:
            pass  # column already exists

    # Backfill: give pre-existing product_platforms rows a stable, distinct
    # order instead of leaving them all at priority 0.
    if added_priority_column:
        rows = conn.execute(
            text("SELECT rowid FROM product_platforms ORDER BY product_id, platform_id")
        ).fetchall()
        for index, row in enumerate(rows):
            conn.execute(
                text("UPDATE product_platforms SET priority = :priority WHERE rowid = :rowid"),
                {"priority": index, "rowid": row.rowid}
            )
        conn.commit()

# Seed platforms (idempotent — skips any that already exist)
_PLATFORMS = ["PS5", "Switch 2", "Switch", "PC", "Xbox Series X"]

db = SessionLocal()
for name in _PLATFORMS:
    if not db.query(Platform).filter(Platform.name == name).first():
        db.add(Platform(name=name))
db.commit()
db.close()

print("Database initialised.")
