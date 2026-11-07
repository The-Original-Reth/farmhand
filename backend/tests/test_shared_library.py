from __future__ import annotations

import io
import os
import struct

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import storage
from app.database import Base
from app.models import Bundle, BundleSourceModel, BundleStar, BundleVersion, SourceFileType, SourceModel
from app.services import library_records, printer_service, source_model_service


def _stl() -> bytes:
    tri = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 10, 0, 0, 0, 10, 0, 0)
    return b"\0" * 80 + struct.pack("<I", 1) + tri


@pytest.fixture()
def other_farmhand():
    """A second Farmhand: its own (empty) database, sharing the same folders."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    yield db
    db.close()


def _goldfish(db) -> tuple[SourceModel, Bundle]:
    """A model (two versions, with notes) and a 3MF sliced from it for the V2 BOG, two versions, the first starred."""
    model = source_model_service.create_source_model(db, name="Goldfish.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(_stl()))
    source_model_service.add_source_model_version(db, source_model_id=model.id, file_obj=io.BytesIO(_stl()), filename="Goldfish.stl", note="Thicker fins")
    source_model_service.set_notes(db, model.id, "Print it standing up", 0)
    printer = printer_service.create_printer(db, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)
    bundle = Bundle(printer_id=printer.id)
    db.add(bundle)
    db.flush()
    db.add(BundleSourceModel(bundle_id=bundle.id, source_model_id=model.id))
    for n in (1, 2):
        d = storage.bundle_version_dir(bundle.id, n, fresh=True)
        threemf = d / f"Goldfish ver {n}.3mf"
        threemf.write_bytes(b"3mf %d" % n)
        (d / f"Goldfish ver {n}.gcode").write_bytes(b"G28")
        db.add(BundleVersion(
            bundle_id=bundle.id, version=n, filename=threemf.name, slicer_family="orcaslicer", slicer_display_name="OrcaSlicer 2.3",
            printer_profile_name="V2 BOG", threemf_path=str(threemf), gcode_path=str(d / f"Goldfish ver {n}.gcode"),
            settings={"layer_height": "0.2", "n": n},
        ))
    db.flush()
    first = db.query(BundleVersion).filter_by(bundle_id=bundle.id, version=1).one()
    bundle.star_row = BundleStar(bundle_id=bundle.id, version_id=first.id)
    db.commit()
    assert library_records.write_model(db, model.id) and library_records.write_bundle(db, bundle.id)
    return model, bundle


def test_models_and_3mfs_come_into_another_farmhand_from_their_records(db_session, other_farmhand):
    model, bundle = _goldfish(db_session)
    printer_service.create_printer(other_farmhand, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)

    out = library_records.import_library(other_farmhand)
    assert out == {"models": ["Goldfish.stl"], "threemfs": ["Goldfish ver 2.3mf"], "skipped": []}

    there = other_farmhand.query(SourceModel).one()
    assert there.name == "Goldfish.stl" and there.notes == "Print it standing up"
    by_version = lambda vs: [v.file_path for v in sorted(vs, key=lambda v: v.version)]  # noqa: E731
    assert by_version(there.versions) == by_version(model.versions)
    assert sorted(v.note or "" for v in there.versions) == ["", "Thicker fins"]

    b = other_farmhand.query(Bundle).one()
    assert b.printer.name == "V2 BOG" and [link.source_model.name for link in b.source_model_links] == ["Goldfish.stl"]
    versions = sorted(b.versions, key=lambda v: v.version)
    assert [v.threemf_path for v in versions] == [v.threemf_path for v in sorted(bundle.versions, key=lambda v: v.version)]
    assert versions[1].gcode_path.endswith("Goldfish ver 2.gcode") and versions[1].settings == {"layer_height": "0.2", "n": 2}
    assert b.star_row.version.version == 1

    assert library_records.import_library(other_farmhand) == {"models": [], "threemfs": [], "skipped": []}  # once


def test_a_3mf_for_a_printer_not_here_waits_for_it(db_session, other_farmhand):
    _goldfish(db_session)
    out = library_records.import_library(other_farmhand)
    assert out["threemfs"] == [] and "V2 BOG, which isn't here" in out["skipped"][0]["reason"]
    printer_service.create_printer(other_farmhand, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)
    assert library_records.import_library(other_farmhand)["threemfs"] == ["Goldfish ver 2.3mf"]


def test_the_models_scan_leaves_another_farmhands_files_alone(db_session, other_farmhand):
    _goldfish(db_session)
    root = storage.effective_root("stl")
    (root / "Dropped in.stl").write_bytes(_stl())  # a file someone copied there: that one is offered
    found = [f["name"] for f in source_model_service.scan_for_new_files(other_farmhand)["files"]]
    assert found == ["Dropped in.stl"]


def test_a_pruned_version_comes_back_with_its_settings(db_session, other_farmhand):
    _, bundle = _goldfish(db_session)
    first = next(v for v in bundle.versions if v.version == 1)
    os.remove(first.threemf_path)  # pruned on the first Farmhand: only the second version's 3MF is left
    first.threemf_path, first.gcode_path, first.full_files_retained = None, None, False
    db_session.commit()
    library_records.write_bundle(db_session, bundle.id)
    printer_service.create_printer(other_farmhand, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)
    library_records.import_library(other_farmhand)
    v1 = other_farmhand.query(BundleVersion).filter_by(version=1).one()
    assert not v1.full_files_retained and v1.threemf_path is None and v1.settings["n"] == 1


def test_models_another_farmhand_moved_are_relinked_and_their_doubles_taken_out(db_session, other_farmhand):
    """The Pi's case: the other Farmhand's Models scan (before it left other Farmhands' files alone) took the first
    one's STLs in and moved them; the first then brought those in again as new models from the other's records."""
    # a model (one version, as the Pi's were) with notes, and a 3MF sliced from it
    model = source_model_service.create_source_model(db_session, name="Flexi-Rex.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(_stl()))
    source_model_service.set_notes(db_session, model.id, "Print it standing up", 0)
    printer = printer_service.create_printer(db_session, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)
    bundle = Bundle(printer_id=printer.id)
    db_session.add(bundle)
    db_session.flush()
    db_session.add(BundleSourceModel(bundle_id=bundle.id, source_model_id=model.id))
    db_session.commit()
    files = list(model.versions)
    # the other Farmhand takes in each file where it lies, moving it into its own folders (as its scan used to)
    for v in files:
        source_model_service.import_scanned_file(other_farmhand, v.file_path)
    for m in other_farmhand.query(SourceModel):
        library_records.write_model(other_farmhand, m.id)
    assert not any(os.path.exists(v.file_path) for v in files)  # gone from where the first Farmhand put them

    library_records.import_models(db_session)  # ...and brought in again as a new model (the double)
    assert db_session.query(SourceModel).count() == 2

    out = library_records.import_library(db_session)
    assert out["models"] == []
    left = db_session.query(SourceModel).all()
    assert [m.id for m in left] == [model.id]  # the doubles taken out, the original kept
    kept = left[0]
    assert kept.notes == "Print it standing up" and kept.bundle_links[0].bundle_id == bundle.id
    assert all(os.path.isfile(v.file_path) for v in kept.versions)  # pointed at its files where they are now
    assert {os.path.realpath(v.file_path) for v in kept.versions} == {
        os.path.realpath(v.file_path) for m in other_farmhand.query(SourceModel) for v in m.versions
    }


def test_a_model_used_by_a_3mf_is_never_taken_out_as_a_double(db_session):
    a = source_model_service.create_source_model(db_session, name="Fin.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(_stl()))
    b = SourceModel(name="Fin.stl", file_type=SourceFileType.stl)
    db_session.add(b)
    db_session.flush()
    from app.models import SourceModelVersion

    db_session.add(SourceModelVersion(source_model_id=b.id, version=1, file_path=a.versions[0].file_path))
    printer = printer_service.create_printer(db_session, name="P", kind=None, wired_ip=None, wireless_ip=None)
    bundle = Bundle(printer_id=printer.id)
    db_session.add(bundle)
    db_session.flush()
    db_session.add(BundleSourceModel(bundle_id=bundle.id, source_model_id=b.id))
    db_session.commit()
    assert library_records.drop_doubles(db_session) == []  # b is used: kept
    assert db_session.query(SourceModel).count() == 2
