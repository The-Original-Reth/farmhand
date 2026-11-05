from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class CadVersionOut(BaseModel):
    version: int
    filename: str  # as kept: "Bracket ver 2.f3d"
    size_bytes: int
    note: str | None  # what changed in this version
    uploaded_at: dt.datetime
    has_preview: bool


class CadFileOut(BaseModel):
    id: int
    name: str  # its newest version's file name
    created_at: dt.datetime
    versions: list[CadVersionOut]  # newest first


class ProjectOut(BaseModel):
    id: int
    name: str
    created_at: dt.datetime
    cad_files: list[CadFileOut] = []


class ProjectIn(BaseModel):
    """A new project, or a project's new name."""

    name: str
