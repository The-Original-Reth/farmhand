"""
A project's CAD files: any kind (Fusion, STEP, SolidWorks, OpenSCAD...), each with numbered versions like a 3MF's.
A version is kept as "<name> ver <n>.<ext>" in {project files}/{project id}/cad/{CAD file id}/v{n}/, with a preview next
to it when one can be made (thumbnails/cad_preview.py). Deleting goes rows first, then files.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..errors import NotFound
from ..models import ProjectCadFile, ProjectCadVersion
from ..names import with_version
from ..thumbnails.cad_preview import render_cad_preview
from .project_service import require_project

MAX_NOTE_LENGTH = 2000


def _clean_note(note: str | None) -> str | None:
    note = (note or "").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise ValueError(f"A version's note can be at most {MAX_NOTE_LENGTH} characters.")
    return note or None


def _require_cad(db: Session, project_id: int, cad_id: int) -> ProjectCadFile:
    cad = db.get(ProjectCadFile, cad_id)
    if cad is None or cad.project_id != project_id:
        raise NotFound("CAD file not found")
    return cad


def require_version(db: Session, project_id: int, cad_id: int, version: int) -> ProjectCadVersion:
    cad = _require_cad(db, project_id, cad_id)
    v = next((v for v in cad.versions if v.version == version), None)
    if v is None:
        raise NotFound("CAD file version not found")
    return v


def _files_of(v: ProjectCadVersion) -> list[str | None]:
    return [v.file_path, v.thumbnail_path, storage.preview_beside(v.file_path)]


def _add_version(db: Session, cad: ProjectCadFile, number: int, filename: str, file_obj, note: str | None) -> None:
    """Write the file (and its preview) and record it. A record that can't be saved takes its files back out."""
    name = with_version(Path(filename or "").name or "CAD file", number)
    path = storage.save_upload(storage.cad_version_dir(cad.project_id, cad.id, number), name, file_obj)
    png = render_cad_preview(path)
    thumb = storage.save_preview_beside(path, png) if png else None
    try:
        db.add(ProjectCadVersion(
            cad_file_id=cad.id, version=number, filename=name, file_path=path, thumbnail_path=thumb,
            size_bytes=os.path.getsize(path), note=note,
        ))
        db.commit()
    except Exception:
        db.rollback()
        storage.delete_files([path, thumb])
        raise


def upload(db: Session, project_id: int, filename: str, file_obj, note: str | None = None) -> ProjectCadFile:
    """A new CAD file in the project, as its version 1. 503 (StorageUnavailableError) if the folder isn't there."""
    require_project(db, project_id)
    note = _clean_note(note)
    storage.ready_root("project")  # refuse before anything is recorded
    cad = ProjectCadFile(project_id=project_id)
    db.add(cad)
    db.flush()
    try:
        _add_version(db, cad, 1, filename, file_obj, note)
    except Exception:
        db.rollback()
        raise
    return cad


def add_version(db: Session, project_id: int, cad_id: int, filename: str, file_obj, note: str | None = None) -> None:
    cad = _require_cad(db, project_id, cad_id)
    note = _clean_note(note)
    newest = max((v.version for v in cad.versions), default=0)
    _add_version(db, cad, newest + 1, filename, file_obj, note)


def delete_version(db: Session, project_id: int, cad_id: int, version: int) -> None:
    """Delete one version's file for good. Deleting the only one deletes the CAD file."""
    v = require_version(db, project_id, cad_id, version)
    cad = v.cad_file
    paths = _files_of(v)
    if len(cad.versions) == 1:
        db.delete(cad)
    else:
        db.delete(v)
    db.commit()
    storage.delete_files(paths)


def delete_cad_file(db: Session, project_id: int, cad_id: int) -> None:
    cad = _require_cad(db, project_id, cad_id)
    paths = [p for v in cad.versions for p in _files_of(v)]
    db.delete(cad)
    db.commit()
    storage.delete_files(paths)


def files_of_project(db: Session, project_id: int) -> list[str | None]:
    """Every file the project's CAD files keep (for deleting the project: rows first, then these)."""
    versions = db.scalars(
        select(ProjectCadVersion).join(ProjectCadFile).where(ProjectCadFile.project_id == project_id)
    )
    return [p for v in versions for p in _files_of(v)]
