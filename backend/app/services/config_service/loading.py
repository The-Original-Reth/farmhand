"""
Choosing the settings folder, Save all, and Load all (restore): everything in the settings folder brought back, so
a new Farmhand works and looks like the one that saved it.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import config_store, mounts, storage
from ...models import NetworkShare
from .. import app_settings, network_shares_service, records_service, storage_settings_service

from .nas_copy import FARM_COST_LOCATION, KEY_LOCATION, _orders_here, describe, inspect_location, location_path, mirror
from .settings import save_config

log = logging.getLogger("farmhand.settings")

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


DEFAULT_FOLDER = storage.CONFIG_FOLDER  # Save all with no settings folder chosen: this one, beside the STL folder


def save_all(db: Session, if_exists: str = "ask") -> dict:
    """
    Save all: everything written to the settings folder now (farmhand-config.json, and every printer's and model's
    file), and every model's, 3MF's and project's record beside its files (write_records). With no folder chosen yet, "farmhand-configs" beside the STL folder is chosen for it, made if need be; one
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
    return {
        "saved": True, "needs_choice": False, "found": None, "restored": restored, "location": describe(db), "mirror": written,
        "records": write_records(db),
    }


def write_records(db: Session) -> dict:
    """
    The records kept beside the files, written now too: each model's and library 3MF's in its folder, and each project's
    (its 3MFs, STLs and other files, its parts list) in the project's folder. Otherwise they're written only after a
    change and when Farmhand starts, so one missed then (a share away, an older version) waited for the next change.
    Answers how many of each were written; a folder that's away is skipped.
    """
    from .. import library_records, project_records  # (they import services that import this package)

    return {"library": library_records.write_all(db), "projects": project_records.write_all(db)}


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
        match = next((row for row in here if network_shares_service.folder_inside(
            row, entry.get("protocol"), entry.get("server"), entry.get("share")) == ""), None)
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
        from ..farm_cost import set_location as set_farm_cost_location  # (farm_cost reads these settings itself)

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
    result["brought_in"] = bring_in_files(db, result["warnings"])
    if records["models_missing"] and (result["brought_in"]["models"] or result["brought_in"]["threemfs"]):
        # the notes and stars of the models and 3MFs just brought in
        again = records_service.restore_model_notes(db, path)
        for key in ("model_notes", "threemf_notes", "stars"):
            records[key] += again[key]
        records["models_missing"] = again["models_missing"]
    return result


def bring_in_files(db: Session, warnings: list[str]) -> dict:
    """
    Load all's last step, once the printers are here (each 3MF is for one): every model, 3MF and project another Farmhand
    keeps in the shared folders that isn't here yet, from the records beside their files, and every file it added to a
    project that's here already. "Here" is the same file on the NAS: nothing is copied, brought in twice, or changed.
    Answers {models: [names], threemfs: [names], projects: [{name, files, added}]}; what's left out goes in warnings.
    """
    from .. import library_records, project_scan  # (they import services that import this package)

    library = library_records.import_library(db)  # a folder that's away is passed over
    warnings += [f"{s['name']} wasn't brought in: {s['reason']}" for s in library["skipped"]]
    projects = []
    try:
        found = project_scan.import_projects_folder(db, add_missing=True)
    except storage.StorageUnavailableError as e:
        warnings.append(f"The projects weren't brought in: {e}")
    else:
        for p in found["imported"]:
            projects.append({"name": p["name"], "files": p["files"], "added": bool(p.get("updated"))})
            warnings += [f"{p['name']}: {w}" for w in p["warnings"]]
        warnings += [f"The project {s['name']} wasn't brought in: {s['reason']}" for s in found["skipped"]]
    return {"models": library["models"], "threemfs": library["threemfs"], "projects": projects}
