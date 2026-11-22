"""
A folder chosen on the Settings page, else a default beside the STL folder: what the printer backups folder
(config_backups/location.py) and the farm cost folder (farm_cost.py) have in common. Each keeps its choice under its
own app_settings key and works out its own default.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from .. import storage
from . import app_settings


def info(chosen: str | None, default: Path) -> dict:
    """For Settings: {path, is_default, default_path, status: {exists, writable, marker_ok, ready}}. The default is made
    when first used, so it counts as ready while the STL folder is."""
    if chosen:
        return {"path": chosen, "is_default": False, "default_path": str(default), "status": storage.folder_status(Path(chosen))}
    try:
        storage.ready_root("stl")
        ready = True
    except storage.StorageUnavailableError:
        ready = False
    status = {"exists": default.is_dir(), "writable": ready, "marker_ok": ready, "ready": ready}
    return {"path": str(default), "is_default": True, "default_path": str(default), "status": status}


def choose(db: Session, key: str, raw: str | None) -> None:
    """
    Keep the folder chosen (None or "" = back to the default) under `key`. A chosen folder must be one that lasts (on a
    connected share or in Farmhand's own storage) and can be written; it gets Farmhand's marker, so nothing is written
    to it while it isn't really there. ValueError says why one can't be used.
    """
    if raw and raw.strip():
        real = storage.validate_location(raw.strip())
        storage.mark_location(real)
        app_settings.put(db, key, str(real))
    else:
        app_settings.put(db, key, None)
    db.commit()
