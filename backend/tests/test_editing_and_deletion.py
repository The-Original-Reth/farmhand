from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select

from app.models import Bundle, BundleVersion, SourceModel
from app.services import bundle_service, printer_service, source_model_service

from . import factories as make


# ------------------------------------------------------------------ printers


def test_update_printer_edits_fields_and_clears_ips(db_session):
    p = printer_service.create_printer(
        db_session, name="Old", kind="Voron", wired_ip="10.0.0.1", wireless_ip="10.0.0.2"
    )
    updated = printer_service.update_printer(
        db_session, p.id, {"name": "New", "kind": "Trident", "wired_ip": None, "decommissioned": True}
    )
    assert updated.name == "New"
    assert updated.kind == "Trident"
    assert updated.wired_ip is None  # explicitly cleared
    assert updated.wireless_ip == "10.0.0.2"  # not mentioned, untouched
    assert updated.decommissioned is True


def test_update_printer_rejects_duplicate_name(db_session):
    printer_service.create_printer(db_session, name="A", kind=None, wired_ip=None, wireless_ip=None)
    b = printer_service.create_printer(db_session, name="B", kind=None, wired_ip=None, wireless_ip=None)
    with pytest.raises(ValueError, match="already exists"):
        printer_service.update_printer(db_session, b.id, {"name": "A"})


def test_a_decommissioned_printer_is_deleted_with_everything_kept_about_it(api):
    pid = api.post("/printers", json={"name": "Old V2", "wired_ip": "10.0.6.21"}).json()["id"]
    api.put(f"/printers/{pid}/notes", json={"notes": "belt replaced", "base_revision": 0}).raise_for_status()
    api.post(f"/printers/{pid}/sub-printers", json={"name": "0.6 nozzle"}).raise_for_status()

    assert api.delete(f"/printers/{pid}").status_code == 409  # no confirm=true
    r = api.delete(f"/printers/{pid}", params={"confirm": "true"})
    assert r.status_code == 409 and "Decommission it first" in r.json()["detail"]  # still active

    api.patch(f"/printers/{pid}/decommission", json={"decommissioned": True}).raise_for_status()
    assert api.delete(f"/printers/{pid}", params={"confirm": "true"}).status_code == 204
    assert api.get(f"/printers/{pid}").status_code == 404
    assert api.get("/printers").json() == []
    assert api.delete(f"/printers/{pid}", params={"confirm": "true"}).status_code == 404


def test_a_printer_with_3mf_files_isnt_deleted(db_session, sample_3mf_paths):
    printer = make.printer(db_session, "VT 1190")
    make.bundle(db_session, sample_3mf_paths["shark_vt1190"], printer_id=printer.id)
    printer_service.set_decommissioned(db_session, printer.id, True)
    with pytest.raises(ValueError, match="still has 1 3MF file. Delete it from its page first"):
        printer_service.delete_printer(db_session, printer.id)
    assert printer_service.get_printer(db_session, printer.id) is not None


def test_renamed_printer_still_matches_files_sliced_under_old_name(db_session, sample_3mf_paths):
    path = sample_3mf_paths["shark_vt1190"]  # sliced for "VT 1190"
    printer = make.printer(db_session, "VT 1190")
    bundle = make.bundle(db_session, path, [make.model(db_session)])

    printer_service.update_printer(db_session, printer.id, {"name": "Trident"})

    # A new file sliced under the old profile name still finds the renamed printer...
    with open(path, "rb") as f:
        result = bundle_service.inspect_3mf(db_session, f)
    assert result["matched_printer"].id == printer.id

    # ...and an "Update" to the existing bundle is not rejected as a wrong-printer file
    v2 = make.add_version(db_session, bundle, path)
    assert v2.version == 2


# ------------------------------------------------------------------ 3MF deletion


def test_delete_version_removes_its_files_but_keeps_bundle(db_session, sample_3mf_paths):
    path = sample_3mf_paths["shark_vt1190"]
    make.printer(db_session)
    bundle = make.bundle(db_session, path, [make.model(db_session)])
    make.add_version(db_session, bundle, path)
    db_session.refresh(bundle)

    v1 = next(v for v in bundle.versions if v.version == 1)
    v1_id, v1_3mf = v1.id, v1.threemf_path
    assert os.path.exists(v1_3mf)

    assert bundle_service.delete_bundle_version(db_session, v1_id) is False

    assert not os.path.exists(v1_3mf)
    db_session.expire_all()
    assert db_session.get(BundleVersion, v1_id) is None
    assert [v.version for v in db_session.get(Bundle, bundle.id).versions] == [2]


