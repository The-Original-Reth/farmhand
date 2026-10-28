from __future__ import annotations

from pydantic import BaseModel, Field

from ..notes import MAX_NOTES_LENGTH


class NotesUpdate(BaseModel):
    """What the person typed, and which revision of the notes they started from (0 if there weren't any)."""

    notes: str = Field(max_length=MAX_NOTES_LENGTH)
    base_revision: int = Field(ge=0)


class NotesConflictOut(BaseModel):
    detail: str
    current: dict
