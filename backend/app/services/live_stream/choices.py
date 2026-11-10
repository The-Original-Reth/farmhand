"""
What's chosen for the stream (kept in app_settings), checked on the way in: where to, the grid and its squares, taking turns, the resolution, the colours and the YouTube title and description.
"""
from __future__ import annotations

import json
import math

from sqlalchemy.orm import Session

from .. import app_settings
from .fonts import DEFAULT_FONT, FONTS
from .constants import DEFAULT_TEXT_COLOR
from .constants import CAMERA_KEY, COLOR, DEFAULT_BACKGROUND, DEFAULT_BORDER, DEFAULT_DESTINATION, DEFAULT_RESOLUTION, DESCRIPTION_MAX, DESTINATIONS, KEY_SHAPE, LAYOUTS, MAX_CAMERAS, MAX_SIDE, RESOLUTIONS, SAVED, SECONDS, SETTINGS_KEY, STREAM_KEY_KEY, TITLE_MAX
from .squares import SLIDE_SECONDS, TEXT_MAX, _cell, _color

# ------------------------------------------------------------------ what's chosen


def _seconds(raw: dict, name: str) -> int:
    least, most, default = SECONDS[name]
    v = raw.get(name)
    return v if isinstance(v, int) and not isinstance(v, bool) and least <= v <= most else default


def auto_grid(n: int) -> tuple[int, int]:
    """(columns, rows) of the smallest near-square grid that holds n squares (1x1 for none)."""
    cols = min(MAX_SIDE, max(1, math.ceil(math.sqrt(n))))
    return cols, min(MAX_SIDE, max(1, math.ceil(n / cols)))

def _side(v) -> int | None:
    return v if type(v) is int and 1 <= v <= MAX_SIDE else None


def settings(db: Session) -> dict:
    """
    {destination, cols, rows, cells: [one per square, row by row, see _cell], cameras (the
    cameras' keys in the grid, square by square), show_status, layout: "grid" | "cycle", seconds_all, seconds_each,
    resolution, border_color: "#RRGGBB", background: the stream's colour "#RRGGBB", font and color: the
    stream's words' (every square's and camera's unless it has its own), enabled: the Stream page's switch (off: nothing
    streams), title, description, key_set}.
    The key itself is never given. Settings from before the grid (a list of cameras) come back as the grid they made.
    """
    try:
        raw = json.loads(app_settings.get(db, SETTINGS_KEY) or "{}")
    except ValueError:
        raw = {}
    destination = raw.get("destination") if raw.get("destination") in DESTINATIONS else DEFAULT_DESTINATION
    text = lambda name: raw.get(name) if isinstance(raw.get(name), str) else ""  # noqa: E731
    if isinstance(raw.get("cells"), list) and _side(raw.get("cols")) and _side(raw.get("rows")):
        cols, rows = raw["cols"], raw["rows"]
        cells = [_cell(c) for c in raw["cells"][: cols * rows]]
    else:  # before the grid: the cameras, in a grid just big enough
        old = [k for k in raw.get("cameras") or [] if isinstance(k, str) and CAMERA_KEY.match(k)][:MAX_CAMERAS]
        cols, rows = auto_grid(len(old))
        cells = [{"camera": k} for k in old]
    cells += [None] * (cols * rows - len(cells))
    return {
        "destination": destination,
        "cols": cols,
        "rows": rows,
        "cells": cells,
        "cameras": [c["camera"] for c in cells if c and "camera" in c],
        "show_status": raw.get("show_status", True) is not False,
        "layout": raw.get("layout") if raw.get("layout") in LAYOUTS else "grid",
        "resolution": raw.get("resolution") if raw.get("resolution") in RESOLUTIONS else DEFAULT_RESOLUTION,
        "seconds_all": _seconds(raw, "seconds_all"),
        "seconds_each": _seconds(raw, "seconds_each"),
        "border_color": _color(raw.get("border_color"), DEFAULT_BORDER),
        "background": _color(raw.get("background"), DEFAULT_BACKGROUND),
        "enabled": raw.get("enabled") is not False,  # the Stream page's switch: off, nothing streams
        "font": raw.get("font") if raw.get("font") in FONTS else DEFAULT_FONT,
        "color": _color(raw.get("color"), DEFAULT_TEXT_COLOR),
        "title": text("title"),
        "description": text("description"),
        "key_set": bool(app_settings.get(db, STREAM_KEY_KEY)),
    }


def _youtube_text(text: str, most: int, what: str) -> str:
    text = text.strip()
    if len(text) > most:
        raise ValueError(f"YouTube allows a {what} of up to {most} characters; this one has {len(text)}.")
    if "<" in text or ">" in text:
        raise ValueError(f"YouTube doesn't allow < or > in a {what}.")
    return text


