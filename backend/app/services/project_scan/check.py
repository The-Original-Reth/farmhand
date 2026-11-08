"""
Check: every file the projects have on record, against the disk (missing, or not the size it was), and any file in
the project files folder that isn't on record. Changes nothing.
"""
from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import storage
from ...models import Project
from .. import project_files, project_records
from ..project_files import CAD, DOC, STL, THREEMF
from .common import SKIPPED_NAMES

MAX_LISTED = 500  # problems or unknown files listed by a check


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
            for path in project_files.files_of(v):
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
                if name.startswith(".") or name.lower() in SKIPPED_NAMES or project_records.is_record(name):
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
