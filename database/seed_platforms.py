from database.db import SessionLocal
from database.models import Platform

platforms = [
    "PS5",
    "NS2",
    "NS",
    "PC",
    "Xbox Series X"
]

db = SessionLocal()

for platform_name in platforms:

    existing = db.query(Platform).filter(
        Platform.name == platform_name
    ).first()

    if not existing:

        db.add(
            Platform(name=platform_name)
        )

db.commit()

db.close()

print("Platforms seeded.")