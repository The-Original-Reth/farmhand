from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import mounts, storage
from ..models import NetworkShare
from ..mounts import MountError, ShareSpec
from .storage_settings_service import count_version_files

log = logging.getLogger("farmhand.shares")

# Errors where trying again by itself can't help — and where repeated attempts with a wrong
# password could get the NAS account locked out. The person fixes it, then presses Reconnect.
_NO_AUTO_RETRY = ("auth", "privilege", "unsupported")


class ShareNotFound(ValueError):
    pass


class ShareInUse(ValueError):
    """The share is still chosen as a storage location."""


def _get(db: Session, share_id: int) -> NetworkShare:
    row = db.get(NetworkShare, share_id)
    if row is None:
        raise ShareNotFound(f"No network share with id {share_id}")
    return row


def _name_taken(db: Session, name: str) -> bool:
    """Is there a share already whose name gives the same mount folder (names that differ only in case, say)?"""
    wanted = mounts.slug(name)
    return any(mounts.slug(existing) == wanted for existing in db.scalars(select(NetworkShare.name)))


def _spec(row: NetworkShare) -> ShareSpec:
    return ShareSpec(row.protocol, row.server, row.share, row.username, row.password, row.domain, row.version)


def _files_here(db: Session, mount_point: Path) -> int:
    here = lambda p: storage.is_inside(p, mount_point)  # noqa: E731
    return sum(count_version_files(db, here, here))


def _out(db: Session, row: NetworkShare) -> dict:
    mount_point = mounts.mount_point_for(row.name)
    err = mounts.get_error(row.id)
    address = f"smb://{row.server}/{row.share}" if row.protocol == "smb" else f"{row.server}:{row.share}"
    return {
        "id": row.id,
        "name": row.name,
        "protocol": row.protocol,
        "server": row.server,
        "share": row.share,
        "username": row.username,
        "domain": row.domain,
        "version": row.version,
        "has_password": bool(row.password),
        "address": address,
        "mount_point": str(mount_point),
        "mounted": mounts.is_mounted(mount_point),
        "error": err[1] if err else None,
        "error_kind": err[0] if err else None,
        "files_here": _files_here(db, mount_point),
    }


def list_shares(db: Session) -> dict:
    rows = db.scalars(select(NetworkShare).order_by(NetworkShare.name))
    return {"shares": [_out(db, r) for r in rows], "capability": mounts.mount_capability()}


def create_share(db: Session, data: dict) -> dict:
    """Mount first; only a share that actually connected is saved, so there are no half-working entries."""
    name = mounts.validate_name(data.get("name"))
    if (data.get("location") or "").strip():
        protocol, server, share = mounts.parse_location(data["location"])
    else:
        protocol, server, share = data.get("protocol"), data.get("server"), data.get("share")
    spec = mounts.validate_fields(
        protocol, server, share,
        data.get("username"), data.get("password"), data.get("domain"), data.get("version"),
    )
    if _name_taken(db, name):
        raise ValueError(f"There's already a share called “{name}”.")

    mount_point = mounts.mount_point_for(name)
    mounts.mount(spec, mount_point)  # raises MountError with a plain-language reason

    row = NetworkShare(
        name=name, protocol=spec.protocol, server=spec.server, share=spec.share,
        username=spec.username, password=spec.password, domain=spec.domain, version=spec.version,
    )
    try:
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        _unmount_quietly(mount_point)
        raise
    mounts.clear_error(row.id)
    return _out(db, row)


def _unmount_quietly(mount_point: Path, lazy: bool = False) -> None:
    """Unmount it if that can be done; tidying up, so a failure isn't news."""
    try:
        mounts.unmount(mount_point, lazy=lazy)
    except MountError:
        pass


def _rmdir_quietly(folder: Path) -> None:
    """Remove the folder if it's empty (and leave it if it isn't)."""
    try:
        folder.rmdir()
    except OSError:
        pass


def _discard_scratch(scratch: Path) -> None:
    _unmount_quietly(scratch, lazy=True)
    _rmdir_quietly(scratch)


