from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, field_validator


class PrinterCreate(BaseModel):
    name: str
    kind: str | None = None
    wired_ip: str | None = None
    wireless_ip: str | None = None


class PrinterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: str | None
    wired_ip: str | None
    wireless_ip: str | None
    decommissioned: bool
    created_at: dt.datetime
    notes: str = ""
    notes_revision: int = 0
    notes_updated_at: dt.datetime | None = None


class PrinterDecommission(BaseModel):
    decommissioned: bool


class PrinterUpdate(BaseModel):
    """
    Partial update: only fields actually present in the request are applied
    (so `"wired_ip": null` clears the IP, while omitting it leaves it alone).
    """

    name: str | None = None
    kind: str | None = None
    wired_ip: str | None = None
    wireless_ip: str | None = None
    decommissioned: bool | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("A printer needs a name")
        return v
