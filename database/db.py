from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///database/tracker.db"

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(
    autoflush=False,
    bind=engine
)

Base = declarative_base()