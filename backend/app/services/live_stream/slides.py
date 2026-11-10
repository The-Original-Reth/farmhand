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


def compose(cd: dict, paths: list[str], screen_pictures: dict[int, list[dict]], frame: Frame, folder: str) -> list[str]:
    """Each screen of a slideshow as one finished picture in `folder` (made): its colour (the card's, or the stream's),
    its picture in its box (the card's picture_box, or the picture's own picture_boxes; none on a blank screen) and its
    more pictures (`screen_pictures`, {place in the slideshow: [{"path", "box"}]}). The pictures' paths, in order."""
    os.makedirs(folder, exist_ok=True)
    colour = "#" + (cd.get("background") or "#" + frame.back).lstrip("#")
    out = []
    for j, path in enumerate(paths):
        canvas = Image.new("RGBA", (frame.tw, frame.th), colour)
        if not stream_media.is_blank(path):
            box = (cd.get("picture_boxes") or {}).get(os.path.basename(path)) or cd.get("picture_box")
            _paste(canvas, path, box, frame, whole_if_full=True)
        for layer in screen_pictures.get(j, []):
            _paste(canvas, layer["path"], layer.get("box"), frame)
        to = os.path.join(folder, f"{j:04d}.png")
        canvas.convert("RGB").save(to, compress_level=1)
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

