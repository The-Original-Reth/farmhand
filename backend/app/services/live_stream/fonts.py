"""
The fonts a square's words and a camera's words can be written in, and their files on the server.
"""
from __future__ import annotations

import os

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"  # fonts-dejavu-core, in the API's image
FONTS_DIR = "/usr/share/fonts"
APP_FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fonts")  # fonts kept with Farmhand: "app:" in FONTS
# The fonts a square's words can be written in: key -> (name, its file in FONTS_DIR (the Dockerfile installs them),
# the kind of font the page falls back to while its own copy loads). A font the server doesn't have writes in FONT (DejaVu Sans).
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
DEFAULT_FONT = "play"  # the stream's words, unless another is chosen


def font_file(key: str | None) -> str:
    """The file a font is written with (none chosen: DEFAULT_FONT): its own when the server has it, else FONT."""
    found = FONTS.get(key or DEFAULT_FONT)
    if found:
        file = found[1]
        path = os.path.join(APP_FONTS, file[4:]) if file.startswith("app:") else os.path.join(FONTS_DIR, file)
        if os.path.isfile(path):
            return path
    return FONT
