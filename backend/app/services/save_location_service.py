"""
The save location: ONE place on the NAS, typed as its address, that everything Farmhand keeps goes inside.

Setting it connects to the share (the one already connected there is reused, also when the address is a folder inside
it; otherwise a new one is added, mounted first as always), then uses a folder inside it for each kind of file,
reusing one already there whatever its capitals, and making the rest:

    STL               the source model files (the Models library)
    3MF               the sliced 3MF files and their G-code
    Projects          each project's own files
    farm-cost         the monthly farm cost records ("farm cost" before: renamed)
    farmhand-configs  the settings copy (Save all / Load all settings) ("Farmhand Configs" before: renamed)

Files already saved elsewhere stay where they are (Settings offers to move them); only new ones go to the new folders.
A settings folder that already holds saved settings is never written over without asking.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import mounts, storage
from ..models import NetworkShare
from . import app_settings, config_service, farm_cost, network_shares_service, storage_settings_service

KEY = "save_location"  # the address as typed
FOLDERS = {
    "stl": storage.STL_FOLDER, "threemf": storage.THREEMF_FOLDER, "project": storage.PROJECTS_FOLDER,
    "farm_cost": storage.FARM_COST_FOLDER, "config": storage.CONFIG_FOLDER,
}


def _existing_share(db: Session, protocol: str, server: str, share: str) -> tuple[NetworkShare, str] | None:
    """The share already connected to that place, and the folder inside it the address points at ("" for its top)."""
    for row in db.scalars(select(NetworkShare).order_by(NetworkShare.id)):
        inside = network_shares_service.folder_inside(row, protocol, server, share)
        if inside is not None:
            return row, inside
    return None


def _new_name(db: Session, share: str) -> str:
    """A name for a share added here: its own name ("Farmhand" for 3d_prints/Farmhand), made unique."""
    base = (share.strip("/").split("/")[-1] or "NAS")[:30]
    name, n = base, 2
    while network_shares_service.name_taken(db, name):
        name, n = f"{base} {n}", n + 1
    return name


def _folder(base: Path, name: str) -> Path:
    """The folder of that name inside base: one already there (whatever its capitals), or one with its old name renamed
    to it (storage.FOLDER_RENAMES), else a new one."""
    if not base.is_dir():
        raise ValueError(f"Couldn't look inside {base}: it isn't there.")
    path = storage.named_folder(base, name, rename=True)
    if path.is_dir():
        return path
    try:
        path.mkdir(exist_ok=True)
    except OSError as e:
        raise ValueError(f"Couldn't make the {name} folder in {base}: {e}") from None
    return path


def _share_of(db: Session, address: str | None) -> NetworkShare | None:
    if not address:
        return None
    try:
        found = _existing_share(db, *mounts.parse_location(address))
    except ValueError:
        return None
    return found[0] if found else None


def describe(db: Session) -> dict:
    """
    The save location as typed (null until it's set), its share as the shares list shows one (connected or not, why
    not, its login without the password, SMB version...; null until set), whether this container may mount shares at
    all, and the folder each kind of file goes to now.
    """
    config_path = config_service.location_path(db)
    address = app_settings.get(db, KEY)
    row = _share_of(db, address)
    return {
        "address": address,
        "share": network_shares_service.share_out(db, row) if row else None,
        "capability": mounts.mount_capability(),
        "folders": {
            "stl": str(storage.effective_root("stl")),
            "threemf": str(storage.effective_root("threemf")),
            "project": str(storage.effective_root("project")),
            "farm_cost": farm_cost.location_info(db)["path"],
            "config": config_path,
        },
    }


def set_save_location(db: Session, data: dict) -> dict:
    """
    Use the address typed (and its login, for SMB) as the place everything goes. ValueError says why it can't be
    (a bad address, the NAS refusing the login, a folder that can't be made). Answers describe(), plus config_choice:
    what's in the farmhand-configs folder when it already holds saved settings that need a choice (Load them, or
    replace them with these), else null.
    """
    address = (data.get("address") or "").strip()
    protocol, server, share = mounts.parse_location(address)
    username = (data.get("username") or "").strip() or None
    password = data.get("password") or None

    found = _existing_share(db, protocol, server, share)
    if found:
        row, inside = found
        changes = {}
        if "username" in data and username != row.username:
            changes["username"] = username
        if password and password != row.password:
            changes["password"] = password
        for field in ("domain", "version"):  # Advanced: the workgroup and the SMB / NFS version
            if field in data and ((data[field] or "").strip() or None) != getattr(row, field):
                changes[field] = (data[field] or "").strip() or None
        if changes:
            network_shares_service.update_share(db, row.id, changes)  # tried on a scratch mount first
        elif not mounts.is_mounted(mounts.mount_point_for(row.name)):
            network_shares_service.reconnect_share(db, row.id)
    else:
        name = _new_name(db, share)
        network_shares_service.create_share(db, {
            "name": name, "location": address, "username": username, "password": password,
            "domain": data.get("domain"), "version": data.get("version"),
        })  # mounted first: only a share that connects is kept
        row = db.scalar(select(NetworkShare).where(NetworkShare.name == name))
        inside = ""

    mount_point = mounts.mount_point_for(row.name)
    if not mounts.is_mounted(mount_point):
        err = mounts.get_error(row.id)
        raise ValueError(f"Couldn't connect to {address}: {err[1] if err else 'the NAS did not answer'}")
    base = mount_point / inside if inside else mount_point
    if inside:
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValueError(f"Couldn't make {inside} on the share: {e}") from None

    folders = {kind: _folder(base, name) for kind, name in FOLDERS.items()}
    storage_settings_service.save(db, {f"{k}_path": str(folders[k]) for k in ("stl", "threemf", "project")})
    farm_cost.set_location(db, str(folders["farm_cost"]))

    config_choice = None
    target = os.path.realpath(folders["config"])
    current = config_service.location_path(db)
    if not current or os.path.realpath(current) != target:
        chosen = config_service.set_location(db, target, "ask")
        if chosen["needs_choice"]:
            config_choice = chosen["found"]  # settings saved there already: the page asks to load or replace them

    app_settings.put(db, KEY, address)
    db.commit()
    config_service.mirror_quietly(db)
    return {**describe(db), "config_choice": config_choice}
