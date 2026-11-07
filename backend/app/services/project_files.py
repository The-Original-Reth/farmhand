"""
A project's own files: its documents (any file) and CAD files (any kind), and its STLs and 3MFs that aren't in Models. All work the same way: a file with
numbered versions like a 3MF's, each kept as "<name> ver <n>.<ext>" in {project files}/{project id}/{docs|cad|stl|threemf}/
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
from ..models import (
    Printer, ProjectCadFile, ProjectCadFilePosition, ProjectCadVersion, ProjectDocFile, ProjectDocFilePosition, ProjectDocVersion,
    ProjectStlFile, ProjectStlVersion, ProjectThreemfFile, ProjectThreemfGcode, ProjectThreemfVersion,
)
from ..names import with_version
from ..thumbnails.cad_preview import render_cad_preview
from .project_service import link_printer, project_folder, require_project

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

    @property
    def folder(self) -> str:
        """The folder its files go in, in the project's folder: docs/, cad/, stl/, threemf/"""
        return "docs" if self.key == "doc" else self.key


DOC = Kind("doc", ProjectDocFile, ProjectDocVersion, "doc_file_id", "document")
CAD = Kind("cad", ProjectCadFile, ProjectCadVersion, "cad_file_id", "CAD file")
STL = Kind(
    "stl", ProjectStlFile, ProjectStlVersion, "stl_file_id", "STL file", (".stl", ".obj"),
    "An STL file has to be an .stl or .obj file.",
)
THREEMF = Kind(
    "threemf", ProjectThreemfFile, ProjectThreemfVersion, "threemf_file_id", "3MF file", (".3mf",),
    "A 3MF file has to be a .3mf file.",
)
KINDS = {k.key: k for k in (DOC, CAD, STL, THREEMF)}


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
    gcode = getattr(v, "gcode", None)  # a 3MF version's G-code goes with it
    return [v.file_path, v.thumbnail_path, storage.preview_beside(v.file_path), gcode.file_path if gcode else None]


def _add_version(db: Session, kind: Kind, f, number: int, filename: str, file_obj, note: str | None) -> None:
    """Write the file (and its preview) and record it. A record that can't be saved takes its files back out."""
    name = with_version(Path(filename or "").name or kind.noun, number)
    folder = project_folder(db, f.project_id)  # its own folder in the project files folder, chosen now if it has none
    path = storage.save_upload(storage.project_file_dir(folder, kind.folder, f.id, number, fresh=True), name, file_obj)
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


# ---- a project 3MF version's G-code: uploaded, downloaded, sent to its printer ----


def attach_gcode(db: Session, project_id: int, file_id: int, version: int, filename: str, file_obj) -> None:
    """Give one version of a project's own 3MF its G-code (a .gcode or .bgcode sliced from it), kept next to the 3MF
    and replacing one it had."""
    from .bundle_service.versions import check_gcode_name

    v = require_version(db, THREEMF, project_id, file_id, version)
    check_gcode_name(filename)
    path = storage.save_upload(Path(v.file_path).parent, Path(filename).name, file_obj)
    old = v.gcode.file_path if v.gcode else None
    if v.gcode:
        v.gcode.filename, v.gcode.file_path = Path(filename).name, path
    else:
        db.add(ProjectThreemfGcode(version_id=v.id, filename=Path(filename).name, file_path=path))
    db.commit()
    if old and os.path.abspath(old) != os.path.abspath(path):
        storage.delete_files([old], prune=False)


def require_gcode(db: Session, project_id: int, file_id: int, version: int) -> ProjectThreemfGcode:
    v = require_version(db, THREEMF, project_id, file_id, version)
    if v.gcode is None:
        raise NotFound("This version has no G-code. Upload one first.")
    return v.gcode


def send_gcode(db: Session, project_id: int, file_id: int, version: int) -> dict:
    """Send the version's G-code to the printer its 3MF is for, and start it (send_print: never while it's busy)."""
    from .send_print import send_file

    gcode = require_gcode(db, project_id, file_id, version)
    printer = gcode.version.file.printer
    if printer is None:
        raise ValueError("This 3MF has no printer to send it to.")
    return send_file(db, printer, gcode.filename, gcode.file_path)


def arrange(db: Session, kind: Kind, project_id: int, ids: list[int]) -> None:
    """
    Put a project's documents or CAD files in this order: `ids` has to be every one of them, each once (a file
    uploaded since the list was shown makes it out of date: 422, so the page is reloaded and arranged again).
    """
    if kind not in (DOC, CAD):
        raise ValueError(f"{kind.noun.capitalize()}s can't be arranged.")
    project = require_project(db, project_id)
    files = {f.id: f for f in (project.doc_files if kind is DOC else project.cad_files)}
    if len(ids) != len(set(ids)) or set(ids) != set(files):
        raise ValueError(f"The list of {kind.noun}s has changed since it was shown: reload the page and arrange them again.")
    row_cls = ProjectDocFilePosition if kind is DOC else ProjectCadFilePosition
    for place, file_id in enumerate(ids):
        f = files[file_id]
        if f.position_row is None:
            f.position_row = row_cls(position=place)
        else:
            f.position_row.position = place
    db.commit()
