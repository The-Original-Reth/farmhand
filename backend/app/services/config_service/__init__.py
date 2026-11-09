"""
Farmhand's settings, and their copy on the NAS that Load all brings back on a new Farmhand. In three parts:
  settings.py   the settings themselves (appearance and preferences)
  nas_copy.py   writing the copy to the settings folder, after each change (in the background) and by Save all
  loading.py    choosing the settings folder, Save all, and Load all (restore)
Everything is used as config_service.<name>, as before.
"""
from __future__ import annotations

from .settings import (
    KEY_CONFIG,
    get_config,
    save_config,
)
from .nas_copy import (
    EVERYTHING,
    FARM_COST_LOCATION,
    KEY_LOCATION,
    MIRROR_DELAY_SECONDS,
    MirrorScope,
    build_document,
    describe,
    enable_background_mirror,
    inspect_location,
    location_path,
    mirror,
    mirror_quietly,
    request_mirror,
)
from .loading import (
    DEFAULT_FOLDER,
    restore,
    save_all,
    write_records,
    set_location,
)
from . import loading, nas_copy, settings

__all__ = [
    "DEFAULT_FOLDER",
    "EVERYTHING",
    "FARM_COST_LOCATION",
    "KEY_CONFIG",
    "KEY_LOCATION",
    "MIRROR_DELAY_SECONDS",
    "MirrorScope",
    "build_document",
    "describe",
    "enable_background_mirror",
    "get_config",
    "inspect_location",
    "location_path",
    "mirror",
    "mirror_quietly",
    "request_mirror",
    "restore",
    "save_all",
    "write_records",
    "save_config",
    "set_location",
    "loading",
    "nas_copy",
    "settings",
]
