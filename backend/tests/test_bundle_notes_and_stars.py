from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config, storage
from app.database import Base, get_db
from app.main import app
from app.models import Bundle, BundleNote, BundleStar, SourceFileType
from app.schemas.bundle import BundleOut
from app.services import bundle_service as svc
from app.services import printer_service
from app.services import source_model_service as models_svc


def _bundle(db, sample_3mf_paths, key="frog_vt1190", printer_name="VT 1190"):
    printer = printer_service.find_by_name(db, printer_name) or printer_service.create_printer(
        db, name=printer_name, kind="Voron", wired_ip=None, wireless_ip=None
    )
    sm = models_svc.create_source_model(db, name=f"{key}.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 64))
    with open(sample_3mf_paths[key], "rb") as f:
        return svc.create_bundle(db, printer_id=printer.id, source_model_ids=[sm.id], threemf_file_obj=f, threemf_filename=f"{key}.3mf")


# ------------------------------------------------------------------ stars


def test_a_new_3mf_is_not_starred(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    assert b.starred is False and db_session.query(BundleStar).count() == 0


def test_starring_and_unstarring(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    assert svc.set_starred(db_session, b.id, True).starred is True
    assert svc.set_starred(db_session, b.id, True).starred is True  # starring twice is harmless
    assert db_session.query(BundleStar).count() == 1
    assert svc.set_starred(db_session, b.id, False).starred is False
    assert svc.set_starred(db_session, b.id, False).starred is False
    assert db_session.query(BundleStar).count() == 0


def test_stars_belong_to_one_3mf(db_session, sample_3mf_paths):
    a = _bundle(db_session, sample_3mf_paths, "frog_vt1190")
    b = _bundle(db_session, sample_3mf_paths, "shark_vt1190")
    svc.set_starred(db_session, a.id, True)
    assert svc.get_bundle(db_session, a.id).starred and not svc.get_bundle(db_session, b.id).starred


def test_starring_an_unknown_3mf_is_an_error(db_session):
    with pytest.raises(ValueError, match="No bundle with id 99"):
        svc.set_starred(db_session, 99, True)


# ------------------------------------------------------------------ notes


def test_a_new_3mf_has_no_notes(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    assert b.notes == "" and b.notes_revision == 0 and b.notes_updated_at is None
    assert db_session.query(BundleNote).count() == 0


def test_saving_notes_counts_revisions_and_refuses_stale_saves(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    out = svc.set_notes(db_session, b.id, "  Prints best at 0.2 layers.\r\n\n", 0)
    assert out.notes == "  Prints best at 0.2 layers." and out.notes_revision == 1
    with pytest.raises(svc.NotesConflict) as caught:
        svc.set_notes(db_session, b.id, "mine", 0)
    assert caught.value.bundle.notes == "  Prints best at 0.2 layers."
    assert svc.set_notes(db_session, b.id, "", 1).notes_revision == 2  # clearing keeps the revision moving


def test_notes_survive_a_new_version_and_are_shared_by_every_version(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    svc.set_notes(db_session, b.id, "keep me", 0)
    svc.set_starred(db_session, b.id, True)
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        svc.add_bundle_version(db_session, bundle_id=b.id, threemf_file_obj=f, threemf_filename="frog_v2.3mf")
    after = svc.get_bundle(db_session, b.id)
    assert len(after.versions) == 2 and after.notes == "keep me" and after.starred


def test_deleting_the_3mf_deletes_its_notes_and_star(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    svc.set_notes(db_session, b.id, "gone with it", 0)
    svc.set_starred(db_session, b.id, True)
    svc.delete_bundle(db_session, b.id)
    assert db_session.query(Bundle).count() == 0
    assert db_session.query(BundleNote).count() == 0 and db_session.query(BundleStar).count() == 0


def test_the_output_schema_carries_star_and_notes(db_session, sample_3mf_paths):
    b = _bundle(db_session, sample_3mf_paths)
    out = BundleOut.model_validate(b)
    assert out.starred is False and out.notes == "" and out.notes_revision == 0
    svc.set_notes(db_session, b.id, "hello", 0)
    svc.set_starred(db_session, b.id, True)
    out = BundleOut.model_validate(svc.get_bundle(db_session, b.id))
    assert out.starred is True and out.notes == "hello" and out.notes_revision == 1 and out.notes_updated_at


def test_an_existing_database_gains_the_new_tables_without_losing_anything():
    from sqlalchemy import inspect

    engine = create_engine("sqlite://", future=True)
    old_tables = [t for t in Base.metadata.sorted_tables if t.name not in ("bundle_notes", "bundle_stars")]
    Base.metadata.create_all(engine, tables=old_tables)
    assert not {"bundle_notes", "bundle_stars"} & set(inspect(engine).get_table_names())
    Base.metadata.create_all(engine)  # what the app does when it starts
    assert {"bundle_notes", "bundle_stars"} <= set(inspect(engine).get_table_names())


# ------------------------------------------------------------------ over the API


@pytest.fixture()
def client(tmp_path, monkeypatch, sample_3mf_paths):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr(config.settings, "storage_root", str(tmp_path / "storage"))
    storage.reset()

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    c = TestClient(app)
    printer = c.post("/printers", json={"name": "VT 1190", "kind": "Voron"}).json()
    model = c.post("/source-models", data={"name": "Frog.stl", "file_type": "STL"}, files={"file": ("Frog.stl", b"x" * 64)}).json()
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        bundle = c.post(
            "/bundles",
            data={"source_model_ids": f"[{model['id']}]", "printer_id": str(printer["id"])},
            files={"threemf": ("frog.3mf", f.read())},
        ).json()
    yield c, bundle["id"]
    app.dependency_overrides.clear()
    storage.reset()


def test_star_over_the_api(client):
    c, bid = client
    assert c.get(f"/bundles/{bid}").json()["starred"] is False
    r = c.put(f"/bundles/{bid}/star", json={"starred": True})
    assert r.status_code == 200 and r.json()["starred"] is True and r.json()["versions"]
    assert {b["id"]: b for b in c.get("/bundles").json()}[bid]["starred"] is True
    assert c.put(f"/bundles/{bid}/star", json={"starred": False}).json()["starred"] is False
    assert c.put("/bundles/999/star", json={"starred": True}).status_code == 404
    assert c.put(f"/bundles/{bid}/star", json={}).status_code == 422


def test_notes_over_the_api(client):
    c, bid = client
    r = c.put(f"/bundles/{bid}/notes", json={"notes": "Use the textured sheet.", "base_revision": 0})
    assert r.status_code == 200 and r.json()["notes"] == "Use the textured sheet." and r.json()["notes_revision"] == 1
    assert {b["id"]: b for b in c.get("/bundles").json()}[bid]["notes"] == "Use the textured sheet."

    conflict = c.put(f"/bundles/{bid}/notes", json={"notes": "mine", "base_revision": 0})
    assert conflict.status_code == 409
    assert conflict.json()["current"]["notes"] == "Use the textured sheet." and conflict.json()["current"]["notes_revision"] == 1

    assert c.put("/bundles/999/notes", json={"notes": "x", "base_revision": 0}).status_code == 404
    assert c.put(f"/bundles/{bid}/notes", json={"notes": "a" * 20001, "base_revision": 1}).status_code == 422
