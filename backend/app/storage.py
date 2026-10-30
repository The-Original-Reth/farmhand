"""
File storage on local disk or a mounted network share.

Two locations for the large files, chosen independently in Settings → Storage:

  STL / OBJ / STEP source files   {stl_root}/{source_model_id}/v{n}/{filename}
  3MF and gcode files             {threemf_root}/{bundle_id}/v{n}/{filename}

Thumbnails are small, derived, and read on every page load, so they always stay
on the app's own local disk — browsing keeps working even if a share is down:

  {storage_root}/thumbnails/source_models/{id}/v{n}/thumbnail.png
  {storage_root}/thumbnails/bundles/{id}/v{n}/thumbnail.png

Until a location is chosen, the defaults keep the original layout:
  {storage_root}/source_models and {storage_root}/bundles

Every path stored in the database is absolute, so files stay readable where
they are when a location changes; `copy_verified` + the migration action in
storage_settings_service move them on request.

Network shares are mounted into the container from outside (see the README);
this module only reads/writes folders. A mount that silently drops leaves an
empty directory behind in its place, and writes would then land on the local
disk by accident. To guard against that, every folder chosen in the UI gets a
marker file, and writes to a chosen folder are refused when the marker is gone.
"""
from __future__ import annotations

import errno
import logging
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import settings

log = logging.getLogger("farmhand.storage")

MARKER_NAME = ".farmhand-storage"
KINDS = ("stl", "threemf")
_LABELS = {"stl": "STL / model file", "threemf": "3MF / gcode"}


class StorageUnavailableError(RuntimeError):
    """A chosen storage folder can't be written right now (e.g. an unmounted network share)."""


# kind -> folder chosen in the UI, or None for the default. Set at startup from the
# database and whenever the setting changes (single-process app, so a module global is fine).
_custom: dict[str, str | None] = {"stl": None, "threemf": None}


def configure(stl_path: str | None = None, threemf_path: str | None = None) -> None:
    _custom["stl"] = stl_path or None
    _custom["threemf"] = threemf_path or None


def reset() -> None:
    configure(None, None)


def custom_path(kind: str) -> str | None:
    return _custom[kind]


# ------------------------------------------------------------------ locations


def local_root() -> Path:
    p = Path(settings.storage_root)
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_root(kind: str) -> Path:
    return local_root() / ("source_models" if kind == "stl" else "bundles")


def effective_root(kind: str) -> Path:
    return Path(_custom[kind]) if _custom[kind] else default_root(kind)


def thumbnails_root() -> Path:
    return local_root() / "thumbnails"


def ready_root(kind: str) -> Path:
    """
    The folder to write into for this kind, if it's usable right now: a chosen folder that looks unmounted is refused
    (StorageUnavailableError).
    """
    custom = _custom[kind]
    if not custom:
        root = default_root(kind)
        root.mkdir(parents=True, exist_ok=True)
        return root

    return ensure_ready_folder(custom, f"{_LABELS[kind]} storage folder")


def ensure_ready_folder(path: str, noun: str) -> Path:
    """
    A folder chosen in the UI that is safe to write into right now: it exists and still has its marker
    file. A share that silently dropped leaves an empty folder with no marker, and writing there would
    quietly fill the local disk instead. `noun` names the folder in the message ("settings folder").
    """
    root = Path(path)
    if not root.is_dir():
        raise StorageUnavailableError(
            f"The {noun} ({root}) isn't available. If it's on a network share, "
            "check that the share is mounted and reachable. Nothing was saved."
        )
    if not (root / MARKER_NAME).is_file():
        raise StorageUnavailableError(
            f"The {noun} ({root}) is missing its Farmhand marker file. That usually "
            "means a network share isn't mounted right now and this is just the empty folder "
            "underneath it. Nothing was saved. Check the mount, or re-select the folder in Storage settings."
        )
    return root


def _version_dir(base: Path, owner_id: int, version: int) -> Path:
    """{base}/{id}/v{n}, made if it isn't there yet."""
    d = base / str(owner_id) / f"v{version}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def source_model_version_dir(source_model_id: int, version: int) -> Path:
    return _version_dir(ready_root("stl"), source_model_id, version)


def bundle_version_dir(bundle_id: int, version: int) -> Path:
    return _version_dir(ready_root("threemf"), bundle_id, version)