def test_deleting_the_only_version_deletes_the_whole_bundle(db_session, sample_3mf_paths):
    make.printer(db_session)
    bundle = make.bundle(db_session, sample_3mf_paths["shark_vt1190"], [make.model(db_session)])
    bundle_id = bundle.id
    only_version = bundle.versions[0]
    path_on_disk = only_version.threemf_path

    assert bundle_service.delete_bundle_version(db_session, only_version.id) is True

    assert not os.path.exists(path_on_disk)
    db_session.expire_all()
    assert db_session.get(Bundle, bundle_id) is None


def test_delete_bundle_removes_all_versions_and_files(db_session, sample_3mf_paths):
    path = sample_3mf_paths["shark_vt1190"]
    make.printer(db_session)
    bundle = make.bundle(db_session, path, [make.model(db_session)])
    make.add_version(db_session, bundle, path)
    db_session.refresh(bundle)
    bundle_id = bundle.id
    files = [v.threemf_path for v in bundle.versions]
    assert all(os.path.exists(p) for p in files)

    bundle_service.delete_bundle(db_session, bundle_id)

    assert not any(os.path.exists(p) for p in files)
    db_session.expire_all()
    assert db_session.get(Bundle, bundle_id) is None
    remaining = db_session.scalar(
        select(func.count()).select_from(BundleVersion).where(BundleVersion.bundle_id == bundle_id)
    )
    assert remaining == 0


# ------------------------------------------------------------------ STL deletion


def test_delete_source_model_refused_while_a_bundle_depends_only_on_it(db_session, sample_3mf_paths):
    make.printer(db_session)
    model = make.model(db_session)
    make.bundle(db_session, sample_3mf_paths["shark_vt1190"], [model])

    with pytest.raises(ValueError, match="sliced only from this model"):
        source_model_service.delete_source_model(db_session, model.id, cascade=False)
    assert db_session.get(SourceModel, model.id) is not None  # nothing was deleted


def test_delete_source_model_with_cascade_also_deletes_its_exclusive_bundles(db_session, sample_3mf_paths):
    make.printer(db_session)
    model = make.model(db_session, data=b"not a real stl, thumbnailing just fails soft")
    bundle = make.bundle(db_session, sample_3mf_paths["shark_vt1190"], [model])
    model_id, bundle_id = model.id, bundle.id

    deleted = source_model_service.delete_source_model(db_session, model_id, cascade=True)

    assert deleted == [bundle_id]
    db_session.expire_all()
    assert db_session.get(SourceModel, model_id) is None
    assert db_session.get(Bundle, bundle_id) is None


def test_delete_source_model_keeps_mixed_plate_bundles_just_unlinked(db_session, sample_3mf_paths):
    make.printer(db_session)
    frog_v = make.model(db_session, "Frog_vertical.stl")
    frog_h = make.model(db_session, "Frog_horizontal.stl")
    bundle = make.bundle(db_session, sample_3mf_paths["frog_vt1190"], [frog_v, frog_h])
    bundle_id, frog_h_id = bundle.id, frog_h.id

    # No cascade needed: the bundle also uses another model, so it survives
    assert source_model_service.delete_source_model(db_session, frog_v.id, cascade=False) == []

    db_session.expire_all()
    surviving = db_session.get(Bundle, bundle_id)
    assert surviving is not None
    assert [m.id for m in surviving.source_models] == [frog_h_id]


def test_delete_source_model_version_keeps_the_folder(db_session):
    model = make.model(db_session, data=b"not a real stl, thumbnailing just fails soft")
    version = model.versions[0]
    file_path = version.file_path
    assert os.path.exists(file_path)

    source_model_service.delete_source_model_version(db_session, model.id, version.version)

    assert not os.path.exists(file_path)
    db_session.expire_all()
    assert db_session.get(SourceModel, model.id) is not None
    assert db_session.get(SourceModel, model.id).versions == []
