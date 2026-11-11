"""A 3MF's versions over time: the rolling window that prunes old files (monuments excepted), downloading a version,
renaming one, and deleting a version or a whole 3MF.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import storage
from ...config import settings
from ...models import Bundle, BundleVersion
from ...names import clean_file_name
from ...parsers.gcode import GCODE_EXTENSIONS, printer_profile
from .marks import star_newest_if_none
from .queries import require_bundle, require_version


def enforce_rolling_window(db: Session, bundle: Bundle) -> None:
    """
    Per spec: the full-file window always covers the most recent N
    versions (N = settings.full_file_version_window, default 5). Any
    version older than that window gets its 3MF/gcode deleted — UNLESS
    it's flagged as a monument, which exempts it from pruning entirely.
    Parsed settings and the thumbnail are always kept, pruned or not.
    """
    db.flush()
    all_versions = list(
        db.scalars(
            select(BundleVersion)
            .where(BundleVersion.bundle_id == bundle.id)
            .order_by(BundleVersion.version.desc())
        )
    )

    window = settings.full_file_version_window
    outside_window = all_versions[window:]

    for v in outside_window:
        if v.full_files_retained and not v.monument:
            # the preview stays where it is (next to where the 3MF was): a pruned version keeps its picture
            beside = storage.preview_beside(v.threemf_path)
            storage.delete_files([v.threemf_path, v.gcode_path, beside if beside != v.thumbnail_path else None])
            v.threemf_path = None
            v.gcode_path = None
            v.full_files_retained = False
            db.add(v)


def download_bundle_version(db: Session, version_id: int) -> tuple[str, str | None]:
    """
    Returns (threemf_path, gcode_path) — gcode_path may be None if gcode
    was never uploaded for this version (it's optional). Raises if this
    version has been pruned (no files left for either).
    """
    version = require_version(db, version_id)
    if not version.full_files_retained:
        raise ValueError(
            "This version's original files were pruned (parsed parameters are still available, "
            "but there's no 3MF/gcode left to download)"
        )
    return version.threemf_path, version.gcode_path


def _files_of(v: BundleVersion) -> list[str | None]:
    """Every file a version has: its 3MF, G-code and preview (kept beside the 3MF, or where it was if it's pruned)."""
    return [v.threemf_path, v.gcode_path, v.thumbnail_path, storage.preview_beside(v.threemf_path)]




def check_gcode_name(filename: str | None) -> None:
    """A G-code must be a sliced .gcode or .bgcode (any case), whether it comes with a 3MF or on its own."""
    if os.path.splitext(filename or "")[1].lower() not in GCODE_EXTENSIONS:
        raise ValueError("Pick a sliced .gcode or .bgcode file")


def wrong_printer(what: str, sliced_for: str, printer_name: str) -> str:
    """The message for a 3MF or G-code sliced for another printer than the one its 3MF entry belongs to."""
    return (
        f"Wrong printer: this {what} was sliced for \"{sliced_for}\", but this 3MF belongs to \"{printer_name}\". "
        f"Slice it again with the \"{printer_name}\" printer profile, or upload it as a new 3MF for \"{sliced_for}\"."
    )


def known_profiles(bundle: Bundle) -> set[str]:
    """
    The printer profile names a 3MF's files may be sliced under: its printer's name now, or any profile its versions
    were sliced under (the printer may have been renamed since).
    """
    return {bundle.printer.name} | {v.printer_profile_name for v in bundle.versions if v.printer_profile_name}


def check_gcode_printer(file_obj, filename: str | None, allowed: set[str], printer_name: str) -> None:
    """A G-code sliced for another printer is refused. One whose printer can't be read is taken as it is."""
    sliced_for = printer_profile(file_obj, filename)
    if sliced_for and sliced_for not in allowed:
        raise ValueError(wrong_printer("G-code", sliced_for, printer_name))


def attach_gcode(db: Session, version_id: int, file_obj, filename: str) -> BundleVersion:
    """
    Give a 3MF version its G-code (sliced from it), replacing one it already had. It's kept beside the version's 3MF.
    """
    version = require_version(db, version_id)
    check_gcode_name(filename)
    if not version.full_files_retained or not version.threemf_path:
        raise ValueError("This version's files were pruned, so it can't be given a G-code any more")
    check_gcode_printer(file_obj, filename, known_profiles(version.bundle), version.bundle.printer.name)
    old = version.gcode_path
    new = storage.save_upload(Path(version.threemf_path).parent, filename, file_obj)
    version.gcode_path = new
    db.commit()
    if old and os.path.abspath(old) != os.path.abspath(new):
        storage.delete_files([old])
    db.refresh(version)
    return version


def delete_bundle(db: Session, bundle_id: int) -> None:
    """Permanently delete a bundle: every version's row, parsed settings, and stored files."""
    bundle = require_bundle(db, bundle_id)
    paths = [p for v in bundle.versions for p in _files_of(v)]
    db.delete(bundle)  # cascades to its versions and its source-model links
    db.commit()
    # Files go after the DB commit: if this fails the records are already
    # consistent, and a few orphaned files on disk are harmless. Only the files
    # recorded for these versions are removed (wherever they live).
    storage.delete_files(paths)


def delete_bundle_version(db: Session, version_id: int) -> bool:
    """
    Permanently delete one version (its 3MF, gcode, thumbnail, and parsed
    settings). If it was the bundle's only version, the whole bundle goes
    with it — a bundle with no versions has nothing left to show.
    Returns True if the whole bundle was deleted.
    """
    version = require_version(db, version_id)
    bundle = version.bundle
    if len(bundle.versions) <= 1:
        delete_bundle(db, bundle.id)
        return True
    paths = _files_of(version)
    if bundle.star_row is not None and bundle.star_row.version_id == version.id:
        bundle.star_row = None  # the starred version is going: its star moves to the newest one left
        db.flush()
        star_newest_if_none(bundle, [v for v in bundle.versions if v.id != version.id])
    db.delete(version)
    db.commit()
    storage.delete_files(paths)
    return False


def rename_version(db: Session, version_id: int, filename: str) -> BundleVersion:
    """
    Change the file name a 3MF version is shown and downloaded as; it always stays a .3mf. The stored file keeps
    the name it was saved under, so nothing on disk moves.
    """
    version = require_version(db, version_id)
    version.filename = clean_file_name(filename, extension=".3mf")
    db.commit()
    db.refresh(version)
    return version
