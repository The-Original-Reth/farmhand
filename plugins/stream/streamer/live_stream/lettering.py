"""
Words drawn with Pillow as the stream writes them everywhere (slideshow screens, the holding screen) and as the page
shows them: in lines a quarter of their size apart, each line centred, the whole centred on a spot.
"""
from __future__ import annotations

from PIL import ImageDraw


def draw_centred(draw: ImageDraw.ImageDraw, text: str, font, size: int, centre: tuple[float, float], fill,
                 band: tuple[int, tuple] | None = None) -> None:
    """`text` in `font` (of `size` px) centred on `centre`, each line centred, in `fill`; with `band` (padding px,
    colour), on a band of that colour round it."""
    spacing = size // 4
    left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
    x = centre[0] - (right - left) / 2 - left
    y = centre[1] - (bottom - top) / 2 - top
    if band:
        pad, colour = band
        draw.rectangle((x + left - pad, y + top - pad, x + right + pad, y + bottom + pad), fill=colour)
    draw.multiline_text((x, y), text, font=font, spacing=spacing, align="center", fill=fill)
