from __future__ import annotations

import datetime as dt
import io
import json
import os

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config, records_store as rs, storage
from app.database import Base
from app.models import Printer, PrinterEnergyReading, PrintJob, SourceFileType
from app.services import bundle_service, config_service, printer_service, records_service
from app.services import moonraker as mr
from app.services import source_model_service as models_svc
from app.services.moonraker import client as mr_client, history as mr_history

from .fake_moonraker import FakeMoonraker


@pytest.fixture()
def fake(monkeypatch):
    f = FakeMoonraker()
    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(f.handle))
    monkeypatch.setattr(mr_history, "READING_SPACING", dt.timedelta(0))
    return f


def _printer_with_everything(db, fake, name="V2 BOG"):
    p = printer_service.create_printer(db, name=name, kind="Voron 2.4", wired_ip="192.168.10.123", wireless_ip=None)
    printer_service.update_printer(db, p.id, {"moonraker_url": "http://192.168.10.123:7125", "moonraker_api_key": "SECRET-KEY"})
    printer_service.set_notes(db, p.id, "Bed: PEI. Lives on shelf 2.", 0)
    fake.meter_kwh = 2070.0
    fake.add_job("0003F2", "gecko.gcode", start=1_700_000_000, energy_kwh=2.9)
    fake.add_job("0003F3", "gecko.gcode", start=1_700_100_000, energy_kwh=3.7)
    mr.sync_history(db, p)
    for r in p.energy_readings:  # a minute apart, as real readings are (two quick syncs can share one clock tick)
        r.taken_at = r.taken_at - dt.timedelta(minutes=1)
    db.commit()
    fake.meter_kwh = 2071.5
    mr.sync_history(db, p)
    mr.service_done(db, p, note="new belts")
    mr.set_service_notes(db, p, "Gates 6mm belts", 0)
    return p


# ------------------------------------------------------------------ the files


def test_each_printer_gets_a_file_with_everything_but_the_api_key(db_session, fake, tmp_path):
    _printer_with_everything(db_session, fake)
    printer_service.create_printer(db_session, name="New/one: test", kind=None, wired_ip=None, wireless_ip=None)
    out = records_service.write_all(db_session, tmp_path)
    assert out["printers"] == {"written": 2, "removed": 0}

    files = sorted(p.name for p in (tmp_path / "printers").iterdir())
    assert files == ["New_one_ test.json", "V2 BOG.json"]
    text = (tmp_path / "printers" / "V2 BOG.json").read_text(encoding="utf-8")
    assert "SECRET-KEY" not in text
    doc = json.loads(text)
    assert doc[rs.RECORD_MARKER] == "printers" and doc["name"] == "V2 BOG"
    assert doc["printer"] == {"kind": "Voron 2.4", "wired_ip": "192.168.10.123", "wireless_ip": None,
                              "decommissioned": False, "moonraker_url": "http://192.168.10.123:7125",
                              "connection_type": "moonraker", "prusalink_url": None, "prusalink_username": None}
    assert doc["notes"] == "Bed: PEI. Lives on shelf 2." and doc["service_notes"] == "Gates 6mm belts"
    assert doc["service"]["history"][0]["note"] == "new belts" and doc["service"]["interval_hours"] == 1500
    assert [j["job_id"] for j in doc["print_jobs"]] == ["0003F2", "0003F3"] and doc["print_jobs"][1]["energy_kwh"] == 3.7
    assert [r[2] for r in doc["energy_readings"]] == [2070.0, 2071.5]


