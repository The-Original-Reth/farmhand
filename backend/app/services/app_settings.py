"""Reading and writing one of the small settings chosen in the UI (AppSetting rows: storage locations, the settings
folder, the appearance...). Writing doesn't commit: the caller does, with whatever else it changed."""
from __future__ import annotations

import hashlib

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import AppSetting


def get(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row else None


def fresh(db: Session, key: str) -> str | None:
    """The value as stored right now (not a copy this session read earlier), for swap()."""
    return db.execute(select(AppSetting.value).where(AppSetting.key == key)).scalar_one_or_none()


def swap(db: Session, key: str, was: str | None, value: str) -> bool:
    """
    Set the value only if it's still `was` (as fresh() read it; None: there was no row), and commit. False when someone
    else changed it in between: nothing is written (and the session is rolled back). The database lets exactly one of
    two writes based on the same value through, so a read-change-write can't silently lose the other one's change.
    """
    try:
        if was is None:
            db.execute(insert(AppSetting).values(key=key, value=value))
            done = True
        else:
            done = db.execute(update(AppSetting).where(AppSetting.key == key, AppSetting.value == was)
                              .values(value=value)).rowcount == 1
    except IntegrityError:  # a row was added in between
        done = False
    if done:
        db.commit()
    else:
        db.rollback()
    db.expire_all()
    return done


def stamp(value: str | None) -> str:
    """A short name for one exact stored value (a revision for a setting that keeps none of its own)."""
    return hashlib.sha1((value or "").encode()).hexdigest()[:12]


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
PRINTER_BACKUPS_DIR_KEY = "printer_backups_dir"  # the printer config backups' folder chosen in Settings; none = the default
FARM_COST_DIR_KEY = "farm_cost_dir"  # the Farm cost records folder chosen in Settings; none = the default


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
