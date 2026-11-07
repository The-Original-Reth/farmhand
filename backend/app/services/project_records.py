"""
Each project's record, kept in its own folder on the NAS: its name, its own files (by kind, with every version's file,
notes, sub-component, counts and printer), its parts list, and the models and printers it uses (by name).

So a project isn't only in this Farmhand's database: Scan projects (here, or in another Farmhand sharing the folders,
or in a new one after this computer is gone) brings it back from its folder. Each Farmhand writes its own record,
farmhand-project-<its id>.json, so two sharing the folders never write over each other's; reading takes them all.
Written after every change to a project, and for every project when Farmhand starts.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..models import Project
from . import app_settings
from .project_files import CAD, DOC, STL, THREEMF
from .project_service import project_folder, require_project

log = logging.getLogger("farmhand.project_records")

PREFIX = "farmhand-project-"  # farmhand-project-<instance>.json
FORMAT = 1
INSTANCE_KEY = "instance_id"
MAX_RECORD_BYTES = 5_000_000


def instance_id(db: Session) -> str:
    """This Farmhand's own short id, made once: it names its records, so two sharing the folders keep theirs apart."""
    value = app_settings.get(db, INSTANCE_KEY)
    if not value:
        value = uuid.uuid4().hex[:8]
        app_settings.put(db, INSTANCE_KEY, value)
        db.commit()
    return value


def record_path(db: Session, folder: str) -> Path:
    return storage.effective_root("project") / folder / f"{PREFIX}{instance_id(db)}.json"


def _where(path: str | None, base: Path) -> str | None:
    """A file's place for the record: relative to the project's folder when it's inside it, else as it is."""
    if not path:
        return None
    try:
        return Path(path).resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path


def _when(value) -> str | None:
    return value.isoformat() if isinstance(value, dt.datetime) else None


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
                    "version": v.version, "filename": v.filename, "path": _where(v.file_path, base), "note": v.note,
                    "size_bytes": v.size_bytes, "uploaded_at": _when(v.uploaded_at),
                    **({"gcode": {"filename": gcode.filename, "path": _where(gcode.file_path, base)}} if gcode else {}),
                })
            files.append(entry)
    return {
        "farmhand_project": FORMAT,
        "instance": instance_id(db),
        "saved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
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
    storage.write_text_atomically(target, json.dumps(build(db, project), indent=2, ensure_ascii=False) + "\n")


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


_background = False  # switched on when the app starts (not in tests, which write records themselves)


def enable_background_writes() -> None:
    global _background
    _background = True


def request_write(project_id: int | None) -> None:
    """After a change: the project's record (or every one, when it isn't one project's), written in the background so
    a slow NAS never holds up the page."""
    if not _background:
        return
    from ..database import SessionLocal

    def run():
        try:
            with SessionLocal() as db:
                if project_id is None:
                    write_all(db)
                elif db.get(Project, project_id) is not None:
                    write(db, project_id)
        except storage.StorageUnavailableError:
            pass  # written again with the next change, or when Farmhand starts
        except Exception:  # noqa: BLE001 - a record failing must never take anything down
            log.exception("Writing a project record failed")

    threading.Thread(target=run, name="project-record", daemon=True).start()


def read_records(folder: Path) -> list[dict]:
    """The records in a project's folder (every Farmhand's), the newest first; ones that can't be read are left out."""
    out = []
    try:
        names = [n for n in os.listdir(folder) if n.startswith(PREFIX) and n.endswith(".json")]
    except OSError:
        return []
    for name in names:
        path = folder / name
        try:
            if path.stat().st_size > MAX_RECORD_BYTES:
                continue
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("farmhand_project") == FORMAT and isinstance(doc.get("name"), str):
            out.append(doc)
    return sorted(out, key=lambda d: str(d.get("saved_at") or ""), reverse=True)


def is_record(name: str) -> bool:
    return name.startswith(PREFIX) and name.endswith(".json")
