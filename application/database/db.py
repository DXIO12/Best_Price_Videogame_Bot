import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

if getattr(sys, "frozen", False):
    # Running as a PyInstaller bundle: keep the DB next to the executable
    # so it lives outside the read-only _internal/ directory.
    _DB_DIR = Path(sys.executable).parent
else:
    _DB_DIR = Path(__file__).resolve().parent

DATABASE_URL = f"sqlite:///{_DB_DIR / 'tracker.db'}"

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(
    autoflush=False,
    bind=engine
)

Base = declarative_base()