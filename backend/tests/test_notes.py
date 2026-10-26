"""
The rules every kind of notes follows (app/notes.py), checked for each kind: a model's, a printer's, a 3MF's and a
printer's 1500-hour service notes. What only one kind does is tested at the end here (models), and in
test_printer_notes.py and test_bundle_notes_and_stars.py.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.errors import NotFound
from app.models import BundleNote, Printer, PrinterNote, PrinterServiceNote, SourceFileType, SourceModel, SourceModelNote
from app.notes import MAX_NOTES_LENGTH, NotesConflict
from app.schemas.source_model import SourceModelOut
from app.services import bundle_service, printer_service
from app.services import moonraker as mr
from app.services import source_model_service as models_svc


@dataclass
class Kind:
    """How to make an owner of this kind of notes, save its notes, and read them back, in the service and over the API."""
    make: Callable  # (db, n, samples) -> id: the n-th owner of this kind
    save: Callable  # (db, id, text, base_revision) -> the owner, as saved
    read: Callable  # (owner) -> (notes, revision)
    reload: Callable  # (db, id) -> the owner, from the database
    row: type  # its notes table
    key: str  # that table's key column
    api_make: Callable  # (client, n, samples) -> id
    url: str  # its notes endpoint, with {id}
    api_read: Callable  # (json of the owner) -> notes
    api_list: str  # where every owner of this kind is listed


def _model(db, n, samples=None):
    return models_svc.create_source_model(db, name=f"Model {n}.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 64)).id


def _printer(db, n, samples=None):
    return printer_service.create_printer(db, name=f"Printer {n}", kind="Voron", wired_ip=None, wireless_ip=None).id


def _bundle(db, n, samples):
    printer = printer_service.find_by_name(db, "VT 1190") or printer_service.create_printer(db, name="VT 1190", kind="Voron", wired_ip=None, wireless_ip=None)
    model = models_svc.create_source_model(db, name=f"Model {n}.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 64))
    with open(samples["frog_vt1190"], "rb") as f:
        return bundle_service.create_bundle(db, printer_id=printer.id, source_model_ids=[model.id], threemf_file_obj=f, threemf_filename=f"frog{n}.3mf").id


def _api_model(c, n, samples=None):
    return c.post("/source-models", data={"name": f"Model {n}.stl", "file_type": "STL"}, files={"file": (f"Model {n}.stl", b"x" * 64)}).json()["id"]


def _api_printer(c, n, samples=None):
    return c.post("/printers", json={"name": f"Printer {n}", "kind": "Voron"}).json()["id"]


def _api_bundle(c, n, samples):
    printers = {p["name"]: p["id"] for p in c.get("/printers").json()}
    pid = printers.get("VT 1190") or c.post("/printers", json={"name": "VT 1190", "kind": "Voron"}).json()["id"]
    mid = _api_model(c, n)
    with open(samples["frog_vt1190"], "rb") as f:
        data = {"source_model_ids": f"[{mid}]", "printer_id": str(pid)}
        return c.post("/bundles", data=data, files={"threemf": (f"frog{n}.3mf", f.read())}).json()["id"]


_plain = lambda o: (o.notes, o.notes_revision)  # noqa: E731
KINDS = {
    "model": Kind(_model, models_svc.set_notes, _plain, models_svc.get_source_model, SourceModelNote, "source_model_id",
                  _api_model, "/source-models/{id}/notes", lambda j: j["notes"], "/source-models"),
    "printer": Kind(_printer, printer_service.set_notes, _plain, printer_service.get_printer, PrinterNote, "printer_id",
                    _api_printer, "/printers/{id}/notes", lambda j: j["notes"], "/printers"),
    "bundle": Kind(_bundle, bundle_service.set_notes, _plain, bundle_service.get_bundle, BundleNote, "bundle_id",
                   _api_bundle, "/bundles/{id}/notes", lambda j: j["notes"], "/bundles"),
    "service": Kind(_printer, lambda db, i, t, r: mr.set_service_notes(db, db.get(Printer, i), t, r),
                    lambda p: (p.service["notes"], p.service["notes_revision"]), printer_service.get_printer,
                    PrinterServiceNote, "printer_id", _api_printer, "/printers/{id}/service/notes",
                    lambda j: j["service"]["notes"], "/printers"),
}


@pytest.fixture(params=list(KINDS))
def kind(request):
    return KINDS[request.param]


@pytest.fixture()
def samples(request, kind):
    # the 3MF files a 3MF owner is made from; the other kinds don't need them
    return request.getfixturevalue("sample_3mf_paths") if kind is KINDS["bundle"] else None


@pytest.fixture()
def owner(db_session, kind, samples):
    return kind.make(db_session, 1, samples)


def notes_of(db, kind, oid):
    db.expire_all()
    return kind.read(kind.reload(db, oid))


# ------------------------------------------------------------------ in the service


def test_a_new_owner_has_no_notes(db_session, kind, owner):
    assert notes_of(db_session, kind, owner) == ("", 0)
    assert db_session.query(kind.row).count() == 0  # no row until there's something to keep


def test_saving_notes_stores_them_and_counts_a_revision(db_session, kind, owner):
    assert kind.read(kind.save(db_session, owner, "Print at 0.2mm, no supports.", 0)) == ("Print at 0.2mm, no supports.", 1)
    assert kind.read(kind.save(db_session, owner, "Now at 0.16mm.", 1)) == ("Now at 0.16mm.", 2)
    assert notes_of(db_session, kind, owner) == ("Now at 0.16mm.", 2)  # and it's really stored


def test_the_text_is_kept_as_typed_apart_from_tidying_the_ends(db_session, kind, owner):
    typed = "\r\n\r\n  Line one  \r\n\r\n    indented 😀 日本語 <b>not html</b> 'quotes' \"too\" ; DROP TABLE x;--   \r\n\r\n"
    notes, _ = kind.read(kind.save(db_session, owner, typed, 0))
    assert notes == "  Line one  \n\n    indented 😀 日本語 <b>not html</b> 'quotes' \"too\" ; DROP TABLE x;--"


def test_a_nul_character_is_removed_because_postgres_cannot_store_it(db_session, kind, owner):
    assert kind.read(kind.save(db_session, owner, "a\x00b\x00", 0))[0] == "ab"


def test_a_save_based_on_an_old_revision_is_refused_and_changes_nothing(db_session, kind, owner):
    kind.save(db_session, owner, "first", 0)
    kind.save(db_session, owner, "someone else's edit", 1)
    with pytest.raises(NotesConflict) as caught:
        kind.save(db_session, owner, "my edit, started from revision 1", 1)
    assert caught.value.current["notes"] == "someone else's edit" and caught.value.current["notes_revision"] == 2
    assert notes_of(db_session, kind, owner) == ("someone else's edit", 2)  # nothing was overwritten


@pytest.mark.parametrize("believed", [0, 5])  # "there were none", "it was further on"
def test_saving_from_a_revision_that_isnt_the_current_one_is_a_conflict(db_session, kind, owner, believed):
    kind.save(db_session, owner, "already here", 0)
    with pytest.raises(NotesConflict):
        kind.save(db_session, owner, "mine", believed)


def test_clearing_notes_keeps_a_row_so_a_revision_number_is_never_reused(db_session, kind, owner):
    kind.save(db_session, owner, "x", 0)  # rev 1: what a slow editor loaded
    assert kind.read(kind.save(db_session, owner, "   \n  ", 1)) == ("", 2)  # rev 2: someone clears it
    kind.save(db_session, owner, "y", 2)  # rev 3: someone writes new notes
    with pytest.raises(NotesConflict):
        kind.save(db_session, owner, "slow editor saves now, based on rev 1", 1)
    assert db_session.query(kind.row).count() == 1


def test_clearing_when_there_is_nothing_creates_nothing(db_session, kind, owner):
    assert kind.read(kind.save(db_session, owner, "  \n ", 0))[1] == 0
    assert db_session.query(kind.row).count() == 0


def test_the_length_limit(db_session, kind, owner):
    assert len(kind.read(kind.save(db_session, owner, "a" * MAX_NOTES_LENGTH, 0))[0]) == MAX_NOTES_LENGTH
    with pytest.raises(ValueError, match="at most 20,000"):
        kind.save(db_session, owner, "a" * (MAX_NOTES_LENGTH + 1), 1)


@pytest.mark.parametrize("kind", [KINDS["model"], KINDS["printer"], KINDS["bundle"]], ids=["model", "printer", "bundle"])
def test_an_unknown_owner_is_an_error(db_session, kind):  # (service notes are saved on a printer already found)
    with pytest.raises(NotFound, match="No "):
        kind.save(db_session, 999, "x", 0)


def test_each_owner_keeps_its_own_notes(db_session, kind, samples):
    a, b = kind.make(db_session, 1, samples), kind.make(db_session, 2, samples)
    kind.save(db_session, a, "about A", 0)
    assert notes_of(db_session, kind, b) == ("", 0) and notes_of(db_session, kind, a) == ("about A", 1)
    kind.save(db_session, b, "about B", 0)
    assert notes_of(db_session, kind, a) == ("about A", 1)


def test_a_save_that_loses_a_race_is_a_conflict_not_an_overwrite(db_session, monkeypatch, kind, owner):
    """
    Both people pass the quick revision check, then one writes first. The write is conditional on the revision, so
    the second one matches no row and is refused — it must never overwrite what the first saved.
    """
    from sqlalchemy import text as sql

    kind.save(db_session, owner, "start", 0)  # revision 1: what both people loaded
    table = kind.row.__tablename__
    real_execute = db_session.execute
    state = {"raced": False}

    def execute(statement, *a, **k):
        if not state["raced"] and f"UPDATE {table}" in str(statement):
            state["raced"] = True  # the other person's save lands in the gap between the check and the write
            real_execute(sql(f"UPDATE {table} SET body='theirs, saved a moment earlier', revision=2"))
            db_session.commit()  # theirs is committed: another person's finished save, not part of our transaction
        return real_execute(statement, *a, **k)

    monkeypatch.setattr(db_session, "execute", execute)
    with pytest.raises(NotesConflict) as caught:
        kind.save(db_session, owner, "mine", 1)
    monkeypatch.undo()

    assert state["raced"]
    assert caught.value.current["notes"] == "theirs, saved a moment earlier" and caught.value.current["notes_revision"] == 2
    assert notes_of(db_session, kind, owner) == ("theirs, saved a moment earlier", 2)


def test_two_first_saves_at_once_cannot_both_win(db_session, monkeypatch, kind, owner):
    real_commit = db_session.commit
    calls = {"n": 0}

    def commit():
        calls["n"] += 1
        if calls["n"] == 1:  # the other person's first save gets in just before ours
            db_session.rollback()
            db_session.add(kind.row(**{kind.key: owner}, body="theirs", revision=1))
            real_commit()
            db_session.add(kind.row(**{kind.key: owner}, body="mine", revision=1))
        return real_commit()

    monkeypatch.setattr(db_session, "commit", commit)
    with pytest.raises(NotesConflict):
        kind.save(db_session, owner, "mine", 0)
    monkeypatch.undo()
    assert notes_of(db_session, kind, owner)[0] == "theirs"


def test_an_existing_database_gains_the_notes_table_without_losing_anything(kind):
    """
    The app builds its tables with create_all, which adds what's missing and never alters what exists. So a
    database from before these notes existed just gets their table on the next start.
    """
    from sqlalchemy import inspect

    table = kind.row.__tablename__
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name != table])
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        db.add(Printer(name="Old printer", kind="Voron"))
        db.commit()
    assert table not in inspect(engine).get_table_names()

    Base.metadata.create_all(engine)  # what the app does when it starts

    assert table in inspect(engine).get_table_names()
    with Session() as db:
        assert db.query(Printer).one().name == "Old printer"  # intact


# ------------------------------------------------------------------ over the API


@pytest.fixture()
def api_owner(api, kind, samples):
    return kind.api_make(api, 1, samples)


def test_notes_over_the_api(api, kind, api_owner):
    url = kind.url.format(id=api_owner)
    r = api.put(url, json={"notes": "Needs a brim.", "base_revision": 0})
    assert r.status_code == 200 and kind.api_read(r.json()) == "Needs a brim."
    listed = {o["id"]: o for o in api.get(kind.api_list).json()}
    assert kind.api_read(listed[api_owner]) == "Needs a brim."  # the list carries them too


def test_a_conflicting_save_answers_409_with_the_current_notes(api, kind, api_owner):
    url = kind.url.format(id=api_owner)
    api.put(url, json={"notes": "theirs", "base_revision": 0})
    r = api.put(url, json={"notes": "mine", "base_revision": 0})
    assert r.status_code == 409
    body = r.json()
    assert "changed by someone else" in body["detail"]
    assert body["current"]["notes"] == "theirs" and body["current"]["notes_revision"] == 1 and body["current"]["notes_updated_at"]
    ok = api.put(url, json={"notes": "mine, knowing theirs", "base_revision": body["current"]["notes_revision"]})
    assert ok.status_code == 200 and kind.api_read(ok.json()) == "mine, knowing theirs"  # saving from their revision works


def test_bad_requests_are_refused_cleanly(api, kind, api_owner):
    url = kind.url.format(id=api_owner)
    assert api.put(kind.url.format(id=999), json={"notes": "x", "base_revision": 0}).status_code == 404
    for bad in ({"notes": "a" * 20001, "base_revision": 0}, {"notes": "x", "base_revision": -1}, {"notes": 5, "base_revision": 0}, {"base_revision": 0}):
        assert api.put(url, json=bad).status_code == 422
    listed = {o["id"]: o for o in api.get(kind.api_list).json()}
    assert kind.api_read(listed[api_owner]) == ""  # none of that changed anything


def test_a_large_note_with_every_kind_of_character_round_trips(api, kind, api_owner):
    text = "\n".join(f"line {i}: <script>alert({i})</script> ' \" \\ 日本語 😀 %s {{x}}" for i in range(300))
    assert len(text) < 20000
    r = api.put(kind.url.format(id=api_owner), json={"notes": text, "base_revision": 0})
    assert kind.api_read(r.json()) == text


# ------------------------------------------------------------------ only models


def test_notes_belong_to_the_model_not_to_a_version(db_session):
    m = _model(db_session, 1)
    models_svc.set_notes(db_session, m, "keep me", 0)
    models_svc.add_source_model_version(db_session, source_model_id=m, file_obj=io.BytesIO(b"y" * 80), filename="Frog.stl", note="about v2 only")
    model = models_svc.get_source_model(db_session, m)
    assert model.notes == "keep me"  # a new file version leaves the model's notes alone...
    assert model.versions[0].version == 2 and model.versions[0].note == "about v2 only"  # ...and its own note is a separate thing
    assert model.versions[1].note is None
    models_svc.delete_source_model_version(db_session, m, 2)
    assert models_svc.get_source_model(db_session, m).notes == "keep me"  # deleting a version doesn't touch them either


def test_deleting_the_model_deletes_its_notes(db_session):
    m = _model(db_session, 1)
    models_svc.set_notes(db_session, m, "bye", 0)
    models_svc.delete_source_model(db_session, m)
    assert db_session.query(SourceModelNote).count() == 0 and db_session.query(SourceModel).count() == 0


def test_the_model_output_schema_carries_the_notes(db_session):
    m = _model(db_session, 1)
    models_svc.set_notes(db_session, m, "hello", 0)
    out = SourceModelOut.model_validate(models_svc.get_source_model(db_session, m))
    assert out.notes == "hello" and out.notes_revision == 1 and out.notes_updated_at is not None
    assert SourceModelOut.model_validate(models_svc.get_source_model(db_session, _model(db_session, 2))).notes == ""
