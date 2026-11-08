"""
File storage on local disk or a mounted network share.

In four parts: roots.py (where each kind goes), writing.py, deleting.py and locations.py (choosing a folder).
Everything is used as storage.<name>, as before. Tests that fake a mounted share patch locations._is_mount.

Two locations for the large files, chosen independently in Settings → Storage:

  STL / OBJ / STEP source files   {stl_root}/{source_model_id}/v{n}/{filename}
  3MF and gcode files             {threemf_root}/{bundle_id}/v{n}/{filename}

Thumbnails are small, derived, and read on every page load, so they always stay
on the app's own local disk — browsing keeps working even if a share is down:

  {storage_root}/thumbnails/source_models/{id}/v{n}/thumbnail.png
  {storage_root}/thumbnails/bundles/{id}/v{n}/thumbnail.png

Until a location is chosen, the defaults keep the original layout:
  {storage_root}/source_models and {storage_root}/bundles

Every path stored in the database is absolute, so files stay readable where
they are when a location changes; `copy_verified` + the migration action in
storage_settings_service move them on request.

Network shares are mounted into the container from outside (see the README);
this module only reads/writes folders. A mount that silently drops leaves an
empty directory behind in its place, and writes would then land on the local
disk by accident. To guard against that, every folder chosen in the UI gets a
marker file, and writes to a chosen folder are refused when the marker is gone.
"""
from __future__ import annotations

from .roots import (
    CONFIG_FOLDER,
    FARM_COST_FOLDER,
    FOLDER_LABELS,
    FOLDER_RENAMES,
    KINDS,
    MARKER_NAME,
    PROJECTS_FOLDER,
    STL_FOLDER,
    StorageUnavailableError,
    THREEMF_FOLDER,
    bundle_version_dir,
    configure,
    current_folder,
    custom_path,
    default_root,
    effective_root,
    ensure_ready_folder,
    local_root,
    named_folder,
    project_file_dir,
    ready_root,
    reset,
    source_model_version_dir,
    thumbnails_root,
)
from .writing import (
    copy_verified,
    move_file,
    preview_beside,
    preview_cache_headers,
    save_preview_beside,
    save_upload,
    write_bytes_atomically,
    write_text_atomically,
)
from .deleting import (
    delete_files,
    is_managed_layout,
    rmdir_if_empty,
    tidy_project_folder,
)
from .locations import (
    browse_root,
    create_folder,
    folder_status,
    is_inside,
    is_persistent,
    list_subdirs,
    location_status,
    mark_location,
    overlapping_kinds,
    overlaps,
    resolve_location,
    validate_location,
)
from . import deleting, locations, roots, writing

__all__ = [
    "CONFIG_FOLDER",
    "FARM_COST_FOLDER",
    "FOLDER_LABELS",
    "FOLDER_RENAMES",
    "KINDS",
    "MARKER_NAME",
    "PROJECTS_FOLDER",
    "STL_FOLDER",
    "StorageUnavailableError",
    "THREEMF_FOLDER",
    "browse_root",
    "bundle_version_dir",
    "configure",
    "copy_verified",
    "create_folder",
    "current_folder",
    "custom_path",
    "default_root",
    "delete_files",
    "effective_root",
    "ensure_ready_folder",
    "folder_status",
    "is_inside",
    "is_managed_layout",
    "is_persistent",
    "list_subdirs",
    "local_root",
    "location_status",
    "mark_location",
    "move_file",
    "named_folder",
    "overlapping_kinds",
    "overlaps",
    "preview_beside",
    "preview_cache_headers",
    "project_file_dir",
    "ready_root",
    "reset",
    "resolve_location",
    "rmdir_if_empty",
    "save_preview_beside",
    "save_upload",
    "source_model_version_dir",
    "thumbnails_root",
    "tidy_project_folder",
    "validate_location",
    "write_bytes_atomically",
    "write_text_atomically",
    "deleting",
    "locations",
    "roots",
    "writing",
]
