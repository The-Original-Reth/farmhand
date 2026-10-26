from __future__ import annotations

import io

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app
from app.models import Printer, PrinterNote, SourceFileType
from app.schemas.printer import PrinterOut
from app.services import printer_service as svc
from app.services import source_model_service as models_svc


def _printer(db, name="VT 1190"):
    return svc.create_printer(db, name=name, kind="Voron Trident", wired_ip=None, wireless_ip=None)


# ------------------------------------------------------------------ the service


def test_a_new_printer_has_no_notes(db_session):
    p = _printer(db_session)
    assert p.notes == "" and p.notes_revision == 0 and p.notes_updated_at is None
    assert db_session.query(PrinterNote).count() == 0  # no row until there's something to keep


def test_saving_notes_stores_them_and_counts_a_revision(db_session):
    p = _printer(db_session)
    out = svc.set_notes(db_session, p.id, "Nozzle: 0.4 hardened. Bed leveled 2026-09-02.", 0)
    assert out.notes == "Nozzle: 0.4 hardened. Bed leveled 2026-09-02." and out.notes_revision == 1 and out.notes_updated_at
    again = svc.set_notes(db_session, p.id, "Nozzle: 0.6 now.", 1)
    assert again.notes == "Nozzle: 0.6 now." and again.notes_revision == 2


def test_the_text_is_kept_as_typed_apart_from_tidying_the_ends(db_session):
    p = _printer(db_session)
    typed = "\n\n  Line one  \r\n\r\n    indented <b>not bold</b> & \"quoted\"  \n日本語 😀\n\n"
    out = svc.set_notes(db_session, p.id, typed, 0)
    assert out.notes == "  Line one  \n\n    indented <b>not bold</b> & \"quoted\"  \n日本語 😀"


def test_a_nul_character_is_removed_because_postgres_cannot_store_it(db_session):
    p = _printer(db_session)
    assert svc.set_notes(db_session, p.id, "a\x00b", 0).notes == "ab"


def test_a_save_based_on_an_old_revision_is_refused_and_changes_nothing(db_session):
    p = _printer(db_session)
    svc.set_notes(db_session, p.id, "theirs", 0)
    with pytest.raises(svc.NotesConflict) as caught:
        svc.set_notes(db_session, p.id, "mine", 0)
    assert caught.value.current["notes"] == "theirs" and caught.value.current["notes_revision"] == 1
    assert svc.get_printer(db_session, p.id).notes == "theirs"


def test_saving_as_if_there_were_no_notes_when_there_are_is_a_conflict(db_session):
    p = _printer(db_session)
    svc.set_notes(db_session, p.id, "already here", 0)
    with pytest.raises(svc.NotesConflict):
        svc.set_notes(db_session, p.id, "I thought it was empty", 0)
    with pytest.raises(svc.NotesConflict):
        svc.set_notes(db_session, p.id, "I thought it was further on", 5)


def test_clearing_notes_keeps_a_row_so_a_revision_number_is_never_reused(db_session):
    p = _printer(db_session)
    svc.set_notes(db_session, p.id, "something", 0)
    cleared = svc.set_notes(db_session, p.id, "   \n ", 1)
    assert cleared.notes == "" and cleared.notes_revision == 2
    assert db_session.query(PrinterNote).count() == 1
    assert svc.set_notes(db_session, p.id, "back again", 2).notes_revision == 3


def test_clearing_when_there_is_nothing_creates_nothing(db_session):
    p = _printer(db_session)
    out = svc.set_notes(db_session, p.id, "  \n", 0)
    assert out.notes_revision == 0 and db_session.query(PrinterNote).count() == 0


def test_the_length_limit(db_session):
    p = _printer(db_session)
    assert len(svc.set_notes(db_session, p.id, "a" * 20000, 0).notes) == 20000
    with pytest.raises(ValueError, match="at most 20,000"):
        svc.set_notes(db_session, p.id, "a" * 20001, 1)


def test_an_unknown_printer_is_an_error(db_session):
    with pytest.raises(ValueError, match="No printer with id 99"):
        svc.set_notes(db_session, 99, "x", 0)


