from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from .printer import PrinterOut
from .source_model import SourceModelOut


class BundleVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    filename: str
    slicer_family: str
    slicer_display_name: str
    printer_profile_name: str | None
    uploaded_at: dt.datetime
    monument: bool
    monument_note: str | None
    full_files_retained: bool
    thumbnail_path: str | None
    # settings intentionally omitted from the list view (can be large) —
    # fetch BundleVersionDetailOut for a single version to get it.


class BundleVersionDetailOut(BundleVersionOut):
    settings: dict


class BundleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    printer_id: int
    created_at: dt.datetime
    source_models: list[SourceModelOut] = []
    versions: list[BundleVersionOut] = []


class MonumentUpdate(BaseModel):
    monument: bool
    note: str | None = None
    confirm: bool = False


class ThreeMFInspection(BaseModel):
    """What a 3MF says about itself, before anything is stored."""

    printer_profile_name: str | None
    slicer_display_name: str
    matched_printer: PrinterOut | None  # the registered printer with that exact name, if any
