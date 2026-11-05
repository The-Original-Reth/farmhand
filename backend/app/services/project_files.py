"""
A project's own files: its CAD files (any kind), and its STLs and 3MFs that aren't in Models. All work the same way: a file with
numbered versions like a 3MF's, each kept as "<name> ver <n>.<ext>" in {project files}/{project id}/{cad|stl|threemf}/
{file id}/v{n}/, with a preview next to it when one can be made (thumbnails/cad_preview.py). Deleting goes rows first, then
files.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..errors import NotFound
from ..models import Printer, ProjectCadFile, ProjectCadVersion, ProjectStlFile, ProjectStlVersion, ProjectThreemfFile, ProjectThreemfVersion
from ..names import with_version
from ..thumbnails.cad_preview import render_cad_preview
from .project_service import link_printer, require_project

MAX_NOTE_LENGTH = 2000


@dataclass(frozen=True)
class Kind:
    key: str  # "cad" / "stl": the URL's word and the folder's name
    file_cls: type
    version_cls: type
    file_fk: str  # the version's column pointing at its file
    noun: str  # "CAD file"
    extensions: tuple[str, ...] | None = None  # the only ones taken (None: any)
    wrong_type: str = ""


CAD = Kind("cad", ProjectCadFile, ProjectCadVersion, "cad_file_id", "CAD file")
STL = Kind(
    "stl", ProjectStlFile, ProjectStlVersion, "stl_file_id", "STL file", (".stl", ".obj"),
    "An STL file has to be an .stl or .obj file.",
)
THREEMF = Kind(
    "threemf", ProjectThreemfFile, ProjectThreemfVersion, "threemf_file_id", "3MF file", (".3mf",),
    "A 3MF file has to be a .3mf file.",
)
KINDS = {k.key: k for k in (CAD, STL, THREEMF)}


def _clean_note(note: str | None) -> str | None:
    note = (note or "").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise ValueError(f"A version's note can be at most {MAX_NOTE_LENGTH} characters.")
    return note or None


def check_type(kind: Kind, filename: str | None) -> None:
    if kind.extensions and Path(filename or "").suffix.lower() not in kind.extensions:
        raise ValueError(kind.wrong_type)


def _require_file(db: Session, kind: Kind, project_id: int, file_id: int):
    f = db.get(kind.file_cls, file_id)
    if f is None or f.project_id != project_id:
        raise NotFound(f"{kind.noun} not found")
    return f


def require_version(db: Session, kind: Kind, project_id: int, file_id: int, version: int):
    f = _require_file(db, kind, project_id, file_id)
    v = next((v for v in f.versions if v.version == version), None)
    if v is None:
        raise NotFound(f"{kind.noun} version not found")
    return v


def _files_of(v) -> list[str | None]:
    return [v.file_path, v.thumbnail_path, storage.preview_beside(v.file_path)]


def _add_version(db: Session, kind: Kind, f, number: int, filename: str, file_obj, note: str | None) -> None:
    """Write the file (and its preview) and record it. A record that can't be saved takes its files back out."""
    name = with_version(Path(filename or "").name or kind.noun, number)
    path = storage.save_upload(storage.project_file_dir(f.project_id, kind.key, f.id, number), name, file_obj)
    png = render_cad_preview(path)
    thumb = storage.save_preview_beside(path, png) if png else None
    try:
        db.add(kind.version_cls(
            **{kind.file_fk: f.id}, version=number, filename=name, file_path=path, thumbnail_path=thumb,
            size_bytes=os.path.getsize(path), note=note,
        ))
        db.commit()
    except Exception:
        db.rollback()
        storage.delete_files([path, thumb])
        raise


def upload(
    db: Session, kind: Kind, project_id: int, filename: str, file_obj, note: str | None = None, printer_id: int | None = None,
):
    """
    A new file in the project, as its version 1. 503 (StorageUnavailableError) if the folder isn't there. A 3MF is for
    `printer_id` (chosen at upload; none is allowed), and that printer then comes into the project too.
    """
    require_project(db, project_id)
    check_type(kind, filename)
    note = _clean_note(note)
    if kind is THREEMF and printer_id is not None and db.get(Printer, printer_id) is None:
        raise NotFound("Printer not found")
    storage.ready_root("project")  # refuse before anything is recorded
    f = kind.file_cls(project_id=project_id)
    if kind is THREEMF:
        f.printer_id = printer_id
    db.add(f)
    db.flush()
    try:
        _add_version(db, kind, f, 1, filename, file_obj, note)
    except Exception:
        db.rollback()
        raise
    if kind is THREEMF and printer_id is not None:
        link_printer(db, project_id, printer_id)
    return f


def add_version(db: Session, kind: Kind, project_id: int, file_id: int, filename: str, file_obj, note: str | None = None) -> None:
    f = _require_file(db, kind, project_id, file_id)
    check_type(kind, filename)
    note = _clean_note(note)
    newest = max((v.version for v in f.versions), default=0)
    _add_version(db, kind, f, newest + 1, filename, file_obj, note)


def delete_version(db: Session, kind: Kind, project_id: int, file_id: int, version: int) -> None:
    """Delete one version's file for good. Deleting the only one deletes the file."""
    v = require_version(db, kind, project_id, file_id, version)
    f = v.file
    paths = _files_of(v)
    if len(f.versions) == 1:
        db.delete(f)
    else:
        db.delete(v)
    db.commit()
    storage.delete_files(paths)


def delete_file(db: Session, kind: Kind, project_id: int, file_id: int) -> None:
    f = _require_file(db, kind, project_id, file_id)
    paths = [p for v in f.versions for p in _files_of(v)]
    db.delete(f)
    db.commit()
    storage.delete_files(paths)


def all_versions(db: Session):
    """Every version of every project's own files, each kind (for the Settings page's counts and Move them now)."""
    for kind in KINDS.values():
        yield from db.scalars(select(kind.version_cls))


def files_of_project(db: Session, project_id: int) -> list[str | None]:
    """Every file the project's own files keep (for deleting the project: rows first, then these)."""
    paths: list[str | None] = []
    for kind in KINDS.values():
        versions = db.scalars(select(kind.version_cls).join(kind.file_cls).where(kind.file_cls.project_id == project_id))
        paths += [p for v in versions for p in _files_of(v)]
    return paths
