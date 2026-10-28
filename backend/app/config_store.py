"""
Farmhand's settings, and the file they're copied to on the network storage the person chose.

What counts as a setting: how the site looks (colour scheme, text brightness, font, size), display
preferences (the Models sort order), and the storage setup (the STL and 3MF folders, and which network
shares exist). The server keeps these in its database. When a settings folder is chosen, a copy is written
there after every change, so the settings survive a rebuild and can be put back with Restore.

The file NEVER contains passwords. A share's login has to be known before the share can be mounted, so it
couldn't live only on the share anyway; restoring brings a share back "needing its password".

This module is the format and the file handling. No database, so it's easy to test.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

from .storage import write_text_atomically

CONFIG_FILENAME = "farmhand-config.json"
FORMAT_MARKER = "farmhand_config"  # the key that says "this is one of ours"
FORMAT_VERSION = 1
MAX_FILE_BYTES = 1_000_000

# file_name_color: the colour of 3MF file names, "auto" (the scheme's own) or a #RRGGBB chosen on the Appearance page
DEFAULT_APPEARANCE = {"scheme": "farmhand", "contrast": 0, "font": "archivo", "size": "default", "file_name_color": "auto"}
# monitor_order: the Monitor page's cameras in the order they were dragged into, as "printer id:camera name"
# monitor_max_zoom: how far in a camera can be zoomed on the Monitor page, one of MONITOR_ZOOMS
DEFAULT_PREFERENCES = {"model_sort": {"key": "name", "dir": "asc"}, "monitor_order": [], "monitor_max_zoom": 4}
MAX_MONITOR_CAMERAS = 500
MONITOR_ZOOMS = (2, 3, 4, 6, 8)

_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_SHARE_FIELDS = ("name", "protocol", "server", "share", "username", "domain", "version")


class ConfigFileError(ValueError):
    """The settings file exists but can't be used."""


def _id(value, default):
    # ids are validated for shape only: the web app falls back to its default for ones it doesn't know,
    # so a newer or older version of Farmhand can share the same file without rejecting each other's values
    return value if isinstance(value, str) and _ID.match(value) else default


def normalize_appearance(raw) -> dict:
    a = raw if isinstance(raw, dict) else {}
    try:
        contrast = int(round(float(a.get("contrast", 0))))
    except (TypeError, ValueError):
        contrast = DEFAULT_APPEARANCE["contrast"]
    return {
        "scheme": _id(a.get("scheme"), DEFAULT_APPEARANCE["scheme"]),
        "contrast": min(100, max(0, contrast)),
        "font": _id(a.get("font"), DEFAULT_APPEARANCE["font"]),
        "size": _id(a.get("size"), DEFAULT_APPEARANCE["size"]),
        "file_name_color": a["file_name_color"].upper() if isinstance(a.get("file_name_color"), str) and _HEX.match(a["file_name_color"])
        else DEFAULT_APPEARANCE["file_name_color"],
    }


def normalize_preferences(raw) -> dict:
    p = raw if isinstance(raw, dict) else {}
    sort = p.get("model_sort") if isinstance(p.get("model_sort"), dict) else {}
    return {
        "model_sort": {
            "key": _id(sort.get("key"), DEFAULT_PREFERENCES["model_sort"]["key"]),
            "dir": sort.get("dir") if sort.get("dir") in ("asc", "desc") else DEFAULT_PREFERENCES["model_sort"]["dir"],
        },
        "monitor_order": _camera_keys(p.get("monitor_order")),
        "monitor_max_zoom": p["monitor_max_zoom"] if type(p.get("monitor_max_zoom")) is int and p["monitor_max_zoom"] in MONITOR_ZOOMS
        else DEFAULT_PREFERENCES["monitor_max_zoom"],
    }


def _camera_keys(raw) -> list[str]:
    """The Monitor order: short strings only, each once, in the order given."""
    keys = raw if isinstance(raw, list) else []
    out: list[str] = []
    for k in keys:
        if isinstance(k, str) and 0 < len(k) <= 200 and k not in out:
            out.append(k)
        if len(out) >= MAX_MONITOR_CAMERAS:
            break
    return out


def normalize_config(raw) -> dict:
    c = raw if isinstance(raw, dict) else {}
    return {"appearance": normalize_appearance(c.get("appearance")), "preferences": normalize_preferences(c.get("preferences"))}


def _path_or_none(value) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 500 else None


def build_document(config: dict, stl_path: str | None, threemf_path: str | None, shares: list[dict]) -> dict:
    """What gets written. Share entries are cut down to the fields in _SHARE_FIELDS — never a password."""
    return {
        FORMAT_MARKER: FORMAT_VERSION,
        "saved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "note": "Written by Farmhand after every settings change. Passwords are never stored in this file.",
        "appearance": config["appearance"],
        "preferences": config["preferences"],
        "storage": {"stl_path": stl_path, "threemf_path": threemf_path},
        "shares": [{k: s.get(k) for k in _SHARE_FIELDS} for s in shares],
    }


def write_document(folder: str | os.PathLike, document: dict) -> Path:
    """Write atomically: a share dropping mid-write must never leave a half-written settings file."""
    target = Path(folder) / CONFIG_FILENAME
    write_text_atomically(target, json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    return target


def file_info(folder: str | os.PathLike) -> dict:
    target = Path(folder) / CONFIG_FILENAME
    try:
        st = target.stat()
    except OSError:
        return {"exists": False, "modified_at": None, "size": None}
    return {
        "exists": True,
        "modified_at": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).isoformat(timespec="seconds"),
        "size": st.st_size,
    }


def read_document(folder: str | os.PathLike) -> dict | None:
    """The settings in the folder's file, cleaned up; None if there's no file. Raises ConfigFileError if unusable."""
    target = Path(folder) / CONFIG_FILENAME
    if not target.is_file():
        return None
    try:
        if target.stat().st_size > MAX_FILE_BYTES:
            raise ConfigFileError("That settings file is far too large to be one of Farmhand's.")
        raw = json.loads(target.read_text(encoding="utf-8"))
    except ConfigFileError:
        raise
    except (OSError, ValueError) as e:
        raise ConfigFileError(f"That settings file can't be read: {e}")
    if not isinstance(raw, dict) or FORMAT_MARKER not in raw:
        raise ConfigFileError("That file isn't a Farmhand settings file.")
    if not isinstance(raw[FORMAT_MARKER], int) or raw[FORMAT_MARKER] > FORMAT_VERSION:
        raise ConfigFileError("That settings file was written by a newer Farmhand than this one.")

    storage = raw.get("storage") if isinstance(raw.get("storage"), dict) else {}
    shares = []
    for entry in (raw.get("shares") if isinstance(raw.get("shares"), list) else [])[:100]:
        if isinstance(entry, dict):
            shares.append({k: (entry.get(k) if isinstance(entry.get(k), str) else None) for k in _SHARE_FIELDS})
    return {
        "saved_at": raw.get("saved_at") if isinstance(raw.get("saved_at"), str) else None,
        **normalize_config(raw),
        "storage": {"stl_path": _path_or_none(storage.get("stl_path")), "threemf_path": _path_or_none(storage.get("threemf_path"))},
        "shares": shares,
    }
