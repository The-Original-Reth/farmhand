"""
A slideshow made ready for the stream, once, at going live: each of its screens put together as one finished picture,
the square's size (its colour, its picture fitted in its box, and the screen's more pictures, each in its own box), and
the list ffmpeg reads them from, each shown for its seconds.

ffmpeg then reads the whole slideshow as one input, a picture at a time. Giving it each picture as an input of its own
made it read, fit and lay out every one of them fifteen times a second, on show or not: a slideshow of a hundred logos
filled the container's memory and the stream fell behind. This way a slideshow costs the same with three pictures as
with three hundred. The words on it (the card's, and each screen's own) stay drawtext, each in its screen's seconds.
"""
from __future__ import annotations

import hashlib
import json
import os

from PIL import Image

from .. import stream_media
from .frame import Frame
from .squares import _picture_box

LIST_FOR = 24 * 3600  # the list covers a day (as the timetable of turns does); ffmpeg then starts again


def _place(box, frame: Frame, whole_if_full: bool) -> tuple[int, int, int, int, bool]:
    """A box (a part of the square inside its border) in px: (width, height, left, top, centred on the whole square).
    A card's own picture filling its box entirely is centred on the whole square, as the stream has always placed it."""
    edge = frame.edge
    iw, ih = frame.tw - 2 * edge, frame.th - 2 * edge
    pb = _picture_box(box)
    bw, bh = max(2, round(pb["w"] * iw)), max(2, round(pb["h"] * ih))
    bx, by = edge + round(pb["x"] * iw), edge + round(pb["y"] * ih)
    return bw, bh, bx, by, whole_if_full and (bw, bh) == (iw, ih)


def _paste(canvas: Image.Image, path: str, box, frame: Frame, whole_if_full: bool = False) -> None:
    """A picture fitted into its box, keeping its shape (larger or smaller, as ffmpeg's force_original_aspect_ratio=
    decrease does), in the box's middle. One that can't be read is left off (its screen shows its colour)."""
    try:
        with Image.open(path) as img:
            img = img.convert("RGBA")
    except Exception:  # noqa: BLE001 - not a picture Pillow can read, or gone: the screen without it
        return
    bw, bh, bx, by, whole = _place(box, frame, whole_if_full)
    k = min(bw / img.width, bh / img.height)
    w, h = max(1, round(img.width * k)), max(1, round(img.height * k))
    img = img.resize((w, h), Image.LANCZOS)
    x = (frame.tw - w) // 2 if whole else bx + (bw - w) // 2
    y = (frame.th - h) // 2 if whole else by + (bh - h) // 2
    canvas.alpha_composite(img, (x, y))


def _made_from(*parts) -> str:
    """A name for a finished screen from everything that makes it (its pictures' contents by their size and time too),
    so one put together before (by an earlier layout this time live) is used again instead of made again."""
    def stamp(p):
        try:
            st = os.stat(p)
            return [os.path.basename(p), st.st_size, st.st_mtime_ns]
        except (OSError, TypeError):
            return [str(p)]
    return hashlib.sha1(json.dumps([stamp(p) if isinstance(p, str) else p for p in parts], sort_keys=True, default=str).encode()).hexdigest()


def compose(cd: dict, paths: list[str], screen_pictures: dict[int, list[dict]], frame: Frame, folder: str, cache: str | None = None) -> list[str]:
    """Each screen of a slideshow as one finished picture in `folder` (made): its colour (the card's, or the stream's),
    its picture in its box (the card's picture_box, or the picture's own picture_boxes; none on a blank screen) and its
    more pictures (`screen_pictures`, {place in the slideshow: [{"path", "box"}]}). The pictures' paths, in order. With
    `cache` (a folder kept while live), each screen is kept there by what makes it, and one already there is used again:
    a burst of layout changes doesn't put the same hundred screens together each time."""
    os.makedirs(cache or folder, exist_ok=True)
    colour = "#" + (cd.get("background") or "#" + frame.back).lstrip("#")
    out = []
    for j, path in enumerate(paths):
        box = None if stream_media.is_blank(path) else (cd.get("picture_boxes") or {}).get(os.path.basename(path)) or cd.get("picture_box")
        layers = [[layer["path"], layer.get("box")] for layer in screen_pictures.get(j, [])]
        if cache:
            to = os.path.join(cache, _made_from(frame.tw, frame.th, frame.edge, colour, path, box, *layers) + ".png")
            if os.path.exists(to):
                out.append(to)
                continue
        else:
            to = os.path.join(folder, f"{j:04d}.png")
        canvas = Image.new("RGBA", (frame.tw, frame.th), colour)
        if not stream_media.is_blank(path):
            _paste(canvas, path, box, frame, whole_if_full=True)
        for layer in screen_pictures.get(j, []):
            _paste(canvas, layer["path"], layer.get("box"), frame)
        tmp = to + ".new.png"
        canvas.convert("RGB").save(tmp, compress_level=1)
        os.replace(tmp, to)  # (whole or not at all: another layout may be reading it)
        out.append(to)
    return out


def playlist(frames: list[str], seconds: int, clock: float, path: str, horizon: int = LIST_FOR) -> str:
    """The slideshow as ffmpeg's concat reads it, written to `path`: its screens in order, round and round, each for its
    seconds, for `horizon` seconds. It starts on the screen the time of day (`clock`) says, for what's left of its
    seconds: the rounds count from midnight 1970, as the page counts them, so the stream shows the page's screen."""
    period = len(frames) * seconds
    phase = clock % period if period else 0
    j = int(phase // seconds) if period else 0
    left = round(seconds - (phase % seconds), 3) if period else seconds
    lines, total = ["ffconcat version 1.0"], 0.0
    quoted = [f.replace("'", "'\\''") for f in frames]
    while total < horizon + seconds:
        lines += [f"file '{quoted[j]}'", f"duration {left:g}"]
        total += left
        j, left = (j + 1) % len(frames), seconds
    lines.append(f"file '{quoted[(j - 1) % len(frames)]}'")  # (concat holds the last picture for its duration only when it's listed again)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path

