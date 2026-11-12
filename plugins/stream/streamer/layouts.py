"""
The Stream page's saved layouts, kept in the plugin's store (LAYOUTS_KEY) instead of Farmhand's settings: each named,
its grid and squares, timings, colours and words' font, checked as Farmhand checked them (config_store._stream_layouts,
copied here unchanged but for its imports).
"""
from __future__ import annotations

import math
import re

from .live_stream.fonts import DEFAULT_FONT, FONTS
from .live_stream.squares import _cell
from .store import Store

LAYOUTS_KEY = "stream_layouts"
MAX_STREAM_LAYOUTS = 50
MAX_STREAM_SIDE = 5  # the stream's grid is 1x1 to 5x5 (live_stream/constants.py)
STREAM_SECONDS = {"seconds_all": (0, 3600, 30), "seconds_each": (3, 3600, 20)}  # (least, most, default)
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def layouts(db: Store) -> list[dict]:
    """The saved layouts, in the order saved."""
    return _stream_layouts(db.json(LAYOUTS_KEY, []))


def save(db: Store, raw) -> list[dict]:
    """Keep these as the saved layouts (checked: anything that can't be a layout is left out)."""
    if not isinstance(raw, list):
        raise ValueError("The saved layouts must be a list.")
    kept = _stream_layouts(raw)
    db.put_json(LAYOUTS_KEY, kept)
    db.commit()
    return kept


def _camera_keys(raw) -> list[str]:
    """The Monitor order: short strings only, each once, in the order given."""
    keys = raw if isinstance(raw, list) else []
    out: list[str] = []
    for k in keys:
        if isinstance(k, str) and 0 < len(k) <= 200 and k not in out:
            out.append(k)
        if len(out) >= MAX_STREAM_SIDE * MAX_STREAM_SIDE:
            break
    return out


def _stream_cell(raw) -> dict | None:
    """A saved layout's square: a camera, or a card (as live_stream/squares.py _cell keeps them), or None."""
    if isinstance(raw, dict) and isinstance(raw.get("camera"), str) and 0 < len(raw["camera"]) <= 200:
        return {**_cell({**raw, "camera": "0:x"}), "camera": raw["camera"]}  # its own choices, as the Stream page keeps them
    cell = _cell(raw)
    if cell and "camera" not in cell:
        cell["text"] = cell["text"].strip()[:500]
    return cell


def _stream_layouts(raw) -> list[dict]:
    """
    The Stream page's saved layouts: each named (trimmed, up to 60 characters, unique in any case), its grid 1x1 to 5x5
    with what's in each square (a camera, each once; a logo; or nothing), its timings within the Stream page's limits
    (else the defaults) and its border colour. One saved before the grid (a list of cameras) gets the grid they made.
    """
    out: list[dict] = []
    seen: set[str] = set()
    side = lambda v: v if type(v) is int and 1 <= v <= MAX_STREAM_SIDE else None  # noqa: E731
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = item.get("name").strip() if isinstance(item.get("name"), str) else ""
        if not name or len(name) > 60 or name.lower() in seen:
            continue
        seen.add(name.lower())
        cols, rows = side(item.get("cols")), side(item.get("rows"))
        if cols and rows and isinstance(item.get("cells"), list):
            cells = [_stream_cell(c) for c in item["cells"][: cols * rows]]
        else:
            cameras = _camera_keys(item.get("cameras"))[: MAX_STREAM_SIDE * MAX_STREAM_SIDE]
            cols = min(MAX_STREAM_SIDE, max(1, math.ceil(math.sqrt(len(cameras)))))  # a grid just big enough
            rows = min(MAX_STREAM_SIDE, max(1, math.ceil(len(cameras) / cols)))
            cells = [{"camera": k} for k in cameras]
        cells += [None] * (cols * rows - len(cells))
        taken: set[str] = set()
        for i, cell in enumerate(cells):  # each camera in one square only
            if cell and "camera" in cell:
                if cell["camera"] in taken:
                    cells[i] = None
                taken.add(cell["camera"])
        layout = {"name": name, "cols": cols, "rows": rows, "cells": cells,
                  "layout": item.get("layout") if item.get("layout") in ("grid", "cycle") else "grid"}
        for key, (least, most, default) in STREAM_SECONDS.items():
            v = item.get(key)
            layout[key] = v if type(v) is int and least <= v <= most else default
        layout["show_status"] = item.get("show_status") is not False
        for key in ("border_color", "background"):
            color = item.get(key)
            layout[key] = color.upper() if isinstance(color, str) and _HEX.match(color) else "#000000"
        layout["font"] = item.get("font") if item.get("font") in FONTS else DEFAULT_FONT
        color = item.get("color")
        layout["color"] = color.upper() if isinstance(color, str) and _HEX.match(color) else "#FFFFFF"
        out.append(layout)
        if len(out) >= MAX_STREAM_LAYOUTS:
            break
    return out