def test_an_unchanged_file_isnt_rewritten_and_a_deleted_models_file_goes(db_session, fake, tmp_path):
    p = _printer_with_everything(db_session, fake)
    m = models_svc.create_source_model(db_session, name="Frog.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 64))
    records_service.write_all(db_session, tmp_path)
    assert records_service.write_all(db_session, tmp_path) == {"printers": {"written": 0, "removed": 0}, "models": {"written": 0, "removed": 0}}
    printer_service.update_printer(db_session, p.id, {"kind": "Voron 2.4 r2"})
    assert records_service.write_all(db_session, tmp_path)["printers"]["written"] == 1

    (tmp_path / "models" / "my own notes.json").write_text('{"mine": true}')  # not ours: never touched
    models_svc.delete_source_model(db_session, m.id)
    assert records_service.write_all(db_session, tmp_path)["models"]["removed"] == 1
    assert sorted(f.name for f in (tmp_path / "models").iterdir()) == ["my own notes.json"]


def test_file_names_are_safe_and_never_collide():
    taken = set()
    assert rs.file_stem("V2 BOG", taken) == "V2 BOG"
    assert rs.file_stem("v2 bog", taken) == "v2 bog (2)"  # a NAS may ignore case
    assert rs.file_stem("a/b:c*?", taken) == "a_b_c__"
    assert rs.file_stem("...", taken) == "unnamed"


def test_a_models_file_holds_its_notes_and_its_3mf_files_notes_and_stars(db_session, sample_3mf_paths, tmp_path):
    p = printer_service.create_printer(db_session, name="VT 1190", kind=None, wired_ip=None, wireless_ip=None)
    m = models_svc.create_source_model(db_session, name="Frog.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 64))
    models_svc.set_notes(db_session, m.id, "Print at 0.2", 0)
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        b = bundle_service.create_bundle(db_session, printer_id=p.id, source_model_ids=[m.id], threemf_file_obj=f, threemf_filename="frog.3mf")
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        v2 = bundle_service.add_bundle_version(db_session, bundle_id=b.id, threemf_file_obj=f, threemf_filename="frog-v2.3mf")
    bundle_service.set_notes(db_session, b.id, "Textured sheet", 0)
    bundle_service.set_starred_version(db_session, b.id, v2.id)
    records_service.write_all(db_session, tmp_path)
    doc = json.loads((tmp_path / "models" / "Frog.stl.json").read_text(encoding="utf-8"))
    assert doc["notes"] == "Print at 0.2" and doc["file_type"] == "STL"
    assert doc["threemf"] == [{"printer": "VT 1190", "filenames": ["frog ver 1.3mf", "frog-v2 ver 2.3mf"], "notes": "Textured sheet",
                               "starred": {"version": 2, "filename": "frog-v2 ver 2.3mf"}}]


# ------------------------------------------------------------------ restoring: only ever adds


def _fresh_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_restoring_into_an_empty_farmhand_brings_the_printers_back_whole(db_session, fake, tmp_path):
    _printer_with_everything(db_session, fake)
    records_service.write_all(db_session, tmp_path)

    db = _fresh_session()
    out = records_service.restore_all(db, tmp_path)
    assert out["printers_added"] == ["V2 BOG"] and out["prints_added"] == 2 and out["readings_added"] == 2 and out["warnings"] == []
    p = db.query(Printer).one()
    assert p.kind == "Voron 2.4" and p.wired_ip == "192.168.10.123" and p.moonraker_url == "http://192.168.10.123:7125"
    assert not p.has_moonraker_api_key  # never in the file
    assert p.notes == "Bed: PEI. Lives on shelf 2." and p.service["notes"] == "Gates 6mm belts"
    assert p.service["last_done"]["note"] == "new belts" and p.service["state"] == "ok"
    assert db.query(PrintJob).filter_by(job_id="0003F3").one().energy_kwh == 3.7
    assert [r.energy_kwh for r in db.query(PrinterEnergyReading).order_by(PrinterEnergyReading.taken_at)] == [2070.0, 2071.5]

    again = records_service.restore_all(db, tmp_path)  # a second restore adds nothing
    assert again["printers_added"] == [] and again["printers_filled"] == [] and again["prints_added"] == 0


def test_restoring_never_overwrites_what_farmhand_already_has(db_session, fake, tmp_path):
    _printer_with_everything(db_session, fake)
    records_service.write_all(db_session, tmp_path)

    db = _fresh_session()
    mine = printer_service.create_printer(db, name="V2 BOG", kind="My own kind", wired_ip="10.0.0.5", wireless_ip=None)
    printer_service.set_notes(db, mine.id, "My notes", 0)
    out = records_service.restore_all(db, tmp_path)
    assert out["printers_added"] == [] and out["printers_filled"] == ["V2 BOG"] and out["prints_added"] == 2
    p = db.query(Printer).one()
    assert p.kind == "My own kind" and p.wired_ip == "10.0.0.5" and p.notes == "My notes"  # untouched
    assert p.service["notes"] == "Gates 6mm belts"  # it had none: filled in


def test_notes_and_stars_go_back_onto_matching_models_and_3mf_files(db_session, sample_3mf_paths, tmp_path):
    def build(db, with_notes):
        p = printer_service.create_printer(db, name="VT 1190", kind=None, wired_ip=None, wireless_ip=None)
        m = models_svc.create_source_model(db, name="Frog.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 64))
        with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
            b = bundle_service.create_bundle(db, printer_id=p.id, source_model_ids=[m.id], threemf_file_obj=f, threemf_filename="frog.3mf")
        with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
            v2 = bundle_service.add_bundle_version(db, bundle_id=b.id, threemf_file_obj=f, threemf_filename="frog-v2.3mf")
        if with_notes:
            models_svc.set_notes(db, m.id, "Print at 0.2", 0)
            bundle_service.set_notes(db, b.id, "Textured sheet", 0)
            bundle_service.set_starred_version(db, b.id, v2.id)
        return m, b

    build(db_session, True)
    records_service.write_all(db_session, tmp_path)
    (tmp_path / "models" / "Gone.stl.json").write_text(json.dumps({**rs.header("models", "Gone.stl"), "notes": "x"}))
    (tmp_path / "models" / "broken.json").write_text("{not json")

    db = _fresh_session()
    m, b = build(db, False)
    out = records_service.restore_all(db, tmp_path)
    assert (out["model_notes"], out["threemf_notes"], out["stars"]) == (1, 1, 1)
    assert out["models_missing"] == ["Gone.stl"] and any("broken.json" in w for w in out["warnings"])
    db.expire_all()
    assert m.notes == "Print at 0.2" and b.notes == "Textured sheet" and b.starred_version_id == b.versions[0].id


def test_a_record_from_a_newer_farmhand_is_skipped(tmp_path):
    (tmp_path / "printers").mkdir()
    (tmp_path / "printers" / "x.json").write_text(json.dumps({rs.RECORD_MARKER: "printers", "version": 99, "name": "x"}))
    records, warnings = rs.read_records(tmp_path, "printers")
    assert records == [] and "newer Farmhand" in warnings[0]


# ------------------------------------------------------------------ through the settings folder


@pytest.fixture()
def share(tmp_path, monkeypatch):
    area = tmp_path / "data"
    nas = area / "nas" / "lab"
    nas.mkdir(parents=True)
    monkeypatch.setattr(config.settings, "storage_browse_root", str(area))
    real = str(nas.resolve())
    monkeypatch.setattr(storage, "_is_mount", lambda p: os.path.realpath(p) == real)
    return nas


def test_the_settings_copy_and_restore_include_printers(db_session, fake, share):
    _printer_with_everything(db_session, fake)
    folder = share / "settings"
    folder.mkdir()
    config_service.set_location(db_session, str(folder))
    assert (folder / "printers" / "V2 BOG.json").is_file()
    assert config_service.inspect_location(str(folder))["summary"]["printers"] == 1

    db_session.query(PrintJob).delete()
    db_session.commit()
    result = config_service.restore(db_session)
    assert "printers" in result["restored"] and result["records"]["prints_added"] == 2


def test_background_copies_are_off_until_the_app_starts(monkeypatch):
    monkeypatch.setattr(config_service, "_background_mirror", False)
    config_service.request_mirror()  # does nothing (and starts no thread) in tests
    assert not config_service._mirror_wanted.is_set()
