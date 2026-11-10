"""
The Stream page: printers' cameras sent live to YouTube (or Twitch) by Farmhand itself, no OBS needed.

The picture is a grid of squares, 1x1 to 5x5, on a background colour, each square holding a camera, a "card" or nothing,
in the order chosen, each with a border round it in the colour chosen. A card is a colour, with a picture or a slideshow
over it if you like, and words over that if you like; its pictures are files in the stream folder (stream_media.py). Taking turns, the picture shows
the whole grid for a while, then each camera on its own, round and round; only the camera on screen is enlarged, the
way Monitor enlarges the one clicked.

What's chosen (where to, the grid and its squares, the words, taking turns, the resolution, the YouTube title and
description) is kept in app_settings; the pictures in the stream folder. The stream key is kept in app_settings
under a key of its own and never leaves Farmhand again: it isn't returned by the API, isn't written to the settings
copy, and is blanked out of anything ffmpeg says.

Going live runs ffmpeg in the API's own container: it reads each camera in the grid (a Mainsail MJPEG stream, go2rtc on
the printer, or a Buddy3D's RTSP), lays the squares out, writes each printer's name and print under its camera, adds the
silent sound track YouTube insists on, and sends it all to the destination. If ffmpeg stops (a camera dropped, the
network blinked) it is started again after a short wait, for as long as the stream is meant to be live.

The YouTube broadcast's own title and description are set through YouTube's API (services/youtube_live.py) once the
broadcast has started.
"""
from __future__ import annotations

import collections
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlsplit

from sqlalchemy.orm import Session

from ..errors import NotFound
from .. import storage
from ..models import Printer
from . import app_settings, cameras, go2rtc, print_progress, stream_media, youtube_live

SETTINGS_KEY = "live_stream"  # see settings()
STREAM_KEY_KEY = "live_stream_key"  # the stream key itself, on its own

# Where each destination takes a stream: its RTMPS address, the stream key goes on the end
DESTINATIONS = {
    "youtube": {"label": "YouTube Live", "url": "rtmps://a.rtmps.youtube.com/live2/"},
    "twitch": {"label": "Twitch", "url": "rtmps://live.twitch.tv/app/"},
}
DEFAULT_DESTINATION = "youtube"
KEY_SHAPE = re.compile(r"^[A-Za-z0-9_\-?=&.]{4,200}$")
MAX_SIDE = 5  # the grid is 1x1 to 5x5
MAX_CAMERAS = MAX_SIDE * MAX_SIDE
CAMERA_KEY = re.compile(r"^\d+:.{1,100}$")  # "printer id:camera name", as Monitor names them

FPS = 15
# The sizes the stream can be sent at: (width, height, video bitrate as YouTube suggests for each), and their names
RESOLUTIONS = {
    "720p": (1280, 720, 2500),
    "1080p": (1920, 1080, 4500),
    "1440p": (2560, 1440, 9000),
}
RESOLUTION_LABELS = {"720p": "720p (1280×720)", "1080p": "1080p (1920×1080)", "1440p": "2K (2560×1440)"}
DEFAULT_RESOLUTION = "1080p"
WIDTH, HEIGHT, _ = RESOLUTIONS[DEFAULT_RESOLUTION]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"  # fonts-dejavu-core, in the API's image
FONTS_DIR = "/usr/share/fonts"
APP_FONTS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")  # fonts kept with Farmhand: "app:" in FONTS
# The fonts a square's words can be written in: key -> (name, its file in FONTS_DIR (the Dockerfile installs them),
# the kind of font the page falls back to while its own copy loads). A font the server doesn't have writes in FONT.
FONTS = {
    "dejavu-sans": ("DejaVu Sans", "truetype/dejavu/DejaVuSans.ttf", "sans-serif"),
    "play": ("Play (Farmhand's own)", "app:Play-Regular.ttf", "sans-serif"),
    "play-bold": ("Play Bold", "app:Play-Bold.ttf", "sans-serif"),
    "dejavu-sans-bold": ("DejaVu Sans Bold", "truetype/dejavu/DejaVuSans-Bold.ttf", "sans-serif"),
    "dejavu-serif": ("DejaVu Serif", "truetype/dejavu/DejaVuSerif.ttf", "serif"),
    "dejavu-mono": ("DejaVu Sans Mono", "truetype/dejavu/DejaVuSansMono.ttf", "monospace"),
    "liberation-sans": ("Liberation Sans (like Arial)", "truetype/liberation/LiberationSans-Regular.ttf", "sans-serif"),
    "liberation-sans-bold": ("Liberation Sans Bold", "truetype/liberation/LiberationSans-Bold.ttf", "sans-serif"),
    "liberation-serif": ("Liberation Serif (like Times New Roman)", "truetype/liberation/LiberationSerif-Regular.ttf", "serif"),
    "roboto": ("Roboto", "truetype/roboto/unhinted/RobotoTTF/Roboto-Regular.ttf", "sans-serif"),
    "roboto-bold": ("Roboto Bold", "truetype/roboto/unhinted/RobotoTTF/Roboto-Bold.ttf", "sans-serif"),
    "roboto-black": ("Roboto Black", "truetype/roboto/unhinted/RobotoTTF/Roboto-Black.ttf", "sans-serif"),
    "open-sans": ("Open Sans", "truetype/open-sans/OpenSans-Regular.ttf", "sans-serif"),
    "open-sans-bold": ("Open Sans Bold", "truetype/open-sans/OpenSans-Bold.ttf", "sans-serif"),
    "lato": ("Lato", "truetype/lato/Lato-Regular.ttf", "sans-serif"),
    "lato-black": ("Lato Black", "truetype/lato/Lato-Black.ttf", "sans-serif"),
    "montserrat": ("Montserrat", "truetype/montserrat/Montserrat-Regular.ttf", "sans-serif"),
    "montserrat-bold": ("Montserrat Bold", "truetype/montserrat/Montserrat-Bold.ttf", "sans-serif"),
    "montserrat-black": ("Montserrat Black", "truetype/montserrat/Montserrat-Black.ttf", "sans-serif"),
    "bebas-neue": ("Bebas Neue (capitals)", "opentype/bebas-neue/BebasNeue-Regular.otf", "sans-serif"),
    "comic-neue": ("Comic Neue", "opentype/comic-neue/ComicNeue-Regular.otf", "cursive"),
    "comic-neue-bold": ("Comic Neue Bold", "opentype/comic-neue/ComicNeue-Bold.otf", "cursive"),
    "fira-code": ("Fira Code", "truetype/firacode/FiraCode-Regular.ttf", "monospace"),
}
DEFAULT_FONT = "dejavu-sans"


