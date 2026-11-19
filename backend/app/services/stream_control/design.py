"""
The one stream designed in Stream control, kept as an app_settings row (DESIGN_KEY) and checked on the way in as the
stream plugins check their own (live_stream/choices.py there): the grid and its squares, taking turns, the size, the
colours and words' font, the music, the holding screen, the stream delay, and the title and description each site
shows. What only one site has (a stream key, a sign-in, YouTube's privacy or Twitch's category) stays in its plugin.

Each save adds one to `revision`, so a stream plugin asking for the design knows when it has changed.
"""
from __future__ import annotations

import json
import math

from sqlalchemy.orm import Session

from ...timeutil import utc_iso, utc_now
from .. import app_settings
from .constants import (CAMERA_KEY, COLOR, DEFAULT_BACKGROUND, DEFAULT_BORDER, DEFAULT_MUSIC_VOLUME, DEFAULT_RESOLUTION,
                        DEFAULT_TEXT_COLOR, DELAY, DESCRIPTION_MAX, HOLDING_DEFAULTS, HOLDING_TEXT_MAX, LAYOUTS, MAX_CAMERAS,
                        MAX_SIDE, RESOLUTION_LABELS, RESOLUTIONS, SECONDS, TITLE_MAX)
from .fonts import DEFAULT_FONT, FONTS
from .squares import MAX_LAYERS, SLIDE_SECONDS, TEXT_MAX, _cell, _color, _named

DESIGN_KEY = "stream_control_design"
SAVED = ("cols", "rows", "cells", "show_status", "layout", "seconds_all", "seconds_each", "resolution", "border_color",
         "background", "font", "color", "music", "music_volume", "music_shuffle", "music_from", "delay", "holding", "title",
         "description")
# Where the music comes from (music_from): Stream control's own music folder, and/or stream plugins' own (their ids):
# their tracks are listed and passed on from where they are, never copied (music_sources.py)
OWN_MUSIC = "stream-control"
MUSIC_FROM_MAX = 10
# the stream's own colours, as a refusal names them
COLOURS = {"border_color": "the border's colour", "color": "the colour of the stream's words", "background": "the stream's background colour"}


def _saved(db: Session) -> dict:
    try:
        raw = json.loads(app_settings.get(db, DESIGN_KEY) or "{}")
    except ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _seconds(raw: dict, name: str) -> int:
    least, most, default = SECONDS[name]
    v = raw.get(name)
    return v if isinstance(v, int) and not isinstance(v, bool) and least <= v <= most else default


def _side(v) -> int | None:
    return v if type(v) is int and 1 <= v <= MAX_SIDE else None


def _volume(v) -> bool:
    return type(v) is int and 0 <= v <= 100


def auto_grid(n: int) -> tuple[int, int]:
    """(columns, rows) of the smallest near-square grid that holds n squares (1x1 for none)."""
    cols = min(MAX_SIDE, max(1, math.ceil(math.sqrt(n))))
    return cols, min(MAX_SIDE, max(1, math.ceil(n / cols)))


def _holding(raw) -> dict:
    """The holding screen as kept: {text, image (a picture of the stream folder's), background, color, font (None: the stream's)}."""
    raw = raw if isinstance(raw, dict) else {}
    text = raw.get("text") if isinstance(raw.get("text"), str) else HOLDING_DEFAULTS["text"]
    return {
        "text": text[:HOLDING_TEXT_MAX],
        "image": _named(raw.get("image")),
        "background": _color(raw.get("background"), None),
        "color": _color(raw.get("color"), None),
        "font": raw.get("font") if raw.get("font") in FONTS else None,
    }


def _check_holding(sent, now: dict) -> dict:
    """The holding screen as sent (only what's sent changes; null colours and font: the stream's own), checked."""
    if not isinstance(sent, dict):
        raise ValueError("The holding screen's settings didn't come through.")
    out = dict(now)
    if "text" in sent:
        if not isinstance(sent["text"], str) or len(sent["text"].strip()) > HOLDING_TEXT_MAX:
            raise ValueError(f"The holding screen's words can be up to {HOLDING_TEXT_MAX} characters.")
        out["text"] = sent["text"].strip()
    if "image" in sent:
        if sent["image"] is not None and _named(sent["image"]) is None:
            raise ValueError("Choose one of the stream folder's pictures for the holding screen.")
        out["image"] = sent["image"]
    for name, what in (("background", "background"), ("color", "words' colour")):
        if name in sent:
            if sent[name] is not None and not (isinstance(sent[name], str) and COLOR.match(sent[name])):
                raise ValueError(f"Choose the holding screen's {what} with the colour picker (#RRGGBB).")
            out[name] = sent[name].upper() if sent[name] else None
    if "font" in sent:
        if sent["font"] is not None and sent["font"] not in FONTS:
            raise ValueError("Choose one of the fonts listed for the holding screen's words.")
        out["font"] = sent["font"]
    return out


