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


def _text(v: str | None, limit: int, too_long: str) -> str | None:
    """Optional text, trimmed: blank = none; longer than `limit` is refused with `too_long`."""
    v = (v or "").strip()
    if len(v) > limit:
        raise ValueError(too_long)
    return v or None


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


class SubPrinterOut(BaseModel):
    """One of a printer's printer presets in the slicer (see SubPrinter)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    aliases: list[str] = []  # other preset names that mean it (its old names, presets given to it by hand)


class SubPrinterIn(BaseModel):
    name: str  # the preset's name, exactly as the slicer shows it

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A sub printer needs a name")
        if len(v) > 120:
            raise ValueError("A sub printer's name can be at most 120 characters")
        return v


class SubPrinterCopyIn(BaseModel):
    name: str | None = None  # the copy's name; none: "<its name> - copy" (- copy 2... when that's taken)


class DefaultSubPrinterIn(BaseModel):
    sub_printer_id: int | None = None  # one of the printer's sub printers; null: no default


class SubPrinterPartOut(BaseModel):
    """A part fitted to a sub printer, written down on its Printer parts page."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    part: str
    make: str | None = None
    model: str | None = None
    installed_on: dt.date | None = None
    note: str | None = None
    in_name: bool = False


class SubPrinterPartIn(BaseModel):
    part: str  # what it is: "Hotend", "Nozzle"...
    make: str | None = None  # who makes it ("Phaetus"); blank = none
    model: str | None = None  # which one ("Rapido UHF"); blank = none
    installed_on: dt.date | None = None
    note: str | None = None
    in_name: bool = False  # ticked "Add to name": its model goes into the name the sub printer can be renamed to

    @field_validator("part")
    @classmethod
    def _part(cls, v: str) -> str:
        v = _text(v, 120, "A part's name can be at most 120 characters")
        if not v:
            raise ValueError("Say what the part is (e.g. Hotend)")
        return v

    @field_validator("make")
    @classmethod
    def _make(cls, v: str | None) -> str | None:
        return _text(v, 120, "The make can be at most 120 characters")

    @field_validator("model")
    @classmethod
    def _model(cls, v: str | None) -> str | None:
        return _text(v, 200, "The model can be at most 200 characters")

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        return _text(v, 2000, "A part's note can be at most 2000 characters")


class SubPrinterPartRow(SubPrinterPartIn):
    """One part in the whole list, saved at once: with its id when it's already written down, without when it's new."""

    id: int | None = None


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
    sub_printers: list[SubPrinterOut] = []  # its printer presets in the slicer, A to Z
    default_sub_printer_id: int | None = None  # the one its uploads start on (none: Farmhand guesses from the preset)


class DiscoveredPrinterOut(BaseModel):
    """A Moonraker found by a network scan that isn't in Farmhand yet. Nothing is added until the user picks it."""

    ip: str
    moonraker_url: str
    mainsail_url: str
    moonraker_version: str | None = None
    klippy_state: str | None = None  # ready | startup | shutdown | error | disconnected
    hostname: str | None = None  # the machine's own name, a suggestion for the printer's
    needs_api_key: bool = False  # it answered but refused: it wants a Moonraker API key


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
