from application.config.logger import get_logger
from application.config.runtime_config import init_runtime_mode
from application.database.db import SessionLocal
from application.database.models import Platform

init_runtime_mode()
log = get_logger("database")

platforms = [
    "PS5",
    "Switch 2",
    "Switch",
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

log.info("Platforms seeded.")