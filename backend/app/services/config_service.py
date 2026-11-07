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

from .. import config_store, mounts, storage
from ..models import NetworkShare, Printer
from . import app_settings, network_shares_service, records_service, storage_settings_service

log = logging.getLogger("farmhand.settings")

KEY_CONFIG = "config_json"  # the settings themselves (appearance + preferences), as the server holds them
KEY_LOCATION = "config_storage_dir"  # the network folder a copy is written to
FARM_COST_LOCATION = "farm_cost_dir"  # farm_cost.KEY_LOCATION: the farm cost records folder, saved with the rest

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
    prefs = dict(patch.get("preferences") or {})
    if "energy_price_per_kwh" in prefs and "energy_price_history" not in prefs:
        prefs["energy_price_history"] = _new_price_history(current["preferences"], prefs)
    prefs.pop("energy_price_from", None)
    merged = {
        "appearance": patch["appearance"] if patch.get("appearance") is not None else current["appearance"],
        "preferences": {**current["preferences"], **prefs},
    }
    config = config_store.normalize_config(merged)
    app_settings.put(db, KEY_CONFIG, json.dumps(config))
    db.commit()
    return config


def _new_price_history(current: dict, prefs: dict) -> list[dict]:
    """
    The average cost per kWh's history after it's set to a new price: the new price counts from `energy_price_from`
    (the month it is in the viewer's time zone, "2026-11"; this month in UTC if not given) on. Months before it keep
    the price they had: an earlier entry is never changed. Setting it again in the same month replaces that month's.
    """
    price = config_store.normalize_preferences({"energy_price_per_kwh": prefs["energy_price_per_kwh"]})["energy_price_per_kwh"]
    month = prefs.get("energy_price_from")
    if not (isinstance(month, str) and config_store.is_month(month)):
        month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    history = [e for e in current.get("energy_price_history") or [] if e["from"] < month]
    old = current.get("energy_price_per_kwh")
    if not current.get("energy_price_history") and old is not None and price != old:
        # a price set before there was a history: it keeps counting for the months before this one
        history = [{"from": "0001-01", "price": old}]
    if history and history[-1]["price"] == price:
        return history  # no change from what already counts
    return [*history, {"from": month, "price": price}]


# ------------------------------------------------------------------ the copy on the network folder

def location_path(db: Session, rename: bool = False) -> str | None:
    """The settings folder, where it is now: one saved by its old name ("Farmhand Configs") follows its rename to
    "farmhand-configs" (here or by another Farmhand sharing it; renamed now when `rename`), and is saved by the new one."""
    saved = app_settings.get(db, KEY_LOCATION)
    now = storage.current_folder(saved, rename=rename)
    if now != saved:
        app_settings.put(db, KEY_LOCATION, now)
        db.commit()
    return now


def _share_entries(db: Session) -> list[dict]:
    return [
        {"name": r.name, "protocol": r.protocol, "server": r.server, "share": r.share,
         "username": r.username, "domain": r.domain, "version": r.version}
        for r in db.scalars(select(NetworkShare).order_by(NetworkShare.name))
    ]


