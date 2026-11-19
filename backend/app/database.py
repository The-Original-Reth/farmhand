from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# More connections than SQLAlchemy's 5 (+10): a request waiting on a printer or plugin can hold one for a while, and
# the rest of Farmhand shouldn't queue behind it. Postgres allows 100.
_pool = {"pool_size": 10, "max_overflow": 30, "pool_timeout": 30} if settings.database_url.startswith("postgresql") else {}
engine = create_engine(settings.database_url, future=True, **_pool)
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
