from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config_store, storage
from ..models import NetworkShare
from . import app_settings, network_shares_service, records_service, storage_settings_service

log = logging.getLogger("farmhand.settings")

KEY_CONFIG = "config_json"  # the settings themselves (appearance + preferences), as the server holds them
KEY_LOCATION = "config_storage_dir"  # the network folder a copy is written to

# What happened the last time the copy was written, so the page can say so. In memory: it's about now.
_last_mirror: dict = {"ok": None, "error": None, "at": None}


# ------------------------------------------------------------------ the settings

def get_config(db: Session) -> dict:
    try:
        raw = json.loads(app_settings.get(db, KEY_CONFIG) or "{}")
    except ValueError:
        raw = {}
    return config_store.normalize_config(raw)


def save_config(db: Session, patch: dict) -> dict:
    """
    Replace the parts given: the appearance as a whole, and each preference given (the Models sort, the Monitor order)
    on its own. Everything else is left alone.
    """
    current = get_config(db)
    merged = {
        "appearance": patch["appearance"] if patch.get("appearance") is not None else current["appearance"],
        "preferences": {**current["preferences"], **(patch.get("preferences") or {})},
    }
    config = config_store.normalize_config(merged)
    app_settings.put(db, KEY_CONFIG, json.dumps(config))
    db.commit()
    return config


# ------------------------------------------------------------------ the copy on the network folder

def location_path(db: Session) -> str | None:
    return app_settings.get(db, KEY_LOCATION)


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


@dataclass
class MirrorScope:
    """
    What a change touched, so a copy rewrites only those files: printers True = all of them, else the ids of those
    that changed; models = the models' files (they're small, so always all of them).
    """

    printers: bool | set[int] = field(default_factory=set)
    models: bool = False

    def add(self, other: "MirrorScope") -> None:
        if self.printers is not True:
            self.printers = True if other.printers is True else self.printers | other.printers
        self.models = self.models or other.models


EVERYTHING = MirrorScope(printers=True, models=True)


def mirror(db: Session, scope: MirrorScope | None = None) -> dict:
    """
    Write the copy now: the settings file, plus a file per printer and per model (records_service): every one of
    them, each checked against what's there (scope None), or only what a change touched. Never raises: everything
    is safe on the server whatever happens to the share.
    """
    path = location_path(db)
    if not path:
        return {"ok": True, "skipped": True, "path": None, "error": None}
    try:
        folder = storage.ensure_ready_folder(path, "settings folder")
        config_store.write_document(folder, build_document(db))
        records_service.write_all(db, folder, scope)
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


# Printers, models and notes change all the time (every edit, every 15-minute sync). Rather than each of those
# writing the files itself, they ask for a copy and a background thread writes one shortly after, once, however
# many changes came in meanwhile.
MIRROR_DELAY_SECONDS = 3.0
_mirror_wanted = threading.Event()
_mirror_thread: threading.Thread | None = None
_mirror_lock = threading.Lock()
_mirror_scope: MirrorScope | None = None  # what the changes waiting to be copied touched (None: a full copy is due)
_mirror_full = False


_background_mirror = False  # switched on when the app starts (not in tests, which have no settings folder)


def enable_background_mirror() -> None:
    global _background_mirror
    _background_mirror = True


def request_mirror(scope: MirrorScope | None = None) -> None:
    """
    Something changed: write the copy in a few seconds, in the background. scope: what changed (only those files are
    rewritten); None = a full copy, every file checked.
    """
    global _mirror_thread, _mirror_scope, _mirror_full
    if not _background_mirror:
        return
    with _mirror_lock:
        if scope is None:
            _mirror_full = True
        elif _mirror_scope is None:
            _mirror_scope = MirrorScope(printers=set(scope.printers) if scope.printers is not True else True, models=scope.models)
        else:
            _mirror_scope.add(scope)
    _mirror_wanted.set()
    with _mirror_lock:
        if _mirror_thread is None or not _mirror_thread.is_alive():
            _mirror_thread = threading.Thread(target=_mirror_worker, name="settings-copy", daemon=True)
            _mirror_thread.start()


def _mirror_worker() -> None:
    from ..database import SessionLocal

    while _mirror_wanted.wait(timeout=60):
        time.sleep(MIRROR_DELAY_SECONDS)  # let a burst of changes settle into one write
        global _mirror_scope, _mirror_full
        with _mirror_lock:
            _mirror_wanted.clear()
            scope = None if _mirror_full else (_mirror_scope or MirrorScope())
            _mirror_scope, _mirror_full = None, False
        try:
            with SessionLocal() as db:
                mirror(db, scope)
        except Exception:  # noqa: BLE001 — a background copy must never take anything down
            log.exception("Writing the settings copy failed")


def describe(db: Session) -> dict:
    path = location_path(db)
    status = file = None
    if path:
        folder = Path(path)
        status = storage.folder_status(folder)
        file = config_store.file_info(folder) if status["exists"] else {"exists": False, "modified_at": None, "size": None}
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
                **records_service.count_records(real),  # "printers": n, "models": n
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
        app_settings.put(db, KEY_LOCATION, None)
        db.commit()
        return {"saved": True, "needs_choice": False, "found": None, "restored": None, "location": describe(db)}

    found = inspect_location(raw)
    if found["file_exists"] and if_exists == "ask":
        return {"saved": False, "needs_choice": True, "found": found, "restored": None, "location": describe(db)}
    if found["file_exists"] and if_exists == "restore" and not found["file_valid"]:
        raise ValueError(found["error"])

    storage.mark_location(Path(found["path"]))
    app_settings.put(db, KEY_LOCATION, found["path"])
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

    # The printers/ and models/ files: only ever adds what Farmhand is missing
    records = records_service.restore_all(db, path)
    result["warnings"] += records.pop("warnings")
    if records["printers_added"] or records["printers_filled"]:
        result["restored"].append("printers")
    if records["model_notes"] or records["threemf_notes"] or records["stars"]:
        result["restored"].append("notes and stars")
    result["records"] = records
    return result