def source_model_thumbnail_dir(source_model_id: int, version: int) -> Path:
    return _version_dir(thumbnails_root() / "source_models", source_model_id, version)


def bundle_thumbnail_dir(bundle_id: int, version: int) -> Path:
    return _version_dir(thumbnails_root() / "bundles", bundle_id, version)


# ------------------------------------------------------------------ writing


def _safe_name(filename: str) -> str:
    """Just the file's own name — never a path an upload tried to smuggle in."""
    name = Path(filename or "").name
    if name in ("", ".", ".."):
        raise ValueError("Invalid file name")
    return name


def preview_cache_headers(request_query: dict) -> dict:
    """
    How long a browser may keep a preview image. Asked for with ?r=<its revision> (as the page does), the address
    changes whenever the picture does, so it can be kept for good; otherwise check back each time (cheap: 304).
    """
    return {"Cache-Control": "public, max-age=31536000, immutable" if "r" in request_query else "no-cache"}


@contextmanager
def _written_whole(dest: Path) -> Iterator[Path]:
    """
    Write `dest` whole or not at all: the block writes the temporary file it's given ("<name>.part"), which then
    replaces `dest`. If anything goes wrong part-way (a share dropping mid-write), the temporary file is removed and
    `dest` is left as it was, so a truncated file never looks real.
    """
    part = dest.with_name(dest.name + ".part")
    try:
        yield part
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def save_upload(dest_dir: Path, filename: str, file_obj) -> str:
    """
    Write an uploaded file (anything with .read()) into dest_dir. Written under a
    temporary name and renamed, so a failure part-way (a network share dropping
    mid-write) never leaves a truncated file that looks real.
    """
    dest = Path(dest_dir) / _safe_name(filename)
    with _written_whole(dest) as part, open(part, "wb") as out:
        shutil.copyfileobj(file_obj, out)
    return str(dest)


def write_text_atomically(target: str | os.PathLike, text: str) -> None:
    """
    Write a UTF-8 text file whole or not at all: under a temporary name, then renamed over the old one, so a share
    dropping mid-write never leaves a half-written file behind (the settings file, the printer and model files).
    """
    with _written_whole(Path(target)) as part:
        part.write_text(text, encoding="utf-8")


def preview_beside(model_file: str | None) -> str | None:
    """Where a model file's preview is kept next to it: "Frog.stl" -> "Frog.stl.png" (on the NAS if that's where it is)."""
    return f"{model_file}.png" if model_file else None


def save_preview_beside(model_file: str, png: bytes) -> str | None:
    """
    Keep a copy of a model's preview next to its file. The local copy is the one the page shows (so browsing keeps
    working when a share is offline), so this fails soft: a folder that can't be written to just goes without.
    """
    target = Path(preview_beside(model_file))
    try:
        with _written_whole(target) as part:
            part.write_bytes(png)
        return str(target)
    except OSError as e:
        log.warning("Couldn't save the preview next to %s: %s", model_file, e)
        return None


def save_bytes(dest_dir: Path, filename: str, data: bytes) -> str:
    dest = Path(dest_dir) / _safe_name(filename)
    dest.write_bytes(data)
    return str(dest)


def copy_verified(src: str | os.PathLike, dest_dir: str | os.PathLike, name: str | None = None) -> str:
    """Copy a file into dest_dir and confirm the size matches before it counts. Returns the new path."""
    src = Path(src)
    dest = Path(dest_dir) / _safe_name(name or src.name)
    with _written_whole(dest) as part:
        shutil.copy2(src, part)
        if part.stat().st_size != src.stat().st_size:
            raise OSError(f"Copy of {src.name} came out the wrong size — it was not used")
    return str(dest)


def move_file(src: str | os.PathLike, dest_dir: str | os.PathLike, name: str | None = None) -> str:
    """
    Move a file into dest_dir and return its new path. Never overwrites, and never leaves two copies or a
    half-moved file behind: it either ends up moved, or stays exactly where it was and this raises.

    Within one filesystem (the normal case: a folder and its sub-folders, on a NAS or not) that's a rename:
    instant, whatever the size. Across filesystems it's a verified copy followed by deleting the original;
    and if the original can't be deleted (a read-only share) the copy is removed again and this raises.
    """
    src = Path(src)
    dest = Path(dest_dir) / _safe_name(name or src.name)
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")
    try:
        os.rename(src, dest)
        return str(dest)
    except OSError as e:
        if e.errno != errno.EXDEV:  # anything but "different filesystems" is a real problem: leave the file alone
            raise
    copied = copy_verified(src, dest_dir, name)
    try:
        src.unlink()
    except OSError:
        Path(copied).unlink(missing_ok=True)
        raise
    return copied