def font_file(key: str | None) -> str:
    """The file a font is written with: its own when the server has it, else FONT."""
    found = FONTS.get(key or "")
    if found:
        file = found[1]
        path = os.path.join(APP_FONTS, file[4:]) if file.startswith("app:") else os.path.join(FONTS_DIR, file)
        if os.path.isfile(path):
            return path
    return FONT
RETRY_SECONDS = 10  # how long after ffmpeg stops it is started again
STATUS_EVERY = 15  # how often the print progress written on the video is brought up to date
KEPT_LINES = 30  # how much of what ffmpeg said is kept, to say why it stopped
TITLE_TRIES, TITLE_EVERY = 16, 15  # the YouTube title is tried this often after going live, until the broadcast is there

LAYOUTS = ("grid", "cycle")  # the grid all the time, or taking turns
SECONDS = {"seconds_all": (0, 3600, 30), "seconds_each": (3, 3600, 20)}  # (least, most, default); seconds_all 0: never
TITLE_MAX, DESCRIPTION_MAX = 100, 5000  # YouTube's own limits
DEFAULT_BORDER = "#000000"
DEFAULT_BACKGROUND = "#000000"  # the stream's own colour: empty squares, and round anything that doesn't fill its square
BORDER_WIDTH = 3  # px round each square, on the 720-high picture
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
SAVED = ("destination", "cols", "rows", "cells", "show_status", "layout", "seconds_all", "seconds_each", "title", "description",
         "resolution", "border_color", "background")

# ------------------------------------------------------------------ what's chosen


def _seconds(raw: dict, name: str) -> int:
    least, most, default = SECONDS[name]
    v = raw.get(name)
    return v if isinstance(v, int) and not isinstance(v, bool) and least <= v <= most else default


def auto_grid(n: int) -> tuple[int, int]:
    """(columns, rows) of the smallest near-square grid that holds n squares (1x1 for none)."""
    cols = min(MAX_SIDE, max(1, math.ceil(math.sqrt(n))))
    return cols, min(MAX_SIDE, max(1, math.ceil(n / cols)))


TEXT_MAX = 500
# Where a card's picture and words are, as parts of the square (0 to 1), moved and resized on the page's canvas.
# picture_box {x, y, w, h}: the box the picture is fitted into (left, top, width, height); text_box {x, y, size}: the
# words' centre and their height. Cards of before had a size (small/medium/large) and a place (top/middle/bottom).
FULL_BOX = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
BOX_LEAST = 0.05
TEXT_SIZE = (0.02, 0.6, 0.125)  # (least, most, default) height of the words
OLD_SIZES = {"small": 1 / 12, "medium": 1 / 8, "large": 1 / 5}
OLD_PLACES = {"top": 0.18, "middle": 0.5, "bottom": 0.82}
SLIDE_SECONDS = (3, 3600, 10)  # (least, most, default): how long each picture of a slideshow is shown
PICTURE_NAME = re.compile(r"^[^/\\\0]{1,120}$")
CARD_KEYS = ("background", "image", "slideshow", "seconds", "text", "color", "font", "band", "picture_box", "text_box")


def _color(v, default: str | None) -> str | None:
    return v.upper() if isinstance(v, str) and COLOR.match(v) else default


def _named(v) -> str | None:
    return v if isinstance(v, str) and PICTURE_NAME.match(v) and v not in (".", "..") else None


