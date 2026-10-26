from __future__ import annotations

import datetime as dt

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.models import PrinterConnection, PrinterEnergyReading, PrinterServiceReminder, PrintJob
from app.schemas.printer import PrinterOut
from app.services import moonraker as mr
from app.services import printer_service
from app.services.moonraker import client as mr_client, history as mr_history, maintenance as mr_maintenance

from .fake_moonraker import FakeMoonraker


@pytest.fixture()
def fake(monkeypatch):
    f = FakeMoonraker()
    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(f.handle))
    return f


def _printer(db, name="VT 1190", ip="10.0.6.21"):
    return printer_service.create_printer(db, name=name, kind="Voron", wired_ip=ip, wireless_ip=None)


# ------------------------------------------------------------------ where Moonraker is


def test_the_default_address_is_port_7125_of_the_wired_ip(db_session):
    p = printer_service.create_printer(db_session, name="A", kind=None, wired_ip="10.0.6.21", wireless_ip="10.0.6.121")
    assert p.moonraker_url == "http://10.0.6.21:7125" and p.mainsail_url == "http://10.0.6.21/"
    wireless_only = printer_service.create_printer(db_session, name="B", kind=None, wired_ip=None, wireless_ip="10.0.6.9")
    assert wireless_only.moonraker_url == "http://10.0.6.9:7125"
    no_ip = printer_service.create_printer(db_session, name="C", kind=None, wired_ip=None, wireless_ip=None)
    assert no_ip.moonraker_url is None and no_ip.mainsail_url is None


def test_an_address_and_api_key_can_be_set_and_the_key_is_never_shown(db_session):
    p = _printer(db_session)
    p = printer_service.update_printer(db_session, p.id, {"moonraker_url": "http://voron.local:7130", "moonraker_api_key": "abc123"})
    assert p.moonraker_url == "http://voron.local:7130" and p.mainsail_url == "http://voron.local/"
    out = PrinterOut.model_validate(p).model_dump()
    assert out["has_moonraker_api_key"] is True and "abc123" not in str(out)
    p = printer_service.update_printer(db_session, p.id, {"kind": "Voron 2.4"})  # key not sent: kept
    assert p.connection_row.api_key == "abc123"
    p = printer_service.update_printer(db_session, p.id, {"moonraker_url": None, "moonraker_api_key": ""})  # cleared
    assert p.moonraker_url == "http://10.0.6.21:7125" and not p.has_moonraker_api_key


def test_the_address_is_tidied_and_must_be_http():
    from app.schemas.printer import PrinterUpdate

    assert PrinterUpdate(moonraker_url=" 10.0.6.21:7125/ ").moonraker_url == "http://10.0.6.21:7125"
    assert PrinterUpdate(moonraker_url="").moonraker_url is None
    with pytest.raises(ValueError):
        PrinterUpdate(moonraker_url="ftp://10.0.6.21")


# ------------------------------------------------------------------ history: copied into Farmhand


def test_sync_copies_the_history_and_totals(db_session, fake):
    fake.add_job("000001", "frog.gcode", start=1_700_000_000)
    fake.add_job("000002", "shark.gcode", status="cancelled", start=1_700_100_000, print_s=600, filament_mm=300)
    p = _printer(db_session)
    assert mr.sync_history(db_session, p) == {"added": 2, "updated": 0}
    jobs = {j.job_id: j for j in db_session.query(PrintJob)}
    assert jobs["000002"].status == "cancelled" and jobs["000002"].filament_used == 300
    assert jobs["000001"].job_metadata["slicer"] == "PrusaSlicer"
    assert p.connection_row.totals["total_jobs"] == 2 and p.connection_row.last_sync_at and p.connection_row.last_sync_error is None


def test_a_second_sync_only_brings_what_changed(db_session, fake):
    fake.add_job("000001", "frog.gcode")
    fake.add_job("000002", "shark.gcode", status="in_progress", start=1_700_100_000)
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    assert mr.sync_history(db_session, p) == {"added": 0, "updated": 0}
    fake.jobs[1].update(status="completed", end_time=1_700_103_700)  # the print finished
    fake.add_job("000003", "frog.gcode", start=1_700_200_000)
    assert mr.sync_history(db_session, p) == {"added": 1, "updated": 1}
    assert db_session.query(PrintJob).filter_by(job_id="000002").one().status == "completed"


