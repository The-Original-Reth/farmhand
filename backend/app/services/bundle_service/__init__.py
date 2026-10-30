"""3MF files (bundles): each is a printer's slicing of one or more models, kept as numbered versions.

  queries   looking them up
  uploads   a new 3MF, or a new version of one
  versions  pruning, monuments, downloads, renaming, deleting
  marks     the starred version, and notes

Everything is re-exported here, so callers keep using bundle_service.<name>.
"""
from __future__ import annotations

from .queries import get_bundle, require_bundle, require_version, list_all_bundles, list_bundles_for_printer, list_bundles_for_source_model
from .uploads import inspect_3mf, create_bundle, add_bundle_version
from .versions import attach_gcode, set_monument, download_bundle_version, delete_bundle, delete_bundle_version, rename_version
from .marks import StarNotAllowed, set_starred_version, set_notes
from ...notes import NotesConflict  # noqa: F401  (raised by set_notes)

__all__ = [
    "get_bundle",
    "require_bundle",
    "require_version",
    "list_all_bundles",
    "list_bundles_for_printer",
    "list_bundles_for_source_model",
    "inspect_3mf",
    "create_bundle",
    "add_bundle_version",
    "attach_gcode",
    "set_monument",
    "download_bundle_version",
    "delete_bundle",
    "delete_bundle_version",
    "rename_version",
    "StarNotAllowed",
    "set_starred_version",
    "set_notes",
    "NotesConflict",
]
