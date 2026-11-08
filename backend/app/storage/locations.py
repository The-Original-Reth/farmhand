"""Choosing a folder: only under the browse root, only where files outlive the container, and whether it's ready now."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from ..config import settings
from .roots import MARKER_NAME, _custom, _has_marker, _made_default_root, effective_root, local_root


def browse_root() -> Path:
    raw = (settings.storage_browse_root or "").strip()
    return Path(os.path.realpath(Path(raw) if raw else local_root().parent))


def _real(p: str | os.PathLike) -> Path:
    return Path(os.path.realpath(p))


def is_inside(path: str | os.PathLike, root: str | os.PathLike) -> bool:
    p, r = _real(path), _real(root)
    return p == r or r in p.parents


def overlaps(a: str | os.PathLike, b: str | os.PathLike) -> bool:
    """Same folder, or one inside the other."""
    return is_inside(a, b) or is_inside(b, a)


def overlapping_kinds(roots: dict[str, Path]) -> tuple[str, str] | None:
    """Two of the locations that are the same folder or one inside the other (their numbered folders would collide)."""
    kinds = list(roots)
    for i, a in enumerate(kinds):
        for b in kinds[i + 1:]:
            if overlaps(roots[a], roots[b]):
                return a, b
    return None


def resolve_location(raw: str) -> Path:
    """Turn user input into a real path, confined to the browse root. No filesystem changes."""
    if not raw or not raw.strip():
        raise ValueError("Choose a folder.")
    p = Path(raw.strip())
    if not p.is_absolute():
        raise ValueError("Use a full path (starting with /).")
    real, root = _real(p), browse_root()
    if not is_inside(real, root):
        raise ValueError(
            f"That folder isn't under {root}. Only folders where network storage is mounted for "
            "Farmhand can be chosen — see the README for how to mount a share."
        )
    return real


def _probe_writable(d: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=d, prefix=".farmhand-write-test-"):
            pass
        return True
    except OSError:
        return False


def _is_mount(path: str | os.PathLike) -> bool:
    try:
        return os.path.ismount(path)
    except OSError:
        return False


def _has_mount_ancestor(path: Path) -> bool:
    """Is `path` on a mounted volume, i.e. it or a parent below the browse root is a mount point?"""
    root = browse_root()
    for candidate in [path, *path.parents]:
        if candidate == root:
            break
        if _is_mount(candidate):
            return True
    return False


def is_persistent(path: str | os.PathLike) -> bool:
    """
    Will files saved here still exist after the container restarts? Only inside Farmhand's own
    storage volume, or on a mounted share. Anything else (including the empty folder a share
    gets mounted over, while it's disconnected) lives in the container's throwaway filesystem.
    """
    p = _real(path)
    return is_inside(p, local_root()) or _has_mount_ancestor(p)


def validate_location(raw: str) -> Path:
    real = resolve_location(raw)
    if not real.is_dir():
        raise ValueError(f"{real} isn't an existing folder. Create it (New folder in the picker) and pick it.")
    if not is_persistent(real):
        raise ValueError(
            f"{real} isn't on a connected network share or inside Farmhand's own storage, so files saved "
            "there would be lost when the container restarts. Connect the share first (if it shows as "
            "not connected, reconnect it), then pick a folder on it."
        )
    if not _probe_writable(real):
        raise ValueError(
            f"Farmhand can't write to {real}. Check the share's permissions — the app runs as root inside its container."
        )
    return real


def mark_location(path: Path) -> None:
    marker = Path(path) / MARKER_NAME
    if not marker.exists():
        marker.write_text(
            "This folder is used by Farmhand to store files.\n"
            "If this file is missing, Farmhand refuses to write here (it assumes a network share isn't mounted).\n"
        )


def folder_status(folder: Path, *, needs_marker: bool = True) -> dict:
    """
    Whether a folder can be used: it's there, it can be written to, and (when `needs_marker`, as for every chosen
    folder) its marker is in it, so it isn't the empty folder left behind by a share that isn't mounted.
    """
    exists = folder.is_dir()
    writable = exists and _probe_writable(folder)
    marker_ok = (exists and _has_marker(folder)) if needs_marker else True
    return {"exists": exists, "writable": writable, "marker_ok": marker_ok, "ready": bool(exists and writable and marker_ok)}


def location_status(kind: str) -> dict:
    custom = bool(_custom[kind])
    root = effective_root(kind) if custom else _made_default_root(kind)
    status = folder_status(root, needs_marker=custom)  # the default folder is the app's own: no marker needed
    free = total = None
    separate = False
    if status["exists"]:
        free, total = _disk_space(root)
        separate = _has_mount_ancestor(_real(root)) and not is_inside(root, local_root())
    return {**status, "free_bytes": free, "total_bytes": total, "separate_volume": separate}


def _disk_space(folder: Path) -> tuple[int | None, int | None]:
    """(free, total) bytes on the folder's volume, or (None, None) when that can't be read."""
    try:
        du = shutil.disk_usage(folder)
    except OSError:
        return None, None
    return du.free, du.total


def _require_folder(path: Path) -> Path:
    if not path.is_dir():
        raise ValueError(f"{path} isn't a folder.")
    return path


def list_subdirs(raw: str | None) -> dict:
    """Sub-folders of `raw` (or of the browse root), for the folder picker. Confined to the browse root."""
    root = browse_root()
    target = _require_folder(resolve_location(raw) if raw else root)
    try:
        with os.scandir(target) as it:
            entries = [entry for e in it if (entry := _picker_entry(e, target, root))]
    except OSError as e:
        raise ValueError(f"Couldn't read {target}: {e}")
    entries.sort(key=lambda x: x["name"].casefold())
    return {
        "path": str(target),
        "root": str(root),
        "parent": None if target == root else str(target.parent),
        "entries": entries[:500],
    }


def _picker_entry(e: os.DirEntry, target: Path, root: Path) -> dict | None:
    """One sub-folder as the picker lists it, or None for what it skips: hidden names, files, and unreadable entries."""
    if e.name.startswith("."):
        return None
    try:
        if not e.is_dir():
            return None
        if not is_inside(e.path, root):  # a symlink leading out of the allowed area
            return None
        return {"name": e.name, "path": str(target / e.name), "is_mount": _is_mount(e.path)}
    except OSError:
        return None


_FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,79}$")


def create_folder(parent_raw: str, name: str) -> Path:
    """
    Make a new folder, for the picker's "New folder". Because the web app is the only way
    some people can reach their NAS, this is how a location gets created. Only allowed
    where it will persist (a connected share or Farmhand's own storage), never in the
    container's throwaway filesystem.
    """
    parent = _require_folder(resolve_location(parent_raw))
    name = (name or "").strip()
    if not _FOLDER_NAME.match(name):
        raise ValueError(
            "Folder names can use letters, numbers, spaces and . _ - ( ) + — and must start with a letter or number."
        )
    if not is_persistent(parent):
        raise ValueError(
            "New folders can only be made on a connected network share or inside Farmhand's own storage — "
            "open a connected share first."
        )
    target = parent / name
    if target.exists():
        raise ValueError(f"There's already a folder called “{name}” here.")
    try:
        target.mkdir()
    except OSError as e:
        raise ValueError(f"Couldn't create the folder: {e}")
    return target