# ------------------------------------------------------------------ deleting

_VERSION_DIR = re.compile(r"^v\d+$")
_ID_DIR = re.compile(r"^\d+$")


def _rmdir_if_empty(d: Path) -> bool:
    try:
        d.rmdir()  # only ever succeeds on an empty directory
        return True
    except OSError:
        return False


def is_managed_layout(path: str | None, owner_id: int, version: int) -> bool:
    """
    Is this file where Farmhand itself put it — `.../{owner_id}/v{version}/{file}`? Files found by a scan
    are filed that way too now, but ones imported by earlier versions were registered where they sat, and
    the folders around those belong to the person who made them, so deleting such a file must never tidy
    those folders away.
    """
    if not path:
        return False
    parent = Path(path).parent
    return parent.name == f"v{version}" and parent.parent.name == str(owner_id)


def delete_files(paths: Iterable[str | None], prune: bool = True) -> None:
    """
    Delete exactly the files we recorded, then (if `prune`) tidy up the now-empty `v{n}` and `{id}`
    folders we created for them. Never deletes anything else — no recursive removes —
    which matters when the folder is someone's network share.
    """
    folders: set[Path] = set()
    for p in paths:
        if not p:
            continue
        path = Path(p)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("Couldn't delete %s: %s", path, e)
        folders.add(path.parent)
    if not prune:
        return
    for d in folders:
        if _VERSION_DIR.match(d.name):
            _rmdir_if_empty(d)
            if _ID_DIR.match(d.parent.name):
                _rmdir_if_empty(d.parent)


# ------------------------------------------------------------------ choosing a location


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
    marker_ok = (exists and (folder / MARKER_NAME).is_file()) if needs_marker else True
    return {"exists": exists, "writable": writable, "marker_ok": marker_ok, "ready": bool(exists and writable and marker_ok)}


def location_status(kind: str) -> dict:
    root, custom = effective_root(kind), bool(_custom[kind])
    if not custom:
        root.mkdir(parents=True, exist_ok=True)
    status = folder_status(root, needs_marker=custom)  # the default folder is the app's own: no marker needed
    exists = status["exists"]
    free = total = None
    separate = False
    if exists:
        try:
            du = shutil.disk_usage(root)
            free, total = du.free, du.total
        except OSError:
            pass
        separate = _has_mount_ancestor(_real(root)) and not is_inside(root, local_root())
    return {**status, "free_bytes": free, "total_bytes": total, "separate_volume": separate}


def list_subdirs(raw: str | None) -> dict:
    """Sub-folders of `raw` (or of the browse root), for the folder picker. Confined to the browse root."""
    root = browse_root()
    target = resolve_location(raw) if raw else root
    if not target.is_dir():
        raise ValueError(f"{target} isn't a folder.")
    entries = []
    try:
        with os.scandir(target) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if not e.is_dir():
                        continue
                    if not is_inside(e.path, root):  # a symlink leading out of the allowed area
                        continue
                    entries.append(
                        {"name": e.name, "path": str(target / e.name), "is_mount": _is_mount(e.path)}
                    )
                except OSError:
                    continue
    except OSError as e:
        raise ValueError(f"Couldn't read {target}: {e}")
    entries.sort(key=lambda x: x["name"].casefold())
    return {
        "path": str(target),
        "root": str(root),
        "parent": None if target == root else str(target.parent),
        "entries": entries[:500],
    }


_FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,79}$")


def create_folder(parent_raw: str, name: str) -> Path:
    """
    Make a new folder, for the picker's "New folder". Because the web app is the only way
    some people can reach their NAS, this is how a location gets created. Only allowed
    where it will persist (a connected share or Farmhand's own storage), never in the
    container's throwaway filesystem.
    """
    parent = resolve_location(parent_raw)
    if not parent.is_dir():
        raise ValueError(f"{parent} isn't a folder.")
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
