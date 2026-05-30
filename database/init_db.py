from sqlalchemy import text
from database.db import engine
from database.models import Base

Base.metadata.create_all(bind=engine)

# Migrate: add columns that may not exist in older DBs
with engine.connect() as conn:
    for stmt in [
        "ALTER TABLE product_shops ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE product_shops ADD COLUMN next_retry_at DATETIME",
    ]:
        try:
            conn.execute(text(stmt))
            conn.commit()
        except Exception:
            pass  # column already exists

print("Database initialised.")
