"""What the Moonraker router takes in: the 1500-hour service (kept in Farmhand) and maintenance reminders (in Moonraker)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ServiceDone(BaseModel):
    note: str = Field("", max_length=5000)


class ServiceUpdate(BaseModel):
    enabled: bool


class Reminder(BaseModel):
    type: str | None = None  # null | "one-time" | "repeat"
    filament: dict | None = None  # {"bool": true, "value": metres}
    printtime: dict | None = None  # {"bool": true, "value": hours}
    date: dict | None = None  # {"bool": true, "value": days}


class MaintenanceIn(BaseModel):
    name: str = Field(max_length=200)
    note: str = Field("", max_length=5000)
    reminder: Reminder | None = None


class MaintenanceUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    note: str | None = Field(None, max_length=5000)
    reminder: Reminder | None = None


class PerformIn(BaseModel):
    note: str = Field("", max_length=5000)
