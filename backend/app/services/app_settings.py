"""Reading and writing one of the small settings chosen in the UI (AppSetting rows: storage locations, the settings
folder, the appearance...). Writing doesn't commit: the caller does, with whatever else it changed."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AppSetting


def get(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row else None


def put(db: Session, key: str, value: str | None) -> None:
    """Set the value, or remove the setting with None."""
    row = db.get(AppSetting, key)
    if value is None:
        if row is not None:
            db.delete(row)
    elif row is not None:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
