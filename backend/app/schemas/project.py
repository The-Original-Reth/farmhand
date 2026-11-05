from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class FileVersionOut(BaseModel):
    version: int
    filename: str  # as kept: "Bracket ver 2.f3d"
    size_bytes: int
    note: str | None  # what changed in this version
    uploaded_at: dt.datetime
    has_preview: bool


class ProjectFileOut(BaseModel):
    """A project's own file, CAD, STL or 3MF."""

    id: int
    printer_id: int | None = None  # a 3MF's: the printer it's for (absent for CAD and STL files)
    name: str  # its newest version's file name
    created_at: dt.datetime
    versions: list[FileVersionOut]  # newest first


class ProjectOut(BaseModel):
    id: int
    name: str
    created_at: dt.datetime
    cad_files: list[ProjectFileOut] = []
    stl_files: list[ProjectFileOut] = []  # STLs of its own (not in Models)
    threemf_files: list[ProjectFileOut] = []  # 3MFs of its own (not in Models)
    source_model_ids: list[int] = []  # models from the Models page it uses
    bundle_ids: list[int] = []  # 3MFs from the rest of Farmhand it uses
    printer_ids: list[int] = []  # printers it uses (brought by its 3MFs, or added)


class ProjectIn(BaseModel):
    """A new project, or a project's new name."""

    name: str
