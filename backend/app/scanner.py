"""
Finding model files that were put into the STL folder from outside Farmhand (copied onto the
NAS from a PC, say) so they can be added to the library.

Pure filesystem logic — no database — so the rules are easy to test:
  * looks for STL / OBJ / STEP files by extension, anywhere under the folder
  * skips hidden folders, Synology/QNAP housekeeping folders (@eaDir, #recycle, …), partial
    uploads (*.part) and symlinks (so a link can't lead the scan somewhere unexpected)
  * skips files that are already in the library (`known`)
  * stops after MAX_RESULTS so one scan can't run away on a huge share
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SOURCE_EXTENSIONS = {".stl": "STL", ".obj": "OBJ", ".step": "STEP", ".stp": "STEP"}
SKIP_DIR_PREFIXES = (".", "@")  # hidden folders, @eaDir (Synology), @Recycle (QNAP)…
SKIP_DIR_NAMES = {"#recycle", "$recycle.bin", "system volume information"}
MAX_RESULTS = 500


@dataclass(frozen=True)
class ScannedFile:
    path: str  # absolute
    name: str
    folder: str  # relative to the scanned root; "" = top level
    size_bytes: int
    file_type: str  # STL | OBJ | STEP


def file_type_for(name: str) -> str | None:
    return SOURCE_EXTENSIONS.get(os.path.splitext(name)[1].lower())


def normalise(path: str | os.PathLike) -> str:
    """The form paths are compared in — no filesystem access, so it's cheap over a network."""
    return os.path.abspath(path)


def scan_folder(root: str | os.PathLike, known: set[str], limit: int = MAX_RESULTS) -> tuple[list[ScannedFile], bool]:
    """
    Returns (new files sorted by path, truncated). `known` holds normalised paths already in the library.
    """
    root = Path(normalise(root))
    found: list[ScannedFile] = []
    truncated = False
    pending = [root]

    while pending and not truncated:
        folder = pending.pop()
        try:
            with os.scandir(folder) as it:
                entries = list(it)
        except OSError:
            continue  # unreadable folder: skip it rather than fail the whole scan

        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    lowered = entry.name.lower()
                    if not entry.name.startswith(SKIP_DIR_PREFIXES) and lowered not in SKIP_DIR_NAMES:
                        pending.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if entry.name.startswith(".") or entry.name.endswith(".part"):
                    continue
                file_type = file_type_for(entry.name)
                if file_type is None:
                    continue
                path = normalise(entry.path)
                if path in known:
                    continue
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue

            if len(found) >= limit:
                truncated = True
                break
            rel = os.path.relpath(os.path.dirname(path), root)
            found.append(ScannedFile(path, entry.name, "" if rel == "." else rel, size, file_type))

    found.sort(key=lambda f: f.path.casefold())
    return found, truncated
