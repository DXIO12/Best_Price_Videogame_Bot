from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

_DB_DIR = Path(__file__).resolve().parent
DATABASE_URL = f"sqlite:///{_DB_DIR / 'tracker.db'}"

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(
    autoflush=False,
    bind=engine
)

Base = declarative_base()