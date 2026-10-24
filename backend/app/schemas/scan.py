from __future__ import annotations

from pydantic import BaseModel, Field


class ScannedFileOut(BaseModel):
    path: str
    name: str
    folder: str  # relative to the STL folder; "" = top level
    size_bytes: int
    file_type: str
    name_in_library: bool  # a model with this name already exists


class ScanOut(BaseModel):
    root: str
    truncated: bool  # more were found than are listed; add these and scan again
    files: list[ScannedFileOut]


class ScanImportRequest(BaseModel):
    paths: list[str] = Field(max_length=100)  # the browser sends small batches


class ScanImportItem(BaseModel):
    path: str
    ok: bool
    error: str | None
    source_model_id: int | None


class ScanImportOut(BaseModel):
    results: list[ScanImportItem]
