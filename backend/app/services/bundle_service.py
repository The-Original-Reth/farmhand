from __future__ import annotations

import os
import tempfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import notes as notes_helper
from .. import storage
from . import printer_service
from ..config import settings
from ..models import Bundle, BundleNote, BundleSourceModel, BundleStar, BundleVersion, Printer, SourceModel
from ..parsers import parse_3mf


def get_bundle(db: Session, bundle_id: int) -> Bundle | None:
    return db.get(Bundle, bundle_id)


def list_all_bundles(db: Session) -> list[Bundle]:
    return list(db.scalars(select(Bundle)))


def list_bundles_for_printer(db: Session, printer_id: int) -> list[Bundle]:
    return list(db.scalars(select(Bundle).where(Bundle.printer_id == printer_id)))


def list_bundles_for_source_model(db: Session, source_model_id: int) -> list[Bundle]:
    return list(
        db.scalars(
            select(Bundle)
            .join(BundleSourceModel)
            .where(BundleSourceModel.source_model_id == source_model_id)
        )
    )


def _parse_upload_to_tempfile(threemf_file_obj) -> tuple[str, "object"]:
    """
    Our parser reads from a path (it needs real zip seek access), but
    uploads arrive as file-like objects — spool to a tempfile first, parse
    it, and hand the tempfile path back so the caller can also use it for
    the permanent copy without re-reading the upload stream twice.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".3mf", delete=False)
    tmp.write(threemf_file_obj.read())
    tmp.close()
    try:
        parsed = parse_3mf(tmp.name)
    except Exception:
        os.remove(tmp.name)  # don't leak a multi-MB tempfile per rejected upload
        raise
    return tmp.name, parsed


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def inspect_3mf(db: Session, threemf_file_obj) -> dict:
    """
    Read a 3MF without storing anything: which printer profile was it sliced
    for, and is a printer with that exact name already registered? Lets the
    upload form offer "create it from the file" or "pick an existing one"
    up front, instead of failing at submit time.
    """
    tmp_path, parsed = _parse_upload_to_tempfile(threemf_file_obj)
    try:
        matched = None
        if parsed.printer_profile_name:
            matched = printer_service.find_by_profile_name(db, parsed.printer_profile_name)
        return {
            "printer_profile_name": parsed.printer_profile_name,
            "slicer_display_name": parsed.slicer_display_name,
            "matched_printer": matched,
        }
    finally:
        os.remove(tmp_path)


def create_bundle(
    db: Session,
    *,
    source_model_ids: list[int],
    threemf_file_obj,
    threemf_filename: str,
    gcode_file_obj=None,
    gcode_filename: str | None = None,
    printer_id: int | None = None,
) -> Bundle:
    """
    Create a brand-new bundle (a new 3MF+printer version tree) and its
    first version (version 1, monument by default per spec).

    Per the upload-flow UI decision: printer_id is optional here. When
    omitted, the printer is read from the 3MF's own embedded profile
    (physical_printer_settings_id) rather than asked for — there must
    already be a matching Printer registered by that exact name, or this
    raises rather than silently inventing a printer record.

    gcode is optional (NOTE: this relaxes the original spec's "3MF and
    gcode files must be uploaded together" rule — real usage showed gcode
    isn't always on hand at upload time; the written spec doc should be
    updated to reflect this).
    """
    if not source_model_ids:
        raise ValueError("A bundle needs at least one source model (a 3MF is sliced from something)")

    tmp_path, parsed = _parse_upload_to_tempfile(threemf_file_obj)
    try:

        printer = None
        if printer_id is not None:
            printer = db.get(Printer, printer_id)
            if printer is None:
                raise ValueError(f"No printer with id {printer_id}")
        else:
            if not parsed.printer_profile_name:
                raise ValueError(
                    "This 3MF has no printer profile embedded in it — a printer must be selected manually"
                )
            printer = printer_service.find_by_profile_name(db, parsed.printer_profile_name)
            if printer is None:
                raise ValueError(
                    f"3MF was sliced for printer {parsed.printer_profile_name!r}, but no printer with "
                    "that exact name is registered yet — add it to the printer registry first"
                )

        models = list(db.scalars(select(SourceModel).where(SourceModel.id.in_(source_model_ids))))
        if len(models) != len(source_model_ids):
            raise ValueError("One or more source_model_ids don't exist")

        bundle = Bundle(printer_id=printer.id)
        db.add(bundle)
        db.flush()

        for model in models:
            db.add(BundleSourceModel(bundle_id=bundle.id, source_model_id=model.id))

        _store_version(
            db,
            bundle=bundle,
            version_number=1,
            parsed=parsed,
            tmp_threemf_path=tmp_path,
            threemf_filename=threemf_filename,
            gcode_file_obj=gcode_file_obj,
            gcode_filename=gcode_filename,
            monument=True,  # first upload is a monument by default, per spec
            monument_note="Initial upload",
        )

        db.commit()
        db.refresh(bundle)
        return bundle
    except BaseException:
        _remove_quietly(tmp_path)  # a rejected upload must not leave its scratch copy behind
        raise


def add_bundle_version(
    db: Session,
    *,
    bundle_id: int,
    threemf_file_obj,
    threemf_filename: str,
    gcode_file_obj=None,
    gcode_filename: str | None = None,
) -> BundleVersion:
    """
    The 'Update' button: create a new version within an existing bundle.
    Printer is already locked — this only proceeds if the new 3MF's own
    embedded printer profile still matches, as a data-integrity check
    (catches 'wrong file dragged into the wrong folder' mistakes).
    """
    bundle = get_bundle(db, bundle_id)
    if bundle is None:
        raise ValueError(f"No bundle with id {bundle_id}")

    tmp_path, parsed = _parse_upload_to_tempfile(threemf_file_obj)
    try:

        # The printer may have been renamed since this bundle was created, so
        # accept its current name OR any profile name this bundle's earlier
        # versions were sliced under.
        known_profile_names = {bundle.printer.name} | {
            v.printer_profile_name for v in bundle.versions if v.printer_profile_name
        }
        if parsed.printer_profile_name and parsed.printer_profile_name not in known_profile_names:
            raise ValueError(
                f"This 3MF was sliced for printer {parsed.printer_profile_name!r}, but this bundle is "
                f"locked to {bundle.printer.name!r} — printer can't change after a bundle is created"
            )

        next_version = (bundle.latest_version.version + 1) if bundle.latest_version else 1

        version = _store_version(
            db,
            bundle=bundle,
            version_number=next_version,
            parsed=parsed,
            tmp_threemf_path=tmp_path,
            threemf_filename=threemf_filename,
            gcode_file_obj=gcode_file_obj,
            gcode_filename=gcode_filename,
            monument=False,
            monument_note=None,
        )

        _enforce_rolling_window(db, bundle)

        db.commit()
        db.refresh(version)
        return version
    except BaseException:
        _remove_quietly(tmp_path)  # a rejected upload must not leave its scratch copy behind
        raise


def _store_version(
    db: Session,
    *,
    bundle: Bundle,
    version_number: int,
    parsed,
    tmp_threemf_path: str,
    threemf_filename: str,
    gcode_file_obj,
    gcode_filename: str | None,
    monument: bool,
    monument_note: str | None,
) -> BundleVersion:
    written: list[str] = []  # everything put on disk so far, to undo if a later step fails
    try:
        # May raise StorageUnavailableError if the chosen 3MF folder looks unmounted
        dest_dir = storage.bundle_version_dir(bundle.id, version_number)

        threemf_path = storage.copy_verified(tmp_threemf_path, dest_dir, name=threemf_filename)
        written.append(threemf_path)

        gcode_path = None
        if gcode_file_obj is not None:
            gcode_path = storage.save_upload(dest_dir, gcode_filename, gcode_file_obj)
            written.append(gcode_path)

        thumbnail_path = None
        if parsed.thumbnail_bytes:
            thumb_dir = storage.bundle_thumbnail_dir(bundle.id, version_number)
            thumbnail_path = storage.save_bytes(thumb_dir, "thumbnail.png", parsed.thumbnail_bytes)
            written.append(thumbnail_path)

        version = BundleVersion(
            bundle_id=bundle.id,
            version=version_number,
            filename=threemf_filename,
            slicer_family=parsed.slicer_family,
            slicer_display_name=parsed.slicer_display_name,
            printer_profile_name=parsed.printer_profile_name,
            monument=monument,
            monument_note=monument_note,
            full_files_retained=True,
            threemf_path=threemf_path,
            gcode_path=gcode_path,
            thumbnail_path=thumbnail_path,
            settings=parsed.settings,
        )
        db.add(version)
        db.flush()
        return version
    except BaseException:
        storage.delete_files(written)
        raise
    finally:
        try:
            os.remove(tmp_threemf_path)  # the parsed upload's scratch copy
        except FileNotFoundError:
            pass


def _enforce_rolling_window(db: Session, bundle: Bundle) -> None:
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
            storage.delete_files([v.threemf_path, v.gcode_path])
            v.threemf_path = None
            v.gcode_path = None
            v.full_files_retained = False
            db.add(v)


def set_monument(
    db: Session, *, version_id: int, monument: bool, note: str | None = None, confirm: bool = False
) -> BundleVersion:
    version = db.get(BundleVersion, version_id)
    if version is None:
        raise ValueError(f"No bundle version with id {version_id}")

    if monument:
        if not note:
            raise ValueError("Monumenting a version requires a note explaining why it matters")
        version.monument = True
        version.monument_note = note
    else:
        if not confirm:
            raise ValueError(
                "Un-monumenting re-exposes this version to pruning — pass confirm=True to proceed"
            )
        version.monument = False

    db.commit()
    db.refresh(version)
    return version


def download_bundle_version(db: Session, version_id: int) -> tuple[str, str | None]:
    """
    Returns (threemf_path, gcode_path) — gcode_path may be None if gcode
    was never uploaded for this version (it's optional). Raises if this
    version has been pruned (no files left for either).
    """
    version = db.get(BundleVersion, version_id)
    if version is None:
        raise ValueError(f"No bundle version with id {version_id}")
    if not version.full_files_retained:
        raise ValueError(
            "This version's original files were pruned (parsed parameters are still available, "
            "but there's no 3MF/gcode left to download) — flag it as a monument before this "
            "happens to keep it downloadable"
        )
    return version.threemf_path, version.gcode_path


def delete_bundle(db: Session, bundle_id: int) -> None:
    """Permanently delete a bundle: every version's row, parsed settings, and stored files."""
    bundle = get_bundle(db, bundle_id)
    if bundle is None:
        raise ValueError(f"No bundle with id {bundle_id}")
    paths = [p for v in bundle.versions for p in (v.threemf_path, v.gcode_path, v.thumbnail_path)]
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
    version = db.get(BundleVersion, version_id)
    if version is None:
        raise ValueError(f"No bundle version with id {version_id}")
    bundle = version.bundle
    if len(bundle.versions) <= 1:
        delete_bundle(db, bundle.id)
        return True
    paths = [version.threemf_path, version.gcode_path, version.thumbnail_path]
    if bundle.star_row is not None and bundle.star_row.version_id == version.id:
        bundle.star_row = None  # the starred version is going: so is its star
    db.delete(version)
    db.commit()
    storage.delete_files(paths)
    return False


# ------------------------------------------------------------------ starring a 3MF


class StarNotAllowed(ValueError):
    """The version can't be starred (not part of this 3MF, or its initial version)."""


def set_starred_version(db: Session, bundle_id: int, version_id: int | None) -> Bundle:
    """
    Star one version of a 3MF (gold), or clear the star with None. Only one version per 3MF is starred: starring
    another moves the star there. Version 1, the initial upload, can't be starred (it always shows as silver).
    """
    bundle = get_bundle(db, bundle_id)
    if bundle is None:
        raise ValueError(f"No bundle with id {bundle_id}")
    if version_id is None:
        bundle.star_row = None  # delete-orphan removes the row
    else:
        version = db.get(BundleVersion, version_id)
        if version is None or version.bundle_id != bundle.id:
            raise StarNotAllowed(f"Version {version_id} isn't a version of this 3MF")
        if version.version == 1:
            raise StarNotAllowed("The initial version can't be starred")
        if bundle.star_row is None:
            bundle.star_row = BundleStar(bundle_id=bundle.id, version_id=version.id)
        else:
            bundle.star_row.version_id = version.id
    db.commit()
    db.refresh(bundle)
    return bundle


# ------------------------------------------------------------------ notes about a 3MF


class NotesConflict(Exception):
    """The notes were saved by someone else since the person started editing them."""

    def __init__(self, bundle: Bundle):
        super().__init__("These notes were changed by someone else while you were editing.")
        self.bundle = bundle


def set_notes(db: Session, bundle_id: int, notes: str, base_revision: int) -> Bundle:
    """Save the notes for a 3MF (the rules are in app/notes.py: conflict-safe, tidied, length-limited)."""
    bundle = get_bundle(db, bundle_id)
    if bundle is None:
        raise ValueError(f"No bundle with id {bundle_id}")
    return notes_helper.save(
        db, owner=bundle, note_cls=BundleNote, owner_key="bundle_id", base_revision=base_revision,
        notes=notes, conflict=NotesConflict, reload=lambda: get_bundle(db, bundle_id),
    )
