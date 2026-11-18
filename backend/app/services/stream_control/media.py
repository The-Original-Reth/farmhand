"""
Stream control's pictures and music, as files in Farmhand's stream folder: "stream" in the folder above the STL /
OBJ / STEP folder (beside "farm-cost"), so on the NAS when that's where the files are:

    <stream folder>/images/<name>.png                 single pictures, for a square of the grid
    <stream folder>/slideshows/<slideshow>/<name>.jpg  each slideshow a folder of pictures, shown in turn
    <stream folder>/music/<name>.mp3                   the stream's music, played round and round

The same layout as a stream plugin's own stream folder (its stream_media.py, which this is copied from), so a folder
copied from one reads the same here. The stream plugins fetch these files through the plugin API (stream:read).
Pictures dropped in by hand count just the same. Deleting only ever removes files listed here, and a slideshow's
folder once it's empty: never a folder with anything else in it.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from sqlalchemy.orm import Session

from ... import storage
from ...errors import NotFound

FOLDER_NAME = "stream"
IMAGES, SLIDESHOWS, MUSIC = "images", "slideshows", "music"
PICTURE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                 ".svg": "image/svg+xml"}  # (an SVG is drawn as a PNG for the stream: live_stream/svg.py)
PICTURE_MAX = 10 * 1024 * 1024  # an upload; pictures dropped in by hand can be any size
# The music is MP3s only: ffmpeg plays them one after another as one long track, which needs them all the same kind
TRACK_TYPES = {".mp3": "audio/mpeg"}
TRACK_MAX = 50 * 1024 * 1024  # an upload; tracks copied in by hand can be any size
NAME = re.compile(r"^[^/\\\0]{1,120}$")


def _root() -> Path:
    """Where the stream folder is (made or not)."""
    return storage.named_folder(storage.effective_root("stl").parent, FOLDER_NAME)


def folder(db: Session, make: bool = False) -> Path:
    """The stream folder, while it can be used (StorageUnavailableError otherwise: the STL folder's share is
    unmounted, say); with `make`, it and its folders made."""
    root = storage.named_folder(storage.ready_root("stl").parent, FOLDER_NAME)
    if make:
        root.mkdir(exist_ok=True)
    elif not root.is_dir():
        raise storage.StorageUnavailableError(
            f"The stream folder ({root}) isn't there yet. Add a picture or a track on Stream control's page and it's made.")
    if make:
        for d in (IMAGES, SLIDESHOWS, MUSIC):
            (root / d).mkdir(parents=True, exist_ok=True)
    return root


def _slideshow_dir(db: Session, name: str, must_be_there: bool = False) -> Path:
    """A slideshow's folder; with `must_be_there`, NotFound when it isn't."""
    d = folder(db) / SLIDESHOWS / _name(name, "slideshow")
    if must_be_there and not d.is_dir():
        raise NotFound("That slideshow isn't there.")
    return d


def _pictures_dir(root: Path, slideshow: str | None) -> Path:
    """Where a picture is: the single pictures (`slideshow` None), or a slideshow's folder."""
    return root / IMAGES if slideshow is None else root / SLIDESHOWS / _name(slideshow, "slideshow")


