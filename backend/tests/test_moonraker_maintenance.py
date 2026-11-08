"""Maintenance reminders: kept in Moonraker, in Mainsail's format."""
from __future__ import annotations

import datetime as dt

import pytest

from app.services import moonraker as mr
from app.services.moonraker import maintenance as mr_maintenance

from .factories import klipper_printer as _printer


# ------------------------------------------------------------------ maintenance: in Moonraker, Mainsail's format


def test_adding_a_reminder_stores_it_the_way_mainsail_does(db_session, moonraker):
    moonraker.add_job("000001", "frog.gcode", print_s=7200, filament_mm=10_000)
    p = _printer(db_session)
    key = mr.add_maintenance(p, name="Lube rails", note="Use PTFE oil", reminder={
        "type": "repeat", "printtime": {"bool": True, "value": 50}, "filament": {"bool": False, "value": None},
        "date": {"bool": True, "value": 30},
    })
    stored = moonraker.db["maintenance"][key]
    assert stored["name"] == "Lube rails" and stored["note"] == "Use PTFE oil" and stored["perform_note"] is None
    assert stored["start_printtime"] == 7200 and stored["start_filament"] == 10_000
    assert stored["end_time"] is None and stored["end_filament"] is None and stored["end_printtime"] is None
    assert stored["last_entry"] is None and isinstance(stored["start_time"], float)
    assert stored["reminder"] == {
        "type": "repeat", "filament": {"bool": False, "value": None}, "printtime": {"bool": True, "value": 50.0},
        "date": {"bool": True, "value": 30.0},
    }


def test_a_reminder_comes_due_by_print_time_filament_or_days(db_session, moonraker, monkeypatch):
    p = _printer(db_session)
    mr.add_maintenance(p, name="Nozzle", note="", reminder={"type": "one-time", "printtime": {"bool": True, "value": 2}})
    mr.add_maintenance(p, name="Belts", note="", reminder={"type": "one-time", "filament": {"bool": True, "value": 10}})
    mr.add_maintenance(p, name="Fans", note="", reminder={"type": "one-time", "date": {"bool": True, "value": 7}})
    mr.add_maintenance(p, name="Just a log", note="", reminder=None)
    state = {e["name"]: e for e in mr.list_maintenance(p)["entries"]}
    assert {n: e["state"] for n, e in state.items()} == {"Nozzle": "ok", "Belts": "ok", "Fans": "ok", "Just a log": "no_reminder"}

    moonraker.add_job("000001", "frog.gcode", print_s=3 * 3600, filament_mm=4000)  # 3 h, 4 m
    state = {e["name"]: e for e in mr.list_maintenance(p)["entries"]}
    assert state["Nozzle"]["state"] == "due" and state["Belts"]["state"] == "ok"
    assert state["Nozzle"]["checks"][0] == {"kind": "printtime", "used": 3.0, "limit": 2.0, "unit": "h", "due": True}
    assert state["Belts"]["checks"][0]["used"] == 4.0 and state["Belts"]["checks"][0]["limit"] == 10.0

    monkeypatch.setattr(mr_maintenance, "_now", lambda: dt.datetime.now(dt.timezone.utc).timestamp() + 8 * 86400)
    assert {e["name"]: e["state"] for e in mr.list_maintenance(p)["entries"]}["Fans"] == "due"


def test_marking_done_closes_it_and_a_repeat_starts_again(db_session, moonraker):
    moonraker.add_job("000001", "frog.gcode", print_s=3600, filament_mm=1000)
    p = _printer(db_session)
    once = mr.add_maintenance(p, name="Replace PTFE", note="", reminder={"type": "one-time", "date": {"bool": True, "value": 90}})
    rep = mr.add_maintenance(p, name="Lube rails", note="PTFE oil", reminder={"type": "repeat", "printtime": {"bool": True, "value": 50}})
    moonraker.add_job("000002", "shark.gcode", print_s=1800, filament_mm=500)

    assert mr.perform_maintenance(p, once, note="  done with Capricorn  ") is None
    done = moonraker.db["maintenance"][once]
    assert done["end_time"] and done["end_printtime"] == 5400 and done["end_filament"] == 1500
    assert done["perform_note"] == "done with Capricorn"

    nxt = mr.perform_maintenance(p, rep, note="")
    assert moonraker.db["maintenance"][rep]["perform_note"] is None
    new = moonraker.db["maintenance"][nxt]
    assert new["last_entry"] == rep and new["name"] == "Lube rails" and new["note"] == "PTFE oil"
    assert new["start_printtime"] == 5400 and new["end_time"] is None and new["reminder"]["type"] == "repeat"

    with pytest.raises(ValueError, match="already been marked done"):
        mr.perform_maintenance(p, once, note="")


def test_reminders_mainsail_made_are_read_and_its_placeholder_is_ignored(db_session, moonraker):
    moonraker.db["maintenance"] = {
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


def test_a_printer_with_no_reminders_yet_lists_none(db_session, moonraker):
    assert mr.list_maintenance(_printer(db_session))["entries"] == []


def test_editing_and_deleting_a_reminder(db_session, moonraker):
    p = _printer(db_session)
    key = mr.add_maintenance(p, name="Belts", note="", reminder={"type": "one-time", "date": {"bool": True, "value": 30}})
    started = moonraker.db["maintenance"][key]["start_time"]
    mr.update_maintenance(p, key, name="Belt tension", note="GT2 6mm", reminder={"type": "repeat", "date": {"bool": True, "value": 60}})
    e = moonraker.db["maintenance"][key]
    assert e["name"] == "Belt tension" and e["note"] == "GT2 6mm" and e["reminder"]["date"]["value"] == 60
    assert e["reminder"]["type"] == "repeat" and e["start_time"] == started
    mr.delete_maintenance(p, key)
    assert key not in moonraker.db["maintenance"]
    with pytest.raises(LookupError):
        mr.delete_maintenance(p, key)


@pytest.mark.parametrize("reminder, message", [
    ({"type": "weekly"}, "repeats, happens once"),
    ({"type": "one-time"}, "Pick at least one"),
    ({"type": "one-time", "printtime": {"bool": True, "value": 0}}, "more than 0"),
    ({"type": "one-time", "filament": {"bool": True, "value": "lots"}}, "Give a number"),
])
def test_bad_reminders_are_refused(db_session, moonraker, reminder, message):
    with pytest.raises(ValueError, match=message):
        mr.add_maintenance(_printer(db_session), name="x", note="", reminder=reminder)
    assert "maintenance" not in moonraker.db
