"""
Each project's record, kept in its own folder on the NAS: its name, its own files (by kind, with every version's file,
notes, sub-component, counts and printer), its parts list, and the models and printers it uses (by name).

So a project isn't only in this Farmhand's database: Scan projects (here, or in another Farmhand sharing the folders,
or in a new one after this computer is gone) brings it back from its folder. Each Farmhand writes its own record,
farmhand-project-<its id>.json, so two sharing the folders never write over each other's; reading takes them all.
Written after every change to a project, and for every project when Farmhand starts.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import record_files, storage
from ..models import Project
from ..record_files import iso_or_none, relative_to
from .app_settings import instance_id
from .project_files import CAD, DOC, STL, THREEMF
from .project_service import project_folder, require_project

log = logging.getLogger("farmhand.project_records")

PREFIX = "farmhand-project-"  # farmhand-project-<instance>.json
FORMAT = 1
MAX_RECORD_BYTES = 5_000_000
background = record_files.BackgroundWriter("project-record", "a project record")


def record_path(db: Session, folder: str) -> Path:
    return storage.effective_root("project") / folder / f"{PREFIX}{instance_id(db)}.json"


def build(db: Session, project: Project) -> dict:
    base = storage.effective_root("project") / project.folder
    files = []
    for kind, rows in ((DOC, project.doc_files), (CAD, project.cad_files), (STL, project.stl_files), (THREEMF, project.threemf_files)):
        for f in rows:
            entry = {"kind": kind.key, "versions": []}
            if kind is STL:
                entry.update(need=f.need, have=f.have, component=f.component)
            if kind is THREEMF:
                entry["printer"] = f.printer.name if f.printer else None
            for v in f.versions:
                gcode = getattr(v, "gcode", None)
                entry["versions"].append({
                    "version": v.version, "filename": v.filename, "path": relative_to(v.file_path, base), "note": v.note,
                    "size_bytes": v.size_bytes, "uploaded_at": iso_or_none(v.uploaded_at),
                    **({"gcode": {"filename": gcode.filename, "path": relative_to(gcode.file_path, base)}} if gcode else {}),
                })
            files.append(entry)
    return {
        "farmhand_project": FORMAT,
        "instance": instance_id(db),
        "saved_at": record_files.stamp(),
        "note": "Written by Farmhand whenever this project changes: Scan projects brings the project back from it.",
        "name": project.name,
        "files": files,
        "parts": [{"name": p.name, "need": p.need, "have": p.have, "link": p.link, "note": p.note} for p in project.parts],
        "models": [
            {"name": link.source_model.name, "need": link.need, "have": link.have, "component": link.component}
            for link in project.model_links if link.source_model
        ],
        "printers": [link.printer.name for link in project.printer_links if getattr(link, "printer", None)],
    }


def write(db: Session, project_id: int) -> None:
    """Write this Farmhand's record of the project into its folder (made if need be). StorageUnavailableError while the
    project files folder isn't there."""
    project = require_project(db, project_id)
    folder = project_folder(db, project_id)
    db.commit()
    target = storage.ready_root("project") / folder / f"{PREFIX}{instance_id(db)}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    record_files.write_json(target, build(db, project))


def write_all(db: Session) -> int:
    """Every project's record, written now (at startup). Answers how many were written."""
    written = 0
    for pid in db.scalars(select(Project.id)):
        try:
            write(db, pid)
            written += 1
        except storage.StorageUnavailableError:
            return written  # the folder is away: all of them would fail the same way
        except Exception:  # noqa: BLE001 - one project's record failing must not stop the rest
            db.rollback()
            log.exception("Writing project %s's record failed", pid)
    return written


def request_write(project_id: int | None) -> None:
    """After a change: the project's record (or every one, when it isn't one project's), written in the background."""
    def write_it(db: Session):
        if project_id is None:
            write_all(db)
        elif db.get(Project, project_id) is not None:
            write(db, project_id)

    background.run(write_it)


def read_records(folder: Path) -> list[dict]:
    """The records in a project's folder (every Farmhand's), the newest first; ones that can't be read are left out."""
    docs = [record_files.read_json(folder / name, MAX_RECORD_BYTES) for name in record_files.names_in(folder, PREFIX)]
    return record_files.newest_first([
        d for d in docs if isinstance(d, dict) and d.get("farmhand_project") == FORMAT and isinstance(d.get("name"), str)
    ])


def is_record(name: str) -> bool:
    return name.startswith(PREFIX) and name.endswith(".json")
