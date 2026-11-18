"""
The fonts the stream's words can be written in: the stream plugins' own list (live_stream/fonts.py there), so a font
chosen here is one they write with. Farmhand serves the files too, so its page shows the words as the stream will.
"""
from __future__ import annotations

import os

FONTS_DIR = "/usr/share/fonts"  # the API's image installs the same font packages as the stream plugins (Dockerfile)
APP_FONTS = os.path.join(os.path.dirname(__file__), "fonts")  # fonts kept with Farmhand: "app:" below
# key -> (name, its file, the kind of font the page falls back to while its own copy loads)
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
FONT_TYPES = {".ttf": "font/ttf", ".otf": "font/otf"}


def listed() -> list[dict]:
    """[{key, label, generic}] for the page's font choices."""
    return [{"key": k, "label": name, "generic": generic} for k, (name, _, generic) in FONTS.items()]


def font_file(key: str) -> str | None:
    """A font's file, when this Farmhand has it (None otherwise: the page falls back to its kind of font)."""
    found = FONTS.get(key)
    if not found:
        return None
    file = found[1]
    path = os.path.join(APP_FONTS, file[4:]) if file.startswith("app:") else os.path.join(FONTS_DIR, file)
    return path if os.path.isfile(path) else None