def test_a_long_history_is_fetched_page_by_page(db_session, fake, monkeypatch):
    monkeypatch.setattr(mr_history, "PAGE", 10)
    for i in range(35):
        fake.add_job(f"{i:06d}", f"part{i}.gcode", start=1_700_000_000 + i * 10_000)
    p = _printer(db_session)
    assert mr.sync_history(db_session, p)["added"] == 35
    assert [m for m, path in fake.requests if path == "/server/history/list"] == ["GET"] * 4


def test_jobs_the_printer_forgets_are_kept(db_session, fake):
    fake.add_job("000001", "frog.gcode")
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    fake.jobs.clear()  # history wiped on the printer
    mr.sync_history(db_session, p)
    assert db_session.query(PrintJob).count() == 1


def test_an_unreachable_printer_is_recorded_and_keeps_what_was_synced(db_session, fake):
    fake.add_job("000001", "frog.gcode")
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    fake.down = True
    with pytest.raises(mr.MoonrakerError) as caught:
        mr.sync_history(db_session, p)
    assert caught.value.kind == "unreachable"
    conn = db_session.get(PrinterConnection, p.id)
    assert "Couldn't connect" in conn.last_sync_error and conn.totals["total_jobs"] == 1
    assert db_session.query(PrintJob).count() == 1


def test_an_api_key_is_sent_and_a_missing_one_is_explained(db_session, fake):
    fake.api_key = "secret"
    p = _printer(db_session)
    with pytest.raises(mr.MoonrakerError) as caught:
        mr.server_info(p)
    assert caught.value.kind == "unauthorized" and "API key" in str(caught.value)
    printer_service.update_printer(db_session, p.id, {"moonraker_api_key": "secret"})
    assert mr.server_info(p)["klippy_state"] == "ready"


def test_no_address_is_explained(db_session, fake):
    p = printer_service.create_printer(db_session, name="C", kind=None, wired_ip=None, wireless_ip=None)
    with pytest.raises(mr.MoonrakerError) as caught:
        mr.server_info(p)
    assert caught.value.kind == "no_address"


def test_deleting_a_printer_deletes_its_history_and_connection(db_session, fake):
    fake.add_job("000001", "frog.gcode")
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    db_session.delete(p)
    db_session.commit()
    assert db_session.query(PrintJob).count() == 0 and db_session.query(PrinterConnection).count() == 0


# ------------------------------------------------------------------ energy


def test_sync_brings_each_prints_energy_and_the_totals(db_session, fake):
    fake.add_job("000001", "a.gcode", print_s=2 * 3600, energy_kwh=0.5)
    fake.add_job("000002", "b.gcode", start=1_700_100_000)  # no power meter back then
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    jobs = {j.job_id: j for j in db_session.query(PrintJob)}
    assert jobs["000001"].energy_kwh == 0.5 and jobs["000001"].avg_power_w == 250 and jobs["000001"].max_power_w == 650
    assert jobs["000002"].energy_kwh is None
    assert p.connection_row.auxiliary_totals[0]["total"] == 0.5


def test_jobs_synced_before_energy_was_stored_get_it_on_the_next_sync(db_session, fake):
    fake.add_job("000001", "a.gcode", energy_kwh=1.2)
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    job = db_session.query(PrintJob).one()
    job.energy_kwh = None  # as an older copy would have it
    db_session.commit()
    assert mr.sync_history(db_session, p)["updated"] == 1
    assert db_session.query(PrintJob).one().energy_kwh == 1.2


def test_an_energy_value_in_wh_is_converted():
    assert mr_history._aux({"auxiliary_data": [{"name": "energy_consumption", "value": 1500, "units": "Wh"}]}, "energy_consumption") == 1.5


