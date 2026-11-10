from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


class EnergyPriceData(BaseModel):
    model_config = {"populate_by_name": True}

    from_: str = Field(alias="from", serialization_alias="from")  # "2026-11": the month it counts from
    price: float | None


class StreamLayoutData(BaseModel):
    """One of the Stream page's saved layouts."""

    name: str
    cols: int = 1  # the grid, 1 to 5 squares across and down
    rows: int = 1
    cells: list[dict | None] = []  # each square, row by row: {"camera": "printer id:camera name"} | a card | null
    layout: str = "grid"  # "grid" (the whole grid) | "cycle" (taking turns)
    seconds_all: int = 30
    seconds_each: int = 20
    show_status: bool = True
    border_color: str = "#000000"
    background: str = "#000000"  # the stream's own colour


class PreferencesData(BaseModel):
    model_sort: SortData
    printer_sort: SortData = SortData(key="name", dir="asc")  # the Printers page's list
    monitor_order: list[str] = []
    monitor_max_zoom: int = 4
    farm_cost_order: list[int] = []  # the Farm cost page's printers as dragged into order (printer ids)
    stream_layouts: list[StreamLayoutData] = []  # the Stream page's saved layouts, in the order saved
    tool_links: list[ToolLinkData] = []  # the Tools page's websites, in order
    energy_price_per_kwh: float | None = None  # $ per kWh, typed on the Power page; null = not set
    energy_price_history: list[EnergyPriceData] = []  # each time it was set: counts from that month on
    energy_price_months: dict[str, float] = {}  # {"2026-03": 0.14}: months given a price of their own
    time_zone: str | None = None  # the farm's, as its browser last said: when a month ends for the Farm cost record


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


class SaveAllIn(BaseModel):
    if_exists: Literal["ask", "restore", "overwrite"] = "ask"  # only matters when Save all chooses the folder


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
    # From the printers/ and models/ files: printers_added, printers_filled, prints_added, readings_added, prices_added,
    # model_notes, threemf_notes, stars, models_missing
    records: dict | None = None
    # The files another Farmhand keeps in the shared folders, brought in: {models: [names], threemfs: [names],
    # projects: [{name, files: {doc, cad, stl, threemf, gcode}, added}]} (added: a project here already, given its new files)
    brought_in: dict | None = None


class LocationResult(BaseModel):
    saved: bool
    needs_choice: bool  # the folder already holds a settings file: say whether to use it or replace it
    found: InspectOut | None
    restored: RestoreOut | None
    location: LocationOut


class SaveAllOut(LocationResult):
    """What Save all did: as choosing the folder answers, and the copy it wrote (null when a choice is needed first)."""

    mirror: MirrorOut | None
    # the records written beside the files: {"library": models' and 3MFs', "projects": n} (null when a choice is needed)
    records: dict[str, int] | None = None
