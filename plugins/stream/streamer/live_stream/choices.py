"""
What's chosen for the stream (kept in app_settings), checked on the way in: where to, the grid and its squares, taking turns, the resolution, the colours, the music and the YouTube title and description.
"""
from __future__ import annotations

import json
import math

from sqlalchemy.orm import Session

from .. import app_settings
from .fonts import DEFAULT_FONT, FONTS
from .constants import DEFAULT_TEXT_COLOR
from .constants import CATEGORIES, DELAY, LATENCIES, PRIVACIES, TAGS_MAX, YOUTUBE_DEFAULTS
from .constants import CAMERA_KEY, COLOR, DEFAULT_BACKGROUND, DEFAULT_BORDER, DEFAULT_DESTINATION, DEFAULT_MUSIC_VOLUME, DEFAULT_RESOLUTION, DESCRIPTION_MAX, DESTINATIONS, KEY_SHAPE, LAYOUTS, MAX_CAMERAS, MAX_SIDE, RESOLUTIONS, SAVED, SECONDS, SETTINGS_KEY, STREAM_KEY_KEY, TITLE_MAX
from .squares import MAX_LAYERS, SLIDE_SECONDS, TEXT_MAX, _cell, _color

# the stream's own colours, as a refusal names them
COLOURS = {"border_color": "the border's colour", "color": "the colour of the stream's words", "background": "the stream's background colour"}


def _seconds(raw: dict, name: str) -> int:
    least, most, default = SECONDS[name]
    v = raw.get(name)
    return v if isinstance(v, int) and not isinstance(v, bool) and least <= v <= most else default


def auto_grid(n: int) -> tuple[int, int]:
    """(columns, rows) of the smallest near-square grid that holds n squares (1x1 for none)."""
    cols = min(MAX_SIDE, max(1, math.ceil(math.sqrt(n))))
    return cols, min(MAX_SIDE, max(1, math.ceil(n / cols)))


def _youtube(raw) -> dict:
    """The video's YouTube settings as kept (anything missing or not one of the choices: its default)."""
    raw = raw if isinstance(raw, dict) else {}
    tags = [t.strip() for t in raw.get("tags") or [] if isinstance(t, str) and t.strip()] if isinstance(raw.get("tags"), list) else []
    return {
        "privacy": raw.get("privacy") if raw.get("privacy") in PRIVACIES else YOUTUBE_DEFAULTS["privacy"],
        "tags": list(dict.fromkeys(tags)),
        "category": raw.get("category") if raw.get("category") in CATEGORIES else YOUTUBE_DEFAULTS["category"],
        "made_for_kids": raw.get("made_for_kids") is True,
        "latency": raw.get("latency") if raw.get("latency") in LATENCIES else YOUTUBE_DEFAULTS["latency"],
        "dvr": raw.get("dvr") is not False,
        "auto_start": raw.get("auto_start") is not False,
        "auto_stop": raw.get("auto_stop") is not False,
    }


def _check_youtube(sent: dict, now: dict) -> dict:
    """The video's YouTube settings as sent (only what's sent changes), checked: ValueError says what's wrong."""
    if not isinstance(sent, dict):
        raise ValueError("The YouTube settings didn't come through.")
    out = dict(now)
    if sent.get("privacy") is not None:
        if sent["privacy"] not in PRIVACIES:
            raise ValueError("Choose public, unlisted or private.")
        out["privacy"] = sent["privacy"]
    if sent.get("latency") is not None:
        if sent["latency"] not in LATENCIES:
            raise ValueError("Choose normal, low or ultra-low latency.")
        out["latency"] = sent["latency"]
    if sent.get("category") is not None:
        if sent["category"] not in CATEGORIES:
            raise ValueError("Choose one of the categories listed.")
        out["category"] = sent["category"]
    if sent.get("tags") is not None:
        if not isinstance(sent["tags"], list) or not all(isinstance(t, str) for t in sent["tags"]):
            raise ValueError("The tags didn't come through.")
        tags = list(dict.fromkeys(t.strip() for t in sent["tags"] if t.strip()))
        if any(c in t for t in tags for c in "<>"):
            raise ValueError("YouTube doesn't allow < or > in a tag.")
        if len(",".join(tags)) > TAGS_MAX:
            raise ValueError(f"YouTube allows {TAGS_MAX} characters of tags; these come to {len(','.join(tags))}.")
        out["tags"] = tags
    for name in ("made_for_kids", "dvr", "auto_start", "auto_stop"):
        if sent.get(name) is not None:
            out[name] = bool(sent[name])
    return out


def _volume(v) -> bool:
    return type(v) is int and 0 <= v <= 100


