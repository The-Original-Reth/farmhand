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
    """A project's own file, CAD or STL."""

    id: int
    name: str  # its newest version's file name
    created_at: dt.datetime
    versions: list[FileVersionOut]  # newest first


class ProjectOut(BaseModel):
    id: int
    name: str
    created_at: dt.datetime
    cad_files: list[ProjectFileOut] = []
    stl_files: list[ProjectFileOut] = []  # STLs of its own (not in Models)
    source_model_ids: list[int] = []  # models from the Models page it uses


class ProjectIn(BaseModel):
    """A new project, or a project's new name."""

    name: str
