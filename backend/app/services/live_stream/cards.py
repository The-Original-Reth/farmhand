"""
A card's square in the ffmpeg command: its colour; its picture, or its slideshow's pictures each in its own seconds;
and its words over that.
"""
from __future__ import annotations

import os

from typing import Callable

from .. import stream_media
from .constants import DEFAULT_TEXT_COLOR, FPS
from .fonts import font_file
from .frame import Frame
from .squares import SLIDE_SECONDS, _picture_box, _text_box
from .words import filter_path


def card_square(c: int, cd: dict, frame: Frame, picture: Callable[[str], int], clock: float = 0,
                font: str | None = None, color: str | None = None) -> str:
    """
    Square `c`'s filters, ending in [c{c}]: its colour; its pictures fitted over it (`picture(path)`: the input that
    reads it, once a second), each but the first only in its own seconds (with a blank screen in the slideshow, the
    first too); its words over that (on a dark band when chosen); its border. `clock`: the time of day at the stream's
    start, which the slideshow counts from; `font`, `color`: the stream's words', unless the card has its own.
    """
    tw, th = frame.tw, frame.th
    chain = [f"{frame.plain((cd.get('background') or '#' + frame.back).lstrip('#'))}[c{c}b]"]
    shown = f"[c{c}b]"
    paths, seconds = cd.get("pictures") or [], cd.get("seconds") or SLIDE_SECONDS[2]
    period = len(paths) * seconds
    window = _windows(period, seconds, clock)

    blanks = any(stream_media.is_blank(p) for p in paths)  # then even the first picture shows only in its turn
    for j, path in enumerate(paths):
        if stream_media.is_blank(path):  # a blank screen: the square's colour (and its words) in its turn
            continue
        bw, bh, at = _fit(cd, path, frame)
        chain.append(f"[{picture(path)}:v]scale={bw}:{bh}:force_original_aspect_ratio=decrease,setsar=1,fps={FPS}[c{c}i{j}]")
        when = "" if j == 0 and not blanks else f":enable='{window(j)}'"
        chain.append(f"{shown}[c{c}i{j}]overlay={at}{when}[c{c}o{j}]")
        shown = f"[c{c}o{j}]"

    def words(file: str, tb: dict, enable: str = "") -> str:
        big = round(tb["size"] * th)
        band = f":box=1:boxcolor=black@0.5:boxborderw={max(frame.px(4), big // 5)}" if cd.get("band") else ""
        return (f"drawtext=fontfile={filter_path(font_file(cd.get('font') or font))}:textfile={filter_path(file)}:reload=1:expansion=none"
                f":fontsize={max(frame.px(10), big)}:fontcolor=0x{(cd.get('color') or color or DEFAULT_TEXT_COLOR).lstrip('#')}:line_spacing={big // 4}"
                f":x={round(tb['x'] * tw)}-text_w/2:y={round(tb['y'] * th)}-text_h/2{band}{enable}")

    last = []
    own = cd.get("picture_words") or {}  # a slideshow's pictures' own words, by their place in it
    if cd.get("words"):
        tb = _text_box(cd.get("text_box"), cd.get("size"), cd.get("position"))
        rest = [j for j in range(len(paths)) if j not in own]
        if not own:
            last.append(words(cd["words"], tb))
        elif rest:  # the card's words over the pictures without words of their own
            last.append(words(cd["words"], tb, f":enable='{'+'.join(window(j) for j in rest)}'"))
    for j, cap in sorted(own.items()):
        last.append(words(cap["words"], _text_box(cap.get("text_box")), f":enable='{window(j)}'" if len(paths) > 1 else ""))
    last.append(frame.border)
    chain.append(f"{shown}{','.join(last)}[c{c}]")
    return ";".join(chain)


def _windows(period: int, seconds: int, clock: float) -> Callable[[int], str]:
    """While picture j of a slideshow is on show, as an ffmpeg expression: its time counted from midnight 1970 (`clock`
    at the stream's start), as the page counts it."""
    lag = round(clock % period, 3) if period else 0
    t = f"t+{lag:g}" if lag else "t"
    return lambda j: f"gte(mod({t},{period}),{j * seconds})*lt(mod({t},{period}),{(j + 1) * seconds})"


def _fit(cd: dict, path: str, frame: Frame) -> tuple[int, int, str]:
    """A picture's size and where it goes in its square: (width, height, overlay's x:y). Its box is a part of the
    square inside its border, so the border never covers the picture; a slideshow's picture resized or moved on its own
    has its own box (picture_boxes, by its file's name)."""
    edge = frame.edge
    iw, ih = frame.tw - 2 * edge, frame.th - 2 * edge
    pb = _picture_box((cd.get("picture_boxes") or {}).get(os.path.basename(path)) or cd.get("picture_box"))
    bw, bh = max(2, round(pb["w"] * iw)), max(2, round(pb["h"] * ih))
    bx, by = edge + round(pb["x"] * iw), edge + round(pb["y"] * ih)
    return bw, bh, "(W-w)/2:(H-h)/2" if (bw, bh) == (iw, ih) else f"{bx}+({bw}-w)/2:{by}+({bh}-h)/2"