def _side(v) -> int | None:
    return v if type(v) is int and 1 <= v <= MAX_SIDE else None


def _saved(db: Session) -> dict:
    """The settings as kept, unchecked ({} when there are none, or they can't be read)."""
    try:
        raw = json.loads(app_settings.get(db, SETTINGS_KEY) or "{}")
    except ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}


def settings(db: Session) -> dict:
    """
    {destination, cols, rows, cells: [one per square, row by row, see _cell], cameras (the
    cameras' keys in the grid, square by square), show_status, layout: "grid" | "cycle", seconds_all, seconds_each,
    resolution, border_color: "#RRGGBB", background: the stream's colour "#RRGGBB", font and color: the
    stream's words' (every square's and camera's unless it has its own), enabled: the Stream page's switch (off: nothing
    streams), music: the stream folder's music played, starting with the stream (on unless turned off; False: a silent
    sound track), music_volume (0 to 100), music_shuffle: each round in a new order (False: in name order), title,
    description, key_set, delay: seconds the stream is held before YouTube gets it (0 to 120), so a stall shorter than
    that never reaches it, youtube: the video's own YouTube settings (_youtube: privacy, tags, category, made_for_kids,
    latency, dvr, auto_start, auto_stop), key_from_youtube: Farmhand has a stream of its own on the channel, so its key
    comes from YouTube}.
    The key itself is never given. Settings from before the grid (a list of cameras) come back as the grid they made.
    """
    raw = _saved(db)
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
        "music": raw.get("music") is not False,
        "music_volume": raw["music_volume"] if _volume(raw.get("music_volume")) else DEFAULT_MUSIC_VOLUME,
        "music_shuffle": raw.get("music_shuffle", True) is not False,
        "delay": raw["delay"] if type(raw.get("delay")) is int and DELAY[0] <= raw["delay"] <= DELAY[1] else DELAY[2],
        "youtube": _youtube(raw.get("youtube")),
        "title": text("title"),
        "description": text("description"),
        "key_set": bool(app_settings.get(db, STREAM_KEY_KEY)),
        "key_from_youtube": bool(app_settings.get(db, "youtube_stream_id")),
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


def save(db: Session, *, destination=None, chosen=None, show_status=None, stream_key=None, clear_key=False, layout=None,
         resolution=None, border_color=None, background=None, font=None, color=None, enabled=None, cols=None, rows=None, cells=None,
         seconds_all=None, seconds_each=None, title=None, description=None, music=None, music_volume=None, music_shuffle=None,
         delay=None, youtube=None) -> dict:
    """
    Change what's given (None: left as it is). The grid comes as cols, rows and cells together; or `chosen`, a list of
    cameras, which makes a grid just big enough for them, in that order. Anything that can't be
    used is refused with why.
    """
    now = settings(db)
    if destination is not None:
        if destination not in DESTINATIONS:
            raise ValueError("Farmhand streams to YouTube Live for now.")
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
    for name, value in (("border_color", border_color), ("color", color), ("background", background)):
        if value is not None:
            if not isinstance(value, str) or not COLOR.match(value):
                raise ValueError(f"Choose {COLOURS[name]} with the colour picker (#RRGGBB).")
            now[name] = value.upper()
    if enabled is not None:
        now["enabled"] = bool(enabled)
    if music is not None:
        now["music"] = bool(music)
    if music_shuffle is not None:
        now["music_shuffle"] = bool(music_shuffle)
    if youtube is not None:
        now["youtube"] = _check_youtube(youtube, now["youtube"])
    if delay is not None:
        if type(delay) is not int or not DELAY[0] <= delay <= DELAY[1]:
            raise ValueError(f"The stream's delay has to be from {DELAY[0]} to {DELAY[1]} seconds.")
        now["delay"] = delay
    if music_volume is not None:
        if not _volume(music_volume):
            raise ValueError("The music's volume has to be from 0 to 100%.")
        now["music_volume"] = music_volume
    if font is not None:
        if font not in FONTS:
            raise ValueError("Choose one of the fonts listed for the stream's words.")
        now["font"] = font
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


def rename_slideshow(db: Session, old: str, new: str) -> int:
    """A slideshow's folder was renamed: every square showing it, on the Stream page and in each saved layout, shows it
    by its new name. How many squares changed."""
    from .. import config_service  # (it reads these settings itself)

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
        app_settings.put(db, SETTINGS_KEY, json.dumps(raw))
        db.commit()
    layouts = config_service.get_config(db)["preferences"]["stream_layouts"]
    in_layouts = sum(follow(lay["cells"]) for lay in layouts)
    if in_layouts:
        config_service.save_config(db, {"preferences": {"stream_layouts": layouts}})
    return changed + in_layouts