def test_each_sync_records_a_meter_reading_but_not_twice_in_a_row(db_session, fake, monkeypatch):
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    assert db_session.query(PrinterEnergyReading).count() == 0  # no meter: nothing recorded, and no error
    fake.meter_kwh = 2070.38
    mr.sync_history(db_session, p)
    mr.sync_history(db_session, p)  # straight after: skipped
    readings = db_session.query(PrinterEnergyReading).all()
    assert len(readings) == 1 and readings[0].energy_kwh == 2070.38 and readings[0].sensor == "powermeter"
    monkeypatch.setattr(mr_history, "READING_SPACING", dt.timedelta(0))
    fake.meter_kwh = 2071.0
    mr.sync_history(db_session, p)
    assert [r.energy_kwh for r in db_session.query(PrinterEnergyReading).order_by(PrinterEnergyReading.id)] == [2070.38, 2071.0]


def test_the_energy_endpoint(client, fake, monkeypatch):
    c, pid = client
    assert c.get(f"/printers/{pid}/energy").json() == {"meter": None, "print_total_kwh": None, "jobs": [], "readings": []}
    monkeypatch.setattr(mr_history, "READING_SPACING", dt.timedelta(0))
    fake.meter_kwh = 100.0
    fake.add_job("000001", "a.gcode", start=1_700_000_000, energy_kwh=0.5)
    fake.add_job("000002", "b.gcode", start=1_702_600_000, energy_kwh=0.7)
    c.post(f"/printers/{pid}/moonraker/sync")
    fake.meter_kwh = 101.5
    c.post(f"/printers/{pid}/moonraker/sync")
    e = c.get(f"/printers/{pid}/energy").json()
    assert e["meter"]["energy_kwh"] == 101.5 and e["meter"]["sensor"] == "powermeter"
    assert e["print_total_kwh"] == 1.2
    assert [kwh for _, kwh in e["jobs"]] == [0.5, 0.7] and e["jobs"][0][0].startswith("2023-11-14")
    assert [kwh for _, kwh in e["readings"]] == [100.0, 101.5]
    assert c.get(f"/printers/{pid}/print-jobs").json()["jobs"][0]["energy_kwh"] == 0.7


def test_the_poller_syncs_every_active_printer_and_survives_one_being_off(db_session, fake, monkeypatch):
    from app import printer_poller

    on = _printer(db_session, "On", "10.0.6.21")
    printer_service.create_printer(db_session, name="No address", kind=None, wired_ip=None, wireless_ip=None)
    retired = _printer(db_session, "Retired", "10.0.6.22")
    printer_service.set_decommissioned(db_session, retired.id, True)
    monkeypatch.setattr(printer_poller, "SessionLocal", sessionmaker(bind=db_session.get_bind(), future=True))
    fake.add_job("000001", "a.gcode")
    printer_poller.PrinterPoller().run_once()
    db_session.expire_all()
    assert db_session.get(PrinterConnection, on.id).last_sync_at is not None
    assert db_session.get(PrinterConnection, retired.id) is None  # decommissioned: left alone
    fake.down = True
    printer_poller.PrinterPoller().run_once()  # must not raise
    db_session.expire_all()
    assert "Couldn't connect" in db_session.get(PrinterConnection, on.id).last_sync_error


# ------------------------------------------------------------------ the 1500-hour service: kept in Farmhand

H = 3600.0


def test_the_service_count_starts_at_the_first_sync_from_the_printers_print_time(db_session, fake):
    p = _printer(db_session)
    assert p.service["state"] == "waiting" and p.service["hours_since"] is None  # never synced
    fake.add_job("000001", "a.gcode", print_s=6897 * H)  # a printer that has printed for years
    mr.sync_history(db_session, p)
    s = p.service
    assert s["state"] == "ok" and s["hours_since"] == 0 and s["interval_hours"] == 1500 and s["enabled"]
    assert db_session.get(PrinterServiceReminder, p.id).start_printtime == 6897 * H


def test_it_comes_due_after_1500_more_print_hours(db_session, fake):
    p = _printer(db_session)
    fake.add_job("000001", "a.gcode", print_s=100 * H)
    mr.sync_history(db_session, p)
    fake.add_job("000002", "b.gcode", print_s=1499 * H, start=1_700_100_000)
    mr.sync_history(db_session, p)
    assert p.service["state"] == "ok" and p.service["hours_since"] == 1499
    fake.add_job("000003", "c.gcode", print_s=1 * H, start=1_700_200_000)
    mr.sync_history(db_session, p)
    assert p.service["state"] == "due" and p.service["hours_since"] == 1500