def _part(v, least: float, most: float, default: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return default
    return round(min(most, max(least, float(v))), 4)


def _picture_box(raw) -> dict:
    if not isinstance(raw, dict):
        return dict(FULL_BOX)
    w, h = _part(raw.get("w"), BOX_LEAST, 1, 1.0), _part(raw.get("h"), BOX_LEAST, 1, 1.0)
    return {"x": _part(raw.get("x"), 0, round(1 - w, 4), round((1 - w) / 2, 4)),
            "y": _part(raw.get("y"), 0, round(1 - h, 4), round((1 - h) / 2, 4)), "w": w, "h": h}


def _text_box(raw, old_size=None, old_place=None) -> dict:
    least, most, default = TEXT_SIZE
    if not isinstance(raw, dict):
        return {"x": 0.5, "y": round(OLD_PLACES.get(old_place, 0.5), 4), "size": round(OLD_SIZES.get(old_size, default), 4)}
    return {"x": _part(raw.get("x"), 0, 1, 0.5), "y": _part(raw.get("y"), 0, 1, 0.5), "size": _part(raw.get("size"), least, most, default)}


WORDS_SIZE = (0.02, 0.3)  # the height of a camera's words, as part of its square's, when chosen (none: sized to fit)


def _camera_cell(raw: dict) -> dict:
    """
    A camera's square: {"camera"}, and only what differs from the usual: "background" (round its picture; none: the
    stream's), "show_words": False (its printer's name and print not written on it), "words_size" (their height, part
    of the square's, 0.02 to 0.3; none: sized to the square), "words_color" (none: white), "words_font" (none: DejaVu Sans).
    """
    out = {"camera": raw["camera"]}
    back = _color(raw.get("background"), None)
    if back:
        out["background"] = back
    if raw.get("show_words") is False:
        out["show_words"] = False
    size = raw.get("words_size")
    if not isinstance(size, bool) and isinstance(size, (int, float)) and math.isfinite(size):
        out["words_size"] = _part(size, *WORDS_SIZE, 0.06)
    color = _color(raw.get("words_color"), None)
    if color and color != "#FFFFFF":
        out["words_color"] = color
    if raw.get("words_font") in FONTS and raw["words_font"] != DEFAULT_FONT:
        out["words_font"] = raw["words_font"]
    return out


def _cell(raw) -> dict | None:
    """
    A square as kept: {"camera": "printer id:camera name"}; a card, {"background": its colour (None: the stream's),
    "image": a picture's file name in the stream folder's images | None, "slideshow": a slideshow's folder name | None,
    "seconds": each slideshow picture's, "text": words over it ("" none), "color", "font" (one of FONTS), "band" (a dark band behind the words), "picture_box": {x, y, w, h} where the
    picture is fitted, "text_box": {x, y, size} the words' centre and height (all parts of the square, 0 to 1)}; or None (empty: the stream's background colour). Missing parts get defaults.
    """
    if not isinstance(raw, dict):
        return None
    if isinstance(raw.get("camera"), str) and CAMERA_KEY.match(raw["camera"]):
        return _camera_cell(raw)
    if not any(k in raw for k in ("background", "image", "slideshow", "text")):
        return None  # anything else (a logo or folder of before the stream folder) leaves the square empty
    least, most, default = SLIDE_SECONDS
    sec = raw.get("seconds")
    card = {
        "background": _color(raw.get("background"), None),
        "image": _named(raw.get("image")),
        "slideshow": _named(raw.get("slideshow")),
        "seconds": sec if type(sec) is int and least <= sec <= most else default,
        "text": raw["text"] if isinstance(raw.get("text"), str) else "",
        "color": _color(raw.get("color"), "#FFFFFF"),
        "font": raw.get("font") if raw.get("font") in FONTS else DEFAULT_FONT,
        "band": raw.get("band") is True,
        "picture_box": _picture_box(raw.get("picture_box")),
        "text_box": _text_box(raw.get("text_box"), raw.get("size"), raw.get("position")),
    }
    if card["slideshow"]:
        card["image"] = None
    return card


def _side(v) -> int | None:
    return v if type(v) is int and 1 <= v <= MAX_SIDE else None


def settings(db: Session) -> dict:
    """
    {destination, cols, rows, cells: [one per square, row by row, see _cell], cameras (the
    cameras' keys in the grid, square by square), show_status, layout: "grid" | "cycle", seconds_all, seconds_each,
    resolution, border_color: "#RRGGBB", background: the stream's colour "#RRGGBB", title, description, key_set}.
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
         resolution=None, border_color=None, background=None, cols=None, rows=None, cells=None,
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


# ------------------------------------------------------------------ the cameras, as ffmpeg reads them


@dataclass
class Source:
    """One camera in the stream: what's written under it, and how ffmpeg reads it."""

    printer_id: int
    label: str
    input_args: list[str]
    turn: list[str] = field(default_factory=list)  # ffmpeg filters that turn it the way Mainsail shows it


def _turn(cam: dict) -> list[str]:
    out = []
    rotation = int(cam.get("rotation") or 0) % 360
    if rotation == 90:
        out.append("transpose=1")
    elif rotation == 270:
        out.append("transpose=2")
    flip_h = bool(cam.get("flip_horizontal")) ^ (rotation == 180)
    flip_v = bool(cam.get("flip_vertical")) ^ (rotation == 180)
    if flip_h:
        out.append("hflip")
    if flip_v:
        out.append("vflip")
    return out


def input_args(printer: Printer, cam: dict) -> list[str]:
    """How ffmpeg reads this camera, or ValueError saying why it can't."""
    name = f"{printer.name}'s camera" if cam.get("name") in (None, "Camera") else f"{printer.name}'s {cam['name']} camera"
    if cam.get("service") == "farmhand-go2rtc":  # a Buddy3D: its RTSP stream, straight from the camera
        return ["-rtsp_transport", "tcp", "-i", go2rtc.rtsp_url(printer.camera_address)]
    stream = cam.get("stream_url")
    # an MJPEG stream; Mainsail's "adaptive" service shows snapshots in the browser, but its address is the same stream
    if stream and (cam.get("mjpeg") or cam.get("service") == "mjpegstreamer-adaptive" or "action=stream" in stream):
        return ["-f", "mpjpeg", "-i", stream]
    if stream and cam.get("service") == "webrtc-go2rtc":
        # go2rtc on the printer: the same camera over RTSP, on go2rtc's own RTSP port
        parts = urlsplit(stream)
        src = parse_qs(parts.query).get("src", [None])[0]
        if parts.hostname and src:
            return ["-rtsp_transport", "tcp", "-i", f"rtsp://{parts.hostname}:8554/{quote(src, safe='')}"]
    if stream and cam.get("service") == "webrtc-camerastreamer" and stream.rstrip("/").endswith("/webrtc"):
        # camera-streamer serves the same camera as MJPEG beside its WebRTC page
        return ["-f", "mpjpeg", "-i", stream.rstrip("/")[: -len("webrtc")] + "stream"]
    raise ValueError(
        f"{name} only plays in a browser (WebRTC), which Farmhand can't send to a stream. "
        "In Mainsail (Settings → Webcams) give it the MJPEG streamer service, or leave it out of the stream."
    )


def sources(db: Session, chosen: list[str]) -> list[Source]:
    """The chosen cameras, each asked of its printer now. ValueError says which one can't be streamed and why."""
    out = []
    asked: dict[int, dict] = {}
    for key in chosen:
        pid_text, cam_name = key.split(":", 1)
        printer = db.get(Printer, int(pid_text))
        if printer is None:
            raise ValueError("A chosen camera's printer is gone. Untick it and save.")
        if printer.id not in asked:
            asked[printer.id] = cameras.printer_cameras(printer)
        found = asked[printer.id]
        listed = found["webcams"]
        cam = next((c for c in listed if c.get("name") == cam_name), None)
        if cam is None:
            why = found.get("error") or "it isn't set up in Mainsail any more"
            raise ValueError(f"{printer.name}'s {cam_name} camera can't be reached: {why}")
        label = printer.name if len(listed) == 1 else f"{printer.name} · {cam_name}"
        out.append(Source(printer.id, label, input_args(printer, cam), _turn(cam)))
    return out


# ------------------------------------------------------------------ the ffmpeg command


def grid(n: int, width: int = WIDTH, height: int = HEIGHT) -> tuple[int, int, int, int]:
    """(columns, rows, square width, square height) of the near-square grid for n squares, sizes even."""
    cols, rows = auto_grid(n)
    return cols, rows, (width // cols) // 2 * 2, (height // rows) // 2 * 2


def windows(n: int, seconds_all: int, seconds_each: int) -> tuple[int, list[tuple[int, int]]]:
    """
    Taking turns: (the whole round in seconds, each camera's [from, to) within it). All the cameras come first, for
    seconds_all, then each camera on its own for seconds_each. With seconds_all 0 the first camera's turn starts it.
    """
    period = seconds_all + n * seconds_each
    return period, [(seconds_all + i * seconds_each, seconds_all + (i + 1) * seconds_each) for i in range(n)]


def _filter_path(path: str) -> str:
    """A file's path as an ffmpeg filter option: forward slashes, and its : and ' escaped."""
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _words(path: str, size: int | str, foot: int | str, border: int | str = 6, left: int | str = 10, own: dict | None = None) -> str:
    """The words under a camera; `own`: its square's choices (_camera_cell: words_color, words_font)."""
    own = own or {}
    color = (own.get("words_color") or "#FFFFFF").lstrip("#")
    return (f"drawtext=fontfile={_filter_path(font_file(own.get('words_font')))}:textfile={_filter_path(path)}:reload=1:expansion=none"
            f":fontsize={size}:fontcolor=0x{color}:box=1:boxcolor=black@0.6:boxborderw={border}:x={left}:y=h-th-{foot}")


# The words on a camera shown on its own, taking turns: written on the camera's own picture before it's enlarged, so
# sized to it (28 px on the 720-high stream, whatever the camera's size)
FULL_WORDS = {"size": "h/26", "foot": "h/30", "border": "h/120", "left": "w/128"}
TURNS_FOR = 24 * 3600  # the timetable of turns covers a day; ffmpeg then ends and is started again at once


def timetable(n: int, seconds_all: int, seconds_each: int, horizon: int = TURNS_FOR) -> str:
    """
    Taking turns, as ffmpeg's sendcmd reads it: at each turn, which view (0: all the cameras, 1: one on its own) and
    which camera. Covers `horizon` seconds of stream.
    """
    period, turns = windows(n, seconds_all, seconds_each)
    lines = []
    for r in range(math.ceil(horizon / period)):
        base = r * period
        if seconds_all:
            lines.append(f"{base} streamselect@view map 0;")
        for i, (start, _) in enumerate(turns):
            lines.append(f"{base + start} {'streamselect@view map 1, ' if seconds_all else ''}streamselect@pick map {i};")
    return "\n".join(lines) + "\n"


@dataclass
class Look:
    """
    How the picture is put together. cells: the grid's squares row by row, each ("camera", its place in srcs[, its square's own
    choices (_camera_cell) | just its background colour]), ("card",
    {background, pictures: [files] (none, one picture, or a slideshow's), seconds, words: its words' file | None, color,
    picture_box, text_box}) or None (empty), cols x rows of them (None: the cameras, in a grid just big enough). background:
    the stream's colour, behind everything. turns_file: the timetable
    of taking turns (timetable()), when the cameras take turns. The words
    under each camera (a file per camera; None: no words); taking turns ((seconds on the whole grid, on each camera), and
    the timetable's file; None: the grid all the time); the border's colour round each square; the resolution.
    """

    status_files: list[str] | None = None
    cycle: tuple[int, int] | None = None
    turns_file: str | None = None
    resolution: str = DEFAULT_RESOLUTION  # one of RESOLUTIONS
    border_color: str = DEFAULT_BORDER
    background: str = DEFAULT_BACKGROUND
    cols: int | None = None
    rows: int | None = None
    cells: list | None = None


def command(ffmpeg: str, srcs: list[Source], url: str, look: Look | None = None) -> list[str]:
    """
    The whole ffmpeg command: the grid's squares laid out, each camera turned as Mainsail shows it and fitted into its
    square with the printer and its print written along its foot; each card its colour, its picture (or slideshow,
    each picture over the first in its own seconds) fitted over it and its words over that; an empty square the stream's
    background colour; every square with a border round it; a silent sound track; sent as FLV to `url`.

    Taking turns works the way Monitor's enlarging does: only the camera on screen is made full size. Every camera's
    picture goes to a switch (streamselect "pick") that lets through only the one whose turn it is, and only that one
    is enlarged; a second switch ("view") chooses between it and the grid. The timetable (look.turns_file, see
    timetable()) moves both switches. It covers a day, so the command then ends (-t) and the stream starts it again.
    """
    look = look or Look()
    n = len(srcs)
    if look.cells is None:
        cols, rows = auto_grid(n)
        cells = [("camera", i) for i in range(n)] + [None] * (cols * rows - n)
    else:
        cols, rows, cells = look.cols, look.rows, list(look.cells)
    cycle = look.cycle if n > 1 else None
    need_grid = cycle is None or cycle[0] > 0
    width, height, kbps = RESOLUTIONS.get(look.resolution, RESOLUTIONS[DEFAULT_RESOLUTION])
    k = height / 720  # the words and borders grow with the picture
    px = lambda v: max(1, round(v * k))  # noqa: E731
    tw, th = (width // cols) // 2 * 2, (height // rows) // 2 * 2
    edge = px(BORDER_WIDTH)
    border = f"drawbox=x=0:y=0:w=iw:h=ih:color=0x{(look.border_color or DEFAULT_BORDER).lstrip('#')}:t={edge}"
    back = (look.background or DEFAULT_BACKGROUND).lstrip("#")
    full_size = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x{back},setsar=1"

    args = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin"]
    for s in srcs:
        args += ["-thread_queue_size", "64", *s.input_args]
    args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    extra = n + 1  # the next input's number: each picture shown is an input of its own, read once a second

    def picture(path: str) -> int:
        nonlocal args, extra
        args += ["-loop", "1", "-framerate", "1", "-i", path]
        extra += 1
        return extra - 1

    def card(c: int, cd: dict) -> str:
        """A card's square: its colour; its pictures fitted over it, each but the first only in its own seconds (each
        read and fitted once a second); its words over that (on a dark band when chosen)."""
        chain = [f"color=c=0x{(cd.get('background') or '#' + back).lstrip('#')}:s={tw}x{th}:r={FPS},setsar=1[c{c}b]"]
        shown = f"[c{c}b]"
        paths, seconds = cd.get("pictures") or [], cd.get("seconds") or SLIDE_SECONDS[2]
        period = len(paths) * seconds
        pb = _picture_box(cd.get("picture_box"))
        bw, bh = max(2, round(pb["w"] * tw)), max(2, round(pb["h"] * th))
        bx, by = round(pb["x"] * tw), round(pb["y"] * th)
        at = "(W-w)/2:(H-h)/2" if (bw, bh) == (tw, th) else f"{bx}+({bw}-w)/2:{by}+({bh}-h)/2"
        for j, path in enumerate(paths):
            chain.append(f"[{picture(path)}:v]scale={bw}:{bh}:force_original_aspect_ratio=decrease,setsar=1,fps={FPS}[c{c}i{j}]")
            when = "" if j == 0 else f":enable='gte(mod(t,{period}),{j * seconds})*lt(mod(t,{period}),{(j + 1) * seconds})'"
            chain.append(f"{shown}[c{c}i{j}]overlay={at}{when}[c{c}o{j}]")
            shown = f"[c{c}o{j}]"
        last = []
        if cd.get("words"):
            tb = _text_box(cd.get("text_box"), cd.get("size"), cd.get("position"))
            big = round(tb["size"] * th)
            band = f":box=1:boxcolor=black@0.5:boxborderw={max(px(4), big // 5)}" if cd.get("band") else ""
            last.append(f"drawtext=fontfile={_filter_path(font_file(cd.get('font')))}:textfile={_filter_path(cd['words'])}:reload=1:expansion=none"
                        f":fontsize={max(px(10), big)}:fontcolor=0x{(cd.get('color') or '#FFFFFF').lstrip('#')}:line_spacing={big // 4}"
                        f":x={round(tb['x'] * tw)}-text_w/2:y={round(tb['y'] * th)}-text_h/2{band}")
        last.append(border)
        chain.append(f"{shown}{','.join(last)}[c{c}]")
        return ";".join(chain)

    # the words under a camera, sized to its square (20 px in a quarter of a 720p picture)
    small = max(px(11), min(th // 18, tw // 32))
    # each camera's own square choices, by its place in srcs: ("camera", place, its cell or just its colour (tests))
    camera_own = {}
    for cell in cells or []:
        if cell and cell[0] == "camera" and len(cell) > 2 and cell[2]:
            camera_own[cell[1]] = cell[2] if isinstance(cell[2], dict) else {"background": cell[2]}
    foot, left = small * 2 // 3 + edge, small // 2 + edge
    parts = []
    for i, s in enumerate(srcs):
        base = ",".join([*s.turn, "setpts=PTS-STARTPTS", f"fps={FPS}", "setsar=1"])
        outs = ([f"[g{i}]"] if need_grid else []) + ([f"[s{i}]"] if cycle else [])
        parts.append(f"[{i}:v]{base}" + (f",split=2{''.join(outs)}" if len(outs) == 2 else outs[0]))
    if need_grid:
        tiles = []
        for c, cell in enumerate(cells):
            if cell and cell[0] == "camera":
                i = cell[1]
                mine = camera_own.get(i, {})
                colour = (mine.get("background") or "#" + back).lstrip("#")  # the square's own colour round it
                chain = [f"scale={tw}:{th}:force_original_aspect_ratio=decrease", f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=0x{colour}"]
                if look.status_files and mine.get("show_words", True):
                    if mine.get("words_size"):
                        size = max(px(8), round(mine["words_size"] * th))
                        chain.append(_words(look.status_files[i], size, size * 2 // 3 + edge, max(2, size // 3), size // 2 + edge, mine))
                    else:
                        chain.append(_words(look.status_files[i], small, foot, px(6), left, mine))
                parts.append(f"[g{i}]{','.join(chain)},{border}[c{c}]")
            elif cell and cell[0] == "card":
                parts.append(card(c, cell[1]))
            else:
                parts.append(f"color=c=0x{back}:s={tw}x{th}:r={FPS},setsar=1,{border}[c{c}]")
            tiles.append(f"[c{c}]")
        if len(tiles) == 1:
            parts.append(f"{tiles[0]}{full_size}[grid]")
        else:
            layout = "|".join(f"{(c % cols) * tw}_{(c // cols) * th}" for c in range(len(tiles)))
            parts.append(f"{''.join(tiles)}xstack=inputs={len(tiles)}:layout={layout}:fill=0x{back},{full_size}[grid]")
    if cycle is None:
        video = "[grid]"
    else:
        picked = ""
        for i in range(n):
            if look.status_files:
                mine = camera_own.get(i, {})
                if not mine.get("show_words", True):
                    picked += f"[s{i}]"
                    continue
                full = FULL_WORDS
                if mine.get("words_size"):  # its own size, as part of the camera's own picture's height
                    f = mine["words_size"]
                    full = {"size": f"h*{f}", "foot": f"h*{f * 2 / 3:.4f}", "border": f"h*{f / 3:.4f}", "left": f"h*{f / 2:.4f}"}
                parts.append(f"[s{i}]{_words(look.status_files[i], **full, own=mine)}[w{i}]")
                picked += f"[w{i}]"
            else:
                picked += f"[s{i}]"
        parts.append(f"{picked}streamselect@pick=inputs={n}:map=0,{full_size}[full]")
        parts.append(f"[grid][full]streamselect@view=inputs=2:map=0[turns]" if need_grid else "[full]null[turns]")
        video = "[turns]"
    if look.turns_file:  # the timetable moves the switches of taking turns
        parts.append(f"{video}sendcmd=f={_filter_path(look.turns_file)}[timed]")
        video = "[timed]"
    args += ["-filter_complex", ";".join(parts), "-map", video, "-map", f"{n}:a"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-r", str(FPS),
             "-g", str(FPS * 2), "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k",
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100"]
    if look.turns_file:
        args += ["-t", str(TURNS_FOR)]
    args += ["-f", "flv", url]
    return args


def status_line(label: str, p: dict) -> str:
    """What's written under a camera: "VT 1190 · Printing 42% · benchy.gcode", or "VT 1190 · Idle"."""
    if p.get("state"):
        pct = p.get("progress")
        line = f"{label} · {'Paused' if p['state'] == 'paused' else 'Printing'}"
        if isinstance(pct, (int, float)):
            line += f" {round(pct)}%"
        if p.get("file"):
            line += f" · {os.path.basename(str(p['file']))[:60]}"
        return line
    return f"{label} · Idle"


# ------------------------------------------------------------------ the stream itself


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def popen(args: list[str]):
    """ffmpeg started (tests swap this for a stand-in)."""
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")


class Stream:
    """The one live stream: started with go_live, ended with stop. Its threads keep ffmpeg running, the words on the
    video current, and set the YouTube title once the broadcast is there, while it's meant to be live."""

    def __init__(self):
        self._lock = threading.Lock()
        self._wanted = threading.Event()
        self._proc = None
        self._said: collections.deque[str] = collections.deque(maxlen=KEPT_LINES)
        self._error: str | None = None
        self._started_at: str | None = None
        self._destination: str | None = None
        self._labels: list[str] = []
        self._key = ""
        self._dir: str | None = None
        self._generation = 0
        self._title: dict | None = None  # setting the YouTube title: {state: "waiting" | "done" | "failed", message}

    # what the page shows
    def status(self) -> dict:
        with self._lock:
            proc = self._proc
            on_air = bool(proc is not None and proc.poll() is None)
            return {
                "live": self._wanted.is_set(),
                "on_air": on_air and self._wanted.is_set(),
                "started_at": self._started_at,
                "destination": self._destination,
                "cameras": list(self._labels),
                "error": self._error,
                "title": dict(self._title) if self._title else None,
            }

    def go_live(self, db: Session, session_factory) -> dict:
        """Start (or start again, with what's chosen now). ValueError says why it can't."""
        chosen = settings(db)
        key = app_settings.get(db, STREAM_KEY_KEY)
        where = DESTINATIONS[chosen["destination"]]
        if not key:
            raise ValueError(f"Add your {where['label']} stream key first.")
        if not chosen["cameras"]:
            raise ValueError("Put at least one camera in the grid.")
        ffmpeg = ffmpeg_path()
        if not ffmpeg:
            raise ValueError("ffmpeg isn't installed where Farmhand's API runs, so it can't stream. Rebuild with the latest update.sh.")
        srcs = sources(db, chosen["cameras"])
        cards = {c: cell for c, cell in enumerate(chosen["cells"]) if cell and "camera" not in cell}
        pictures = _card_pictures(db, cards)
        wants_title = chosen["destination"] == "youtube" and (chosen["title"] or chosen["description"])
        creds = youtube_live.credentials(db) if wants_title else None
        self.stop()
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._dir = folder = tempfile.mkdtemp(prefix="farmhand-stream-")
            files = [os.path.join(self._dir, f"{i}.txt") for i in range(len(srcs))] if chosen["show_status"] else None
            for i, s in enumerate(srcs):
                if files:
                    _write_atomically(files[i], s.label)
            self._key = key
            self._destination = chosen["destination"]
            self._labels = [s.label for s in srcs]
            self._error = None
            self._said.clear()
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._title = None
            if wants_title:
                self._title = ({"state": "waiting", "message": "Setting the YouTube title once the broadcast starts…"} if creds
                               else {"state": "failed", "message": "Sign in to YouTube (below) for Farmhand to set the title and description."})
            self._wanted.set()
        cycle = (chosen["seconds_all"], chosen["seconds_each"]) if chosen["layout"] == "cycle" and len(srcs) > 1 else None
        # each card's words, as a file ffmpeg reads (its pictures are read where they are, in the stream folder)
        text_paths = {}
        for c, cell in cards.items():
            if cell.get("text"):
                text_paths[c] = os.path.join(folder, f"text-{c}.txt")
                _write_atomically(text_paths[c], cell["text"])
        timed = timetable(len(srcs), *cycle) if cycle else ""
        turns_file = None
        if timed:
            turns_file = os.path.join(folder, "turns.txt")
            with open(turns_file, "w", encoding="utf-8") as f:
                f.write(timed)
        place = {k: i for i, k in enumerate(chosen["cameras"])}
        def square(c: int, cell: dict | None):
            if not cell:
                return None
            if "camera" in cell:
                return ("camera", place[cell["camera"]], cell)
            return ("card", {**cell, "pictures": pictures.get(c, []), "words": text_paths.get(c)})

        cells = [square(c, cell) for c, cell in enumerate(chosen["cells"])]
        args = command(ffmpeg, srcs, where["url"] + key, Look(
            status_files=files, cycle=cycle, turns_file=turns_file,
            resolution=chosen["resolution"], border_color=chosen["border_color"], background=chosen["background"], cols=chosen["cols"],
            rows=chosen["rows"], cells=cells,
        ))
        threading.Thread(target=self._keep_running, args=(gen, args), name="stream", daemon=True).start()
        if files:
            threading.Thread(target=self._keep_words_current, args=(gen, srcs, files, session_factory), name="stream-words", daemon=True).start()
        if wants_title and creds:
            threading.Thread(target=self._set_title, args=(gen, creds, chosen["title"], chosen["description"]), name="stream-title", daemon=True).start()
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._wanted.clear()
            self._generation += 1
            proc, self._proc = self._proc, None
            folder, self._dir = self._dir, None
            self._started_at = None
            self._title = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001 - one that won't end is killed
                proc.kill()
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        return self.status()

    def title_set(self, outcome: dict) -> None:
        """What setting the YouTube title came to, when done from the page while live."""
        with self._lock:
            if self._wanted.is_set():
                self._title = outcome

    def _current(self, gen: int) -> bool:
        return self._wanted.is_set() and self._generation == gen

    def _hide_key(self, text: str) -> str:
        return text.replace(self._key, "<stream key>") if self._key else text

    def _keep_running(self, gen: int, args: list[str]) -> None:
        while self._current(gen):
            try:
                proc = popen(args)
            except OSError as e:
                with self._lock:
                    self._error = f"ffmpeg couldn't be started: {e.strerror or e}"
                    self._wanted.clear()
                return
            with self._lock:
                if not self._current(gen):
                    proc.terminate()
                    return
                self._proc = proc
            started = time.monotonic()
            for line in proc.stderr or []:
                line = self._hide_key(line.strip())
                if line:
                    self._said.append(line)
            code = proc.wait()
            if not self._current(gen):
                return
            if code == 0 and "-t" in args and time.monotonic() - started >= TURNS_FOR - 60:
                continue  # the day's timetable of turns is done: started again at once, from the top
            with self._lock:
                last = next((l for l in reversed(self._said) if l), None)
                self._error = f"The stream stopped (ffmpeg exit {code}): {last or 'no reason given'}. Trying again in {RETRY_SECONDS} s."
                if time.monotonic() - started > 60:
                    self._said.clear()
            if not _sleep_unless(self, gen, RETRY_SECONDS):
                return

    def _keep_words_current(self, gen: int, srcs: list[Source], files: list[str], session_factory) -> None:
        while self._current(gen):
            try:
                with session_factory() as db:
                    by_printer: dict[int, dict] = {}
                    for s in srcs:
                        if s.printer_id not in by_printer:
                            printer = db.get(Printer, s.printer_id)
                            by_printer[s.printer_id] = print_progress.progress(db, printer) if printer else {}
                    for s, f in zip(srcs, files):
                        if not self._current(gen):
                            return
                        _write_atomically(f, status_line(s.label, by_printer.get(s.printer_id) or {}))
            except Exception:  # noqa: BLE001 - the words stay as they were until the next time round
                pass
            if not _sleep_unless(self, gen, STATUS_EVERY):
                return

    def _set_title(self, gen: int, creds: dict, title: str, description: str) -> None:
        """YouTube makes the broadcast a little after the stream reaches it: tried every TITLE_EVERY seconds until then."""
        last = None
        for _ in range(TITLE_TRIES):
            if not _sleep_unless(self, gen, TITLE_EVERY):
                return
            try:
                done = youtube_live.set_broadcast_text(creds, title, description)
            except youtube_live.YouTubeError as e:
                last = str(e)
                if not e.retry:
                    break
                continue
            with self._lock:
                if self._current(gen):
                    self._title = {"state": "done", "message": f"Title and description set on “{done['title']}”."}
            return
        with self._lock:
            if self._current(gen):
                self._title = {"state": "failed", "message": f"The YouTube title wasn't set: {last or 'no broadcast found'}"}


def _card_pictures(db: Session, cards) -> dict:
    """Each card's pictures, as files in the stream folder: {square: [paths]} (its picture, or its slideshow's). One not
    there (or a stream folder that isn't available) shows just the card's colour and words."""
    out = {}
    for c, cell in (cards.items() if isinstance(cards, dict) else []):
        try:
            if cell.get("slideshow"):
                out[c] = [str(p) for p in stream_media.slideshow_paths(db, cell["slideshow"])]
            elif cell.get("image"):
                out[c] = [str(stream_media.picture_path(db, None, cell["image"]))]
        except (NotFound, ValueError, storage.StorageUnavailableError, OSError):
            out[c] = []
    return out


def _sleep_unless(stream: Stream, gen: int, seconds: float) -> bool:
    """Wait `seconds`, in short steps; False as soon as the stream is stopped or started again."""
    end = time.monotonic() + seconds
    while stream._current(gen) and (left := end - time.monotonic()) > 0:
        time.sleep(min(0.5, left))
    return stream._current(gen)


def _write_atomically(path: str, text: str) -> None:
    """drawtext reads the file again every frame: it's swapped in whole, never seen half written."""
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


stream = Stream()


def page(db: Session) -> dict:
    """Everything the Stream page shows: {settings, media (the stream folder's pictures and slideshows, stream_media.media),
    status, destinations, resolutions, fonts (what a square's words can be written in), youtube}."""
    return {
        "settings": settings(db),
        "media": stream_media.media(db),
        "status": stream.status(),
        "destinations": [{"key": k, "label": v["label"]} for k, v in DESTINATIONS.items()],
        "resolutions": [{"key": k, "label": RESOLUTION_LABELS[k]} for k in RESOLUTIONS],
        "fonts": [{"key": k, "label": v[0], "generic": v[2]} for k, v in FONTS.items()],
        "youtube": youtube_live.account(db),
    }
