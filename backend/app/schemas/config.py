from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AppearanceData(BaseModel):
    scheme: str
    contrast: int
    font: str
    size: str
    file_name_color: str = "auto"  # 3MF file names: "auto" (the scheme's own) or #RRGGBB


class SortData(BaseModel):
    key: str
    dir: str


class ToolLinkData(BaseModel):
    name: str  # blank: the page shows the address
    url: str


class PreferencesData(BaseModel):
    model_sort: SortData
    monitor_order: list[str] = []
    monitor_max_zoom: int = 4
    tool_links: list[ToolLinkData] = []  # the Tools page's websites, in order


class ConfigData(BaseModel):
    appearance: AppearanceData
    preferences: PreferencesData


class ConfigUpdate(BaseModel):
    """Only the parts given are replaced. Values are checked and cleaned up on the server."""

    appearance: dict | None = None
    preferences: dict | None = None


class FileInfo(BaseModel):
    exists: bool
    modified_at: str | None
    size: int | None


class FolderStatus(BaseModel):
    exists: bool
    writable: bool
    marker_ok: bool
    ready: bool


class LastWrite(BaseModel):
    ok: bool | None
    error: str | None
    at: str | None


class LocationOut(BaseModel):
    path: str | None
    is_set: bool
    status: FolderStatus | None
    file: FileInfo | None
    last_write: LastWrite


class ConfigOut(BaseModel):
    config: ConfigData
    location: LocationOut


class MirrorOut(BaseModel):
    ok: bool
    skipped: bool
    path: str | None
    error: str | None


class ConfigSaveOut(BaseModel):
    config: ConfigData
    mirror: MirrorOut


class InspectOut(BaseModel):
    path: str
    file_exists: bool
    file_valid: bool | None
    modified_at: str | None
    summary: dict | None
    error: str | None


class LocationUpdate(BaseModel):
    path: str | None = None  # null clears it: the server alone keeps the settings
    if_exists: Literal["ask", "restore", "overwrite"] = "ask"


class RestoreOut(BaseModel):
    restored: list[str]
    shares_added: list[str]
    shares_kept: list[str]
    needs_password: list[str]
    warnings: list[str]
    # From the printers/ and models/ files: printers_added, printers_filled, prints_added, readings_added,
    # model_notes, threemf_notes, stars, models_missing
    records: dict | None = None


class LocationResult(BaseModel):
    saved: bool
    needs_choice: bool  # the folder already holds a settings file: say whether to use it or replace it
    found: InspectOut | None
    restored: RestoreOut | None
    location: LocationOut