def check_cells(db: Session, cols, rows, cells) -> list[dict | None]:
    """
    The squares as sent, made sure of: one per square of a cols x rows grid, each camera once, a card's text that fits,
    pictures and slideshows by names a file can have, a picture or a slideshow but not both, seconds in range. (A
    picture or slideshow not in the stream folder (yet) is allowed: the square shows its colour until it's there.)
    """
    if _side(cols) is None or _side(rows) is None:
        raise ValueError(f"The grid can be 1 to {MAX_SIDE} squares across and 1 to {MAX_SIDE} down.")
    if not isinstance(cells, list) or len(cells) != cols * rows:
        raise ValueError(f"Say what's in each of the grid's {cols * rows} squares.")
    out, seen = [], set()
    for raw in cells:
        if raw is None:
            out.append(None)
            continue
        cell = _cell(raw)
        if cell is None:
            raise ValueError("A square can hold a camera, a colour, a picture or a slideshow with words over it, or nothing.")
        if "camera" in cell:
            if cell["camera"] in seen:
                raise ValueError("A camera can only be in one square.")
            seen.add(cell["camera"])
        else:
            if raw.get("image") and raw.get("slideshow"):
                raise ValueError("A square shows a picture or a slideshow, not both.")
            for key in ("image", "slideshow"):
                if raw.get(key) and not cell[key]:
                    raise ValueError(f"That isn't a name a {'picture' if key == 'image' else 'slideshow'} can have.")
            cell["text"] = cell["text"].strip()
            if len(cell["text"]) > TEXT_MAX:
                raise ValueError(f"A square's text can be up to {TEXT_MAX} characters; this one has {len(cell['text'])}.")
            least, most, _ = SLIDE_SECONDS
            if raw.get("seconds") is not None and not (type(raw.get("seconds")) is int and least <= raw["seconds"] <= most):
                raise ValueError(f"A slideshow shows each picture for {least} to {most} seconds.")
        out.append(cell)
    return out


def save(db: Session, *, destination=None, chosen=None, show_status=None, stream_key=None, clear_key=False, layout=None,
         resolution=None, border_color=None, background=None, font=None, color=None, enabled=None, cols=None, rows=None, cells=None,
         seconds_all=None, seconds_each=None, title=None, description=None) -> dict:
    """
    Change what's given (None: left as it is). The grid comes as cols, rows and cells together; or `chosen`, a list of
    cameras, which makes a grid just big enough for them, in that order. Anything that can't be
    used is refused with why.
    """
    now = settings(db)
    if destination is not None:
        if destination not in DESTINATIONS:
            raise ValueError("Choose YouTube Live or Twitch.")
        now["destination"] = destination
    if cells is not None or cols is not None or rows is not None:
        now["cells"] = check_cells(db, cols if cols is not None else now["cols"], rows if rows is not None else now["rows"],
                                   cells if cells is not None else now["cells"])
        now["cols"], now["rows"] = (cols or now["cols"]), (rows or now["rows"])
    elif chosen is not None:
        keys = []
        for k in chosen:
            if not isinstance(k, str) or not CAMERA_KEY.match(k):
                raise ValueError(f"That isn't a camera Farmhand knows: {str(k)[:60]}")
            if k not in keys:
                keys.append(k)
        if len(keys) > MAX_CAMERAS:
            raise ValueError(f"A stream can show up to {MAX_CAMERAS} cameras at once.")
        now["cols"], now["rows"] = auto_grid(len(keys))
        now["cells"] = [{"camera": k} for k in keys] + [None] * (now["cols"] * now["rows"] - len(keys))
    if show_status is not None:
        now["show_status"] = bool(show_status)
    if border_color is not None:
        if not isinstance(border_color, str) or not COLOR.match(border_color):
            raise ValueError("Choose the border's colour with the colour picker (#RRGGBB).")
        now["border_color"] = border_color.upper()
    if enabled is not None:
        now["enabled"] = bool(enabled)
    if font is not None:
        if font not in FONTS:
            raise ValueError("Choose one of the fonts listed for the stream's words.")
        now["font"] = font
    if color is not None:
        if not isinstance(color, str) or not COLOR.match(color):
            raise ValueError("Choose the colour of the stream's words with the colour picker (#RRGGBB).")
        now["color"] = color.upper()
    if background is not None:
        if not isinstance(background, str) or not COLOR.match(background):
            raise ValueError("Choose the stream's background colour with the colour picker (#RRGGBB).")
        now["background"] = background.upper()
    if resolution is not None:
        if resolution not in RESOLUTIONS:
            raise ValueError("Choose 720p, 1080p or 2K.")
        now["resolution"] = resolution
    if layout is not None:
        if layout not in LAYOUTS:
            raise ValueError("Choose the whole grid, or taking turns.")
        now["layout"] = layout
    for name, value in (("seconds_all", seconds_all), ("seconds_each", seconds_each)):
        if value is not None:
            least, most, _ = SECONDS[name]
            if not isinstance(value, int) or not least <= value <= most:
                what = "showing the whole grid" if name == "seconds_all" else "each camera"
                raise ValueError(f"The time for {what} has to be from {least} to {most} seconds.")
            now[name] = value
    if title is not None:
        now["title"] = _youtube_text(title, TITLE_MAX, "title")
    if description is not None:
        now["description"] = _youtube_text(description, DESCRIPTION_MAX, "description")
    if clear_key:
        app_settings.put(db, STREAM_KEY_KEY, None)
    elif stream_key is not None and stream_key.strip():
        key = stream_key.strip()
        if not KEY_SHAPE.match(key):
            raise ValueError("That doesn't look like a stream key. Copy it again from YouTube Studio (Go live → Stream → Stream key).")
        app_settings.put(db, STREAM_KEY_KEY, key)
    app_settings.put(db, SETTINGS_KEY, json.dumps({k: now[k] for k in SAVED}))
    db.commit()
    return settings(db)
