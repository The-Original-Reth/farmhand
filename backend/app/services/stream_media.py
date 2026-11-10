"""
The Stream page's pictures, as files in the stream folder, chosen in Settings like the other storage locations:

    <stream folder>/images/<name>.png                 single pictures, for a square of the grid
    <stream folder>/slideshows/<slideshow>/<name>.jpg  each slideshow a folder of pictures, shown in turn (by name)

By default the stream folder is "stream" in the folder above the STL / OBJ / STEP folder, beside "farm-cost". Pictures
uploaded on the Stream page are written there; pictures dropped in by hand (over the network share, say) count just the
same. Squares name a picture by its file name and a slideshow by its folder's name, so they read the same on any
Farmhand sharing the folder. Deleting only ever removes picture files Farmhand lists, and a slideshow's folder once
it's empty: never a folder with anything else in it.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy.orm import Session

from .. import storage
from ..errors import NotFound
from . import app_settings

STREAM_FOLDER = "stream"
KEY_LOCATION = "stream_media_dir"  # the folder chosen in Settings; none = the default
IMAGES, SLIDESHOWS = "images", "slideshows"
PICTURE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
PICTURE_MAX = 10 * 1024 * 1024  # an upload; pictures dropped in by hand can be any size
NAME = re.compile(r"^[^/\\\0]{1,120}$")


def default_folder() -> Path:
    """The stream folder when none is chosen: "stream" in the folder above the STL / OBJ / STEP folder."""
    return storage.named_folder(storage.effective_root("stl").parent, STREAM_FOLDER)


def _chosen(db: Session) -> str | None:
    return app_settings.get(db, KEY_LOCATION)


def location_info(db: Session) -> dict:
    """For Settings: {path, is_default, default_path, status: {exists, writable, marker_ok, ready}}."""
    chosen = _chosen(db)
    default = default_folder()
    if chosen:
        return {"path": chosen, "is_default": False, "default_path": str(default), "status": storage.folder_status(Path(chosen))}
    try:
        storage.ready_root("stl")
        ready = True
    except storage.StorageUnavailableError:
        ready = False
    status = {"exists": default.is_dir(), "writable": ready, "marker_ok": ready, "ready": ready}  # made when first used
    return {"path": str(default), "is_default": True, "default_path": str(default), "status": status}


def set_location(db: Session, raw: str | None) -> dict:
    """
    Choose the stream folder (None or "" = back to the default). A chosen folder must last (on a connected share or in
    Farmhand's own storage) and be writable; it gets Farmhand's marker, so an unmounted share is never written under.
    ValueError says why one can't be used. Pictures already in the old folder stay there.
    """
    if raw and raw.strip():
        real = storage.validate_location(raw.strip())
        storage.mark_location(real)
        app_settings.put(db, KEY_LOCATION, str(real))
    else:
        app_settings.put(db, KEY_LOCATION, None)
    db.commit()
    return location_info(db)


def folder(db: Session, make: bool = False) -> Path:
    """The stream folder, while it can be used (StorageUnavailableError otherwise); with `make`, its two folders made."""
    chosen = _chosen(db)
    root = storage.ensure_ready_folder(chosen, "stream folder") if chosen else storage.named_folder(storage.ready_root("stl").parent, STREAM_FOLDER)
    if make:
        (root / IMAGES).mkdir(parents=True, exist_ok=True)
        (root / SLIDESHOWS).mkdir(parents=True, exist_ok=True)
    return root


def _natural(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _pictures_in(d: Path) -> list[str]:
    try:
        return sorted((e.name for e in os.scandir(d) if e.is_file() and Path(e.name).suffix.lower() in PICTURE_TYPES and not e.name.startswith(".")),
                      key=_natural)
    except OSError:
        return []


def media(db: Session) -> dict:
    """{path, images: [names], slideshows: [{name, images: [names]}], error}: what's in the stream folder now."""
    try:
        root = folder(db)
    except storage.StorageUnavailableError as e:
        return {"path": location_info(db)["path"], "images": [], "slideshows": [], "error": str(e)}
    shows = []
    try:
        for e in sorted(os.scandir(root / SLIDESHOWS), key=lambda e: _natural(e.name)):
            if e.is_dir() and not e.name.startswith("."):
                shows.append({"name": e.name, "images": _pictures_in(Path(e.path))})
    except OSError:
        pass
    return {"path": str(root), "images": _pictures_in(root / IMAGES), "slideshows": shows, "error": None}


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
    root = folder(db)
    d = root / IMAGES if slideshow is None else root / SLIDESHOWS / _name(slideshow, "slideshow")
    path = _picture_path(d, name)
    return path.read_bytes(), PICTURE_TYPES[path.suffix.lower()]


def picture_path(db: Session, slideshow: str | None, name: str) -> Path:
    root = folder(db)
    return _picture_path(root / IMAGES if slideshow is None else root / SLIDESHOWS / _name(slideshow, "slideshow"), name)


def slideshow_paths(db: Session, name: str) -> list[Path]:
    """A slideshow's pictures, in name order ([] for one that isn't there)."""
    d = folder(db) / SLIDESHOWS / _name(name, "slideshow")
    return [d / n for n in _pictures_in(d)]


def _check_picture(filename: str, data: bytes) -> str:
    name = Path(filename or "").name
    if Path(name).suffix.lower() not in PICTURE_TYPES:
        raise ValueError("A picture has to be a PNG, JPEG or WebP file.")
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
    root = folder(db, make=True)
    d = root / IMAGES if slideshow is None else root / SLIDESHOWS / _name(slideshow, "slideshow")
    d.mkdir(parents=True, exist_ok=True)
    name = _free_name(d, name)
    storage.write_bytes_atomically(d / name, data)
    return name


def remove_picture(db: Session, slideshow: str | None, name: str) -> None:
    picture_path(db, slideshow, name).unlink()


def add_slideshow(db: Session, name: str) -> str:
    """A new, empty slideshow folder. ValueError for a name taken (any case) or one a folder can't have."""
    name = _name(name, "slideshow")
    d = folder(db, make=True) / SLIDESHOWS
    if any(e.name.lower() == name.lower() for e in os.scandir(d) if e.is_dir()):
        raise ValueError(f"There's already a slideshow called “{name}”.")
    (d / name).mkdir()
    return name


def remove_slideshow(db: Session, name: str) -> None:
    """Delete a slideshow: its pictures, then its folder, which is only removed once nothing else is left in it."""
    d = folder(db) / SLIDESHOWS / _name(name, "slideshow")
    if not d.is_dir():
        raise NotFound("That slideshow isn't there.")
    for n in _pictures_in(d):
        (d / n).unlink(missing_ok=True)
    try:
        d.rmdir()
    except OSError:
        raise ValueError(f"The slideshow's pictures are deleted, but its folder still holds other files, so it was left: {d}") from None
