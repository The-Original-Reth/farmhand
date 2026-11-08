"""
What bringing in a folder of project files and checking them share: which files count (hidden and system files
don't), each file's kind by its name, which folders are Farmhand's own, and the printer a 3MF was sliced for.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import storage
from ...models import Project
from ...parsers import parse_3mf
from .. import printer_service
from ..project_service import clean_component

CAD_EXTENSIONS = {
    ".step", ".stp", ".iges", ".igs", ".brep", ".brp", ".f3d", ".f3z", ".sldprt", ".sldasm", ".slddrw", ".scad",
    ".fcstd", ".ipt", ".iam", ".x_t", ".x_b", ".sat", ".3dm", ".blend", ".skp", ".dwg", ".dxf",
}
GCODE_EXTENSIONS = {".gcode", ".bgcode"}
SKIPPED_NAMES = {"thumbs.db", "desktop.ini", ".ds_store", storage.MARKER_NAME.lower()}
MAX_FILES = 2000  # in one project folder: more than this is very likely not a project
OWN_FILES = "Farmhand keeps its own files there"


class ProjectExists(ValueError):
    """A folder to bring in is named like a project already here."""


def no_counts() -> dict[str, int]:
    """How many files of each kind were found or brought in: none yet."""
    return {"doc": 0, "cad": 0, "stl": 0, "threemf": 0, "gcode": 0}


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in (".stl", ".obj"):
        return "stl"
    if ext == ".3mf":
        return "threemf"
    if ext in GCODE_EXTENSIONS:
        return "gcode"
    if ext in CAD_EXTENSIONS:
        return "cad"
    return "doc"


def files_in(folder: Path) -> list[Path]:
    """Every file in the folder and the folders inside it, by path, leaving out hidden and system files."""
    out: list[Path] = []
    for here, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.startswith(".") or name.lower() in SKIPPED_NAMES or name.endswith(".part"):
                continue
            out.append(Path(here) / name)
            if len(out) > MAX_FILES:
                raise ValueError(f"{folder.name} has more than {MAX_FILES} files: is it really one project's folder?")
    return out


def subfolders(root: Path) -> list[os.DirEntry]:
    """The folders in a folder (not hidden ones), by name."""
    try:
        return sorted((e for e in os.scandir(root) if e.is_dir() and not e.name.startswith(".")), key=lambda e: e.name.lower())
    except OSError as e:
        raise ValueError(f"Couldn't read {root}: {e}") from None


def _own_folders() -> list[Path]:
    """Where Farmhand keeps its own files: its storage, and the STL, 3MF and project files folders chosen for it."""
    roots = [storage.local_root(), *(storage.effective_root(k) for k in ("stl", "threemf", "project"))]
    return [Path(os.path.realpath(r)) for r in roots]


def farmhands_own(path: Path, holding_too: bool = True) -> bool:
    """Whether a folder is one of Farmhand's own, or inside one (or, with holding_too, holds one)."""
    return any(path == own or own in path.parents or (holding_too and path in own.parents) for own in _own_folders())


def picked_folder(raw: str, scanning: bool = False) -> Path:
    """
    A folder picked to scan or import: under the browse root, and not one of Farmhand's own folders. A folder that
    holds one of them can still be scanned (that subfolder is then marked), but not imported.
    """
    path = storage.resolve_location(raw)
    if not path.is_dir():
        raise ValueError(f"{path} isn't a folder.")
    if farmhands_own(path, holding_too=not scanning):
        raise ValueError(f"{OWN_FILES}: pick the folder your projects are in.")
    return path


def existing_names(db: Session) -> set[str]:
    return {n.lower() for n in db.scalars(select(Project.name))}


def printer_for(db: Session, path: Path):
    """The printer a 3MF was sliced for, when it's one here (None when it isn't, or the file can't be read)."""
    try:
        parsed = parse_3mf(str(path))
    except Exception:  # noqa: BLE001 - an unreadable 3MF is still imported, just without a printer
        return None
    return printer_service.find_by_profile_name(db, parsed.printer_profile_name) if parsed.printer_profile_name else None


def component(value, warnings: list[str]):
    """A sub-component's name, cleaned; one that can't be used is said in warnings and left out."""
    try:
        return clean_component(value) if isinstance(value, str) else None
    except ValueError as e:
        warnings.append(str(e))
        return None