def test_printers_keep_their_own_notes(db_session):
    a, b = _printer(db_session, "VT 1190"), _printer(db_session, "V2 BOG")
    svc.set_notes(db_session, a.id, "A's notes", 0)
    assert svc.get_printer(db_session, b.id).notes == "" and svc.get_printer(db_session, a.id).notes == "A's notes"
    svc.set_notes(db_session, b.id, "B's notes", 0)
    assert svc.get_printer(db_session, a.id).notes == "A's notes"


def test_a_printers_notes_and_a_models_notes_never_mix(db_session):
    p = _printer(db_session)
    m = models_svc.create_source_model(db_session, name="Frog.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 64))
    assert p.id == m.id  # the same number on purpose: they must be told apart by what they belong to
    svc.set_notes(db_session, p.id, "about the printer", 0)
    models_svc.set_notes(db_session, m.id, "about the model", 0)
    assert svc.get_printer(db_session, p.id).notes == "about the printer"
    assert models_svc.get_source_model(db_session, m.id).notes == "about the model"
    svc.set_notes(db_session, p.id, "printer, edited", 1)
    assert models_svc.get_source_model(db_session, m.id).notes == "about the model"  # untouched


def test_editing_or_retiring_a_printer_leaves_its_notes_alone(db_session):
    p = _printer(db_session)
    svc.set_notes(db_session, p.id, "keep me", 0)
    svc.update_printer(db_session, p.id, {"kind": "Voron 2.4", "wired_ip": "10.0.0.9"})
    svc.set_decommissioned(db_session, p.id, True)
    after = svc.get_printer(db_session, p.id)
    assert after.notes == "keep me" and after.notes_revision == 1 and after.decommissioned


def test_notes_belong_to_the_printer_not_to_its_3mf_files(db_session, sample_3mf_paths):
    from app.services import bundle_service

    p = _printer(db_session)
    svc.set_notes(db_session, p.id, "printer notes", 0)
    sm = models_svc.create_source_model(db_session, name="Frog.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 64))
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        bundle_service.create_bundle(db_session, printer_id=p.id, source_model_ids=[sm.id], threemf_file_obj=f, threemf_filename="frog.3mf")
    assert svc.get_printer(db_session, p.id).notes == "printer notes"


def test_deleting_the_printer_deletes_its_notes(db_session):
    p = _printer(db_session)
    svc.set_notes(db_session, p.id, "gone with it", 0)
    db_session.delete(db_session.get(Printer, p.id))
    db_session.commit()
    assert db_session.query(PrinterNote).count() == 0


def test_the_output_schema_carries_the_notes(db_session):
    p = _printer(db_session)
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


def test_notes_over_the_api(client):
    c, pid = client
    assert c.get(f"/printers/{pid}").json()["notes"] == ""
    r = c.put(f"/printers/{pid}/notes", json={"notes": "Bed mesh: redo after moving.", "base_revision": 0})
    assert r.status_code == 200 and r.json()["notes"] == "Bed mesh: redo after moving." and r.json()["notes_revision"] == 1
    assert r.json()["name"] == "VT 1190"  # the whole printer comes back, as the page needs it
    assert c.get(f"/printers/{pid}").json()["notes"] == "Bed mesh: redo after moving."
    listed = {p["id"]: p for p in c.get("/printers").json()}
    assert listed[pid]["notes"] == "Bed mesh: redo after moving." and listed[pid]["notes_revision"] == 1  # the list carries them too


def test_a_conflicting_save_answers_409_with_the_current_notes(client):
    c, pid = client
    c.put(f"/printers/{pid}/notes", json={"notes": "theirs", "base_revision": 0})
    r = c.put(f"/printers/{pid}/notes", json={"notes": "mine", "base_revision": 0})
    assert r.status_code == 409
    body = r.json()
    assert "changed by someone else" in body["detail"]
    assert body["current"]["notes"] == "theirs" and body["current"]["notes_revision"] == 1 and body["current"]["notes_updated_at"]
    assert c.get(f"/printers/{pid}").json()["notes"] == "theirs"  # not overwritten
    ok = c.put(f"/printers/{pid}/notes", json={"notes": "mine, knowing theirs", "base_revision": body["current"]["notes_revision"]})
    assert ok.status_code == 200 and ok.json()["notes_revision"] == 2


def test_bad_requests_are_refused_cleanly(client):
    c, pid = client
    assert c.put("/printers/999/notes", json={"notes": "x", "base_revision": 0}).status_code == 404
    assert c.put(f"/printers/{pid}/notes", json={"notes": "a" * 20001, "base_revision": 0}).status_code == 422
    assert c.put(f"/printers/{pid}/notes", json={"notes": "x", "base_revision": -1}).status_code == 422
    assert c.put(f"/printers/{pid}/notes", json={"notes": 5, "base_revision": 0}).status_code == 422
    assert c.put(f"/printers/{pid}/notes", json={"base_revision": 0}).status_code == 422
    assert c.get(f"/printers/{pid}").json()["notes"] == ""  # none of that changed anything


def test_a_large_note_with_every_kind_of_character_round_trips(client):
    c, pid = client
    text = "\n".join(f"line {i}: <script>alert({i})</script> ' \" \\ 日本語 😀 %s {{x}}" for i in range(300))
    assert len(text) < 20000
    c.put(f"/printers/{pid}/notes", json={"notes": text, "base_revision": 0})
    assert c.get(f"/printers/{pid}").json()["notes"] == text


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


def test_a_save_that_loses_a_race_is_a_conflict_not_an_overwrite(db_session, monkeypatch):
    """Both pass the quick revision check, then one writes first: the conditional write must refuse the second."""
    from sqlalchemy import text as sql

    p = _printer(db_session)
    svc.set_notes(db_session, p.id, "start", 0)
    real_execute = db_session.execute
    state = {"raced": False}

    def execute(statement, *a, **k):
        if not state["raced"] and "UPDATE printer_notes" in str(statement):
            state["raced"] = True
            real_execute(sql("UPDATE printer_notes SET body='theirs, saved a moment earlier', revision=2"))
            db_session.commit()
        return real_execute(statement, *a, **k)

    monkeypatch.setattr(db_session, "execute", execute)
    with pytest.raises(svc.NotesConflict) as caught:
        svc.set_notes(db_session, p.id, "mine", 1)
    monkeypatch.undo()

    assert state["raced"]
    assert caught.value.current["notes"] == "theirs, saved a moment earlier" and caught.value.current["notes_revision"] == 2
    assert svc.get_printer(db_session, p.id).notes == "theirs, saved a moment earlier"


def test_two_first_saves_at_once_cannot_both_win(db_session, monkeypatch):
    p = _printer(db_session)
    real_commit = db_session.commit
    calls = {"n": 0}

    def commit():
        calls["n"] += 1
        if calls["n"] == 1:  # the other person's first save gets in just before ours
            db_session.rollback()
            db_session.add(PrinterNote(printer_id=p.id, body="theirs", revision=1))
            real_commit()
            db_session.add(PrinterNote(printer_id=p.id, body="mine", revision=1))
        return real_commit()

    monkeypatch.setattr(db_session, "commit", commit)
    with pytest.raises(svc.NotesConflict):
        svc.set_notes(db_session, p.id, "mine", 0)
    monkeypatch.undo()
    assert svc.get_printer(db_session, p.id).notes == "theirs"


def test_an_existing_database_gains_the_printer_notes_table_without_losing_anything():
    """create_all adds what's missing and never alters what exists, so older databases just gain the table."""
    from sqlalchemy import inspect

    engine = create_engine("sqlite://", future=True)
    old_tables = [t for t in Base.metadata.sorted_tables if t.name != "printer_notes"]
    Base.metadata.create_all(engine, tables=old_tables)  # the database as it was before this feature
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        db.add(Printer(name="Old printer", kind="Voron"))
        db.commit()
    assert "printer_notes" not in inspect(engine).get_table_names()

    Base.metadata.create_all(engine)  # what the app does when it starts

    assert "printer_notes" in inspect(engine).get_table_names()
    with Session() as db:
        old = db.query(Printer).one()
        assert old.name == "Old printer" and old.notes == "" and old.notes_revision == 0
        svc.set_notes(db, old.id, "works on the upgraded database", 0)
        assert db.query(Printer).one().notes == "works on the upgraded database"
