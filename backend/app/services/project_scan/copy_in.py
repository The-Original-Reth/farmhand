"""
Import: a folder (under the browse root) whose subfolders are projects. Each subfolder becomes a project of that name,
its files copied in (the originals are left where they are), each by its kind:
  .stl / .obj           an STL of the project's own, in the sub-component named by the folders it's in
  .3mf                  a 3MF of the project's own, for the printer it was sliced for (when that's a printer here)
  .gcode / .bgcode      the G-code of the 3MF of the same name beside it; on its own, a document
  CAD_EXTENSIONS        a CAD file
  anything else         a document
Names starting with "." and the system's own files are left out.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.orm import Session

from ... import storage
from .. import project_files
from ..project_files import CAD, DOC, STL, THREEMF
from ..project_service import clean_component, create_project, set_counts
from .common import (
    OWN_FILES, ProjectExists, existing_names, farmhands_own, files_in, kind_of, no_counts, picked_folder, printer_for,
    subfolders,
)


def scan_folder(db: Session, raw: str) -> dict:
    """
    The subfolders of a folder, each as the project it would become: its name, how many files of each kind it holds,
    and whether a project of that name is already in Farmhand (it's then not imported again).
    """
    root = picked_folder(raw, scanning=True)
    taken = existing_names(db)
    folders = []
    for entry in subfolders(root):
        counts = no_counts()
        error = None
        if farmhands_own(Path(os.path.realpath(entry.path))):
            error = f"{OWN_FILES}: it isn't a project"
        else:
            try:
                for f in files_in(Path(entry.path)):
                    counts[kind_of(f.name)] += 1
            except (ValueError, OSError) as e:
                error = str(e)
        name = " ".join(entry.name.split())
        folders.append({
            "name": name, "path": entry.path, "files": counts, "total": sum(counts.values()),
            "in_farmhand": name.lower() in taken, "error": error,
        })
    return {"path": str(root), "folders": folders}


def import_folder(db: Session, raw: str) -> dict:
    """
    Make a project from one folder: named after it, with its files copied in by kind (see the top of this file).
    A file that can't be brought in is left out and said so; the rest still come in. ProjectExists if a project of
    that name is already here.
    """
    folder = picked_folder(raw)
    name = " ".join(folder.name.split())
    if name.lower() in existing_names(db):
        raise ProjectExists(f"There's already a project called {name}: it isn't brought in again.")
    files = files_in(folder)
    storage.ready_root("project")  # refuse before anything is made
    project = create_project(db, folder.name)
    pid = project.id
    warnings: list[str] = []
    counts = no_counts()

    def rel(p: Path) -> str:
        return p.relative_to(folder).as_posix()

    def bring_in(kind, path: Path, **extra):
        with open(path, "rb") as fh:
            return project_files.upload(db, kind, pid, path.name, fh, **extra)

    threemfs: dict[tuple[Path, str], tuple[int, int]] = {}  # (folder, stem) -> (file id, version) of a 3MF brought in
    gcodes: list[Path] = []
    for path in files:
        kind = kind_of(path.name)
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
                printer = printer_for(db, path)
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
