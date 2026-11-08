"""Where each kind of file goes: the folders chosen in Settings or the defaults, and each version's own folder."""
from __future__ import annotations

import os
from pathlib import Path

from ..config import settings


MARKER_NAME = ".farmhand-storage"
KINDS = ("stl", "threemf", "project")
_LABELS = {"stl": "STL / model file", "threemf": "3MF / gcode", "project": "project files"}
FOLDER_LABELS = {"stl": "STL", "threemf": "3MF", "project": "project files"}  # "the STL folder", "the project files folder"


class StorageUnavailableError(RuntimeError):
    """A chosen storage folder can't be written right now (e.g. an unmounted network share)."""


# kind -> folder chosen in the UI, or None for the default. Set at startup from the
# database and whenever the setting changes (single-process app, so a module global is fine).
_custom: dict[str, str | None] = {"stl": None, "threemf": None, "project": None}


def configure(stl_path: str | None = None, threemf_path: str | None = None, project_path: str | None = None) -> None:
    _custom["stl"] = stl_path or None
    _custom["threemf"] = threemf_path or None
    _custom["project"] = project_path or None


def reset() -> None:
    configure(None, None, None)


def custom_path(kind: str) -> str | None:
    return _custom[kind]


# ------------------------------------------------------------------ locations


def local_root() -> Path:
    p = Path(settings.storage_root)
    p.mkdir(parents=True, exist_ok=True)
    return p


# The folders Farmhand names itself, beside the STL folder (or inside the save location)
STL_FOLDER = "STL"  # the source model files, inside a save location
THREEMF_FOLDER = "3MF"  # the sliced 3MFs and their G-code, inside a save location
PROJECTS_FOLDER = "Projects"  # the project files' default when the STL folder is chosen: beside it
FARM_COST_FOLDER = "farm-cost"  # the monthly Farm cost records' default
CONFIG_FOLDER = "farmhand-configs"  # the settings copy's default (Save all / Load all)

# Folders Farmhand names itself, and what each was called before: one with its old name is renamed when it's next used
# (named_folder), and a folder saved by its old name follows the rename (current_folder): also when another Farmhand
# sharing the folders renamed it.
FOLDER_RENAMES = {FARM_COST_FOLDER: ("farm cost",), CONFIG_FOLDER: ("farmhand configs",)}


def _dir_named(parent: Path, names) -> Path | None:
    """The folder in parent with one of these names, whatever its capitals (the first name found first)."""
    wanted = [n.lower() for n in names]
    try:
        found = {e.name.lower(): Path(e.path) for e in os.scandir(parent) if e.is_dir()}
    except OSError:
        return None
    return next((found[n] for n in wanted if n in found), None)


def named_folder(parent: Path, name: str, rename: bool = False) -> Path:
    """
    The folder Farmhand calls `name` in parent: one already there (whatever its capitals); else one with its old name
    (FOLDER_RENAMES), renamed to `name` when `rename` (it stays as it was if it can't be); else parent / name, not made.
    """
    found = _dir_named(parent, [name])
    if found is not None:
        return found
    old = _dir_named(parent, FOLDER_RENAMES.get(name, ()))
    if old is None:
        return parent / name
    if not rename:
        return old
    try:
        os.rename(old, parent / name)
        return parent / name
    except OSError:
        return old


def current_folder(path: str | None, rename: bool = False) -> str | None:
    """
    A folder saved by one of its old names ("…/farm cost"): where it is now ("…/farm-cost") when it's been renamed
    (here or by another Farmhand sharing it), renamed now when `rename`. Anything else as it is.
    """
    if not path:
        return path
    p = Path(path)
    for new, olds in FOLDER_RENAMES.items():
        if p.name.lower() in olds and (rename or not p.is_dir()):
            now = named_folder(p.parent, new, rename=rename)
            if now.is_dir():
                return str(now)
    return path


