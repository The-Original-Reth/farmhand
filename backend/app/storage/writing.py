"""Writing files whole or not at all (a share dropping mid-write never leaves a half file), copying and moving them."""
from __future__ import annotations

import errno
import logging
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("farmhand.storage")


def _safe_name(filename: str) -> str:
    """Just the file's own name — never a path an upload tried to smuggle in."""
    name = Path(filename or "").name
    if name in ("", ".", ".."):
        raise ValueError("Invalid file name")
    return name


def preview_cache_headers(request_query: dict) -> dict:
    """
    How long a browser may keep a preview image. Asked for with ?r=<its revision> (as the page does), the address
    changes whenever the picture does, so it can be kept for good; otherwise check back each time (cheap: 304).
    """
    return {"Cache-Control": "public, max-age=31536000, immutable" if "r" in request_query else "no-cache"}


@contextmanager
def _written_whole(dest: Path) -> Iterator[Path]:
    """
    Write `dest` whole or not at all: the block writes the temporary file it's given ("<name>.part"), which then
    replaces `dest`. If anything goes wrong part-way (a share dropping mid-write), the temporary file is removed and
    `dest` is left as it was, so a truncated file never looks real.
    """
    part = dest.with_name(dest.name + ".part")
    try:
        yield part
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def save_upload(dest_dir: Path, filename: str, file_obj) -> str:
    """
    Write an uploaded file (anything with .read()) into dest_dir. Written under a
    temporary name and renamed, so a failure part-way (a network share dropping
    mid-write) never leaves a truncated file that looks real.
    """
    dest = Path(dest_dir) / _safe_name(filename)
    with _written_whole(dest) as part, open(part, "wb") as out:
        shutil.copyfileobj(file_obj, out)
    return str(dest)


def write_text_atomically(target: str | os.PathLike, text: str) -> None:
    """
    Write a UTF-8 text file whole or not at all: under a temporary name, then renamed over the old one, so a share
    dropping mid-write never leaves a half-written file behind (the settings file, the printer and model files).
    """
    with _written_whole(Path(target)) as part:
        part.write_text(text, encoding="utf-8")


def write_bytes_atomically(target: str | os.PathLike, data: bytes) -> None:
    """write_text_atomically for bytes: written exactly as given (a CSV's \\r\\n line ends stay as they are)."""
    with _written_whole(Path(target)) as part:
        part.write_bytes(data)


def preview_beside(model_file: str | None) -> str | None:
    """Where a model file's preview is kept next to it: "Frog.stl" -> "Frog.stl.png" (on the NAS if that's where it is)."""
    return f"{model_file}.png" if model_file else None


def save_preview_beside(model_file: str, png: bytes) -> str | None:
    """
    Save a model's or 3MF's preview next to its file (on the NAS if that's where the file is): the only copy there is,
    and the one the page shows. Returns where it went. Fails soft (None, logged): a folder that can't be written to
    just goes without a preview, which never stops an upload.
    """
    target = Path(preview_beside(model_file))
    try:
        write_bytes_atomically(target, png)
        return str(target)
    except OSError as e:
        log.warning("Couldn't save the preview next to %s: %s", model_file, e)
        return None


def copy_verified(src: str | os.PathLike, dest_dir: str | os.PathLike, name: str | None = None) -> str:
    """Copy a file into dest_dir and confirm the size matches before it counts. Returns the new path."""
    src = Path(src)
    dest = Path(dest_dir) / _safe_name(name or src.name)
    with _written_whole(dest) as part:
        shutil.copy2(src, part)
        if part.stat().st_size != src.stat().st_size:
            raise OSError(f"Copy of {src.name} came out the wrong size — it was not used")
    return str(dest)


def move_file(src: str | os.PathLike, dest_dir: str | os.PathLike, name: str | None = None) -> str:
    """
    Move a file into dest_dir and return its new path. Never overwrites, and never leaves two copies or a
    half-moved file behind: it either ends up moved, or stays exactly where it was and this raises.

    Within one filesystem (the normal case: a folder and its sub-folders, on a NAS or not) that's a rename:
    instant, whatever the size. Across filesystems it's a verified copy followed by deleting the original;
    and if the original can't be deleted (a read-only share) the copy is removed again and this raises.
    """
    src = Path(src)
    dest = Path(dest_dir) / _safe_name(name or src.name)
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")
    try:
        os.rename(src, dest)
        return str(dest)
    except OSError as e:
        if e.errno != errno.EXDEV:  # anything but "different filesystems" is a real problem: leave the file alone
            raise
    copied = copy_verified(src, dest_dir, dest.name)
    try:
        src.unlink()
    except OSError:
        Path(copied).unlink(missing_ok=True)
        raise
    return copied
