"""
Farmhand's settings, and the file they're copied to on the network storage the person chose.

What counts as a setting: how the site looks (colour scheme, text brightness, font, size), display
preferences (the Models and Printers sort orders, the Monitor and Farm cost arrangements, the Power page's
electricity prices...), the storage setup (the STL, 3MF and project folders, the farm cost records folder, and
which network shares exist). The server keeps these in its database. When a settings folder is chosen, a copy
is written there after every change (and all of it with Save all), so the settings survive a rebuild and can be
put back with Load all.

This file never contains a share's password. A share's login has to be known before the share can be mounted, so
it couldn't live only on the share anyway; loading brings a share back "needing its password". (The printers'
own files beside it, in printers/, do hold their Moonraker API keys and PrusaLink passwords.)

This module is the format and the file handling. No database, so it's easy to test.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path

from . import record_files

CONFIG_FILENAME = "farmhand-config.json"
FORMAT_MARKER = "farmhand_config"  # the key that says "this is one of ours"
FORMAT_VERSION = 1
MAX_FILE_BYTES = 1_000_000

# file_name_color: the colour of 3MF file names, "auto" (the scheme's own) or a #RRGGBB chosen on the Appearance page
DEFAULT_APPEARANCE = {"scheme": "farmhand", "contrast": 0, "font": "archivo", "size": "default", "file_name_color": "auto"}
# monitor_order: the Monitor page's cameras in the order they were dragged into, as "printer id:camera name"
# monitor_max_zoom: how far in a camera can be zoomed on the Monitor page, one of MONITOR_ZOOMS
# farm_cost_order: the Farm cost page's printers in the order they were dragged into, as printer ids (printers not in
# it come after, by name)
# tool_links: the websites listed on the Tools page, in the order given, each {"name", "url"} (url http or https).
# Until a list is saved, the Klipper ones below are shown; a list saved empty stays empty.
DEFAULT_TOOL_LINKS = [
    {"name": "CANBus guide (Esoterical)", "url": "https://canbus.esoterical.online/"},
    {"name": "USB guide (Esoterical)", "url": "https://usb.esoterical.online/"},
    {"name": "A better print_start macro", "url": "https://abetterprintstartmacro.com/"},
    {"name": "Klipper TMC Autotune", "url": "https://github.com/andrewmcgr/klipper_tmc_autotune"},
    {"name": "Klippain Shake&Tune", "url": "https://github.com/Frix-x/klippain-shaketune"},
    {"name": "Klippy Detective", "url": "https://klippydetective.com/"},
    {"name": "Energy usage monitoring (Voron mods)", "url": "https://mjonuschat.github.io/voron-mods/docs/guides/energy-usage-monitoring-tracking/"},
    {"name": "Kalico documentation", "url": "https://docs.kalico.gg/"},
    {"name": "KIAUH (Klipper Installation And Update Helper)", "url": "https://github.com/dw-0/kiauh"},
    {"name": "Klipper documentation", "url": "https://www.klipper3d.org/"},
    {"name": "KlipperScreen documentation", "url": "https://klipperscreen.readthedocs.io/en/latest/"},
    {"name": "Mainsail documentation", "url": "https://docs.mainsail.xyz/"},
    {"name": "Moonraker Timelapse", "url": "https://github.com/mainsail-crew/moonraker-timelapse"},
]
# The price of electricity, in $ per kWh, as set on the Power page:
#   energy_price_per_kwh: the average cost as it is now; None = not set
#   energy_price_history: each time it was set, [{"from": "2026-11", "price": 0.17 | None}] oldest first: a price counts
#     from its month on (the first one for every month before it too), so changing it never changes a past month
#   energy_price_months: {"2026-03": 0.14}: a month's own price, typed in its row; it wins over the history
DEFAULT_PREFERENCES = {
    "model_sort": {"key": "name", "dir": "asc"}, "printer_sort": {"key": "name", "dir": "asc"}, "monitor_order": [],
    "monitor_max_zoom": 4, "farm_cost_order": [],
    "tool_links": DEFAULT_TOOL_LINKS,
    "energy_price_per_kwh": None, "energy_price_history": [], "energy_price_months": {},
    "time_zone": None,
}
# printer_sort: the Printers page's list, by a column ("name", "kind", "wired", "wireless") and "asc" | "desc"
# time_zone: the farm's time zone ("America/New_York"), as its browser last said: when a month ends for the monthly
# Farm cost record; None = not known yet (UTC is used)
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_PRICE_ENTRIES = 1200  # a hundred years of months
MAX_ENERGY_PRICE = 100.0  # $ per kWh: anything above is a typo
MAX_MONITOR_CAMERAS = 500
MAX_PRINTERS_ORDERED = 500
MONITOR_ZOOMS = (2, 3, 4, 6, 8)
MAX_TOOL_LINKS = 200

_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
SHARE_FIELDS = ("name", "protocol", "server", "share", "username", "domain", "version")


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
        "printer_sort": _sort(p.get("printer_sort"), DEFAULT_PREFERENCES["printer_sort"]),
        "monitor_order": _camera_keys(p.get("monitor_order")),
        "monitor_max_zoom": p["monitor_max_zoom"] if type(p.get("monitor_max_zoom")) is int and p["monitor_max_zoom"] in MONITOR_ZOOMS
        else DEFAULT_PREFERENCES["monitor_max_zoom"],
        "farm_cost_order": _printer_ids(p.get("farm_cost_order")),
        "tool_links": _tool_links(p.get("tool_links")),
        "energy_price_per_kwh": _energy_price(p.get("energy_price_per_kwh")),
        "energy_price_history": _price_history(p.get("energy_price_history")),
        "energy_price_months": _price_months(p.get("energy_price_months")),
        "time_zone": _time_zone(p.get("time_zone")),
    }


def _time_zone(raw) -> str | None:
    """A time zone's name that this server knows ("Europe/London"); anything else = not known."""
    if not isinstance(raw, str) or not 0 < len(raw) <= 64:
        return None
    try:
        ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return raw


