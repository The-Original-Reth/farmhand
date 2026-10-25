"""
The rules for a name someone types for a file (renaming a model or a 3MF file). The name is what Farmhand shows,
searches by and downloads as; the stored file on disk keeps the name it was saved under. Only the part before the
extension can change: a model stays .stl / .obj / .step and a 3MF stays .3mf.
"""
from __future__ import annotations

import os

MAX_LENGTH = 255
_FORBIDDEN = set('/\\:*?"<>|')
TYPE_EXTENSIONS = {"STL": ".stl", "OBJ": ".obj", "STEP": ".step"}


def clean_file_name(raw: str, *, extension: str) -> str:
    """
    The new name, always ending in `extension` (e.g. ".3mf"): the typed text is the part before it (if it was typed
    anyway, it isn't doubled). Spaces are tidied; characters a file name can't have on Windows or a NAS are refused.
    Raises ValueError saying what's wrong.
    """
    stem = " ".join((raw or "").split())  # no line breaks or runs of spaces
    if stem.lower().endswith(extension.lower()):
        stem = stem[: -len(extension)]
    stem = stem.rstrip(" .")
    if not stem:
        raise ValueError("The name can't be empty")
    bad = sorted({ch for ch in stem if ch in _FORBIDDEN or ord(ch) < 32})
    if bad:
        raise ValueError(f"A file name can't contain {' '.join(bad)}")
    name = stem + extension
    if len(name) > MAX_LENGTH:
        raise ValueError(f"The name can be at most {MAX_LENGTH} characters")
    return name


def extension_of(name: str, fallback: str) -> str:
    """The extension a file's current name has (".stl"), or `fallback` if it has none."""
    ext = os.path.splitext(name)[1]
    return ext if ext else fallback


def download_name(display_name: str, stored_path: str) -> str:
    """What a download is called: the shown name, with the stored file's extension if the name doesn't have one."""
    ext = os.path.splitext(stored_path)[1]
    return display_name if not ext or display_name.lower().endswith(ext.lower()) else display_name + ext
