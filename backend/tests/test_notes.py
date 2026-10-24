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
from app.models import SourceFileType, SourceModel, SourceModelNote
from app.schemas.source_model import SourceModelOut
from app.services import source_model_service as svc


def _model(db, name="Frog.stl"):
    return svc.create_source_model(db, name=name, file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 64))


# ------------------------------------------------------------------ the service


def test_a_new_model_has_no_notes(db_session):
    m = _model(db_session)
    assert m.notes == "" and m.notes_revision == 0 and m.notes_updated_at is None
    assert db_session.query(SourceModelNote).count() == 0  # no row until there's something to keep


def test_saving_notes_stores_them_and_counts_a_revision(db_session):
    m = _model(db_session)
    out = svc.set_notes(db_session, m.id, "Print at 0.2mm, no supports.", 0)
    assert out.notes == "Print at 0.2mm, no supports." and out.notes_revision == 1 and out.notes_updated_at is not None
    out = svc.set_notes(db_session, m.id, "Print at 0.2mm, no supports.\nSource: https://example.com/frog", 1)
    assert out.notes_revision == 2 and out.notes.endswith("example.com/frog")


def test_the_text_is_kept_as_typed_apart_from_tidying_the_ends(db_session):
    m = _model(db_session)
    typed = "\r\n\r\n  Line one  \r\n\r\n    indented 😀 ünïcode <b>not html</b> 'quotes' \"too\" ; DROP TABLE x;--   \r\n\r\n"
    out = svc.set_notes(db_session, m.id, typed, 0)
    assert out.notes == "  Line one  \n\n    indented 😀 ünïcode <b>not html</b> 'quotes' \"too\" ; DROP TABLE x;--"
    assert svc.get_source_model(db_session, m.id).notes == out.notes  # and it's really stored


def test_a_nul_character_is_removed_because_postgres_cannot_store_it(db_session):
    m = _model(db_session)
    assert svc.set_notes(db_session, m.id, "a\x00b\x00", 0).notes == "ab"


def test_a_save_based_on_an_old_revision_is_refused_and_changes_nothing(db_session):
    m = _model(db_session)
    svc.set_notes(db_session, m.id, "first", 0)  # revision 1
    svc.set_notes(db_session, m.id, "someone else's edit", 1)  # revision 2

    with pytest.raises(svc.NotesConflict) as caught:
        svc.set_notes(db_session, m.id, "my edit, started from revision 1", 1)

    assert caught.value.model.notes == "someone else's edit" and caught.value.model.notes_revision == 2
    assert svc.get_source_model(db_session, m.id).notes == "someone else's edit"  # nothing was overwritten


def test_saving_as_if_there_were_no_notes_when_there_are_is_a_conflict(db_session):
    m = _model(db_session)
    svc.set_notes(db_session, m.id, "written by someone else", 0)
    with pytest.raises(svc.NotesConflict):
        svc.set_notes(db_session, m.id, "mine, written on a page loaded before theirs", 0)


def test_clearing_notes_keeps_a_row_so_a_revision_number_is_never_reused(db_session):
    m = _model(db_session)
    svc.set_notes(db_session, m.id, "x", 0)  # rev 1: this is what a slow editor loaded
    cleared = svc.set_notes(db_session, m.id, "   \n  ", 1)  # rev 2: someone clears it
    assert cleared.notes == "" and cleared.notes_revision == 2
    svc.set_notes(db_session, m.id, "y", 2)  # rev 3: someone writes new notes
    with pytest.raises(svc.NotesConflict):
        svc.set_notes(db_session, m.id, "slow editor saves now, based on rev 1", 1)
    assert db_session.query(SourceModelNote).count() == 1


def test_clearing_when_there_is_nothing_creates_nothing(db_session):
    m = _model(db_session)
    out = svc.set_notes(db_session, m.id, "  \n ", 0)
    assert out.notes_revision == 0 and db_session.query(SourceModelNote).count() == 0


def test_the_length_limit(db_session):
    m = _model(db_session)
    assert len(svc.set_notes(db_session, m.id, "a" * svc.MAX_NOTES_LENGTH, 0).notes) == svc.MAX_NOTES_LENGTH
    with pytest.raises(ValueError, match="at most 20,000"):
        svc.set_notes(db_session, m.id, "a" * (svc.MAX_NOTES_LENGTH + 1), 1)


