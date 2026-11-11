"""
What the plugin API answers (/plugin-api/v1/, docs/plugins.md has every shape). Each answer is kept for a few seconds
(cache.py), so plugins asking often don't load Farmhand or its printers. Nothing secret is ever in one: no Moonraker
API key, PrusaLink password or share login.

v1 only ever gains fields and endpoints; nothing here is renamed or taken away (that would be v2).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Printer
from .. import cameras, config_service, print_progress
from ..camera_streams import stream_address, turn_filters
from .cache import kept

PRINTERS_SECONDS = 5.0
CAMERAS_SECONDS = 15.0  # each Klipper printer is asked for its cameras: kept longer
PRINT_SECONDS = 3.0
FARM_SECONDS = 10.0

PALETTES = Path(__file__).with_name("palettes.json")  # frontend/src/palettes.js's schemes (npm run export:palettes)


def printers(db: Session) -> dict:
    """Every printer in service: its id, name, how Farmhand talks to it, and where."""
    return kept("printers", PRINTERS_SECONDS, lambda: {"printers": [_printer(p) for p in _active(db)]})


def _active(db: Session) -> list[Printer]:
    return list(db.scalars(select(Printer).where(Printer.decommissioned.is_(False)).order_by(Printer.name)))


def _printer(p: Printer) -> dict:
    return {
        "id": p.id, "name": p.name, "kind": p.kind, "connection_type": p.connection_type,
        "addresses": {
            "wired_ip": p.wired_ip, "wireless_ip": p.wireless_ip,
            "moonraker_url": p.moonraker_url if p.connection_type == "moonraker" else None,
            "mainsail_url": p.mainsail_url if p.connection_type == "moonraker" else None,
            "prusalink_url": p.prusalink_url if p.connection_type == "prusalink" else None,
            "camera_address": p.camera_address,
        },
    }


def cameras_of_farm(db: Session) -> dict:
    """Every printer in service with its cameras, each with where ffmpeg reads it, or why it can't be streamed."""
    return {"printers": [kept(("cameras", p.id), CAMERAS_SECONDS, lambda p=p: _cameras(p)) for p in _active(db)]}


def _cameras(printer: Printer) -> dict:
    found = cameras.printer_cameras(printer)
    out = []
    for cam in found["webcams"]:
        entry = {
            "name": cam.get("name") or "Camera", "kind": None, "url": None, "ffmpeg_input": None,
            "rotation": int(cam.get("rotation") or 0), "flip_horizontal": bool(cam.get("flip_horizontal")),
            "flip_vertical": bool(cam.get("flip_vertical")), "ffmpeg_filters": turn_filters(cam),
            "aspect_ratio": cam.get("aspect_ratio"), "target_fps": cam.get("target_fps"),
            "snapshot_url": cam.get("snapshot_url"), "error": None,
        }
        try:
            address = stream_address(printer, cam)
            entry.update(kind=address.kind, url=address.url, ffmpeg_input=address.input_args)
        except ValueError as e:
            entry["error"] = str(e)
        out.append(entry)
    return {"printer_id": printer.id, "printer_name": printer.name, "cameras": out, "error": found["error"]}


def print_of(db: Session, printer: Printer) -> dict:
    """{state, progress, file, error} of the print under way (print_progress.progress)."""
    return kept(("print", printer.id), PRINT_SECONDS, lambda: print_progress.progress(db, printer))


def farm(db: Session) -> dict:
    """Farmhand's colours (the scheme chosen on the Appearance page, as the pages show it) and the farm's time zone."""
    def make() -> dict:
        config = config_service.get_config(db)
        look = config["appearance"]
        mode, colors = palette(look["scheme"], look["contrast"], look["file_name_color"])
        return {"scheme": look["scheme"], "mode": mode, "colors": colors, "time_zone": config["preferences"].get("time_zone")}
    return kept("farm", FARM_SECONDS, make)


@lru_cache(maxsize=1)
def _schemes() -> dict:
    return json.loads(PALETTES.read_text(encoding="utf-8"))


def palette(scheme: str, contrast: int, file_name_color: str = "auto") -> tuple[str, dict]:
    """
    (mode, colours) as the pages apply them (frontend/src/appearance.js): the scheme's colours, the three text colours
    drawn toward the heading colour by the text brightness setting, and the 3MF file name colour if one was chosen.
    """
    schemes = _schemes()
    chosen = schemes.get(scheme) or next(iter(schemes.values()))
    colors = dict(chosen["colors"])
    t = min(100, max(0, int(contrast or 0))) / 100
    for key in ("textPrimary", "textMuted", "textFaint"):
        colors[key] = _mix(colors[key], colors["heading"], t)
    if file_name_color and file_name_color != "auto":
        colors["fileName"] = file_name_color
    return chosen["mode"], colors


def _mix(a: str, b: str, t: float) -> str:
    """Blend two #RRGGBB colours (t = 0 is a), rounding as JavaScript's Math.round does."""
    channel = lambda hex_, i: int(hex_[1 + i * 2: 3 + i * 2], 16)  # noqa: E731
    out = [int(channel(a, i) + (channel(b, i) - channel(a, i)) * t + 0.5) for i in range(3)]
    return "#" + "".join(f"{v:02X}" for v in out)