def test_marking_it_done_restarts_the_count_and_keeps_a_record(db_session, fake):
    p = _printer(db_session)
    fake.add_job("000001", "a.gcode", print_s=10 * H)
    mr.sync_history(db_session, p)
    fake.add_job("000002", "b.gcode", print_s=1600 * H, start=1_700_100_000)
    mr.sync_history(db_session, p)
    assert p.service["state"] == "due"
    mr.service_done(db_session, p, note="  new belts, rails cleaned ")
    s = p.service
    assert s["state"] == "ok" and s["hours_since"] == 0
    assert s["last_done"]["hours"] == 1600 and s["last_done"]["note"] == "new belts, rails cleaned"
    fake.add_job("000003", "c.gcode", print_s=20 * H, start=1_700_200_000)
    mr.sync_history(db_session, p)
    assert p.service["hours_since"] == 20


def test_done_while_the_printer_is_off_uses_the_last_synced_print_time(db_session, fake):
    p = _printer(db_session)
    fake.add_job("000001", "a.gcode", print_s=1700 * H)
    mr.sync_history(db_session, p)
    fake.add_job("000002", "b.gcode", print_s=5 * H, start=1_700_100_000)  # printed, but not synced yet
    fake.down = True
    mr.service_done(db_session, p, note="")
    assert db_session.get(PrinterServiceReminder, p.id).start_printtime == 1700 * H


def test_it_can_be_switched_off_and_on(db_session, fake):
    p = _printer(db_session)
    fake.add_job("000001", "a.gcode", print_s=10 * H)
    mr.sync_history(db_session, p)
    fake.add_job("000002", "b.gcode", print_s=2000 * H, start=1_700_100_000)
    mr.sync_history(db_session, p)
    mr.set_service_enabled(db_session, p, False)
    assert p.service["state"] == "off" and p.service["hours_since"] == 2000
    mr.set_service_enabled(db_session, p, True)
    assert p.service["state"] == "due"


def test_nothing_to_mark_done_before_the_first_sync(db_session, fake):
    p = _printer(db_session)
    with pytest.raises(ValueError, match="synced at least once"):
        mr.service_done(db_session, p, note="")


def test_the_service_is_on_the_printer_list_and_can_be_done_over_the_api(client, fake):
    c, pid = client
    assert c.get("/printers").json()[0]["service"]["state"] == "waiting"
    assert c.post(f"/printers/{pid}/service/done", json={}).status_code == 422
    fake.add_job("000001", "a.gcode", print_s=10 * H)
    c.post(f"/printers/{pid}/moonraker/sync")
    fake.add_job("000002", "b.gcode", print_s=1500 * H, start=1_700_100_000)
    c.post(f"/printers/{pid}/moonraker/sync")
    listed = c.get("/printers").json()[0]["service"]
    assert listed["state"] == "due" and listed["hours_since"] == 1500 and listed["started_at"].endswith("+00:00")
    r = c.post(f"/printers/{pid}/service/done", json={"note": "done"})
    assert r.status_code == 200 and r.json()["service"]["state"] == "ok" and r.json()["service"]["last_done"]["note"] == "done"
    r = c.patch(f"/printers/{pid}/service", json={"enabled": False})
    assert r.json()["service"]["state"] == "off"


def test_service_notes_save_with_the_usual_notes_rules(db_session):
    p = _printer(db_session)  # never synced: notes can still be written
    assert p.service["notes"] == "" and p.service["notes_revision"] == 0
    out = mr.set_service_notes(db_session, p, "  Belts: Gates 6mm.\r\nRails: Super Lube.\n\n", 0)
    assert out.service["notes"] == "  Belts: Gates 6mm.\nRails: Super Lube." and out.service["notes_revision"] == 1
    assert out.service["notes_updated_at"].endswith("+00:00")
    with pytest.raises(mr.NotesConflict) as caught:
        mr.set_service_notes(db_session, p, "mine", 0)
    assert caught.value.current["notes"].startswith("  Belts")
    assert mr.set_service_notes(db_session, p, "", 1).service["notes_revision"] == 2  # clearing still counts
    assert p.notes == ""  # the printer's own notes are separate