def build_document(db: Session) -> dict:
    return config_store.build_document(
        get_config(db), storage.custom_path("stl"), storage.custom_path("threemf"), _share_entries(db),
        project_path=storage.custom_path("project"), farm_cost_path=app_settings.get(db, FARM_COST_LOCATION),
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

    farm = [local(n) for n in prefs.get("farm_cost_order") or []]
    monitor = []
    for key in prefs.get("monitor_order") or []:
        number, sep, camera = str(key).partition(":")
        mapped = local(number) if number.isdigit() and sep else None
        if mapped is not None:
            monitor.append(f"{mapped}:{camera}")
    return {**prefs, "farm_cost_order": [n for n in farm if n is not None], "monitor_order": monitor}


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
                "has_project_folder": bool(doc["storage"]["project_path"]),
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


DEFAULT_FOLDER = "farmhand-configs"  # Save all with no settings folder chosen: this one, beside the STL folder


def save_all(db: Session, if_exists: str = "ask") -> dict:
    """
    Save all: everything written to the settings folder now (farmhand-config.json, and every printer's and model's
    file). With no folder chosen yet, "farmhand-configs" beside the STL folder is chosen for it, made if need be; one
    that already holds settings is never overwritten without asking (if_exists, as set_location's).
    """
    if not location_path(db):
        # StorageUnavailableError while the STL share is away; one still called "farmhand configs" is renamed
        folder = storage.named_folder(storage.ready_root("stl").parent, DEFAULT_FOLDER, rename=True)
        folder.mkdir(exist_ok=True)
        chosen = set_location(db, str(folder), if_exists)
        if not chosen["saved"]:
            return {**chosen, "mirror": None}
        restored = chosen["restored"]
    else:
        restored = None
    written = mirror(db)
    return {"saved": True, "needs_choice": False, "found": None, "restored": restored, "location": describe(db), "mirror": written}


def _same_place(a: dict, b: NetworkShare) -> bool:
    """Does a share in the settings file reach the same folder on the same NAS as one here?"""
    def where(protocol, server, share):
        share = (share or "").strip().strip("/\\").replace("\\", "/")
        same_case = protocol == "nfs"  # SMB ignores case; an NFS export is a path
        return protocol, (server or "").strip().lower(), share if same_case else share.lower()
    return where(a.get("protocol"), a.get("server"), a.get("share")) == where(b.protocol, b.server, b.share)


def _shares_here(db: Session, entries: list[dict]) -> dict[str, NetworkShare]:
    """
    The settings file's shares that reach a NAS folder a share here already does, under another name (the one typed
    as the Save location on a new Farmhand, say): {its name: the share here}. Those aren't added a second time (it
    would only wait for a password, and the folders on it with it): the folders on them are taken as on the one here.
    """
    here = list(db.scalars(select(NetworkShare)))
    out = {}
    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        match = next((row for row in here if _same_place(entry, row)), None)
        if match is not None and mounts.slug(match.name) != mounts.slug(name):
            out[name] = match
    return out


def _moved_onto(path: str | None, shares: dict[str, NetworkShare]) -> str | None:
    """A folder from the settings file, on the share here that reaches the same place (see _shares_here)."""
    if not path:
        return path
    for name, row in shares.items():
        try:
            rest = Path(path).relative_to(mounts.mount_point_for(name))
        except ValueError:
            continue
        return str(mounts.mount_point_for(row.name) / rest)
    return path


def restore(db: Session) -> dict:
    """Load the settings file in the chosen folder into Farmhand."""
    path = location_path(db)
    if not path:
        raise ValueError("Choose a settings folder first.")
    doc = config_store.read_document(path)  # ConfigFileError (a ValueError) if unusable
    if doc is None:
        raise ValueError("There's no settings file in that folder yet.")

    result = {"restored": ["appearance", "display preferences"], "shares_added": [], "shares_kept": [], "needs_password": [], "warnings": []}
    save_config(db, {"appearance": doc["appearance"], "preferences": _orders_here(db, doc["preferences"], doc["printer_names"])})

    same = _shares_here(db, doc["shares"])
    applied, warnings = storage_settings_service.restore_locations(
        db, *(_moved_onto(doc["storage"][k], same) for k in ("stl_path", "threemf_path", "project_path"))
    )
    result["restored"] += applied
    result["warnings"] += warnings

    farm_cost_path = storage.current_folder(_moved_onto(doc["farm_cost"]["records_path"], same))  # saved by its old name: where it is now
    if farm_cost_path and farm_cost_path != app_settings.get(db, FARM_COST_LOCATION):
        from .farm_cost import set_location as set_farm_cost_location  # (farm_cost reads these settings itself)

        try:
            set_farm_cost_location(db, farm_cost_path)
            result["restored"].append("farm cost folder")
        except ValueError as e:
            result["warnings"].append(f"The farm cost folder ({farm_cost_path}) wasn't put back: {e}")

    for entry in doc["shares"]:
        label = entry.get("name") or "(unnamed)"
        if label in same:
            result["shares_kept"].append(f"{label} (the same NAS folder as {same[label].name})")
            continue
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
    # the printer orders once more, now the printers from the printers/ files are here too (a new Farmhand had none)
    ordered = _orders_here(db, doc["preferences"], doc["printer_names"])
    save_config(db, {"preferences": {k: ordered[k] for k in ("farm_cost_order", "monitor_order") if k in ordered}})
    return result
