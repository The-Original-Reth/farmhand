from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from ..models import SourceFileType
from .notes import NotesConflictOut, NotesUpdate  # noqa: F401  (also importable from here, as before)


class SourceModelVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    file_path: str
    thumbnail_path: str | None
    note: str | None
    uploaded_at: dt.datetime


class SourceModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    file_type: SourceFileType
    created_at: dt.datetime
    versions: list[SourceModelVersionOut] = []
    notes: str = ""
    notes_revision: int = 0
    notes_updated_at: dt.datetime | None = None
