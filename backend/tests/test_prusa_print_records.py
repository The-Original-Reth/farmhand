"""A Prusa print's start, end and filament from Prusa Connect's own record of it, and the slicer's estimate as the
fallback (services/prusalink/tracking.py, filament_estimate.py, printed_filament.py)."""
from __future__ import annotations

import datetime as dt

import pytest

from app.services.prusalink import printed_filament

from .test_printer_reports import EXTRAS, PRINTING, _core_one, _fresh, _install, _report  # noqa: F401

PRINT_ID = "0199e3a4-5bb5-7aac-8a2c-9c3982e6373f"
STARTED = "2026-11-20T04:26:10Z"


@pytest.fixture()
def inline_reads(monkeypatch):
    monkeypatch.setattr(printed_filament, "run_in_background", lambda work: work())
    printed_filament.forget_all()
    yield
    printed_filament.forget_all()


def _connect_printer(api):
    auth = _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    return auth, p


def _job(job_id=506, state="PRINTING", time_printing=29000, progress=40, odometer=236033.0, **recorded):
    """A report of print `job_id`; `recorded`: what Prusa Connect's record adds (started, print_id, filament_used...)."""
    return {**PRINTING, "state": state, "extras": {**EXTRAS, "odometer_e": odometer},
            "job": {**PRINTING["job"], "id": job_id, "state": state, "time_printing": time_printing,
                    "progress": progress, **recorded}}


def _jobs(api, p):
    return sorted(api.get(f"/printers/{p['id']}/print-jobs").json()["jobs"], key=lambda j: j["start_time"])


def _at(text):
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def test_prusa_connects_start_is_used_outright_even_after_a_long_pause(api, prusalink):
    auth, p = _connect_printer(api)
    # 29000 s of printing would put the start 8 hours before now; the print waited, paused, and started at STARTED
    assert _report(api, auth, p["id"], _job(started=STARTED, print_id=PRINT_ID)).status_code == 200
    [job] = _jobs(api, p)
    assert _at(job["start_time"]) == _at(STARTED)
    _report(api, auth, p["id"], _job(time_printing=29100, started=STARTED, print_id=PRINT_ID))
    [job] = _jobs(api, p)
    assert _at(job["start_time"]) == _at(STARTED)


def test_a_start_given_later_puts_a_guessed_one_right(api, prusalink):
    auth, p = _connect_printer(api)
    _report(api, auth, p["id"], _job(time_printing=600))  # no record yet: the start is worked back from 600 s
    _report(api, auth, p["id"], _job(time_printing=660, started=STARTED, print_id=PRINT_ID))
    [job] = _jobs(api, p)
    assert _at(job["start_time"]) == _at(STARTED)


def test_prusa_connects_measured_filament_is_the_prints(api, prusalink):
    auth, p = _connect_printer(api)
    _report(api, auth, p["id"], _job(started=STARTED, print_id=PRINT_ID, filament_used=812.25))
    _report(api, auth, p["id"], _job(state="FINISHED", progress=100, started=STARTED, print_id=PRINT_ID,
                                     filament_used=2040.5))
    [job] = _jobs(api, p)
    assert job["filament_used"] == 2040.5 and not job["filament_estimated"] and job["status"] == "completed"


def test_an_ended_print_takes_prusa_connects_end_outcome_and_filament(api, prusalink):
    auth, p = _connect_printer(api)
    _report(api, auth, p["id"], _job(job_id=505, time_printing=60, started="2026-11-19T20:00:00Z", print_id="a-505"))
    ended = {"print_id": "a-505", "id": 505, "file": "Frog keychain.bgcode", "path": "/usb/FROGKE~1.BGC",
             "started": "2026-11-19T20:00:00Z", "ended": "2026-11-19T22:00:05Z", "outcome": "cancelled",
             "progress": 63, "filament_used": 4321.5}
    # the next print has begun: 505's end is what Prusa Connect recorded, not when Farmhand noticed
    _report(api, auth, p["id"], {**_job(started=STARTED, print_id=PRINT_ID), "recent_prints": [ended]})
    first, second = _jobs(api, p)
    assert _at(first["end_time"]) == _at("2026-11-19T22:00:05Z") and first["status"] == "cancelled"
    assert first["filament_used"] == 4321.5 and not first["filament_estimated"]
    assert _at(second["start_time"]) == _at(STARTED) and second["end_time"] is None
    _report(api, auth, p["id"], {**_job(started=STARTED, print_id=PRINT_ID), "recent_prints": [ended]})
    assert len(_jobs(api, p)) == 2  # put on once, nothing added


