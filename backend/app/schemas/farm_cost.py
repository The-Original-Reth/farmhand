from __future__ import annotations

from pydantic import BaseModel


class RecordsLocationIn(BaseModel):
    path: str | None = None  # null or "" = back to the default
