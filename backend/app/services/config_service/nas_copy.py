"""
The copy of the settings on the network folder: farmhand-config.json and every printer's and model's file, written
after each change (in the background, a moment later) and by Save all.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import config_store, record_files, storage
from ...models import NetworkShare, Printer
from .. import app_settings, records_service

from .settings import get_config

log = logging.getLogger("farmhand.settings")

KEY_LOCATION = "config_storage_dir"  # the network folder a copy is written to
FARM_COST_LOCATION = app_settings.FARM_COST_DIR_KEY  # the farm cost records folder, saved with the rest

# What happened the last time the copy was written, so the page can say so. In memory: it's about now.
_last_mirror: dict = {"ok": None, "error": None, "at": None}


# ------------------------------------------------------------------ the copy on the network folder

def location_path(db: Session, rename: bool = False) -> str | None:
    """The settings folder, where it is now: one saved by its old name ("Farmhand Configs") follows its rename to
    "farmhand-configs" (here or by another Farmhand sharing it; renamed now when `rename`), and is saved by the new one."""
    return app_settings.current_folder(db, KEY_LOCATION, rename=rename)


def _share_entries(db: Session) -> list[dict]:
    return [{k: getattr(r, k) for k in config_store.SHARE_FIELDS} for r in db.scalars(select(NetworkShare).order_by(NetworkShare.name))]


def build_document(db: Session) -> dict:
    config = get_config(db)
    # the Stream page's saved layouts have files of their own, in streams/ (records_service.write_streams)
    config = {**config, "preferences": {k: v for k, v in config["preferences"].items() if k != "stream_layouts"}}
    return config_store.build_document(
        config, storage.custom_path("stl"), storage.custom_path("threemf"), _share_entries(db),
        project_path=storage.custom_path("project"), farm_cost_path=app_settings.get(db, FARM_COST_LOCATION),
        stream_path=app_settings.get(db, app_settings.STREAM_MEDIA_DIR_KEY),
        printer_names={p.id: p.name for p in db.scalars(select(Printer))},
    )


def _orders_here(db: Session, prefs: dict, printer_names: dict[str, str]) -> dict:
    """
    The orders kept by printer number (Farm cost's printers, Monitor's "number:camera"), in this Farmhand's numbers:
    the file says which printer each of its numbers was, and they're matched here by name (one not here is left out).
    A file from before it said leaves them as they are.
    """
    if not printer_names:
        return prefs
    here = {p.name: p.id for p in db.scalars(select(Printer))}

    def local(number) -> int | None:
        return here.get(printer_names.get(str(number), ""))

    def cameras(keys) -> list[str]:
        out = []
        for key in keys or []:
            number, sep, camera = str(key).partition(":")
            mapped = local(number) if number.isdigit() and sep else None
            if mapped is not None:
                out.append(f"{mapped}:{camera}")
        return out

    farm = [local(n) for n in prefs.get("farm_cost_order") or []]
    return {**prefs, "farm_cost_order": [n for n in farm if n is not None], "monitor_order": cameras(prefs.get("monitor_order"))}


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
    path = location_path(db, rename=True)  # one still called "Farmhand Configs" is renamed as it's written to
    if not path:
        return {"ok": True, "skipped": True, "path": None, "error": None}
    try:
        folder = storage.ensure_ready_folder(path, "settings folder")
        config_store.write_document(folder, build_document(db))
        records_service.write_all(db, folder, scope)
        records_service.write_streams(db, folder, get_config(db)["preferences"]["stream_layouts"], check_all=scope is None)
        records_service.write_stream_setup(db, folder)  # the Stream page as it's saved (never its key)
        error = None
    except storage.StorageUnavailableError as e:
        error = str(e)
    except OSError as e:
        error = f"Couldn't write the settings file: {e}"
    _last_mirror.update(ok=error is None, error=error, at=record_files.stamp())
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
    from ...database import SessionLocal

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
                "has_project_folder": bool(doc["storage"]["project_path"]),
                **records_service.count_records(real),  # "printers": n, "models": n
            }
        except config_store.ConfigFileError as e:
            out["file_valid"] = False
            out["error"] = str(e)
    return out
