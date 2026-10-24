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
    moonraker_url: str | None = None  # where Farmhand reaches its Moonraker (the override, else <IP>:7125)
    moonraker_url_override: str | None = None  # what was set for it, if anything
    mainsail_url: str | None = None
    has_moonraker_api_key: bool = False  # the key itself is never returned
    # The 1500-hour service reminder Farmhand keeps: {state: waiting | off | ok | due, enabled, interval_hours,
    # hours_since, started_at, last_done: {done_at, hours, note} | null}
    service: dict | None = None


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
    # Moonraker: a blank address goes back to the default (<IP>:7125). The API key is only changed when it's sent:
    # a new key replaces the saved one, "" removes it, and leaving it out keeps it.
    moonraker_url: str | None = None
    moonraker_api_key: str | None = None

    @field_validator("moonraker_url")
    @classmethod
    def _moonraker_url_is_http(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip().rstrip("/")
        if "://" not in v:
            v = f"http://{v}"
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("The Moonraker address must start with http:// or https://")
        return v

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("A printer needs a name")
        return v