def _music_from(raw) -> list[str]:
    """The music folders chosen, as kept: OWN_MUSIC and/or plugin ids, each once ([] for anything unusable)."""
    if not isinstance(raw, list):
        return []
    out = [x for x in dict.fromkeys(raw) if isinstance(x, str) and 0 < len(x) <= 40]
    return out[:MUSIC_FROM_MAX]


def _text(value, most: int, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"The stream's {what} has to be text.")
    value = value.strip()
    if len(value) > most:
        raise ValueError(f"The stream's {what} can be up to {most} characters; this one has {len(value)}.")
    return value


def settings(db: Session) -> dict:
    """
    The design: {cols, rows, cells: [one per square, row by row: a camera {"camera": "printer id:camera name", ...}, a
    card (squares._cell) or None], cameras (the cameras' keys, square by square), show_status (each printer's name and
    print written on its camera), layout: "grid" | "cycle", seconds_all, seconds_each, resolution, border_color,
    background, font, color (the stream's words', every square's unless it has its own), music, music_volume (0 to
    100), music_shuffle, delay (seconds each plugin holds the stream before its site gets it), holding (the holding
    screen), title, description, revision (one more each save), saved_at}.
    """
    raw = _saved(db)
    text = lambda name: raw.get(name) if isinstance(raw.get(name), str) else ""  # noqa: E731
    if isinstance(raw.get("cells"), list) and _side(raw.get("cols")) and _side(raw.get("rows")):
        cols, rows = raw["cols"], raw["rows"]
        cells = [_cell(c) for c in raw["cells"][: cols * rows]]
    else:
        cols, rows, cells = 1, 1, []
    cells += [None] * (cols * rows - len(cells))
    return {
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
        "font": raw.get("font") if raw.get("font") in FONTS else DEFAULT_FONT,
        "color": _color(raw.get("color"), DEFAULT_TEXT_COLOR),
        "music": raw.get("music") is not False,
        "music_volume": raw["music_volume"] if _volume(raw.get("music_volume")) else DEFAULT_MUSIC_VOLUME,
        "music_shuffle": raw.get("music_shuffle", True) is not False,
        "music_from": _music_from(raw.get("music_from")) or [OWN_MUSIC],
        "delay": raw["delay"] if type(raw.get("delay")) is int and DELAY[0] <= raw["delay"] <= DELAY[1] else DELAY[2],
        "holding": _holding(raw.get("holding")),
        "title": text("title"),
        "description": text("description"),
        "revision": raw["revision"] if type(raw.get("revision")) is int and raw["revision"] >= 0 else 0,
        "saved_at": raw.get("saved_at") if isinstance(raw.get("saved_at"), str) else None,
    }


def resolutions() -> list[dict]:
    return [{"key": k, "label": RESOLUTION_LABELS[k]} for k in RESOLUTIONS]


