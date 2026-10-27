from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def create_schema(bind=engine) -> None:
    """
    Make any tables that don't exist yet, and any indexes they're missing: create_all only indexes the tables it
    makes, so an index added later reaches an existing database this way. Safe to run every time.
    """
    Base.metadata.create_all(bind=bind)
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(bind=bind, checkfirst=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