def test_an_unknown_model_is_an_error(db_session):
    with pytest.raises(ValueError, match="No source model"):
        svc.set_notes(db_session, 999, "x", 0)


def test_models_keep_their_own_notes(db_session):
    a, b = _model(db_session, "A.stl"), _model(db_session, "B.stl")
    svc.set_notes(db_session, a.id, "about A", 0)
    assert svc.get_source_model(db_session, b.id).notes == "" and svc.get_source_model(db_session, a.id).notes == "about A"


def test_notes_belong_to_the_model_not_to_a_version(db_session):
    m = _model(db_session)
    svc.set_notes(db_session, m.id, "keep me", 0)
    svc.add_source_model_version(db_session, source_model_id=m.id, file_obj=io.BytesIO(b"y" * 80), filename="Frog.stl", note="about v2 only")
    model = svc.get_source_model(db_session, m.id)
    assert model.notes == "keep me"  # a new file version leaves the model's notes alone...
    assert model.versions[0].version == 2 and model.versions[0].note == "about v2 only"  # ...and its own note is a separate thing
    assert model.versions[1].note is None
    svc.delete_source_model_version(db_session, m.id, 2)
    assert svc.get_source_model(db_session, m.id).notes == "keep me"  # deleting a version doesn't touch them either


def test_deleting_the_model_deletes_its_notes(db_session):
    m = _model(db_session)
    svc.set_notes(db_session, m.id, "bye", 0)
    svc.delete_source_model(db_session, m.id)
    assert db_session.query(SourceModelNote).count() == 0 and db_session.query(SourceModel).count() == 0


def test_the_output_schema_carries_the_notes(db_session):
    m = _model(db_session)
    svc.set_notes(db_session, m.id, "hello", 0)
    out = SourceModelOut.model_validate(svc.get_source_model(db_session, m.id))
    assert out.notes == "hello" and out.notes_revision == 1 and out.notes_updated_at is not None
    assert SourceModelOut.model_validate(_model(db_session, "Other.stl")).notes == ""


# ------------------------------------------------------------------ the API


@pytest.fixture()
def client(tmp_path, monkeypatch):
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
    model = c.post("/source-models", data={"name": "Frog.stl", "file_type": "STL"}, files={"file": ("Frog.stl", b"x" * 64)}).json()
    yield c, model["id"]
    app.dependency_overrides.clear()
    storage.reset()


def test_notes_over_the_api(client):
    c, mid = client
    assert c.get(f"/source-models/{mid}").json()["notes"] == ""
    r = c.put(f"/source-models/{mid}/notes", json={"notes": "Needs a brim.", "base_revision": 0})
    assert r.status_code == 200 and r.json()["notes"] == "Needs a brim." and r.json()["notes_revision"] == 1
    assert c.get(f"/source-models/{mid}").json()["notes"] == "Needs a brim."
    listed = {m["id"]: m for m in c.get("/source-models").json()}
    assert listed[mid]["notes"] == "Needs a brim." and listed[mid]["notes_revision"] == 1  # the list carries them too


def test_a_conflicting_save_answers_409_with_the_current_notes(client):
    c, mid = client
    c.put(f"/source-models/{mid}/notes", json={"notes": "theirs", "base_revision": 0})
    r = c.put(f"/source-models/{mid}/notes", json={"notes": "mine", "base_revision": 0})
    assert r.status_code == 409
    body = r.json()
    assert "changed by someone else" in body["detail"]
    assert body["current"]["notes"] == "theirs" and body["current"]["notes_revision"] == 1 and body["current"]["notes_updated_at"]
    assert c.get(f"/source-models/{mid}").json()["notes"] == "theirs"  # not overwritten
    ok = c.put(f"/source-models/{mid}/notes", json={"notes": "mine, knowing theirs", "base_revision": body["current"]["notes_revision"]})
    assert ok.status_code == 200 and ok.json()["notes_revision"] == 2  # resolving it by saving from their revision works


