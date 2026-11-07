"""
Scan projects: bringing in project folders from the NAS, and checking the project files Farmhand keeps.

Import: a folder (under the browse root) whose subfolders are projects. Each subfolder becomes a project of that name,
its files copied in (the originals are left where they are), each by its kind:
  .stl / .obj           an STL of the project's own, in the sub-component named by the folders it's in
  .3mf                  a 3MF of the project's own, for the printer it was sliced for (when that's a printer here)
  .gcode / .bgcode      the G-code of the 3MF of the same name beside it; on its own, a document
  CAD_EXTENSIONS        a CAD file
  anything else         a document
Names starting with "." and the system's own files are left out.

Check: every file the projects have on record, against the disk (missing, or not the size it was), and any file in
the project files folder that isn't on record.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..models import Project
from ..parsers import parse_3mf
from . import printer_service, project_files
from .project_files import CAD, DOC, STL, THREEMF
from .project_service import clean_component, create_project, set_counts

CAD_EXTENSIONS = {
    ".step", ".stp", ".iges", ".igs", ".brep", ".brp", ".f3d", ".f3z", ".sldprt", ".sldasm", ".slddrw", ".scad",
    ".fcstd", ".ipt", ".iam", ".x_t", ".x_b", ".sat", ".3dm", ".blend", ".skp", ".dwg", ".dxf",
}
GCODE_EXTENSIONS = {".gcode", ".bgcode"}
SKIPPED_NAMES = {"thumbs.db", "desktop.ini", ".ds_store", storage.MARKER_NAME.lower()}
MAX_FILES = 2000  # in one project folder: more than this is very likely not a project
MAX_LISTED = 500  # problems or unknown files listed by a check


class ProjectExists(ValueError):
    """A folder to bring in is named like a project already here."""


def _kind_of(name: str) -> str:
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


def _files_in(folder: Path) -> list[Path]:
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


def _own_folders() -> list[Path]:
    """Where Farmhand keeps its own files: its storage, and the STL, 3MF and project files folders chosen for it."""
    roots = [storage.local_root(), *(storage.effective_root(k) for k in ("stl", "threemf", "project"))]
    return [Path(os.path.realpath(r)) for r in roots]


def _farmhands_own(path: Path, holding_too: bool = True) -> bool:
    """Whether a folder is one of Farmhand's own, or inside one (or, with holding_too, holds one)."""
    return any(path == own or own in path.parents or (holding_too and path in own.parents) for own in _own_folders())


OWN_FILES = "Farmhand keeps its own files there"


def _project_folder(raw: str, scanning: bool = False) -> Path:
    """
    A folder picked to scan or import: under the browse root, and not one of Farmhand's own folders. A folder that
    holds one of them can still be scanned (that subfolder is then marked), but not imported.
    """
    path = storage.resolve_location(raw)
    if not path.is_dir():
        raise ValueError(f"{path} isn't a folder.")
    if _farmhands_own(path, holding_too=not scanning):
        raise ValueError(f"{OWN_FILES}: pick the folder your projects are in.")
    return path


def _existing_names(db: Session) -> set[str]:
    return {n.lower() for n in db.scalars(select(Project.name))}


def scan_folder(db: Session, raw: str) -> dict:
    """
    The subfolders of a folder, each as the project it would become: its name, how many files of each kind it holds,
    and whether a project of that name is already in Farmhand (it's then not imported again).
    """
    root = _project_folder(raw, scanning=True)
    taken = _existing_names(db)
    folders = []
    try:
        subdirs = sorted((e for e in os.scandir(root) if e.is_dir() and not e.name.startswith(".")), key=lambda e: e.name.lower())
    except OSError as e:
        raise ValueError(f"Couldn't read {root}: {e}") from None
    for entry in subdirs:
        counts = {"doc": 0, "cad": 0, "stl": 0, "threemf": 0, "gcode": 0}
        error = None
        if _farmhands_own(Path(os.path.realpath(entry.path))):
            error = f"{OWN_FILES}: it isn't a project"
        else:
            try:
                for f in _files_in(Path(entry.path)):
                    counts[_kind_of(f.name)] += 1
            except (ValueError, OSError) as e:
                error = str(e)
        name = " ".join(entry.name.split())
        folders.append({
            "name": name, "path": entry.path, "files": counts, "total": sum(counts.values()),
            "in_farmhand": name.lower() in taken, "error": error,
        })
    return {"path": str(root), "folders": folders}


def _printer_for(db: Session, path: Path):
    """The printer a 3MF was sliced for, when it's one here (None when it isn't, or the file can't be read)."""
    try:
        parsed = parse_3mf(str(path))
    except Exception:  # noqa: BLE001 - an unreadable 3MF is still imported, just without a printer
        return None
    return printer_service.find_by_profile_name(db, parsed.printer_profile_name) if parsed.printer_profile_name else None


