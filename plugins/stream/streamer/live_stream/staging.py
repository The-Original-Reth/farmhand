"""
What going live puts in the stream's own folder for ffmpeg to read: the cards' pictures, copied once; each card's
words, and each slideshow picture's own, as files; and the grid's squares as the ffmpeg command takes them.
"""
from __future__ import annotations

import os
import shutil

from ..store import Store

from ..errors import NotFound
from .. import storage
from .. import stream_media
from . import slides
from .constants import DEFAULT_TEXT_COLOR
from .fonts import font_file
from .frame import Frame
from .squares import _text_box


def write_atomically(path: str, text: str) -> None:
    """drawtext reads the file again every frame: it's swapped in whole, never seen half written."""
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def card_pictures(db: Store, cards: dict) -> dict:
    """Each card's pictures, as files in the stream folder: {square: [paths]} (its picture, or its slideshow's). One not
    there (or a stream folder that isn't available) shows just the card's colour and words."""
    out = {}
    for c, cell in (cards.items() if isinstance(cards, dict) else []):
        try:
            if cell.get("slideshow"):
                out[c] = [str(p) for p in stream_media.slideshow_paths(db, cell["slideshow"])]
            elif cell.get("image"):
                out[c] = [str(stream_media.picture_path(db, None, cell["image"]))]
        except (NotFound, ValueError, storage.StorageUnavailableError, OSError):
            out[c] = []
    return out


def local_copies(pictures: dict, folder: str) -> dict:
    """The cards' pictures copied once into the stream's own folder, each under its own name (a slideshow picture's
    words go by it): {square: [copies]}. ffmpeg reads each picture again every second: it reads these, never the
    stream folder (on the NAS, that's a hundred files opened a second, and pictures being copied in clash with it).
    One picture in several squares is copied once; one that can't be read now (being copied in, say) is left out, as
    one not there is."""
    copied: dict[str, str | None] = {}
    out = {}
    for c, paths in pictures.items():
        out[c] = []
        for path in paths:
            if stream_media.is_blank(path):  # a blank screen: no picture, just its time
                out[c].append(path)
                continue
            if path not in copied:
                to = os.path.join(folder, "pictures", str(len(copied)), os.path.basename(path))
                try:
                    os.makedirs(os.path.dirname(to), exist_ok=True)
                    shutil.copyfile(path, to)
                    copied[path] = to
                except OSError:
                    copied[path] = None
            if copied[path]:
                out[c].append(copied[path])
    return out


def squares(db: Store, chosen: dict, folder: str, cache: str | None = None) -> list:
    """The grid's squares as the ffmpeg command takes them (picture.Look.cells): ("camera", its place among the
    cameras, its cell), ("card", its cell with its pictures' copies, its words' file and its slideshow pictures' own
    words' files), or None."""
    cards = {c: cell for c, cell in enumerate(chosen["cells"]) if cell and "camera" not in cell}
    pictures = local_copies(card_pictures(db, cards), folder)
    place = {k: i for i, k in enumerate(chosen["cameras"])}
    copied: dict = {}  # the cards' more pictures, each copied once
    out = []
    for c, cell in enumerate(chosen["cells"]):
        if not cell:
            out.append(None)
        elif "camera" in cell:
            out.append(("camera", place[cell["camera"]], cell))
        else:
            words = None
            if cell.get("text"):
                words = os.path.join(folder, f"text-{c}.txt")
                write_atomically(words, cell["text"])
            own = {}  # its picture's place in the slideshow: {"words": file, "text_box"}
            for j, path in enumerate(pictures.get(c, [])):
                cap = (cell.get("captions") or {}).get(os.path.basename(path))
                if cap and cap.get("text"):
                    file = os.path.join(folder, f"text-{c}-{j}.txt")
                    write_atomically(file, cap["text"])
                    own[j] = {"words": file, "text_box": cap.get("text_box")}
            # its more pictures and pieces of text: the card's own, and each slideshow screen's (by its place in it)
            layers = staged_layers(db, cell.get("layers") or [], folder, f"{c}", copied)
            screens = {}
            for j, path in enumerate(pictures.get(c, [])):
                got = staged_layers(db, (cell.get("slide_layers") or {}).get(os.path.basename(path)) or [], folder, f"{c}-{j}", copied)
                if got:
                    screens[j] = got
            card = {**cell, "pictures": pictures.get(c, []), "words": words, "picture_words": own, "layers": layers, "screen_layers": screens}
            if cell.get("slideshow") and card["pictures"]:
                # each screen put together once (its colour, picture and more pictures): ffmpeg reads them as one input
                frame = Frame.of(chosen["resolution"], chosen["cols"], chosen["rows"], chosen["background"], chosen["border_color"])
                baked = {j: [x for x in ls if x["type"] == "picture"] for j, ls in screens.items()}
                on_screens = _screen_words(cell, card, screens, chosen)
                card["frames"] = slides.compose(cell, card["pictures"], baked, frame, os.path.join(folder, "slides", str(c)),
                                                cache=cache, screen_words=on_screens)
                # its screens' words are on the screens themselves now: none drawn over them in their seconds
                card["screen_layers"], card["picture_words"], card["words"] = {}, {}, None
            out.append(("card", card))
    return out


