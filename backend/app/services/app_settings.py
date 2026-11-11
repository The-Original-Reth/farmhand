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


INSTANCE_KEY = "instance_id"
FARM_COST_DIR_KEY = "farm_cost_dir"  # the Farm cost records folder chosen in Settings; none = the default
STREAM_MEDIA_DIR_KEY = "stream_media_dir"  # the Stream page's folder chosen in Settings; none = the default


def current_folder(db: Session, key: str, rename: bool = False) -> str | None:
    """A folder chosen in Settings, where it is now: one saved by its old name follows its rename (here or by another
    Farmhand sharing it; renamed now when `rename`), and is saved by its new one."""
    from .. import storage

    saved = get(db, key)
    now = storage.current_folder(saved, rename=rename)
    if now != saved:
        put(db, key, now)
        db.commit()
    return now


def instance_id(db: Session) -> str:
    """This Farmhand's own short id, made once: it names the records it writes beside the files on the NAS, so two
    Farmhands sharing the folders keep theirs apart."""
    import uuid

    value = get(db, INSTANCE_KEY)
    if not value:
        value = uuid.uuid4().hex[:8]
        put(db, INSTANCE_KEY, value)
        db.commit()
    return value
