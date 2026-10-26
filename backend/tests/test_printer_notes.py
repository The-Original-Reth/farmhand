from __future__ import annotations

import io

import pytest

from app.models import Printer, PrinterNote, SourceFileType
from app.schemas.printer import PrinterOut
from app.services import printer_service as svc
from app.services import source_model_service as models_svc

from . import factories as make


# ------------------------------------------------------------------ the service


def test_a_printers_notes_and_a_models_notes_never_mix(db_session):
    p = make.printer(db_session)
    m = models_svc.create_source_model(db_session, name="Frog.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 64))
    assert p.id == m.id  # the same number on purpose: they must be told apart by what they belong to
    svc.set_notes(db_session, p.id, "about the printer", 0)
    models_svc.set_notes(db_session, m.id, "about the model", 0)
    assert svc.get_printer(db_session, p.id).notes == "about the printer"
    assert models_svc.get_source_model(db_session, m.id).notes == "about the model"
    svc.set_notes(db_session, p.id, "printer, edited", 1)
    assert models_svc.get_source_model(db_session, m.id).notes == "about the model"  # untouched


def test_editing_or_retiring_a_printer_leaves_its_notes_alone(db_session):
    p = make.printer(db_session)
    svc.set_notes(db_session, p.id, "keep me", 0)
    svc.update_printer(db_session, p.id, {"kind": "Voron 2.4", "wired_ip": "10.0.0.9"})
    svc.set_decommissioned(db_session, p.id, True)
    after = svc.get_printer(db_session, p.id)
    assert after.notes == "keep me" and after.notes_revision == 1 and after.decommissioned


def test_notes_belong_to_the_printer_not_to_its_3mf_files(db_session, sample_3mf_paths):
    from app.services import bundle_service

    p = make.printer(db_session)
    svc.set_notes(db_session, p.id, "printer notes", 0)
    sm = models_svc.create_source_model(db_session, name="Frog.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 64))
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        bundle_service.create_bundle(db_session, printer_id=p.id, source_model_ids=[sm.id], threemf_file_obj=f, threemf_filename="frog.3mf")
    assert svc.get_printer(db_session, p.id).notes == "printer notes"


def test_deleting_the_printer_deletes_its_notes(db_session):
    p = make.printer(db_session)
    svc.set_notes(db_session, p.id, "gone with it", 0)
    db_session.delete(db_session.get(Printer, p.id))
    db_session.commit()
    assert db_session.query(PrinterNote).count() == 0


def test_the_output_schema_carries_the_notes(db_session):
    p = make.printer(db_session)
    assert PrinterOut.model_validate(p).notes == "" and PrinterOut.model_validate(p).notes_revision == 0
    svc.set_notes(db_session, p.id, "hello", 0)
    out = PrinterOut.model_validate(svc.get_printer(db_session, p.id))
    assert out.notes == "hello" and out.notes_revision == 1 and out.notes_updated_at


# ------------------------------------------------------------------ over the API


@pytest.fixture()
def client(api):
    c = api
    printer = c.post("/printers", json={"name": "VT 1190", "kind": "Voron"}).json()
    return c, printer["id"]


def test_editing_the_printer_over_the_api_keeps_the_notes(client):
    c, pid = client
    c.put(f"/printers/{pid}/notes", json={"notes": "stay", "base_revision": 0})
    r = c.patch(f"/printers/{pid}", json={"kind": "Voron 2.4"})
    assert r.status_code == 200 and r.json()["notes"] == "stay" and r.json()["kind"] == "Voron 2.4"


def test_the_model_notes_endpoint_still_works_alongside(client):
    c, pid = client
    m = c.post("/source-models", data={"name": "Frog.stl", "file_type": "STL"}, files={"file": ("Frog.stl", b"x" * 64)}).json()
    c.put(f"/printers/{pid}/notes", json={"notes": "printer", "base_revision": 0})
    r = c.put(f"/source-models/{m['id']}/notes", json={"notes": "model", "base_revision": 0})
    assert r.status_code == 200 and r.json()["notes"] == "model"
    assert c.get(f"/printers/{pid}").json()["notes"] == "printer"


# ------------------------------------------------------------------ two people at once, and upgrading an existing database