def _natural(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _files_in(d: Path, types: dict) -> list[str]:
    try:
        return sorted((e.name for e in os.scandir(d) if e.is_file() and Path(e.name).suffix.lower() in types and not e.name.startswith(".")),
                      key=_natural)
    except OSError:
        return []


def _pictures_in(d: Path) -> list[str]:
    return _files_in(d, PICTURE_TYPES)


# A slideshow's own order, kept in its folder (so every square showing it, the stream and another Farmhand sharing the
# folder all follow it): its pictures' names in the order chosen. Pictures not in it (added since) come after, in name
# order; names in it no longer there are skipped.
ORDER_FILE = ".farmhand-order.json"
# A blank screen in a slideshow: no picture, just the square's colour and the words written on it. It's Farmhand's own,
# so it lives only in the order, as "blank:1", "blank:2"... (a colon: never a file's name on Windows, so never a picture's).
BLANK = "blank:"


def is_blank(name) -> bool:
    return isinstance(name, str) and name.startswith(BLANK)


def _write_order(d: Path, names: list[str]) -> None:
    storage.write_text_atomically(d / ORDER_FILE, json.dumps(names, ensure_ascii=False))


def _slides_in(d: Path) -> list[str]:
    """A slideshow's pictures in its own order."""
    names = _pictures_in(d)
    try:
        order = json.loads((d / ORDER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return names
    if not isinstance(order, list):
        return names
    have = set(names)
    first = [n for n in dict.fromkeys(order) if isinstance(n, str) and (n in have or is_blank(n))]  # and its blank screens
    return first + [n for n in names if n not in set(first)]


def set_order(db: Session, name: str, order: list[str]) -> list[str]:
    """Put a slideshow's pictures in this order (its pictures' names; any left out keep their place after these).
    ValueError for a name that isn't one of its pictures. Its order, as now kept."""
    d = _slideshow_dir(db, name, must_be_there=True)
    have = set(_slides_in(d))  # its pictures and blank screens
    missing = [n for n in order if n not in have]
    if missing:
        raise ValueError(f"“{missing[0]}” isn't one of the slideshow's pictures (Scan folder, and try again).")
    keep = list(dict.fromkeys(order)) + [n for n in _slides_in(d) if n not in set(order)]
    _write_order(d, keep)
    forget()
    return keep


def add_blank(db: Session, name: str) -> str:
    """A new blank screen at the end of a slideshow: its name in the order ("blank:3")."""
    d = _slideshow_dir(db, name, must_be_there=True)
    slides = _slides_in(d)
    numbers = [int(n[len(BLANK):]) for n in slides if is_blank(n) and n[len(BLANK):].isdigit()]
    blank = f"{BLANK}{max(numbers, default=0) + 1}"
    _write_order(d, slides + [blank])
    forget()
    return blank


# What was last found in the stream folder, and which folder that was. It's read again only when asked (Scan folder),
# after a change made through Farmhand, or when the folder is another one; never just because the page looked again,
# so a folder on the NAS isn't read every few seconds.
_found: tuple[str, dict] | None = None


def forget() -> None:
    """Read the stream folder again the next time it's asked about."""
    global _found
    _found = None


def media(db: Session, scan: bool = False) -> dict:
    """{path, images: [names], slideshows: [{name, images: [names]}], music: [the tracks' names], error (why the
    folder can't be used now, or None)}:
    what's in the stream folder, as last found (read now when `scan`, or the first time)."""
    global _found
    which = str(_root())
    if not scan and _found and _found[0] == which:
        return _found[1]
    _found = (which, _read(db))
    return _found[1]


def _read(db: Session) -> dict:
    try:
        try:  # made, with its own folders, so each one is there to open and copy into by hand (a read-only share: left)
            root = folder(db, make=True)
        except OSError:
            root = folder(db)
    except storage.StorageUnavailableError as e:
        return {"path": str(_root()), "images": [], "slideshows": [], "music": [], "error": str(e)}
    shows = []
    try:
        for e in sorted(os.scandir(root / SLIDESHOWS), key=lambda e: _natural(e.name)):
            if e.is_dir() and not e.name.startswith("."):
                shows.append({"name": e.name, "images": _slides_in(Path(e.path))})
    except OSError:
        pass
    images, music = _pictures_in(root / IMAGES), _files_in(root / MUSIC, TRACK_TYPES)
    files = [f"{IMAGES}/{n}" for n in images] + [f"{MUSIC}/{n}" for n in music] + [
        f"{SLIDESHOWS}/{s['name']}/{n}" for s in shows for n in s["images"] if not is_blank(n)]
    return {"path": str(root), "images": images, "slideshows": shows, "music": music, "error": None,
            "stamps": _stamps(root, files)}


def _stamps(root: Path, files: list[str]) -> dict[str, str]:
    """Each file's stamp, "<size>-<modified, ns>", by its place in the folder ("images/logo.png",
    "slideshows/Prints/a.png", "music/beat.mp3"): a stream plugin copying them fetches only those whose stamp changed."""
    out = {}
    for rel in files:
        try:
            st = (root / rel).stat()
        except OSError:
            continue
        out[rel] = f"{st.st_size}-{st.st_mtime_ns}"
    return out


def _name(raw: str, what: str) -> str:
    name = (raw or "").strip()
    if not NAME.match(name) or name in (".", "..") or name.startswith("."):
        raise ValueError(f"That isn't a name a {what} can have.")
    return name


def _picture_path(d: Path, name: str) -> Path:
    name = _name(name, "picture")
    path = d / name
    if path.suffix.lower() not in PICTURE_TYPES or not path.is_file():
        raise NotFound("That picture isn't there.")
    return path


def picture(db: Session, slideshow: str | None, name: str) -> tuple[bytes, str]:
    """A picture's bytes and type: one of the single pictures, or one in a slideshow. NotFound when it isn't there."""
    path = picture_path(db, slideshow, name)
    return path.read_bytes(), PICTURE_TYPES[path.suffix.lower()]


def picture_path(db: Session, slideshow: str | None, name: str) -> Path:
    return _picture_path(_pictures_dir(folder(db), slideshow), name)


def slideshow_paths(db: Session, name: str) -> list[Path]:
    """A slideshow's pictures, in its own order ([] for one that isn't there); a blank screen as its name ("blank:1")."""
    d = _slideshow_dir(db, name)
    return [n if is_blank(n) else d / n for n in _slides_in(d)]


def _check_picture(filename: str, data: bytes) -> str:
    name = Path(filename or "").name
    if Path(name).suffix.lower() not in PICTURE_TYPES:
        raise ValueError("A picture has to be a PNG, JPEG, WebP or SVG file.")
    if len(data) > PICTURE_MAX:
        raise ValueError("A picture uploaded here has to be under 10 MB. Save it smaller, or copy it into the stream folder yourself.")
    return _name(name, "picture")


def _free_name(d: Path, name: str) -> str:
    """name, or "name (2).png" and so on when a file of that name (any case) is there already."""
    taken = {n.lower() for n in os.listdir(d)} if d.is_dir() else set()
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, n = name, 2
    while candidate.lower() in taken:
        candidate = f"{stem} ({n}){suffix}"
        n += 1
    return candidate


def add_picture(db: Session, slideshow: str | None, filename: str, data: bytes) -> str:
    """Write an uploaded picture into the single pictures, or into a slideshow (made when it isn't there): its name."""
    name = _check_picture(filename, data)
    d = _pictures_dir(folder(db, make=True), slideshow)
    d.mkdir(parents=True, exist_ok=True)
    name = _free_name(d, name)
    storage.write_bytes_atomically(d / name, data)
    forget()
    return name


def remove_picture(db: Session, slideshow: str | None, name: str) -> None:
    if slideshow and is_blank(name):  # a blank screen: taken out of the order (it has no file)
        d = _slideshow_dir(db, slideshow)
        slides = _slides_in(d)
        if name not in slides:
            raise NotFound("That blank screen isn't there.")
        _write_order(d, [n for n in slides if n != name])
    else:
        picture_path(db, slideshow, name).unlink()
    forget()


def add_slideshow(db: Session, name: str) -> str:
    """A new, empty slideshow folder. ValueError for a name taken (any case) or one a folder can't have."""
    name = _name(name, "slideshow")
    d = folder(db, make=True) / SLIDESHOWS
    if any(e.name.lower() == name.lower() for e in os.scandir(d) if e.is_dir()):
        raise ValueError(f"There's already a slideshow called “{name}”.")
    (d / name).mkdir()
    forget()
    return name


def rename_slideshow(db: Session, name: str, new: str) -> str:
    """Rename a slideshow's folder (its pictures and order go with it): the new name. NotFound when it isn't there;
    ValueError for a name another slideshow has (any case) or one a folder can't have. Only the case can change too."""
    name, new = _name(name, "slideshow"), _name(new, "slideshow")
    d = folder(db) / SLIDESHOWS
    if not (d / name).is_dir():
        raise NotFound("That slideshow isn't there.")
    if new == name:
        return new
    if new.lower() != name.lower() and any(e.name.lower() == new.lower() for e in os.scandir(d)):
        raise ValueError(f"There's already a slideshow called “{new}”.")
    try:
        os.rename(d / name, d / new)
    except OSError as e:
        raise ValueError(f"Couldn't rename the slideshow's folder: {e.strerror or e}") from None
    forget()
    return new


def remove_slideshow(db: Session, name: str) -> None:
    """Delete a slideshow: its pictures, then its folder, which is only removed once nothing else is left in it."""
    d = _slideshow_dir(db, name, must_be_there=True)
    for n in _pictures_in(d):
        (d / n).unlink(missing_ok=True)
    (d / ORDER_FILE).unlink(missing_ok=True)  # Farmhand's own: its order
    forget()
    try:
        d.rmdir()
    except OSError:
        raise ValueError(f"The slideshow's pictures are deleted, but its folder still holds other files, so it was left: {d}") from None


# ------------------------------------------------------------------ the music


def track_path(db: Session, name: str) -> Path:
    """One of the music's tracks. NotFound when it isn't there."""
    path = folder(db) / MUSIC / _name(name, "track")
    if path.suffix.lower() not in TRACK_TYPES or not path.is_file():
        raise NotFound("That track isn't there.")
    return path


def track_paths(db: Session) -> list[Path]:
    """The music's tracks, in name order ([] when there are none, or the stream folder can't be used now)."""
    try:
        d = folder(db) / MUSIC
    except storage.StorageUnavailableError:
        return []
    return [d / n for n in _files_in(d, TRACK_TYPES)]


def add_track(db: Session, filename: str, data: bytes) -> str:
    """Write an uploaded MP3 into the music: its name (numbered when one of that name is there)."""
    name = Path(filename or "").name
    if Path(name).suffix.lower() not in TRACK_TYPES:
        raise ValueError("The music has to be MP3 files.")
    if len(data) > TRACK_MAX:
        raise ValueError("A track uploaded here has to be under 50 MB. Copy bigger ones into the stream folder's music folder yourself.")
    name = _name(name, "track")
    d = folder(db, make=True) / MUSIC
    name = _free_name(d, name)
    storage.write_bytes_atomically(d / name, data)
    forget()
    return name


def remove_track(db: Session, name: str) -> None:
    track_path(db, name).unlink()
    forget()
