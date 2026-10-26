"""
Every preview image is kept next to its file (on the NAS when that's where the file is): "Frog.stl" has
"Frog.stl.png", "Goldfish ver 2.3mf" has "Goldfish ver 2.3mf.png". The app keeps its own copy of each too, which is
what the page shows, so browsing keeps working when a share is offline.

This copies the preview next to any file that doesn't have one yet (files from before previews were kept with them).
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..models import BundleVersion, SourceModelVersion


def save_missing_beside(db: Session) -> int:
    """
    Copy each model's and 3MF's preview next to its file where there isn't one yet. Files that can't be reached right
    now (a share that's offline) and 3MF versions whose files were pruned are skipped. Returns how many were saved.
    """
    pairs = [(v.file_path, v.thumbnail_path) for v in db.scalars(select(SourceModelVersion).where(SourceModelVersion.thumbnail_path.isnot(None)))]
    pairs += [
        (v.threemf_path, v.thumbnail_path)
        for v in db.scalars(select(BundleVersion).where(BundleVersion.thumbnail_path.isnot(None), BundleVersion.full_files_retained.is_(True)))
    ]
    saved = 0
    for file_path, thumbnail_path in pairs:
        beside = storage.preview_beside(file_path)
        if not beside or os.path.exists(beside) or not os.path.isfile(file_path) or not os.path.isfile(thumbnail_path):
            continue
        try:
            png = Path(thumbnail_path).read_bytes()
        except OSError:
            continue
        if storage.save_preview_beside(file_path, png):
            saved += 1
    return saved
