"""
What going live puts in the stream's own folder for ffmpeg to read: the cards' pictures, copied once; each card's
words, and each slideshow picture's own, as files; and the grid's squares as the ffmpeg command takes them.
"""
from __future__ import annotations

import os
import random
import shutil

from sqlalchemy.orm import Session

from ...errors import NotFound
from ... import storage
from .. import stream_media


def write_atomically(path: str, text: str) -> None:
    """drawtext reads the file again every frame: it's swapped in whole, never seen half written."""
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# How many tracks the music's playlist lists: round after round of them, enough for a day of 10-second tracks (ffmpeg
# starts again after a day). ffmpeg's own looping (-stream_loop) fails with a playlist once it comes round again.
PLAYLIST_LENGTH = 8640


def playlist(tracks: list, path: str, shuffle: bool) -> str:
    """The music's tracks as ffmpeg's concat reads them, round after round (each round in a new order when `shuffle`),
    written to `path`: the path."""
    tracks = [str(t).replace("'", "'\\''") for t in tracks]  # concat's own quoting: ' as '\''
    lines = ["ffconcat version 1.0"]
    for _ in range(-(-PLAYLIST_LENGTH // len(tracks)) if tracks else 0):
        if shuffle:
            random.shuffle(tracks)
        lines += [f"file '{t}'" for t in tracks]
    write_atomically(path, "\n".join(lines) + "\n")
    return path


def card_pictures(db: Session, cards: dict) -> dict:
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


def squares(db: Session, chosen: dict, folder: str) -> list:
    """The grid's squares as the ffmpeg command takes them (picture.Look.cells): ("camera", its place among the
    cameras, its cell), ("card", its cell with its pictures' copies, its words' file and its slideshow pictures' own
    words' files), or None."""
    cards = {c: cell for c, cell in enumerate(chosen["cells"]) if cell and "camera" not in cell}
    pictures = local_copies(card_pictures(db, cards), folder)
    place = {k: i for i, k in enumerate(chosen["cameras"])}
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
            out.append(("card", {**cell, "pictures": pictures.get(c, []), "words": words, "picture_words": own}))
    return out