def update_share(db: Session, share_id: int, changes: dict) -> dict:
    """
    Change a share's address or login. The new settings are tried on a scratch mount first,
    so a typo can't take down a share that's working and in use.
    """
    row = _get(db, share_id)
    merged = {
        "server": row.server, "share": row.share, "username": row.username,
        "password": row.password, "domain": row.domain, "version": row.version,
    }
    for field in ("server", "share", "domain", "version"):
        if field in changes:
            merged[field] = changes[field]
    if (changes.get("location") or "").strip():
        protocol, server, share = mounts.parse_location(changes["location"])
        if protocol != row.protocol:
            raise ValueError(
                f"“{row.name}” is an {row.protocol.upper()} share, but that address is {protocol.upper()}. "
                "To use a different kind of share, add it as a new one."
            )
        merged["server"], merged["share"] = server, share
    if "username" in changes:
        merged["username"] = (changes["username"] or "").strip() or None
        if merged["username"] is None:
            merged["password"] = None  # switching to guest access
    if changes.get("password"):
        merged["password"] = changes["password"]
    spec = mounts.validate_fields(row.protocol, merged["server"], merged["share"], merged["username"],
                                  merged["password"], merged["domain"], merged["version"])

    scratch = mounts.scratch_mount_point(row.id)
    try:
        mounts.mount(spec, scratch)
    finally:
        _discard_scratch(scratch)

    mount_point = mounts.mount_point_for(row.name)
    mounts.unmount(mount_point)  # MountError("busy") here leaves everything as it was

    row.server, row.share, row.username = spec.server, spec.share, spec.username
    row.password, row.domain, row.version = spec.password, spec.domain, spec.version
    db.commit()
    _mount_noting_errors(row, spec, mount_point)
    return _out(db, row)


def reconnect_share(db: Session, share_id: int) -> dict:
    row = _get(db, share_id)
    _mount_noting_errors(row, _spec(row), mounts.mount_point_for(row.name))
    return _out(db, row)


def _mount_noting_errors(row: NetworkShare, spec: ShareSpec, mount_point: Path) -> None:
    """Mount a saved share. Why it failed is kept for the page to show (and raised); a success clears that."""
    try:
        mounts.mount(spec, mount_point)
    except MountError as e:
        mounts.set_error(row.id, e.kind, str(e))
        raise
    mounts.clear_error(row.id)


def delete_share(db: Session, share_id: int) -> None:
    """Disconnect and forget a share. Files on the NAS are left alone."""
    row = _get(db, share_id)
    mount_point = mounts.mount_point_for(row.name)

    labels = {"stl": "STL files", "threemf": "3MF files"}
    in_use = [labels[k] for k in storage.KINDS if storage.custom_path(k) and storage.is_inside(storage.custom_path(k), mount_point)]
    if in_use:
        raise ShareInUse(
            f"“{row.name}” is still where your {' and '.join(in_use)} are stored. Choose another location for "
            "them first (or switch back to the default), then remove it."
        )

    mounts.unmount(mount_point)  # MountError("busy") if something is using it
    db.delete(row)
    db.commit()
    mounts.clear_error(share_id)
    _rmdir_quietly(mount_point)


def ensure_mounted(db: Session) -> None:
    """
    Make sure every saved share is mounted. Called at startup and then regularly, which is what
    brings shares back after a restart (mounts don't survive one) or when the NAS is switched
    on later than this computer.
    """
    for row in db.scalars(select(NetworkShare)):
        mount_point = mounts.mount_point_for(row.name)
        if mounts.is_mounted(mount_point):
            mounts.clear_error(row.id)
            continue
        err = mounts.get_error(row.id)
        if err and err[0] in _NO_AUTO_RETRY:
            continue
        try:
            _mount_noting_errors(row, _spec(row), mount_point)
            log.info("Mounted network share %r at %s", row.name, mount_point)
        except MountError as e:
            log.warning("Couldn't mount network share %r: %s", row.name, e)


def restore_share(db: Session, data: dict) -> str:
    """
    Put a share back from the settings file. Returns "added", "kept" (one with that name is already here)
    or raises ValueError if the entry isn't usable. Passwords are never in the file, so the share comes back
    saved but not connected: an SMB share that uses a login says it needs its password (Edit, then enter it);
    one without a login, or an NFS export, simply connects with the others in the background.
    """
    name = mounts.validate_name(data.get("name"))
    spec = mounts.validate_fields(
        data.get("protocol"), data.get("server"), data.get("share"),
        data.get("username"), None, data.get("domain"), data.get("version"),
    )
    if _name_taken(db, name):
        return "kept"
    row = NetworkShare(
        name=name, protocol=spec.protocol, server=spec.server, share=spec.share,
        username=spec.username, password=None, domain=spec.domain, version=spec.version,
    )
    db.add(row)
    db.commit()
    if spec.protocol == "smb" and spec.username:
        mounts.set_error(
            row.id, "auth",
            "Enter this share's password to connect it (passwords aren't kept in the settings file). Use Edit.",
        )
    return "added"
