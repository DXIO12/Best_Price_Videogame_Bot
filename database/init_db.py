from sqlalchemy import text
from database.db import engine, SessionLocal
from database.models import Base, Platform

Base.metadata.create_all(bind=engine)

# Migrate: add columns that may not exist in older DBs
with engine.connect() as conn:
    for stmt in [
        "ALTER TABLE product_shops ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE product_shops ADD COLUMN next_retry_at DATETIME",
        "ALTER TABLE settings ADD COLUMN repeat_notification_minutes INTEGER",
    ]:
        try:
            conn.execute(text(stmt))
            conn.commit()
        except Exception:
            pass  # column already exists

# Seed platforms (idempotent — skips any that already exist)
_PLATFORMS = ["PS5", "Switch 2", "Switch", "PC", "Xbox Series X"]

db = SessionLocal()
for name in _PLATFORMS:
    if not db.query(Platform).filter(Platform.name == name).first():
        db.add(Platform(name=name))
db.commit()
db.close()

print("Database initialised.")
