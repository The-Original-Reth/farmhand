"""The 1500-hour service: kept in Farmhand, counted from the printer's print time."""
from __future__ import annotations


import pytest

from app.models import PrinterServiceReminder
from app.services import moonraker as mr

from .factories import klipper_printer as _printer


# ------------------------------------------------------------------ the 1500-hour service: kept in Farmhand

H = 3600.0


def test_the_service_count_starts_at_the_first_sync_from_the_printers_print_time(db_session, moonraker):
    p = _printer(db_session)
    assert p.service["state"] == "waiting" and p.service["hours_since"] is None  # never synced
    moonraker.add_job("000001", "a.gcode", print_s=6897 * H)  # a printer that has printed for years
    mr.sync_history(db_session, p)
    s = p.service
    assert s["state"] == "ok" and s["hours_since"] == 0 and s["interval_hours"] == 1500 and s["enabled"]
    assert db_session.get(PrinterServiceReminder, p.id).start_printtime == 6897 * H


def test_it_comes_due_after_1500_more_print_hours(db_session, moonraker):
    p = _printer(db_session)
    moonraker.add_job("000001", "a.gcode", print_s=100 * H)
    mr.sync_history(db_session, p)
    moonraker.add_job("000002", "b.gcode", print_s=1499 * H, start=1_700_100_000)
    mr.sync_history(db_session, p)
    assert p.service["state"] == "ok" and p.service["hours_since"] == 1499
    moonraker.add_job("000003", "c.gcode", print_s=1 * H, start=1_700_200_000)
    mr.sync_history(db_session, p)
    assert p.service["state"] == "due" and p.service["hours_since"] == 1500


def test_marking_it_done_restarts_the_count_and_keeps_a_record(db_session, moonraker):
    p = _printer(db_session)
    moonraker.add_job("000001", "a.gcode", print_s=10 * H)
    mr.sync_history(db_session, p)
    moonraker.add_job("000002", "b.gcode", print_s=1600 * H, start=1_700_100_000)
    mr.sync_history(db_session, p)
    assert p.service["state"] == "due"
    mr.service_done(db_session, p, note="  new belts, rails cleaned ")
    s = p.service
    assert s["state"] == "ok" and s["hours_since"] == 0
    assert s["last_done"]["hours"] == 1600 and s["last_done"]["note"] == "new belts, rails cleaned"
    moonraker.add_job("000003", "c.gcode", print_s=20 * H, start=1_700_200_000)
    mr.sync_history(db_session, p)
    assert p.service["hours_since"] == 20


def test_done_while_the_printer_is_off_uses_the_last_synced_print_time(db_session, moonraker):
    p = _printer(db_session)
    moonraker.add_job("000001", "a.gcode", print_s=1700 * H)
    mr.sync_history(db_session, p)
    moonraker.add_job("000002", "b.gcode", print_s=5 * H, start=1_700_100_000)  # printed, but not synced yet
    moonraker.down = True
    mr.service_done(db_session, p, note="")
    assert db_session.get(PrinterServiceReminder, p.id).start_printtime == 1700 * H


def test_it_can_be_switched_off_and_on(db_session, moonraker):
    p = _printer(db_session)
    moonraker.add_job("000001", "a.gcode", print_s=10 * H)
    mr.sync_history(db_session, p)
    moonraker.add_job("000002", "b.gcode", print_s=2000 * H, start=1_700_100_000)
    mr.sync_history(db_session, p)
    mr.set_service_enabled(db_session, p, False)
    assert p.service["state"] == "off" and p.service["hours_since"] == 2000
    mr.set_service_enabled(db_session, p, True)
    assert p.service["state"] == "due"


def test_nothing_to_mark_done_before_the_first_sync(db_session, moonraker):
    p = _printer(db_session)
    with pytest.raises(ValueError, match="synced at least once"):
        mr.service_done(db_session, p, note="")


def test_the_service_is_on_the_printer_list_and_can_be_done_over_the_api(klipper, moonraker):
    c, pid = klipper
    assert c.get("/printers").json()[0]["service"]["state"] == "waiting"
    assert c.post(f"/printers/{pid}/service/done", json={}).status_code == 422
    moonraker.add_job("000001", "a.gcode", print_s=10 * H)
    c.post(f"/printers/{pid}/moonraker/sync")
    moonraker.add_job("000002", "b.gcode", print_s=1500 * H, start=1_700_100_000)
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


def test_service_notes_over_the_api(klipper):
    c, pid = klipper
    r = c.put(f"/printers/{pid}/service/notes", json={"notes": "Order nozzles first", "base_revision": 0})
    assert r.status_code == 200 and r.json()["service"]["notes"] == "Order nozzles first"
    assert c.get("/printers").json()[0]["service"]["notes_revision"] == 1
    clash = c.put(f"/printers/{pid}/service/notes", json={"notes": "mine", "base_revision": 0})
    assert clash.status_code == 409 and clash.json()["current"]["notes"] == "Order nozzles first"
    assert c.put("/printers/999/service/notes", json={"notes": "x", "base_revision": 0}).status_code == 404
    assert c.put(f"/printers/{pid}/service/notes", json={"notes": "a" * 20001, "base_revision": 1}).status_code == 422