def test_service_notes_over_the_api(client):
    c, pid = client
    r = c.put(f"/printers/{pid}/service/notes", json={"notes": "Order nozzles first", "base_revision": 0})
    assert r.status_code == 200 and r.json()["service"]["notes"] == "Order nozzles first"
    assert c.get("/printers").json()[0]["service"]["notes_revision"] == 1
    clash = c.put(f"/printers/{pid}/service/notes", json={"notes": "mine", "base_revision": 0})
    assert clash.status_code == 409 and clash.json()["current"]["notes"] == "Order nozzles first"
    assert c.put("/printers/999/service/notes", json={"notes": "x", "base_revision": 0}).status_code == 404
    assert c.put(f"/printers/{pid}/service/notes", json={"notes": "a" * 20001, "base_revision": 1}).status_code == 422


# ------------------------------------------------------------------ maintenance: in Moonraker, Mainsail's format


def test_adding_a_reminder_stores_it_the_way_mainsail_does(db_session, fake):
    fake.add_job("000001", "frog.gcode", print_s=7200, filament_mm=10_000)
    p = _printer(db_session)
    key = mr.add_maintenance(p, name="Lube rails", note="Use PTFE oil", reminder={
        "type": "repeat", "printtime": {"bool": True, "value": 50}, "filament": {"bool": False, "value": None},
        "date": {"bool": True, "value": 30},
    })
    stored = fake.db["maintenance"][key]
    assert stored["name"] == "Lube rails" and stored["note"] == "Use PTFE oil" and stored["perform_note"] is None
    assert stored["start_printtime"] == 7200 and stored["start_filament"] == 10_000
    assert stored["end_time"] is None and stored["end_filament"] is None and stored["end_printtime"] is None
    assert stored["last_entry"] is None and isinstance(stored["start_time"], float)
    assert stored["reminder"] == {
        "type": "repeat", "filament": {"bool": False, "value": None}, "printtime": {"bool": True, "value": 50.0},
        "date": {"bool": True, "value": 30.0},
    }


def test_a_reminder_comes_due_by_print_time_filament_or_days(db_session, fake, monkeypatch):
    p = _printer(db_session)
    mr.add_maintenance(p, name="Nozzle", note="", reminder={"type": "one-time", "printtime": {"bool": True, "value": 2}})
    mr.add_maintenance(p, name="Belts", note="", reminder={"type": "one-time", "filament": {"bool": True, "value": 10}})
    mr.add_maintenance(p, name="Fans", note="", reminder={"type": "one-time", "date": {"bool": True, "value": 7}})
    mr.add_maintenance(p, name="Just a log", note="", reminder=None)
    state = {e["name"]: e for e in mr.list_maintenance(p)["entries"]}
    assert {n: e["state"] for n, e in state.items()} == {"Nozzle": "ok", "Belts": "ok", "Fans": "ok", "Just a log": "no_reminder"}

    fake.add_job("000001", "frog.gcode", print_s=3 * 3600, filament_mm=4000)  # 3 h, 4 m
    state = {e["name"]: e for e in mr.list_maintenance(p)["entries"]}
    assert state["Nozzle"]["state"] == "due" and state["Belts"]["state"] == "ok"
    assert state["Nozzle"]["checks"][0] == {"kind": "printtime", "used": 3.0, "limit": 2.0, "unit": "h", "due": True}
    assert state["Belts"]["checks"][0]["used"] == 4.0 and state["Belts"]["checks"][0]["limit"] == 10.0

    monkeypatch.setattr(mr_maintenance, "_now", lambda: dt.datetime.now(dt.timezone.utc).timestamp() + 8 * 86400)
    assert {e["name"]: e["state"] for e in mr.list_maintenance(p)["entries"]}["Fans"] == "due"


