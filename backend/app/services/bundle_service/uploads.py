"""A new 3MF arriving: reading it without storing it (which printer it was sliced for), storing it as a new 3MF on
its printer, or as a new version of one already here. The file is spooled to a temporary copy first, since the
parser needs to seek in the zip.
"""
from __future__ import annotations

import os
import shutil
import tempfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import storage
from .. import printer_service, sub_printer_service
from ...names import with_version
from ...models import Bundle, BundleSourceModel, BundleVersion, Printer, SourceModel
from ...parsers import parse_3mf
from .marks import star_newest_if_none
from .queries import require_bundle
from .versions import _enforce_rolling_window, check_gcode_name, check_gcode_printer, known_profiles, wrong_printer


def _parse_upload_to_tempfile(threemf_file_obj) -> tuple[str, "object"]:
    """
    Our parser reads from a path (it needs real zip seek access), but
    uploads arrive as file-like objects — spool to a tempfile first, parse
    it, and hand the tempfile path back so the caller can also use it for
    the permanent copy without re-reading the upload stream twice.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".3mf", delete=False)
    shutil.copyfileobj(threemf_file_obj, tmp, 1024 * 1024)  # a piece at a time: never the whole 3MF in memory
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
            "printer_preset_name": parsed.printer_preset_name,
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
    sub_printer_id: int | None = None,
    new_sub_printer_name: str | None = None,
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
    if gcode_file_obj is not None:
        check_gcode_name(gcode_filename)

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

        if gcode_file_obj is not None:
            # the G-code goes with this 3MF: sliced for the same printer as it, or for the printer picked for it
            allowed = {printer.name} | ({parsed.printer_profile_name} if parsed.printer_profile_name else set())
            check_gcode_printer(gcode_file_obj, gcode_filename, allowed, printer.name)

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
            sub_printer_id=sub_printer_id,
            new_sub_printer_name=new_sub_printer_name,
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
    sub_printer_id: int | None = None,
    new_sub_printer_name: str | None = None,
) -> BundleVersion:
    """
    The 'Update' button: create a new version within an existing bundle.
    Printer is already locked — this only proceeds if the new 3MF's own
    embedded printer profile still matches, as a data-integrity check
    (catches 'wrong file dragged into the wrong folder' mistakes).
    """
    bundle = require_bundle(db, bundle_id)
    if gcode_file_obj is not None:
        check_gcode_name(gcode_filename)

    tmp_path, parsed = _parse_upload_to_tempfile(threemf_file_obj)
    try:

        # The printer may have been renamed since this bundle was created, so
        # accept its current name OR any profile name this bundle's earlier
        # versions were sliced under.
        known_profile_names = known_profiles(bundle)
        if parsed.printer_profile_name and parsed.printer_profile_name not in known_profile_names:
            raise ValueError(wrong_printer("3MF", parsed.printer_profile_name, bundle.printer.name))
        if gcode_file_obj is not None:
            check_gcode_printer(gcode_file_obj, gcode_filename, known_profile_names, bundle.printer.name)

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
            sub_printer_id=sub_printer_id,
            new_sub_printer_name=new_sub_printer_name,
        )

        _enforce_rolling_window(db, bundle)
        star_newest_if_none(bundle, [version])  # nothing starred yet: this newest version is

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
    sub_printer_id: int | None = None,
    new_sub_printer_name: str | None = None,
) -> BundleVersion:
    threemf_filename = with_version(threemf_filename, version_number)  # "Goldfish ver 2.3mf"
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
            # with the 3MF, on the NAS if it's there: the only copy, kept even when the 3MF is pruned
            thumbnail_path = storage.save_preview_beside(threemf_path, parsed.thumbnail_bytes)
            if thumbnail_path:
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
        # its printer profile: the one picked on upload (or a new one), else the one its printer preset goes to
        sub_printer_service.link(
            db, version, bundle.printer, parsed.printer_preset_name,
            sub_printer_id=sub_printer_id, new_name=new_sub_printer_name,
        )
        return version
    except BaseException:
        storage.delete_files(written)
        raise
    finally:
        _remove_quietly(tmp_threemf_path)  # the parsed upload's scratch copy
