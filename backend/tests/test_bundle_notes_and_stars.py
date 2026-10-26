from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from app.database import Base
from app.errors import NotFound
from app.models import Bundle, BundleNote, BundleStar
from app.schemas.bundle import BundleOut
from app.services import bundle_service as svc

from . import factories as make


def _bundle(db, sample_3mf_paths, key="frog_vt1190", printer_name="VT 1190"):
    printer = make.printer(db, printer_name)
    model = make.model(db, f"{key}.stl", b"x" * 64)
    return make.bundle(db, sample_3mf_paths[key], [model], f"{key}.3mf", gcode=None, printer_id=printer.id)


def _add_version(db, sample_3mf_paths, bundle, key="frog_vt1190"):
    return make.add_version(db, bundle, sample_3mf_paths[key], f"{key}_next.3mf", gcode=None)


# ------------------------------------------------------------------ stars: one version per 3MF, never v1


def test_a_new_3mf_has_no_starred_version(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    assert b.starred_version_id is None and db_session.query(BundleStar).count() == 0


def test_starring_a_version_and_clearing_it(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    v2 = _add_version(db_session, sample_3mf_paths, b)
    assert svc.set_starred_version(db_session, b.id, v2.id).starred_version_id == v2.id
    assert svc.set_starred_version(db_session, b.id, v2.id).starred_version_id == v2.id  # starring twice is harmless
    assert db_session.query(BundleStar).count() == 1
    assert svc.set_starred_version(db_session, b.id, None).starred_version_id is None
    assert svc.set_starred_version(db_session, b.id, None).starred_version_id is None
    assert db_session.query(BundleStar).count() == 0


def test_only_one_version_per_3mf_is_starred(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    v2 = _add_version(db_session, sample_3mf_paths, b)
    v3 = _add_version(db_session, sample_3mf_paths, b)
    svc.set_starred_version(db_session, b.id, v2.id)
    assert svc.set_starred_version(db_session, b.id, v3.id).starred_version_id == v3.id  # the star moves
    assert db_session.query(BundleStar).count() == 1


def test_the_initial_version_cannot_be_starred(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    with pytest.raises(svc.StarNotAllowed, match="initial version"):
        svc.set_starred_version(db_session, b.id, b.versions[0].id)


def test_a_version_of_another_3mf_cannot_be_starred(db_session, sample_3mf_paths):
    a = _bundle(db_session, sample_3mf_paths, "frog_vt1190")
    b = _bundle(db_session, sample_3mf_paths, "shark_vt1190")
    b2 = _add_version(db_session, sample_3mf_paths, b, "shark_vt1190")
    with pytest.raises(svc.StarNotAllowed, match="isn't a version of this 3MF"):
        svc.set_starred_version(db_session, a.id, b2.id)
    with pytest.raises(svc.StarNotAllowed):
        svc.set_starred_version(db_session, a.id, 9999)


def test_starring_an_unknown_3mf_is_an_error(db_session):
    with pytest.raises(NotFound, match="No bundle with id 99"):
        svc.set_starred_version(db_session, 99, None)


def test_deleting_the_starred_version_clears_the_star(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    v2 = _add_version(db_session, sample_3mf_paths, b)
    v3 = _add_version(db_session, sample_3mf_paths, b)
    svc.set_starred_version(db_session, b.id, v2.id)
    svc.delete_bundle_version(db_session, v3.id)  # another version: the star stays
    assert svc.get_bundle(db_session, b.id).starred_version_id == v2.id
    svc.delete_bundle_version(db_session, v2.id)
    assert svc.get_bundle(db_session, b.id).starred_version_id is None
    assert db_session.query(BundleStar).count() == 0


# ------------------------------------------------------------------ notes


def test_notes_survive_a_new_version_and_are_shared_by_every_version(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    svc.set_notes(db_session, b.id, "keep me", 0)
    v2 = _add_version(db_session, sample_3mf_paths, b)
    svc.set_starred_version(db_session, b.id, v2.id)
    _add_version(db_session, sample_3mf_paths, b)
    after = svc.get_bundle(db_session, b.id)
    assert len(after.versions) == 3 and after.notes == "keep me" and after.starred_version_id == v2.id


def test_deleting_the_3mf_deletes_its_notes_and_star(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    svc.set_notes(db_session, b.id, "gone with it", 0)
    v2 = _add_version(db_session, sample_3mf_paths, b)
    svc.set_starred_version(db_session, b.id, v2.id)
    svc.delete_bundle(db_session, b.id)
    assert db_session.query(Bundle).count() == 0
    assert db_session.query(BundleNote).count() == 0 and db_session.query(BundleStar).count() == 0


def test_the_output_schema_carries_star_and_notes(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    out = BundleOut.model_validate(b)
    assert out.starred_version_id is None and out.notes == "" and out.notes_revision == 0
    svc.set_notes(db_session, b.id, "hello", 0)
    v2 = _add_version(db_session, sample_3mf_paths, b)
    svc.set_starred_version(db_session, b.id, v2.id)
    out = BundleOut.model_validate(svc.get_bundle(db_session, b.id))
    assert out.starred_version_id == v2.id and out.notes == "hello" and out.notes_revision == 1 and out.notes_updated_at


def test_an_existing_database_gains_the_new_tables_without_losing_anything():
    from sqlalchemy import inspect

    new = {"bundle_notes", "bundle_starred_versions"}
    engine = create_engine("sqlite://", future=True)
    old_tables = [t for t in Base.metadata.sorted_tables if t.name not in new]
    Base.metadata.create_all(engine, tables=old_tables)
    assert not new & set(inspect(engine).get_table_names())
    Base.metadata.create_all(engine)  # what the app does when it starts
    assert new <= set(inspect(engine).get_table_names())


# ------------------------------------------------------------------ over the API


@pytest.fixture()
def client(api, sample_3mf_paths):
    c = api
    printer = c.post("/printers", json={"name": "VT 1190", "kind": "Voron"}).json()
    model = c.post("/source-models", data={"name": "Frog.stl", "file_type": "STL"}, files={"file": ("Frog.stl", b"x" * 64)}).json()
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        bundle = c.post(
            "/bundles",
            data={"source_model_ids": f"[{model['id']}]", "printer_id": str(printer["id"])},
            files={"threemf": ("frog.3mf", f.read())},
        ).json()
    return c, bundle["id"]


def test_star_over_the_api(client, sample_3mf_paths):
    c, bid = client
    v1 = c.get(f"/bundles/{bid}").json()["versions"][0]["id"]
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        versions = c.post(f"/bundles/{bid}/versions", files={"threemf": ("frog_v2.3mf", f.read())}).json()["versions"]
    v2 = next(v["id"] for v in versions if v["version"] == 2)
    assert c.get(f"/bundles/{bid}").json()["starred_version_id"] is None

    r = c.put(f"/bundles/{bid}/star", json={"version_id": v2})
    assert r.status_code == 200 and r.json()["starred_version_id"] == v2 and r.json()["versions"]
    assert {b["id"]: b for b in c.get("/bundles").json()}[bid]["starred_version_id"] == v2
    assert c.put(f"/bundles/{bid}/star", json={"version_id": None}).json()["starred_version_id"] is None

    assert c.put(f"/bundles/{bid}/star", json={"version_id": v1}).status_code == 422  # the initial version
    assert c.put(f"/bundles/{bid}/star", json={"version_id": 9999}).status_code == 422
    assert c.put("/bundles/999/star", json={"version_id": None}).status_code == 404
    assert c.put(f"/bundles/{bid}/star", json={}).status_code == 422
