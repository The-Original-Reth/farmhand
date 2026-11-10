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
CARD_KEYS = ("background", "image", "slideshow", "seconds", "text", "color", "font", "band", "picture_box", "text_box", "captions", "picture_boxes",
             "layers", "slide_layers")
MAX_CAPTIONS = 500  # a slideshow's pictures with words of their own
MAX_LAYERS = 12  # more pictures and pieces of text on a card, or on one of a slideshow's screens


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


def _captions(raw) -> dict:
    """A slideshow's pictures' own words: {picture's file name: {"text", "text_box"}}, those with words only (the text as
    written; check_cells trims it and says when it's too long)."""
    out = {}
    if isinstance(raw, dict):
        for name, cap in raw.items():
            if len(out) >= MAX_CAPTIONS:
                break
            if _named(name) and isinstance(cap, dict) and isinstance(cap.get("text"), str) and cap["text"].strip():
                out[name] = {"text": cap["text"], "text_box": _text_box(cap.get("text_box"))}
    return out


def _picture_boxes(raw) -> dict:
    """A slideshow's pictures' own size and place, {picture's file name: picture_box}, each resized or moved on its own
    (the others keep the card's picture_box)."""
    out = {}
    if isinstance(raw, dict):
        for name, box in raw.items():
            if len(out) >= MAX_CAPTIONS:
                break
            if _named(name) and isinstance(box, dict):
                out[name] = _picture_box(box)
    return out


def _layer(raw) -> dict | None:
    """One more picture or piece of text on a card, placed on its own: {"type": "picture", "image": a picture's file name
    in the stream folder's images (None: not chosen yet), "box": {x, y, w, h}} | {"type": "text", "text", "box": {x, y,
    size}, "font" (None: the stream's), "color" (None: the stream's), "band"}. The text as written (check_cells trims it
    and says when it's too long)."""
    if not isinstance(raw, dict):
        return None
    if raw.get("type") == "picture":
        return {"type": "picture", "image": _named(raw.get("image")), "box": _picture_box(raw.get("box"))}
    if raw.get("type") == "text" and isinstance(raw.get("text"), str):
        return {"type": "text", "text": raw["text"], "box": _text_box(raw.get("box")),
                "font": raw.get("font") if raw.get("font") in FONTS else None, "color": _color(raw.get("color"), None), "band": raw.get("band") is True}
    return None


def _layers(raw) -> list[dict]:
    """A card's (or a slideshow screen's) more pictures and pieces of text, in the order they're drawn (anything else
    sent is left out)."""
    return [x for x in (_layer(r) for r in raw) if x] if isinstance(raw, list) else []


def _slide_layers(raw) -> dict:
    """A slideshow's screens' own more pictures and pieces of text, {a picture's file name, or "blank:N": [layers]},
    those that have some."""
    out = {}
    if isinstance(raw, dict):
        for name, layers in raw.items():
            if len(out) >= MAX_CAPTIONS:
                break
            got = _layers(layers)
            if _named(name) and got:
                out[name] = got
    return out


def _cell(raw) -> dict | None:
    """
    A square as kept: {"camera": "printer id:camera name"}; a card, {"background": its colour (None: the stream's),
    "image": a picture's file name in the stream folder's images | None, "slideshow": a slideshow's folder name | None,
    "seconds": each slideshow picture's, "text": words over it ("" none), "color", "font" (one of FONTS), "band" (a dark band behind the words), "picture_box": {x, y, w, h} where the
    picture is fitted, "text_box": {x, y, size} the words' centre and height (all parts of the square, 0 to 1), "picture_boxes": a
    slideshow's pictures' own size and place, {picture's name: picture_box}, "captions": a
    slideshow's pictures' own words, {picture's name: {text, text_box}}, shown instead of "text" while that picture is,
    "layers": more pictures and pieces of text over it, each placed on its own (see _layer), "slide_layers": a
    slideshow's screens' own, {picture's name or "blank:N": [layers]}, shown while that screen is}; or
    None (empty: the stream's background colour). Missing parts get defaults.
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
    card["captions"] = _captions(raw.get("captions")) if card["slideshow"] else {}
    card["picture_boxes"] = _picture_boxes(raw.get("picture_boxes")) if card["slideshow"] else {}
    card["layers"] = [] if card["slideshow"] else _layers(raw.get("layers"))
    card["slide_layers"] = _slide_layers(raw.get("slide_layers")) if card["slideshow"] else {}
    if card["slideshow"]:
        card["image"] = None
    return card