def test_marking_done_closes_it_and_a_repeat_starts_again(db_session, fake):
    fake.add_job("000001", "frog.gcode", print_s=3600, filament_mm=1000)
    p = _printer(db_session)
    once = mr.add_maintenance(p, name="Replace PTFE", note="", reminder={"type": "one-time", "date": {"bool": True, "value": 90}})
    rep = mr.add_maintenance(p, name="Lube rails", note="PTFE oil", reminder={"type": "repeat", "printtime": {"bool": True, "value": 50}})
    fake.add_job("000002", "shark.gcode", print_s=1800, filament_mm=500)

    assert mr.perform_maintenance(p, once, note="  done with Capricorn  ") is None
    done = fake.db["maintenance"][once]
    assert done["end_time"] and done["end_printtime"] == 5400 and done["end_filament"] == 1500
    assert done["perform_note"] == "done with Capricorn"

    nxt = mr.perform_maintenance(p, rep, note="")
    assert fake.db["maintenance"][rep]["perform_note"] is None
    new = fake.db["maintenance"][nxt]
    assert new["last_entry"] == rep and new["name"] == "Lube rails" and new["note"] == "PTFE oil"
    assert new["start_printtime"] == 5400 and new["end_time"] is None and new["reminder"]["type"] == "repeat"

    with pytest.raises(ValueError, match="already been marked done"):
        mr.perform_maintenance(p, once, note="")


def test_reminders_mainsail_made_are_read_and_its_placeholder_is_ignored(db_session, fake):
    fake.db["maintenance"] = {
        "11111111-init": {"name": "MAINTENANCE_INIT"},
        "22222222-made-in-mainsail": {
            "name": "Clean bed", "note": "", "perform_note": None, "start_time": 1_700_000_000.0, "end_time": None,
            "start_filament": 0, "end_filament": None, "start_printtime": 0, "end_printtime": None, "last_entry": None,
            "reminder": {"type": "one-time", "filament": {"bool": False, "value": None},
                         "printtime": {"bool": False, "value": None}, "date": {"bool": True, "value": 1}},
        },
    }
    entries = mr.list_maintenance(_printer(db_session))["entries"]
    assert [e["name"] for e in entries] == ["Clean bed"] and entries[0]["state"] == "due"


def test_a_printer_with_no_reminders_yet_lists_none(db_session, fake):
    assert mr.list_maintenance(_printer(db_session))["entries"] == []


def test_editing_and_deleting_a_reminder(db_session, fake):
    p = _printer(db_session)
    key = mr.add_maintenance(p, name="Belts", note="", reminder={"type": "one-time", "date": {"bool": True, "value": 30}})
    started = fake.db["maintenance"][key]["start_time"]
    mr.update_maintenance(p, key, name="Belt tension", note="GT2 6mm", reminder={"type": "repeat", "date": {"bool": True, "value": 60}})
    e = fake.db["maintenance"][key]
    assert e["name"] == "Belt tension" and e["note"] == "GT2 6mm" and e["reminder"]["date"]["value"] == 60
    assert e["reminder"]["type"] == "repeat" and e["start_time"] == started
    mr.delete_maintenance(p, key)
    assert key not in fake.db["maintenance"]
    with pytest.raises(LookupError):
        mr.delete_maintenance(p, key)


@pytest.mark.parametrize("reminder, message", [
    ({"type": "weekly"}, "repeats, happens once"),
    ({"type": "one-time"}, "Pick at least one"),
    ({"type": "one-time", "printtime": {"bool": True, "value": 0}}, "more than 0"),
    ({"type": "one-time", "filament": {"bool": True, "value": "lots"}}, "Give a number"),
])
def test_bad_reminders_are_refused(db_session, fake, reminder, message):
    with pytest.raises(ValueError, match=message):
        mr.add_maintenance(_printer(db_session), name="x", note="", reminder=reminder)
    assert "maintenance" not in fake.db


# ------------------------------------------------------------------ over the API


@pytest.fixture()
def client(api, fake):
    c = api
    printer = c.post("/printers", json={"name": "VT 1190", "kind": "Voron", "wired_ip": "10.0.6.21"}).json()
    return c, printer["id"]


