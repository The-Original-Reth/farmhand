from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config_store, storage
from ..models import AppSetting, NetworkShare
from . import network_shares_service, storage_settings_service

KEY_CONFIG = "config_json"  # the settings themselves (appearance + preferences), as the server holds them
KEY_LOCATION = "config_storage_dir"  # the network folder a copy is written to

# What happened the last time the copy was written, so the page can say so. In memory: it's about now.
_last_mirror: dict = {"ok": None, "error": None, "at": None}


def _get(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row else None


def _set(db: Session, key: str, value: str | None) -> None:
    row = db.get(AppSetting, key)
    if value is None:
        if row is not None:
            db.delete(row)
    elif row is not None:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


# ------------------------------------------------------------------ the settings

def get_config(db: Session) -> dict:
    try:
        raw = json.loads(_get(db, KEY_CONFIG) or "{}")
    except ValueError:
        raw = {}
    return config_store.normalize_config(raw)


def save_config(db: Session, patch: dict) -> dict:
    """Replace the parts given (appearance and/or preferences); everything else is left alone."""
    current = get_config(db)
    merged = {
        "appearance": patch["appearance"] if patch.get("appearance") is not None else current["appearance"],
        "preferences": patch["preferences"] if patch.get("preferences") is not None else current["preferences"],
    }
    config = config_store.normalize_config(merged)
    _set(db, KEY_CONFIG, json.dumps(config))
    db.commit()
    return config


# ------------------------------------------------------------------ the copy on the network folder

def location_path(db: Session) -> str | None:
    return _get(db, KEY_LOCATION)


def _share_entries(db: Session) -> list[dict]:
    return [
        {"name": r.name, "protocol": r.protocol, "server": r.server, "share": r.share,
         "username": r.username, "domain": r.domain, "version": r.version}
        for r in db.scalars(select(NetworkShare).order_by(NetworkShare.name))
    ]


def build_document(db: Session) -> dict:
    return config_store.build_document(
        get_config(db), storage.custom_path("stl"), storage.custom_path("threemf"), _share_entries(db)
    )


def mirror(db: Session) -> dict:
    """Write the copy now. Never raises: the settings are safe on the server whatever happens to the share."""
    path = location_path(db)
    if not path:
        return {"ok": True, "skipped": True, "path": None, "error": None}
    try:
        folder = storage.ensure_ready_folder(path, "settings folder")
        config_store.write_document(folder, build_document(db))
        error = None
    except storage.StorageUnavailableError as e:
        error = str(e)
    except OSError as e:
        error = f"Couldn't write the settings file: {e}"
    _last_mirror.update(ok=error is None, error=error, at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    return {"ok": error is None, "skipped": False, "path": path, "error": error}


def mirror_quietly(db: Session) -> None:
    """For use after some other change (a share added, a folder chosen): keep the copy current, ignore trouble."""
    try:
        mirror(db)
    except Exception:  # noqa: BLE001 — keeping a copy up to date must never break the change that triggered it
        pass


def describe(db: Session) -> dict:
    path = location_path(db)
    status = file = None
    if path:
        folder = Path(path)
        exists = folder.is_dir()
        writable = exists and storage._probe_writable(folder)
        marker_ok = exists and (folder / storage.MARKER_NAME).is_file()
        status = {"exists": exists, "writable": writable, "marker_ok": marker_ok, "ready": bool(exists and writable and marker_ok)}
        file = config_store.file_info(folder) if exists else {"exists": False, "modified_at": None, "size": None}
    return {"path": path, "is_set": bool(path), "status": status, "file": file, "last_write": dict(_last_mirror)}


def inspect_location(raw: str) -> dict:
    """Look at a folder someone is about to choose, without changing anything."""
    real = storage.validate_location(raw)  # raises ValueError with a plain reason if it can't be used
    info = config_store.file_info(real)
    out = {"path": str(real), "file_exists": info["exists"], "file_valid": None, "modified_at": info["modified_at"], "summary": None, "error": None}
    if info["exists"]:
        try:
            doc = config_store.read_document(real)
            out["file_valid"] = True
            out["summary"] = {
                "saved_at": doc["saved_at"],
                "scheme": doc["appearance"]["scheme"],
                "shares": len(doc["shares"]),
                "has_stl_folder": bool(doc["storage"]["stl_path"]),
                "has_threemf_folder": bool(doc["storage"]["threemf_path"]),
            }
        except config_store.ConfigFileError as e:
            out["file_valid"] = False
            out["error"] = str(e)
    return out


def set_location(db: Session, raw: str | None, if_exists: str = "ask") -> dict:
    """
    Choose (or clear) the folder the copy goes to. If that folder already holds a settings file it is NEVER
    silently overwritten: with if_exists="ask" nothing is saved and the answer says a choice is needed;
    "restore" loads that file into Farmhand; "overwrite" replaces it with the current settings.
    """
    if not raw:
        _set(db, KEY_LOCATION, None)
        db.commit()
        return {"saved": True, "needs_choice": False, "found": None, "restored": None, "location": describe(db)}

    found = inspect_location(raw)
    if found["file_exists"] and if_exists == "ask":
        return {"saved": False, "needs_choice": True, "found": found, "restored": None, "location": describe(db)}
    if found["file_exists"] and if_exists == "restore" and not found["file_valid"]:
        raise ValueError(found["error"])

    storage.mark_location(Path(found["path"]))
    _set(db, KEY_LOCATION, found["path"])
    db.commit()
    restored = restore(db) if (found["file_exists"] and if_exists == "restore") else None
    mirror(db)  # after a restore too: the file then reflects everything now in force
    return {"saved": True, "needs_choice": False, "found": None, "restored": restored, "location": describe(db)}


def restore(db: Session) -> dict:
    """Load the settings file in the chosen folder into Farmhand."""
    path = location_path(db)
    if not path:
        raise ValueError("Choose a settings folder first.")
    doc = config_store.read_document(path)  # ConfigFileError (a ValueError) if unusable
    if doc is None:
        raise ValueError("There's no settings file in that folder yet.")

    result = {"restored": ["appearance", "display preferences"], "shares_added": [], "shares_kept": [], "needs_password": [], "warnings": []}
    save_config(db, {"appearance": doc["appearance"], "preferences": doc["preferences"]})

    applied, warnings = storage_settings_service.restore_locations(db, doc["storage"]["stl_path"], doc["storage"]["threemf_path"])
    result["restored"] += applied
    result["warnings"] += warnings

    for entry in doc["shares"]:
        label = entry.get("name") or "(unnamed)"
        try:
            outcome = network_shares_service.restore_share(db, entry)
        except ValueError as e:
            result["warnings"].append(f"The share “{label}” was skipped: {e}")
            continue
        if outcome == "added":
            result["shares_added"].append(label)
            if entry.get("protocol") == "smb" and entry.get("username"):
                result["needs_password"].append(label)
        else:
            result["shares_kept"].append(label)
    return result
