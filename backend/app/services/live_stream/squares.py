"""
The grid's squares as kept: a camera (and its own choices), a card (its colour, picture or slideshow, and words, and where they are), or empty. Anything else sent is made sense of or left empty.
"""
from __future__ import annotations

import math
import re

from .constants import CAMERA_KEY, COLOR
from .fonts import FONTS

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
    of the square's, 0.02 to 0.3; none: sized to the square), "words_color" and "words_font" (none: the stream's own, settings()'s color and font).
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
    if color:
        out["words_color"] = color
    if raw.get("words_font") in FONTS:
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
        "color": _color(raw.get("color"), None),  # None: the stream's
        "font": raw.get("font") if raw.get("font") in FONTS else None,  # None: the stream's
        "band": raw.get("band") is True,
        "picture_box": _picture_box(raw.get("picture_box")),
        "text_box": _text_box(raw.get("text_box"), raw.get("size"), raw.get("position")),
    }
    if card["slideshow"]:
        card["image"] = None
    return card
