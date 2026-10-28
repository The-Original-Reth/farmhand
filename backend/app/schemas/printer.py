from __future__ import annotations

import datetime as dt
import re

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


def _http_url(v: str | None) -> str | None:
    """A printer address: blank = the default one; a bare host gets http:// in front."""
    if v is None or not v.strip():
        return None
    v = v.strip().rstrip("/")
    if "://" not in v:
        v = f"http://{v}"
    if not v.lower().startswith(("http://", "https://")):
        raise ValueError("The address must start with http:// or https://")
    return v


def _camera_address(v: str | None) -> str | None:
    """A camera's IP or host name, or a whole rtsp:// URL; blank = no camera."""
    if v is None or not v.strip():
        return None
    v = v.strip()
    if len(v) > 255:
        raise ValueError("That camera address is too long")
    if "://" in v:
        if not v.lower().startswith(("rtsp://", "rtsps://")):
            raise ValueError("A camera address is an IP address, or a whole address starting with rtsp://")
    elif not re.fullmatch(r"[A-Za-z0-9.\-]+(:\d{1,5})?", v):
        raise ValueError("A camera address is an IP address (e.g. 192.168.10.131), or a whole rtsp:// address")
    return v


class PrinterCreate(BaseModel):
    name: str
    kind: str | None = None
    wired_ip: str | None = None
    wireless_ip: str | None = None
    # How Farmhand talks to it, and its login: the same fields and rules as PrinterUpdate
    connection_type: Literal["moonraker", "prusalink"] = "moonraker"
    moonraker_url: str | None = None
    moonraker_api_key: str | None = None
    prusalink_url: str | None = None
    prusalink_username: str | None = None
    prusalink_password: str | None = None
    camera_address: str | None = None

    @field_validator("moonraker_url", "prusalink_url")
    @classmethod
    def _url_is_http(cls, v: str | None) -> str | None:
        return _http_url(v)

    @field_validator("camera_address")
    @classmethod
    def _camera(cls, v: str | None) -> str | None:
        return _camera_address(v)


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
    connection_type: str = "moonraker"  # "moonraker" | "prusalink"
    prusalink_url: str | None = None  # where Farmhand reaches its PrusaLink (the override, else http://<IP>)
    prusalink_url_override: str | None = None
    prusalink_username: str | None = None
    has_prusalink_password: bool = False  # the password itself is never returned
    camera_address: str | None = None  # a camera Farmhand plays itself (a Buddy3D's): its IP, or an rtsp:// URL
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
    # How Farmhand talks to it. Switching to "moonraker" forgets the PrusaLink login; the prints on record stay.
    connection_type: Literal["moonraker", "prusalink"] | None = None
    # PrusaLink: a blank address goes back to the default (http://<IP>). The username defaults to "maker". The
    # password works like the Moonraker API key: a new one replaces the saved one, "" removes it, leaving it out keeps it.
    prusalink_url: str | None = None
    prusalink_username: str | None = None
    prusalink_password: str | None = None
    # A camera Farmhand plays itself (a Buddy3D's): its IP or an rtsp:// URL. Blank (or null) removes it.
    camera_address: str | None = None

    @field_validator("moonraker_url", "prusalink_url")
    @classmethod
    def _url_is_http(cls, v: str | None) -> str | None:
        return _http_url(v)

    @field_validator("camera_address")
    @classmethod
    def _camera(cls, v: str | None) -> str | None:
        return _camera_address(v)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("A printer needs a name")
        return v