def _projects_beside_stl() -> Path | None:
    """With an STL folder chosen (on the NAS, say), the project files' default: "Projects" beside it, or a folder of
    that name already there whatever its capitals. None while the STL folder is Farmhand's own."""
    stl = _custom["stl"]
    if not stl:
        return None
    parent = Path(stl).parent
    try:
        for entry in os.scandir(parent):
            if entry.name.lower() == PROJECTS_FOLDER.lower() and entry.is_dir():
                return Path(entry.path)
    except OSError:
        pass  # the share is away: the name it will have
    return parent / PROJECTS_FOLDER


def default_root(kind: str) -> Path:
    """
    Where this kind goes when no folder is chosen for it: Farmhand's own storage, except project files, which go
    beside the STL folder once one is chosen (so they're on the NAS with everything else).
    """
    if kind == "project":
        beside = _projects_beside_stl()
        if beside is not None:
            return beside
    return local_root() / {"stl": "source_models", "threemf": "bundles", "project": "projects"}[kind]


def _made_default_root(kind: str) -> Path:
    """
    The default folder for this kind, made if it isn't there yet. Farmhand's own are always safe to make; the project
    files beside a chosen STL folder only while that folder is really there (else StorageUnavailableError, so an
    unmounted share never gets files on the local disk underneath it).
    """
    if kind == "project" and _custom["stl"]:
        ready_root("stl")
    root = default_root(kind)
    root.mkdir(parents=True, exist_ok=True)
    return root


def effective_root(kind: str) -> Path:
    return Path(_custom[kind]) if _custom[kind] else default_root(kind)


def thumbnails_root() -> Path:
    """Where the app kept its own copy of each preview before previews were kept only next to their files. Nothing is
    written here any more: services/previews.py moves what's left out to the files."""
    return local_root() / "thumbnails"


def ready_root(kind: str) -> Path:
    """
    The folder to write into for this kind, if it's usable right now: a chosen folder that looks unmounted is refused
    (StorageUnavailableError).
    """
    custom = _custom[kind]
    if not custom:
        return _made_default_root(kind)
    return ensure_ready_folder(custom, f"{_LABELS[kind]} storage folder")


def _has_marker(folder: Path) -> bool:
    return (folder / MARKER_NAME).is_file()


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
    if not _has_marker(root):
        raise StorageUnavailableError(
            f"The {noun} ({root}) is missing its Farmhand marker file. That usually "
            "means a network share isn't mounted right now and this is just the empty folder "
            "underneath it. Nothing was saved. Check the mount, or re-select the folder in Storage settings."
        )
    return root


def _version_dir(base: Path, owner_id: int, version: int, fresh: bool = False) -> Path:
    """
    {base}/{id}/v{n}, made if it isn't there yet. fresh: for a version being saved now, a folder no other Farmhand
    has files in: two Farmhands sharing the same folders each number their own models, 3MFs and files, so their
    {id}/v{n} can be the same folder. Then it's {id}/v{n}-2 (-3...) instead, and nothing is ever written over.
    """
    d = base / str(owner_id) / f"v{version}"
    k = 2
    while fresh and d.is_dir() and any(d.iterdir()):
        d = base / str(owner_id) / f"v{version}-{k}"
        k += 1
    d.mkdir(parents=True, exist_ok=True)
    return d


def source_model_version_dir(source_model_id: int, version: int, fresh: bool = False) -> Path:
    return _version_dir(ready_root("stl"), source_model_id, version, fresh)


def bundle_version_dir(bundle_id: int, version: int, fresh: bool = False) -> Path:
    return _version_dir(ready_root("threemf"), bundle_id, version, fresh)


def project_file_dir(project_folder: str, folder: str, file_id: int, version: int, fresh: bool = False) -> Path:
    """
    A version of a project's own file: {project files}/{the project's folder}/{folder: docs, cad, stl or threemf}/
    {file id}/v{n}. The project's folder is its id ("12"), or another name when that was taken (project_service).
    """
    return _version_dir(ready_root("project") / project_folder / folder, file_id, version, fresh)
