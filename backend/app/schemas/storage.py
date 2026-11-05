from __future__ import annotations

from pydantic import BaseModel


class LocationStatus(BaseModel):
    exists: bool
    writable: bool
    marker_ok: bool
    ready: bool  # exists, writable, and (if chosen in the UI) its marker file is present
    free_bytes: int | None
    total_bytes: int | None
    separate_volume: bool  # on a different filesystem than the app's own local storage (e.g. a network share)


class StorageLocation(BaseModel):
    path: str
    default_path: str
    is_default: bool
    status: LocationStatus


class OutsideCounts(BaseModel):
    """Versions with files still outside the currently selected locations."""

    stl: int
    threemf: int
    project: int = 0  # project files (CAD file versions)


class StorageSettingsOut(BaseModel):
    browse_root: str
    stl: StorageLocation
    threemf: StorageLocation
    project: StorageLocation  # project files: each project's own files (its CAD files)
    outside: OutsideCounts


class StorageSettingsUpdate(BaseModel):
    """Only fields present are changed; null resets that location to its default."""

    stl_path: str | None = None
    threemf_path: str | None = None
    project_path: str | None = None


class BrowseEntry(BaseModel):
    name: str
    path: str
    is_mount: bool


class BrowseOut(BaseModel):
    path: str
    root: str
    parent: str | None
    entries: list[BrowseEntry]


class MigrationFailure(BaseModel):
    name: str
    error: str


class MigrationResult(BaseModel):
    moved_stl: int
    moved_threemf: int
    moved_project: int = 0
    missing: list[str]  # versions whose file wasn't where the database said it was
    failed: list[MigrationFailure]
