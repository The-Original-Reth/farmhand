"""
Every preview image is kept next to its file, and only there (on the NAS when that's where the file is): "Frog.stl"
has "Frog.stl.png", "Goldfish ver 2.3mf" has "Goldfish ver 2.3mf.png". A 3MF version whose files were pruned keeps its
preview where the 3MF was. The app keeps no copy of its own, so while a share is offline its previews don't show.

Farmhand used to keep its own copy of each preview too (under storage.thumbnails_root()). This moves those out: each
goes next to its file (unless one is there already), the version is pointed at it, and the app's copy is deleted.
A version whose file can't be reached right now (a share that's offline) keeps its old copy until the next time.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..models import BundleVersion, SourceModelVersion


def move_app_copies_out(db: Session) -> int:
    """
    Move every preview the app still keeps itself out next to its file (see the top of this file), and point
    versions with no preview recorded at one that's next to their file. Returns how many versions were changed.
    """
    app_root = storage.thumbnails_root()
    changed = 0
    for v in list(db.scalars(select(SourceModelVersion))) + list(db.scalars(select(BundleVersion))):
        file_path = v.file_path if isinstance(v, SourceModelVersion) else v.threemf_path
        target = _target(v, file_path)
        if target is None:
            continue  # its file (or, pruned, its 3MF folder) can't be reached right now: next time
        own = v.thumbnail_path if v.thumbnail_path and storage.is_inside(v.thumbnail_path, app_root) else None
        if own is None:
            if not v.thumbnail_path and os.path.isfile(target):  # a preview beside it the version didn't know of
                v.thumbnail_path = target
                db.commit()
                changed += 1
            continue
        if not os.path.isfile(target) and os.path.isfile(own):
            try:
                png = Path(own).read_bytes()
            except OSError:
                continue
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            if not storage.save_preview_beside(target.removesuffix(".png"), png):
                continue  # can't be written there right now: keep the app's copy until next time
        v.thumbnail_path = target if os.path.isfile(target) else None
        db.commit()
        storage.delete_files([own])  # the app's copy, and its emptied folders
        changed += 1
    _tidy(app_root)
    return changed


def _target(v, file_path: str | None) -> str | None:
    """Where a version's preview belongs: next to its file; a pruned 3MF's in its version folder in the 3MF folder.
    None when that can't be reached right now."""
    if file_path:
        return storage.preview_beside(file_path) if os.path.isfile(file_path) else None
    if isinstance(v, BundleVersion):  # pruned: no 3MF left to sit beside
        try:
            storage.ready_root("threemf")
        except storage.StorageUnavailableError:
            return None
        return storage.preview_beside(str(storage.bundle_version_dir(v.bundle_id, v.version) / v.filename))
    return None


def _tidy(app_root: Path) -> None:
    """Remove the app's preview folders once they're empty (only empty folders, never anything else)."""
    if not app_root.is_dir():
        return
    for d in sorted((p for p in app_root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        storage._rmdir_if_empty(d)
    storage._rmdir_if_empty(app_root)
