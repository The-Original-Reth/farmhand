"""
Where printer config backups are kept: the default folder beside the STL folder, or one chosen on the Settings page.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy.orm import Session

from ... import storage
from ...models import Printer
from .. import app_settings
from .common import DEFAULT_FOLDER, KEY_LOCATION, _safe_name


def default_folder() -> Path:
    """The printer backups folder when none is chosen: "backup" in the folder above the STL / OBJ / STEP folder."""
    return storage.named_folder(storage.effective_root("stl").parent, DEFAULT_FOLDER)


def _chosen(db: Session) -> str | None:
    return app_settings.get(db, KEY_LOCATION)


def backups_folder(db: Session) -> Path:
    """
    Where a new backup goes, only while it can be written: a chosen folder still has its marker, the default's STL
    folder is ready. So an unmounted share never gets a backup on the local disk underneath it
    (StorageUnavailableError otherwise).
    """
    chosen = _chosen(db)
    if chosen:
        return storage.ensure_ready_folder(chosen, "printer backups folder")
    folder = storage.named_folder(storage.ready_root("stl").parent, DEFAULT_FOLDER)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def location_info(db: Session) -> dict:
    """For Settings: {path, is_default, default_path, status: {exists, writable, marker_ok, ready}}."""
    chosen = _chosen(db)
    default = default_folder()
    if chosen:
        return {"path": chosen, "is_default": False, "default_path": str(default), "status": storage.folder_status(Path(chosen))}
    try:
        storage.ready_root("stl")
        ready = True
    except storage.StorageUnavailableError:
        ready = False
    status = {"exists": default.is_dir(), "writable": ready, "marker_ok": ready, "ready": ready}  # made when first used
    return {"path": str(default), "is_default": True, "default_path": str(default), "status": status}


def set_location(db: Session, raw: str | None) -> dict:
    """
    Choose the printer backups folder (None or "" = back to the default). A chosen folder must be one that lasts (on a
    connected share or in Farmhand's own storage) and can be written; it gets Farmhand's marker. ValueError says why
    one can't be used. Backups already taken stay where they are (each knows its own folder).
    """
    if raw and raw.strip():
        real = storage.validate_location(raw.strip())
        storage.mark_location(real)
        app_settings.put(db, KEY_LOCATION, str(real))
    else:
        app_settings.put(db, KEY_LOCATION, None)
    db.commit()
    return location_info(db)


def _new_folder(db: Session, printer: Printer, taken_at: dt.datetime) -> Path:
    base = backups_folder(db) / _safe_name(printer.name, f"printer-{printer.id}")
    stamp = taken_at.strftime("%Y-%m-%d_%H-%M-%S")
    folder, n = base / stamp, 1
    while folder.exists():  # two in one second, or another Farmhand sharing the folder
        n += 1
        folder = base / f"{stamp}-{n}"
    return folder
