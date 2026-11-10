"""
A card's square in the ffmpeg command: its colour; its picture, or its slideshow's pictures each in its own seconds;
its more pictures and pieces of text (a slideshow screen's in that screen's seconds); and its words over that.
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
                font: str | None = None, color: str | None = None, slideshow: Callable[[list, int], int] | None = None) -> str:
    """
    Square `c`'s filters, ending in [c{c}]: its colour; its pictures fitted over it (`picture(path)`: the input that
    reads it, once a second), each but the first only in its own seconds (with a blank screen in the slideshow, the
    first too); its more pictures and pieces of text (cd["layers"], always; cd["screen_layers"], {place in the
    slideshow: [...]}, each in its screen's seconds), in their order, each placed on its own (staging.staged_layers);
    its words over that (on a dark band when chosen); its border. `clock`: the time of day at the stream's start, which
    the slideshow counts from; `font`, `color`: the stream's words', unless the card (or a piece of text) has its own.

    A slideshow made ready at going live (cd["frames"]: each screen as one finished picture, slides.compose) is one
    input instead, `slideshow(frames, seconds)` its number: its pictures and its screens' more pictures are already on
    it, so only the words are drawn here.
    """
    tw, th = frame.tw, frame.th
    chain = [f"{frame.plain((cd.get('background') or '#' + frame.back).lstrip('#'))}[c{c}b]"]
    shown = f"[c{c}b]"
    paths, seconds = cd.get("pictures") or [], cd.get("seconds") or SLIDE_SECONDS[2]
    period = len(paths) * seconds
    window = _windows(period, seconds, clock)

    blanks = any(stream_media.is_blank(p) for p in paths)  # then even the first picture shows only in its turn
    if cd.get("frames") and slideshow:  # one input, a finished picture at a time, on the stream's own clock
        chain = [f"[{slideshow(cd['frames'], seconds)}:v]setpts=PTS-STARTPTS,fps={FPS},setsar=1[c{c}f]"]
        shown, paths_drawn = f"[c{c}f]", []
    else:
        paths_drawn = paths
    for j, path in enumerate(paths_drawn):
        if stream_media.is_blank(path):  # a blank screen: the square's colour (and its words) in its turn
            continue
        bw, bh, at = _fit(cd, path, frame)
        chain.append(f"[{picture(path)}:v]scale={bw}:{bh}:force_original_aspect_ratio=decrease,setsar=1,fps={FPS}[c{c}i{j}]")
        when = "" if j == 0 and not blanks else f":enable='{window(j)}'"
        chain.append(f"{shown}[c{c}i{j}]overlay={at}{when}[c{c}o{j}]")
        shown = f"[c{c}o{j}]"

    def words(file: str, tb: dict, enable: str = "", style: dict | None = None) -> str:
        """drawtext for words in `file`, centred on tb's spot; `style`: a piece of text's own {font, color, band} (None:
        the card's words', each falling back on the stream's)."""
        own = style if style is not None else {"font": cd.get("font"), "color": cd.get("color"), "band": cd.get("band")}
        big = round(tb["size"] * th)
        band = f":box=1:boxcolor=black@0.5:boxborderw={max(frame.px(4), big // 5)}" if own.get("band") else ""
        return (f"drawtext=fontfile={filter_path(font_file(own.get('font') or font))}:textfile={filter_path(file)}:reload=1:expansion=none"
                f":fontsize={max(frame.px(10), big)}:fontcolor=0x{(own.get('color') or color or DEFAULT_TEXT_COLOR).lstrip('#')}:line_spacing={big // 4}"
                f":x={round(tb['x'] * tw)}-text_w/2:y={round(tb['y'] * th)}-text_h/2{band}{enable}")

    # its more pictures and pieces of text, in their order: the card's own, then each slideshow screen's in its turn
    steps = [(layer, "") for layer in cd.get("layers") or []]
    for j, layers in sorted((cd.get("screen_layers") or {}).items()):
        steps += [(layer, f":enable='{window(j)}'" if len(paths) > 1 else "") for layer in layers]
    for k, (layer, when) in enumerate(steps):
        if layer["type"] == "picture":
            bw, bh, at = _box_fit(layer.get("box"), frame)
            chain.append(f"[{picture(layer['path'])}:v]scale={bw}:{bh}:force_original_aspect_ratio=decrease,setsar=1,fps={FPS}[c{c}L{k}]")
            chain.append(f"{shown}[c{c}L{k}]overlay={at}{when}[c{c}l{k}]")
        else:
            chain.append(f"{shown}{words(layer['words'], _text_box(layer.get('box')), when, layer)}[c{c}l{k}]")
        shown = f"[c{c}l{k}]"

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


def _box_fit(box: dict | None, frame: Frame) -> tuple[int, int, str]:
    """A picture placed on its own (one of a card's more pictures): its size and where it goes, (width, height,
    overlay's x:y), fitted into its box (a part of the square inside its border), keeping its shape, in the box's middle."""
    edge = frame.edge
    iw, ih = frame.tw - 2 * edge, frame.th - 2 * edge
    pb = _picture_box(box)
    bw, bh = max(2, round(pb["w"] * iw)), max(2, round(pb["h"] * ih))
    bx, by = edge + round(pb["x"] * iw), edge + round(pb["y"] * ih)
    return bw, bh, f"{bx}+({bw}-w)/2:{by}+({bh}-h)/2"


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