def _screen_words(cell: dict, card: dict, screens: dict, chosen: dict) -> dict[int, list[dict]]:
    """Each slideshow screen's words, for drawing on the screen itself (slides.compose), in the order the stream drew
    them (cards.card_square): its pieces of text, then its caption, or the card's own words when it has none. Each is
    {text, tb, font (file), color, band}: a piece of text in its own font and colour (else the stream's), the caption and
    the card's words in the card's (else the stream's)."""
    def read(file: str) -> str:
        with open(file, encoding="utf-8") as f:
            return f.read()

    def style(own: dict) -> dict:
        return {"font": font_file(own.get("font") or chosen.get("font")),
                "color": own.get("color") or chosen.get("color") or DEFAULT_TEXT_COLOR, "band": bool(own.get("band"))}

    card_style = style({"font": cell.get("font"), "color": cell.get("color"), "band": cell.get("band")})
    out: dict[int, list[dict]] = {}
    for j in range(len(card["pictures"])):
        got = [{"text": read(x["words"]), "tb": _text_box(x.get("box")), **style(x)}
               for x in screens.get(j, []) if x["type"] == "text"]
        cap = card["picture_words"].get(j)
        if cap:
            got.append({"text": read(cap["words"]), "tb": _text_box(cap.get("text_box")), **card_style})
        elif card.get("words"):
            got.append({"text": read(card["words"]), "tb": _text_box(cell.get("text_box"), cell.get("size"), cell.get("position")), **card_style})
        if got:
            out[j] = got
    return out


def staged_layers(db: Store, layers: list, folder: str, tag: str, copied: dict) -> list[dict]:
    """A card's (or a slideshow screen's) more pictures and pieces of text as ffmpeg takes them, in their order: a
    picture copied once into the stream's own folder ({"type": "picture", "path", "box"}; one not chosen, not there or
    unreadable is left out), a piece of text as a file ({"type": "text", "words": file, "box", "font", "color", "band"};
    an empty one is left out). `copied`: the pictures copied so far, {stream folder path: copy}."""
    out = []
    for k, layer in enumerate(layers):
        if layer.get("type") == "picture" and layer.get("image"):
            try:
                path = str(stream_media.picture_path(db, None, layer["image"]))
            except (NotFound, ValueError, storage.StorageUnavailableError, OSError):
                continue
            if path not in copied:
                to = os.path.join(folder, "pictures", f"layer-{len(copied)}", os.path.basename(path))
                try:
                    os.makedirs(os.path.dirname(to), exist_ok=True)
                    shutil.copyfile(path, to)
                    copied[path] = to
                except OSError:
                    copied[path] = None
            if copied[path]:
                out.append({"type": "picture", "path": copied[path], "box": layer.get("box")})
        elif layer.get("type") == "text" and (layer.get("text") or "").strip():
            file = os.path.join(folder, f"layer-{tag}-{k}.txt")
            write_atomically(file, layer["text"].strip())
            out.append({"type": "text", "words": file, "box": layer.get("box"), "font": layer.get("font"), "color": layer.get("color"),
                        "band": layer.get("band") is True})
    return out