def is_month(value: str) -> bool:
    """ "2026-03" """
    return bool(_MONTH.match(value))


def _price_history(raw) -> list[dict]:
    """[{"from": "YYYY-MM", "price"}], oldest first, one per month (the last given wins); bad entries are dropped."""
    by_month: dict[str, float | None] = {}
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("from"), str) and _MONTH.match(entry["from"]):
            by_month[entry["from"]] = _energy_price(entry.get("price"))
    return [{"from": m, "price": by_month[m]} for m in sorted(by_month)][-MAX_PRICE_ENTRIES:]


def _price_months(raw) -> dict[str, float]:
    """{"YYYY-MM": price}: months with a price of their own; a bad month or price is dropped."""
    out: dict[str, float] = {}
    for month, price in (raw.items() if isinstance(raw, dict) else []):
        price = _energy_price(price)
        if isinstance(month, str) and _MONTH.match(month) and price is not None:
            out[month] = price
    return dict(sorted(out.items())[-MAX_PRICE_ENTRIES:])


def energy_price_for(preferences: dict, month: str) -> float | None:
    """
    The price per kWh for a month ("2026-03"): its own, if one was typed for it; else the average cost that counted
    then (the first one set also counts for every month before it); else, with no history, the average cost as it is.
    """
    if month in preferences.get("energy_price_months", {}):
        return preferences["energy_price_months"][month]
    history = preferences.get("energy_price_history") or []
    if not history:
        return preferences.get("energy_price_per_kwh")
    price = history[0]["price"]
    for entry in history:
        if entry["from"] > month:
            break
        price = entry["price"]
    return price