def test_bad_requests_are_refused_cleanly(client):
    c, mid = client
    assert c.put("/source-models/999/notes", json={"notes": "x", "base_revision": 0}).status_code == 404
    assert c.put(f"/source-models/{mid}/notes", json={"notes": "a" * 20001, "base_revision": 0}).status_code == 422
    assert c.put(f"/source-models/{mid}/notes", json={"notes": "x", "base_revision": -1}).status_code == 422
    assert c.put(f"/source-models/{mid}/notes", json={"notes": 5, "base_revision": 0}).status_code == 422
    assert c.put(f"/source-models/{mid}/notes", json={"base_revision": 0}).status_code == 422
    assert c.get(f"/source-models/{mid}").json()["notes"] == ""  # none of that changed anything


def test_a_large_note_with_every_kind_of_character_round_trips(client):
    c, mid = client
    text = "\n".join(f"line {i}: <script>alert({i})</script> ' \" \\ 日本語 😀 %s {{x}}" for i in range(300))
    assert len(text) < 20000
    c.put(f"/source-models/{mid}/notes", json={"notes": text, "base_revision": 0})
    assert c.get(f"/source-models/{mid}").json()["notes"] == text


# ------------------------------------------------------------------ two people at once, and upgrading an existing database


def test_a_save_that_loses_a_race_is_a_conflict_not_an_overwrite(db_session, monkeypatch):
    """
    Both people pass the quick revision check, then one writes first. The write is conditional on the revision, so
    the second one matches no row and is refused — it must never overwrite what the first saved.
    """
    from sqlalchemy import text as sql

    m = _model(db_session)
    svc.set_notes(db_session, m.id, "start", 0)  # revision 1: what both people loaded

    real_execute = db_session.execute
    state = {"raced": False}

    def execute(statement, *a, **k):
        if not state["raced"] and "UPDATE source_model_notes" in str(statement):
            state["raced"] = True  # the other person's save lands in the gap between the check and the write
            real_execute(sql("UPDATE source_model_notes SET body='theirs, saved a moment earlier', revision=2"))
            db_session.commit()  # theirs is committed: it's another person's finished save, not part of our transaction
        return real_execute(statement, *a, **k)

    monkeypatch.setattr(db_session, "execute", execute)
    with pytest.raises(svc.NotesConflict) as caught:
        svc.set_notes(db_session, m.id, "mine", 1)
    monkeypatch.undo()

    assert state["raced"]
    assert caught.value.model.notes == "theirs, saved a moment earlier" and caught.value.model.notes_revision == 2
    assert svc.get_source_model(db_session, m.id).notes == "theirs, saved a moment earlier"


def test_two_first_saves_at_once_cannot_both_win(db_session, monkeypatch):
    m = _model(db_session)
    real_commit = db_session.commit
    calls = {"n": 0}

    def commit():
        calls["n"] += 1
        if calls["n"] == 1:  # the other person's first save gets in just before ours
            db_session.rollback()
            db_session.add(SourceModelNote(source_model_id=m.id, body="theirs", revision=1))
            real_commit()
            db_session.add(SourceModelNote(source_model_id=m.id, body="mine", revision=1))
        return real_commit()

    monkeypatch.setattr(db_session, "commit", commit)
    with pytest.raises(svc.NotesConflict):
        svc.set_notes(db_session, m.id, "mine", 0)
    monkeypatch.undo()
    assert svc.get_source_model(db_session, m.id).notes == "theirs"


def test_an_existing_database_gains_the_notes_table_without_losing_anything():
    """
    The app builds its tables with create_all, which adds what's missing and never alters what exists. So a
    database from before notes existed (no source_model_notes table) just gets that table on the next start.
    """
    from sqlalchemy import inspect

    engine = create_engine("sqlite://", future=True)
    old_tables = [t for t in Base.metadata.sorted_tables if t.name != "source_model_notes"]
    Base.metadata.create_all(engine, tables=old_tables)  # the database as it was before this feature
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        db.add(SourceModel(name="Old.stl", file_type=SourceFileType.stl))
        db.commit()
    assert "source_model_notes" not in inspect(engine).get_table_names()

    Base.metadata.create_all(engine)  # what the app does when it starts

    assert "source_model_notes" in inspect(engine).get_table_names()
    with Session() as db:
        old = db.query(SourceModel).one()
        assert old.name == "Old.stl" and old.notes == "" and old.notes_revision == 0  # intact, with no notes yet
        svc.set_notes(db, old.id, "works on the upgraded database", 0)
        assert db.query(SourceModel).one().notes == "works on the upgraded database"