def check_cells(cols, rows, cells) -> list[dict | None]:
    """
    The squares as sent, made sure of: one per square of a cols x rows grid, each camera once, a card's words that fit,
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
            for name, cap in cell["captions"].items():
                cap["text"] = cap["text"].strip()
                if len(cap["text"]) > TEXT_MAX:
                    raise ValueError(f"The text on “{name}” can be up to {TEXT_MAX} characters; it has {len(cap['text'])}.")
            for where, layers in [("the square", cell["layers"]), *((f"“{n}”", ls) for n, ls in cell["slide_layers"].items())]:
                if len(layers) > MAX_LAYERS:
                    raise ValueError(f"Up to {MAX_LAYERS} more pictures and pieces of text can go on {where}; there are {len(layers)}.")
                for layer in layers:
                    if layer["type"] == "text":
                        layer["text"] = layer["text"].strip()
                        if len(layer["text"]) > TEXT_MAX:
                            raise ValueError(f"A piece of text on {where} can be up to {TEXT_MAX} characters; one has {len(layer['text'])}.")
            least, most, _ = SLIDE_SECONDS
            if raw.get("seconds") is not None and not (type(raw.get("seconds")) is int and least <= raw["seconds"] <= most):
                raise ValueError(f"A slideshow shows each picture for {least} to {most} seconds.")
        out.append(cell)
    return out


def save(db: Session, sent: dict) -> dict:
    """
    Change what's sent (a key left out, or None, stays as it was). The grid comes as cols, rows and cells together;
    or `cameras`, a list of cameras, which makes a grid just big enough for them, in that order. Anything that can't be
    used is refused with why (ValueError).
    """
    now = settings(db)
    get = lambda k: sent.get(k)  # noqa: E731
    if any(get(k) is not None for k in ("cells", "cols", "rows")):
        cols = get("cols") if get("cols") is not None else now["cols"]
        rows = get("rows") if get("rows") is not None else now["rows"]
        now["cells"] = check_cells(cols, rows, get("cells") if get("cells") is not None else now["cells"])
        now["cols"], now["rows"] = cols, rows
    elif get("cameras") is not None:
        keys: list[str] = []
        for k in get("cameras"):
            if not isinstance(k, str) or not CAMERA_KEY.match(k):
                raise ValueError(f"That isn't a camera Farmhand knows: {str(k)[:60]}")
            if k not in keys:
                keys.append(k)
        if len(keys) > MAX_CAMERAS:
            raise ValueError(f"A stream can show up to {MAX_CAMERAS} cameras at once.")
        now["cols"], now["rows"] = auto_grid(len(keys))
        now["cells"] = [{"camera": k} for k in keys] + [None] * (now["cols"] * now["rows"] - len(keys))
    for name in ("border_color", "color", "background"):
        value = get(name)
        if value is not None:
            if not isinstance(value, str) or not COLOR.match(value):
                raise ValueError(f"Choose {COLOURS[name]} with the colour picker (#RRGGBB).")
            now[name] = value.upper()
    for name in ("show_status", "music", "music_shuffle"):
        if get(name) is not None:
            now[name] = bool(get(name))
    if get("music_from") is not None:
        picked = _music_from(get("music_from"))
        if not picked:
            raise ValueError("Choose at least one music folder: Stream control's, or a stream's own.")
        now["music_from"] = picked
    if get("holding") is not None:
        now["holding"] = _check_holding(get("holding"), now["holding"])
    delay = get("delay")
    if delay is not None:
        if type(delay) is not int or not DELAY[0] <= delay <= DELAY[1]:
            raise ValueError(f"The stream's delay has to be from {DELAY[0]} to {DELAY[1]} seconds.")
        now["delay"] = delay
    if get("music_volume") is not None:
        if not _volume(get("music_volume")):
            raise ValueError("The music's volume has to be from 0 to 100%.")
        now["music_volume"] = get("music_volume")
    if get("font") is not None:
        if get("font") not in FONTS:
            raise ValueError("Choose one of the fonts listed for the stream's words.")
        now["font"] = get("font")
    if get("resolution") is not None:
        if get("resolution") not in RESOLUTIONS:
            raise ValueError("Choose 720p, 1080p or 2K.")
        now["resolution"] = get("resolution")
    if get("layout") is not None:
        if get("layout") not in LAYOUTS:
            raise ValueError("Choose the whole grid, or taking turns.")
        now["layout"] = get("layout")
    for name in SECONDS:
        value = get(name)
        if value is not None:
            least, most, _ = SECONDS[name]
            if type(value) is not int or not least <= value <= most:
                what = "showing the whole grid" if name == "seconds_all" else "each camera"
                raise ValueError(f"The time for {what} has to be from {least} to {most} seconds.")
            now[name] = value
    if get("title") is not None:
        now["title"] = _text(get("title"), TITLE_MAX, "title")
    if get("description") is not None:
        now["description"] = _text(get("description"), DESCRIPTION_MAX, "description")
    _write(db, {k: now[k] for k in SAVED}, now["revision"])
    return settings(db)


def _write(db: Session, kept: dict, revision: int) -> None:
    app_settings.put(db, DESIGN_KEY, json.dumps({**kept, "revision": revision + 1, "saved_at": utc_iso(utc_now())}))
    db.commit()


def rename_slideshow(db: Session, old: str, new: str) -> int:
    """A slideshow's folder was renamed: every square showing it, in the design and each saved layout, shows it by its
    new name. How many squares changed."""
    from . import layouts as saved_layouts

    def follow(cells) -> int:
        n = 0
        for c in cells:
            if isinstance(c, dict) and "camera" not in c and c.get("slideshow") == old:
                c["slideshow"] = new
                n += 1
        return n

    raw = _saved(db)
    changed = follow(raw.get("cells") or [])
    if changed:
        _write(db, {k: v for k, v in raw.items() if k not in ("revision", "saved_at")}, settings(db)["revision"])
    layouts = saved_layouts.layouts(db)
    in_layouts = sum(follow(lay["cells"]) for lay in layouts)
    if in_layouts:
        saved_layouts.save(db, layouts)
    return changed + in_layouts


def rename_slideshow_folder(db: Session, old: str, name: str) -> str:
    """Rename a slideshow's folder in the stream folder (media.rename_slideshow), and every square showing it follows
    (rename_slideshow). Its new name, as the folder has it."""
    from . import media

    new = media.rename_slideshow(db, old, name)
    if new != old:
        rename_slideshow(db, old, new)
    return new


def put_whole(db: Session, raw: dict) -> None:
    """A design brought back by Load all settings: kept as it was written (read through settings() as any other)."""
    if isinstance(raw, dict):
        _write(db, {k: raw[k] for k in SAVED if k in raw}, settings(db)["revision"])