def _energy_price(raw) -> float | None:
    """A price per kWh: a number from 0 to MAX_ENERGY_PRICE, rounded to 5 decimal places; anything else = not set."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return round(value, 5) if 0 <= value <= MAX_ENERGY_PRICE else None


def _tool_links(raw) -> list[dict]:
    """The Tools page's websites: web addresses only (http or https), so a link can never run script; a blank name
    is kept blank (the page shows the address instead). No list saved yet: the defaults."""
    if not isinstance(raw, list):
        return [dict(link) for link in DEFAULT_TOOL_LINKS]
    links = raw
    out: list[dict] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        url = link.get("url").strip() if isinstance(link.get("url"), str) else ""
        name = link.get("name").strip() if isinstance(link.get("name"), str) else ""
        if re.match(r"^https?://[^\s/]+", url, re.IGNORECASE) and len(url) <= 2000 and len(name) <= 100:
            out.append({"name": name, "url": url})
        if len(out) >= MAX_TOOL_LINKS:
            break
    return out


def _sort(raw, default: dict) -> dict:
    s = raw if isinstance(raw, dict) else {}
    return {"key": _id(s.get("key"), default["key"]), "dir": s.get("dir") if s.get("dir") in ("asc", "desc") else default["dir"]}


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


def _printer_ids(raw) -> list[int]:
    """The Farm cost order: printer ids (whole numbers above 0), each once, in the order given."""
    ids = raw if isinstance(raw, list) else []
    out: list[int] = []
    for i in ids:
        if type(i) is int and 0 < i < 2**31 and i not in out:
            out.append(i)
        if len(out) >= MAX_PRINTERS_ORDERED:
            break
    return out


def normalize_config(raw) -> dict:
    c = raw if isinstance(raw, dict) else {}
    return {"appearance": normalize_appearance(c.get("appearance")), "preferences": normalize_preferences(c.get("preferences"))}


def _path_or_none(value) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 500 else None


def build_document(
    config: dict, stl_path: str | None, threemf_path: str | None, shares: list[dict], project_path: str | None = None,
    farm_cost_path: str | None = None, printer_names: dict[int, str] | None = None,
) -> dict:
    """What gets written. Share entries are cut down to the fields in SHARE_FIELDS — never a password. printer_names:
    each printer's number here and its name, so the orders kept by number (Farm cost, Monitor) come back in the right
    order on a Farmhand that numbers its printers differently."""
    return {
        FORMAT_MARKER: FORMAT_VERSION,
        "saved_at": record_files.stamp(),
        "note": "Written by Farmhand after every settings change. A share's login is kept here without its secret.",
        "appearance": config["appearance"],
        "preferences": config["preferences"],
        "storage": {"stl_path": stl_path, "threemf_path": threemf_path, "project_path": project_path},
        "shares": [{k: s.get(k) for k in SHARE_FIELDS} for s in shares],
        "farm_cost": {"records_path": farm_cost_path},  # the folder chosen for the monthly records (null: the default)
        "printer_names": {str(k): v for k, v in (printer_names or {}).items()},
    }


def write_document(folder: str | os.PathLike, document: dict) -> Path:
    """Write atomically: a share dropping mid-write must never leave a half-written settings file."""
    target = Path(folder) / CONFIG_FILENAME
    record_files.write_json(target, document)
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
    farm_cost = raw.get("farm_cost") if isinstance(raw.get("farm_cost"), dict) else {}  # files from before it have none
    shares = []
    for entry in (raw.get("shares") if isinstance(raw.get("shares"), list) else [])[:100]:
        if isinstance(entry, dict):
            shares.append({k: (entry.get(k) if isinstance(entry.get(k), str) else None) for k in SHARE_FIELDS})
    return {
        "saved_at": raw.get("saved_at") if isinstance(raw.get("saved_at"), str) else None,
        **normalize_config(raw),
        "storage": {
            "stl_path": _path_or_none(storage.get("stl_path")),
            "threemf_path": _path_or_none(storage.get("threemf_path")),
            "project_path": _path_or_none(storage.get("project_path")),  # files from before project files have none
        },
        "shares": shares,
        "farm_cost": {"records_path": _path_or_none(farm_cost.get("records_path"))},
        # files from before it have none: their orders are taken as they are
        "printer_names": {
            k: v for k, v in (raw.get("printer_names") if isinstance(raw.get("printer_names"), dict) else {}).items()
            if isinstance(k, str) and k.isdigit() and isinstance(v, str) and v
        },
    }