def test_prints_missed_while_farmhand_was_down_are_recorded(api, prusalink):
    auth, p = _connect_printer(api)
    _report(api, auth, p["id"], _job(job_id=505, time_printing=60, started="2026-11-19T20:00:00Z", print_id="a-505"))
    recent = [
        {"print_id": "a-507", "id": 507, "file": "Bolt.bgcode", "started": "2026-11-20T01:00:00Z",
         "ended": "2026-11-20T02:00:00Z", "outcome": "finished", "progress": 100, "filament_used": 900.0},
        {"print_id": "a-506", "id": 506, "file": "Nut.bgcode", "started": "2026-11-19T23:00:00Z",
         "ended": "2026-11-20T00:00:00Z", "outcome": "failed", "progress": 20},
        {"print_id": "a-505", "id": 505, "file": "Frog keychain.bgcode", "started": "2026-11-19T20:00:00Z",
         "ended": "2026-11-19T22:00:00Z", "outcome": "finished", "progress": 100, "filament_used": 4000.0},
        {"print_id": "a-400", "id": 400, "file": "Old.bgcode", "started": "2026-11-18T20:00:00Z",
         "ended": "2026-11-18T22:00:00Z", "outcome": "finished", "progress": 100},
    ]
    _report(api, auth, p["id"], {**_job(job_id=508, started=STARTED, print_id="a-508"), "recent_prints": recent})
    jobs = {j["filename"]: j for j in _jobs(api, p)}
    assert jobs["Bolt.bgcode"]["status"] == "completed" and jobs["Bolt.bgcode"]["filament_used"] == 900.0
    assert jobs["Nut.bgcode"]["status"] == "error" and jobs["Nut.bgcode"]["filament_used"] == 0
    assert "Old.bgcode" not in jobs  # from before Farmhand followed this printer's prints through Prusa Connect


def test_a_print_nobody_measured_gets_prusa_connects_slicer_figure(api, prusalink):
    auth, p = _connect_printer(api)
    slicer = {"filament_mm": 2000.0, "filament_g": 6.0, "estimated_seconds": 3600, "material": "PETG"}
    # seen an hour in (no odometer start, nothing measured), then cancelled half way
    _report(api, auth, p["id"], _job(time_printing=3600, progress=30, print_id=PRINT_ID, slicer=slicer))
    _report(api, auth, p["id"], _job(state="STOPPED", time_printing=3700, progress=50, print_id=PRINT_ID, slicer=slicer))
    [job] = _jobs(api, p)
    assert job["filament_used"] == 1000.0 and job["filament_estimated"]


TEXT_GCODE = b"G28\n" * 50 + b"; filament used [mm] = 4000.00\n; filament used [g] = 12.00\n"


def test_a_prusalink_print_with_no_3mf_is_estimated_from_its_file_read_once(api, prusalink, inline_reads):
    p = _core_one(api, "MK4")
    prusalink.files["Frog keychain.gcode"] = (TEXT_GCODE, 1_700_000_000)
    prusalink.start_job(7, "Frog keychain.gcode", progress=10, time_printing=60)
    api.get(f"/printers/{p['id']}/prusalink")  # no 3MF matches: the file is read (once, read only)
    prusalink.advance(progress=50, time_printing=600, state="STOPPED")
    api.get(f"/printers/{p['id']}/prusalink")
    [job] = _jobs(api, p)
    assert job["filament_used"] == 2000.0 and job["filament_estimated"]
    assert prusalink.downloaded == ["Frog keychain.gcode"] and {m for m, _ in prusalink.requests} == {"GET"}
    api.get(f"/printers/{p['id']}/prusalink")
    assert prusalink.downloaded == ["Frog keychain.gcode"]


def test_a_print_recorded_before_farmhand_followed_prusa_connects_record_is_left_alone(api, prusalink):
    auth, p = _connect_printer(api)
    _report(api, auth, p["id"], _job(job_id=500, time_printing=60))  # recorded with no Prusa Connect id
    _report(api, auth, p["id"], _job(job_id=500, state="FINISHED", time_printing=600, progress=100))
    [before] = _jobs(api, p)
    began = dt.datetime.fromisoformat(before["start_time"])
    recent = [{"print_id": "a-500", "id": 500, "file": "Frog keychain.bgcode", "started": began.isoformat(),
               "ended": (began + dt.timedelta(hours=2)).isoformat(), "outcome": "cancelled", "filament_used": 50.0}]
    _report(api, auth, p["id"], {**_job(job_id=501, started=STARTED, print_id="a-501"), "recent_prints": recent})
    old = next(j for j in _jobs(api, p) if j["id"] == before["id"])
    assert old["end_time"] == before["end_time"] and old["status"] == before["status"] and old["filament_used"] == 0
