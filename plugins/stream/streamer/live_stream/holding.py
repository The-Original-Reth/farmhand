"""
The holding screen: what YouTube is shown right after the plugin's own restart (a new image, a reboot), while the delay
fills again behind it. Without it YouTube would get no video for the restart and the whole delay, and with auto-stop on
it ends a broadcast left that long without any; with it the broadcast carries on, and once the delay is held YouTube is
switched to the live picture (buffer.Buffer.fill_from), the whole delay in place.

It's one picture, drawn here with Pillow at the stream's size: its colour, its picture (from the stream folder's images)
above its words, or its words alone in the middle, each line centred. A small ffmpeg loops it at the live picture's
frame rate, with the stream's music (or its silence), compressed exactly as the live picture is, so the sender passes
both on alike.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from .constants import FPS
from .encoders import compress_args
from .lettering import draw_centred

# where things go, as parts of the picture (the page's preview draws it the same way)
PICTURE_BOX = (0.1, 0.08, 0.8, 0.56)  # x, y, w, h: the picture fitted inside, in the middle
WORDS_UNDER = 0.79  # the words' middle, under a picture...
WORDS_ALONE = 0.5  # ...or with none
WORDS_SIZE = 0.09  # their size, as part of the height


def look(holding: dict, chosen: dict) -> dict:
    """The holding screen's colours and font, the stream's own where it has none of its own."""
    return {"background": holding.get("background") or chosen["background"], "color": holding.get("color") or chosen["color"],
            "font": holding.get("font") or chosen["font"]}


def draw(path: str, width: int, height: int, text: str, background: str, color: str, font_path: str,
         picture_path: str | None = None) -> None:
    """The holding screen as a PNG at `path`: `background`, the picture (if any, and readable) fitted in PICTURE_BOX,
    and `text` centred under it (or in the middle), each line centred, in `color` and the font at `font_path`."""
    canvas = Image.new("RGB", (width, height), "#" + background.lstrip("#"))
    if picture_path:
        try:
            with Image.open(picture_path) as pic:
                pic = pic.convert("RGBA")
                bx, by, bw, bh = (round(v * s) for v, s in zip(PICTURE_BOX, (width, height, width, height)))
                scale = min(bw / pic.width, bh / pic.height)  # (fitted: shrunk, or grown, to its box, its shape kept)
                pic = pic.resize((max(1, round(pic.width * scale)), max(1, round(pic.height * scale))))
                canvas.paste(pic, (bx + (bw - pic.width) // 2, by + (bh - pic.height) // 2), pic)
        except OSError:
            picture_path = None  # (gone or unreadable: the words alone)
    if text.strip():
        size = max(10, round(WORDS_SIZE * height))
        try:
            font = ImageFont.truetype(font_path, size)
        except OSError:
            font = ImageFont.load_default()
        middle = (WORDS_UNDER if picture_path else WORDS_ALONE) * height
        draw_centred(ImageDraw.Draw(canvas), text, font, size, (width / 2, middle), "#" + color.lstrip("#"))
    canvas.save(path, "PNG")


def command(ffmpeg: str, png: str, enc: str, kbps: int) -> list[str]:
    """The holding screen's ffmpeg: `png` looped at FPS at the pace it plays (-re), the music on its stdin (as the live
    picture has it), compressed as the live picture is, MPEG-TS on its stdout for the sender."""
    return [ffmpeg, "-hide_banner", "-loglevel", "warning",
            "-re", "-loop", "1", "-framerate", str(FPS), "-i", png,
            "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", "pipe:0",
            "-map", "0:v", "-map", "1:a",
            *compress_args(enc, kbps), "-f", "mpegts", "pipe:1"]
