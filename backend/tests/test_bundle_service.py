from __future__ import annotations

import io

import pytest

from app.models import SourceFileType
from app.services import bundle_service, printer_service, source_model_service


def _fake_gcode():
    return io.BytesIO(b"; fake gcode for tests\nG28\n")


def _setup_printer_and_model(db, printer_name: str):
    printer = printer_service.create_printer(
        db, name=printer_name, kind="Test printer", wired_ip="10.0.0.1", wireless_ip=None
    )
    model = source_model_service.create_source_model(
        db, name="TestModel.stl", file_type=SourceFileType.stl
    )
    return printer, model


def test_first_version_is_monument_by_default(db_session, sample_3mf_paths):
    printer, model = _setup_printer_and_model(db_session, "VT 1190")

    with open(sample_3mf_paths["shark_vt1190"], "rb") as f:
        bundle = bundle_service.create_bundle(
            db_session,
            source_model_ids=[model.id],
            threemf_file_obj=f,
            threemf_filename="shark.3mf",
            gcode_file_obj=_fake_gcode(),
            gcode_filename="shark.gcode",
        )

    assert len(bundle.versions) == 1
    v1 = bundle.versions[0]
    assert v1.version == 1
    assert v1.monument is True
    assert v1.monument_note == "Initial upload"
    assert v1.full_files_retained is True


def test_inspect_reports_unregistered_printer(db_session, sample_3mf_paths):
    # Nothing registered yet, so the file's printer ("VT 1190") has no match
    with open(sample_3mf_paths["shark_vt1190"], "rb") as f:
        result = bundle_service.inspect_3mf(db_session, f)
    assert result["printer_profile_name"] == "VT 1190"
    assert result["matched_printer"] is None


def test_inspect_finds_registered_printer(db_session, sample_3mf_paths):
    printer, _ = _setup_printer_and_model(db_session, "VT 1190")
    with open(sample_3mf_paths["shark_vt1190"], "rb") as f:
        result = bundle_service.inspect_3mf(db_session, f)
    assert result["matched_printer"].id == printer.id


def test_explicit_printer_overrides_embedded_profile(db_session, sample_3mf_paths):
    """Picking an existing printer by hand works even if its name differs from the file's profile."""
    printer = printer_service.create_printer(
        db_session, name="Some Other Printer", kind=None, wired_ip=None, wireless_ip=None
    )
    model = source_model_service.create_source_model(
        db_session, name="TestModel.stl", file_type=SourceFileType.stl
    )
    with open(sample_3mf_paths["shark_vt1190"], "rb") as f:  # sliced for "VT 1190"
        bundle = bundle_service.create_bundle(
            db_session,
            source_model_ids=[model.id],
            threemf_file_obj=f,
            threemf_filename="shark.3mf",
            printer_id=printer.id,
        )
    assert bundle.printer_id == printer.id


def test_gcode_is_optional(db_session, sample_3mf_paths):
    printer, model = _setup_printer_and_model(db_session, "VT 1190")

    with open(sample_3mf_paths["shark_vt1190"], "rb") as f:
        bundle = bundle_service.create_bundle(
            db_session,
            source_model_ids=[model.id],
            threemf_file_obj=f,
            threemf_filename="shark.3mf",
            # no gcode_file_obj / gcode_filename at all
        )

    v1 = bundle.versions[0]
    assert v1.threemf_path is not None
    assert v1.gcode_path is None
    assert v1.full_files_retained is True  # a missing gcode doesn't count as "pruned"


def test_printer_auto_detected_from_3mf_when_omitted(db_session, sample_3mf_paths):
    printer, model = _setup_printer_and_model(db_session, "VT 1190")  # name must match the 3MF's profile

    with open(sample_3mf_paths["shark_vt1190"], "rb") as f:
        bundle = bundle_service.create_bundle(
            db_session,
            source_model_ids=[model.id],
            threemf_file_obj=f,
            threemf_filename="shark.3mf",
            gcode_file_obj=_fake_gcode(),
            gcode_filename="shark.gcode",
            printer_id=None,  # not provided — must be read from the file
        )

    assert bundle.printer_id == printer.id


def test_create_bundle_raises_if_no_matching_printer_registered(db_session, sample_3mf_paths):
    # No printer named "VT 1190" registered at all
    model = source_model_service.create_source_model(
        db_session, name="TestModel.stl", file_type=SourceFileType.stl
    )
    with open(sample_3mf_paths["shark_vt1190"], "rb") as f:
        with pytest.raises(ValueError, match="no printer with that exact name is registered"):
            bundle_service.create_bundle(
                db_session,
                source_model_ids=[model.id],
                threemf_file_obj=f,
                threemf_filename="shark.3mf",
                gcode_file_obj=_fake_gcode(),
                gcode_filename="shark.gcode",
            )