def test_status_sync_history_and_stats_over_the_api(client, fake):
    c, pid = client
    status = c.get(f"/printers/{pid}/moonraker").json()
    assert status["reachable"] and status["klippy_state"] == "ready" and status["mainsail_url"] == "http://10.0.6.21/"
    assert status["last_sync_at"] is None

    fake.add_job("000001", "VT_1190_frog.gcode", start=1_700_000_000)
    fake.add_job("000002", "VT_1190_shark.gcode", status="cancelled", start=1_700_100_000)
    fake.add_job("000003", "VT_1190_frog.gcode", status="error", start=1_700_200_000)
    r = c.post(f"/printers/{pid}/moonraker/sync")
    assert r.status_code == 200 and r.json()["added"] == 3 and r.json()["totals"]["total_jobs"] == 3

    jobs = c.get(f"/printers/{pid}/print-jobs").json()
    assert jobs["total"] == 3 and [j["job_id"] for j in jobs["jobs"]] == ["000003", "000002", "000001"]  # newest first
    assert jobs["jobs"][0]["slicer"] == "PrusaSlicer" and jobs["jobs"][0]["start_time"].endswith("+00:00")
    assert c.get(f"/printers/{pid}/print-jobs", params={"q": "frog"}).json()["total"] == 2
    assert c.get(f"/printers/{pid}/print-jobs", params={"status": "failed"}).json()["total"] == 2
    assert c.get(f"/printers/{pid}/print-jobs", params={"limit": 1, "offset": 1}).json()["jobs"][0]["job_id"] == "000002"

    stats = c.get(f"/printers/{pid}/print-stats").json()
    assert stats["archive"]["jobs"] == 3 and stats["archive"]["by_status"] == {"completed": 1, "cancelled": 1, "error": 1}
    assert stats["totals"]["total_jobs"] == 3


def test_an_unreachable_printer_answers_502_with_why(client, fake):
    c, pid = client
    fake.down = True
    status = c.get(f"/printers/{pid}/moonraker").json()
    assert status["reachable"] is False and status["error_kind"] == "unreachable"
    r = c.post(f"/printers/{pid}/moonraker/sync")
    assert r.status_code == 502 and r.json()["kind"] == "unreachable"
    assert c.get(f"/printers/{pid}/maintenance").status_code == 502
    assert c.get(f"/printers/{pid}/moonraker").json()["last_sync_error"]  # the failed sync is remembered


def test_maintenance_over_the_api(client, fake):
    c, pid = client
    r = c.post(f"/printers/{pid}/maintenance", json={"name": "Lube rails", "reminder": {"type": "repeat", "printtime": {"bool": True, "value": 50}}})
    assert r.status_code == 201
    key = r.json()["id"]
    assert [e["name"] for e in r.json()["entries"]] == ["Lube rails"]

    r = c.put(f"/printers/{pid}/maintenance/{key}", json={"note": "PTFE oil"})
    assert r.json()["entries"][0]["note"] == "PTFE oil"

    r = c.post(f"/printers/{pid}/maintenance/{key}/done", json={"note": "done"})
    assert r.status_code == 200 and r.json()["next_id"]
    states = sorted(e["state"] for e in r.json()["entries"])
    assert states == ["done", "ok"]

    assert c.delete(f"/printers/{pid}/maintenance/{key}").status_code == 409  # needs confirm
    assert c.delete(f"/printers/{pid}/maintenance/{key}", params={"confirm": "true"}).status_code == 200
    assert c.delete(f"/printers/{pid}/maintenance/nope", params={"confirm": "true"}).status_code == 404
    assert c.post(f"/printers/{pid}/maintenance", json={"name": "  "}).status_code == 422
    assert c.get("/printers/999/maintenance").status_code == 404


def test_the_printer_api_carries_the_moonraker_settings(client):
    c, pid = client
    r = c.patch(f"/printers/{pid}", json={"moonraker_url": "voron.local:7125", "moonraker_api_key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body["moonraker_url"] == "http://voron.local:7125" and body["moonraker_url_override"] == "http://voron.local:7125"
    assert body["has_moonraker_api_key"] is True and "moonraker_api_key" not in body
    assert c.patch(f"/printers/{pid}", json={"moonraker_url": "ftp://x"}).status_code == 422