def import_folder(db: Session, raw: str) -> dict:
    """
    Make a project from one folder: named after it, with its files copied in by kind (see the top of this file).
    A file that can't be brought in is left out and said so; the rest still come in. ProjectExists if a project of
    that name is already here.
    """
    folder = _project_folder(raw)
    name = " ".join(folder.name.split())
    if name.lower() in _existing_names(db):
        raise ProjectExists(f"There's already a project called {name}: it isn't brought in again.")
    files = _files_in(folder)
    storage.ready_root("project")  # refuse before anything is made
    project = create_project(db, folder.name)
    pid = project.id
    warnings: list[str] = []
    counts = {"doc": 0, "cad": 0, "stl": 0, "threemf": 0, "gcode": 0}

    def rel(p: Path) -> str:
        return p.relative_to(folder).as_posix()

    def bring_in(kind, path: Path, **extra):
        with open(path, "rb") as fh:
            return project_files.upload(db, kind, pid, path.name, fh, **extra)

    threemfs: dict[tuple[Path, str], tuple[int, int]] = {}  # (folder, stem) -> (file id, version) of a 3MF brought in
    gcodes: list[Path] = []
    for path in files:
        kind = _kind_of(path.name)
        if kind == "gcode":
            gcodes.append(path)  # after the 3MFs, to go with theirs
            continue
        try:
            if kind == "stl":
                f = bring_in(STL, path)
                component = clean_component(rel(path.parent)) if path.parent != folder else None
                if component:
                    set_counts(db, pid, "stl", f.id, component=component)
            elif kind == "threemf":
                printer = _printer_for(db, path)
                f = bring_in(THREEMF, path, printer_id=printer.id if printer else None)
                threemfs[(path.parent, path.stem.lower())] = (f.id, 1)
            else:
                bring_in(CAD if kind == "cad" else DOC, path)
            counts[kind] += 1
        except (ValueError, OSError) as e:
            db.rollback()
            warnings.append(f"{rel(path)} wasn't brought in: {e}")

    for path in gcodes:
        try:
            match = threemfs.get((path.parent, Path(path.stem).stem.lower())) or threemfs.get((path.parent, path.stem.lower()))
            if match:
                with open(path, "rb") as fh:
                    project_files.attach_gcode(db, pid, match[0], match[1], path.name, fh)
                counts["gcode"] += 1
            else:
                bring_in(DOC, path)  # no 3MF of its name: kept as a document
                counts["doc"] += 1
        except (ValueError, OSError) as e:
            db.rollback()
            warnings.append(f"{rel(path)} wasn't brought in: {e}")

    return {"project_id": pid, "name": project.name, "files": counts, "warnings": warnings}


# ------------------------------------------------------------------ checking


def check_files(db: Session) -> dict:
    """
    Every project's files against the disk: each recorded file (and 3MF G-code) that's missing or isn't the size it
    was when it was saved, and each file in the project files folder that no project has on record. Changes nothing.
    """
    problems: list[dict] = []
    known: set[str] = set()
    checked = 0
    names = {p.id: p.name for p in db.query(Project).all()}
    for kind in (DOC, CAD, STL, THREEMF):
        for v in db.scalars(select(kind.version_cls)):
            f = v.file
            for path in project_files._files_of(v):
                if path:
                    known.add(os.path.realpath(path))
            checked += 1
            where = {"project_id": f.project_id, "project": names.get(f.project_id, ""), "kind": kind.key, "file_id": f.id, "version": v.version}
            problem = None
            try:
                size = os.path.getsize(v.file_path)
                if size != v.size_bytes:
                    problem = f"changed outside Farmhand: it was {v.size_bytes} bytes, it's {size} now"
            except FileNotFoundError:
                problem = "missing"
            except OSError as e:
                problem = f"couldn't be read: {e}"
            if problem:
                problems.append({**where, "filename": v.filename, "path": v.file_path, "problem": problem})
            gcode = getattr(v, "gcode", None)
            if gcode is not None and not os.path.exists(gcode.file_path):
                problems.append({**where, "filename": gcode.filename, "path": gcode.file_path, "problem": "missing (its G-code)"})

    root = storage.effective_root("project")
    unknown: list[str] = []
    error = None
    if not root.is_dir():
        error = f"The project files folder ({root}) isn't there right now, so files no project has on record weren't looked for."
    else:
        for here, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if name.startswith(".") or name.lower() in SKIPPED_NAMES:
                    continue
                path = os.path.realpath(os.path.join(here, name))
                if path not in known:
                    unknown.append(path)
    unknown.sort()
    return {
        "projects": len(names), "files_checked": checked, "root": str(root), "error": error,
        "problems": problems[:MAX_LISTED], "problems_total": len(problems),
        "unknown": unknown[:MAX_LISTED], "unknown_total": len(unknown),
    }