def test_printer_locked_rejects_mismatched_update(db_session, sample_3mf_paths):
    printer, model = _setup_printer_and_model(db_session, "VT 1190")
    with open(sample_3mf_paths["shark_vt1190"], "rb") as f:
        bundle = bundle_service.create_bundle(
            db_session,
            source_model_ids=[model.id],
            threemf_file_obj=f,
            threemf_filename="shark.3mf",
            gcode_file_obj=_fake_gcode(),
            gcode_filename="shark.gcode",
        )

    # Try to "update" this VT-1190-locked bundle with a file sliced for V2 BOG
    with open(sample_3mf_paths["shark_v2bog"], "rb") as f:
        with pytest.raises(ValueError, match="Wrong printer: this 3MF was sliced for"):
            bundle_service.add_bundle_version(
                db_session,
                bundle_id=bundle.id,
                threemf_file_obj=f,
                threemf_filename="shark_v2.3mf",
                gcode_file_obj=_fake_gcode(),
                gcode_filename="shark_v2.gcode",
            )


def test_rolling_window_prunes_oldest_non_monument_version(db_session, sample_3mf_paths):
    """
    The core versioning rule from spec: the most recent 5 versions always
    keep their full files; anything older gets pruned UNLESS it's a
    monument. Reuploading the same real file repeatedly to build up
    version history — the rule under test doesn't depend on the settings
    changing between versions, just the count and monument flags.
    """
    printer, model = _setup_printer_and_model(db_session, "VT 1190")

    def upload(threemf_file_obj):
        return bundle_service.add_bundle_version(
            db_session,
            bundle_id=bundle.id,
            threemf_file_obj=threemf_file_obj,
            threemf_filename="shark.3mf",
            gcode_file_obj=_fake_gcode(),
            gcode_filename="shark.gcode",
        )

    with open(sample_3mf_paths["shark_vt1190"], "rb") as f:
        bundle = bundle_service.create_bundle(
            db_session,
            source_model_ids=[model.id],
            threemf_file_obj=f,
            threemf_filename="shark.3mf",
            gcode_file_obj=_fake_gcode(),
            gcode_filename="shark.gcode",
        )  # v1, monument=True by default

    for _ in range(6):  # v2 through v7
        with open(sample_3mf_paths["shark_vt1190"], "rb") as f:
            upload(f)

    db_session.refresh(bundle)
    versions_by_number = {v.version: v for v in bundle.versions}
    assert set(versions_by_number) == {1, 2, 3, 4, 5, 6, 7}

    # v1: monument, exempt from pruning even though it's outside the window
    assert versions_by_number[1].full_files_retained is True
    assert versions_by_number[1].threemf_path is not None

    # v2: oldest NON-monument version, now outside the most-recent-5 window
    v2 = versions_by_number[2]
    assert v2.full_files_retained is False
    assert v2.threemf_path is None
    assert v2.gcode_path is None
    assert v2.settings, "parsed settings must survive pruning"
    assert v2.thumbnail_path is not None, "thumbnail must survive pruning"

    # v3–v7: the most recent 5, still full
    for n in (3, 4, 5, 6, 7):
        assert versions_by_number[n].full_files_retained is True
        assert versions_by_number[n].threemf_path is not None


def test_mixed_plate_bundle_links_multiple_source_models(db_session, sample_3mf_paths):
    """The corrected many-to-many relationship — one 3MF, multiple source models."""
    printer_service.create_printer(  # the printer the 3MF was sliced for has to be registered
        db_session, name="VT 1190", kind="Test printer", wired_ip=None, wireless_ip=None
    )
    frog_v = source_model_service.create_source_model(
        db_session, name="Frog_verticalEyes.stl", file_type=SourceFileType.stl
    )
    frog_h = source_model_service.create_source_model(
        db_session, name="Frog_horizontalEyes.stl", file_type=SourceFileType.stl
    )

    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        bundle = bundle_service.create_bundle(
            db_session,
            source_model_ids=[frog_v.id, frog_h.id],
            threemf_file_obj=f,
            threemf_filename="frog.3mf",
            gcode_file_obj=_fake_gcode(),
            gcode_filename="frog.gcode",
        )

    linked_ids = {m.id for m in bundle.source_models}
    assert linked_ids == {frog_v.id, frog_h.id}
