from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from ..models import SourceFileType


class SourceModelVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    file_path: str
    thumbnail_path: str | None
    thumbnail_rev: int = 0  # changes when the preview is redrawn
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


class SourceModelRename(BaseModel):
    name: str
