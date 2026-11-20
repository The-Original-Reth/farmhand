"""A Prusa printer taking its status from a plugin (printers:report, e.g. the Prusa Connect plugin) instead of its PrusaLink."""
from __future__ import annotations

import pytest

from app.services import printer_reports
from app.services.plugins import cache, events, limits

MANIFEST = {
    "id": "prusa-connect", "name": "Prusa Connect", "version": "1.0.0", "farmhand_api": "1", "port": 8085,
    "page": {"menu": "Prusa Connect", "icon": "dashboard", "path": "/"},
    "permissions": ["printers:read", "printers:report"], "health": "/health",
}

PRINTING = {
    "state": "PRINTING", "temps": {"temp_nozzle": 214.6, "target_nozzle": 215, "temp_bed": 60, "target_bed": 60},
    "printer_type": "COREONE", "firmware": "6.4.0", "link": "http://192.168.10.93:8080/printers/abc",
    "job": {"id": 12, "state": "PRINTING", "file": "Frog keychain.bgcode", "path": "/usb/FROGKE~1.BGC", "progress": 40,
            "time_printing": 1200, "time_remaining": 1800},
}


@pytest.fixture(autouse=True)
def _fresh():
    cache.clear()
    limits.reset()
    events.reset()
    printer_reports.forget_all()
    yield
    printer_reports.forget_all()


def _install(api, permissions=("printers:read", "printers:report")) -> dict:
    r = api.post("/plugins", json={"manifest": MANIFEST, "permissions": list(permissions)})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _core_one(api, name="Core One"):
    return api.post("/printers", json={"name": name, "connection_type": "prusalink", "wired_ip": "10.0.6.40",
                                       "prusalink_password": "secret123"}).json()


def _report(api, auth, printer_id, body):
    return api.put(f"/plugin-api/v1/printers/{printer_id}/status", json=body, headers=auth)


def test_prusalink_is_the_default_and_a_reporting_plugin_can_be_chosen(api, prusalink):
    p = _core_one(api)
    assert p["status_from"] is None
    assert api.get("/printers/status-reporters").json() == []
    r = api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    assert r.status_code == 409 and "Plugins page" in r.json()["detail"]

    _install(api)
    assert api.get("/printers/status-reporters").json() == [{"id": "prusa-connect", "name": "Prusa Connect"}]
    assert api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"}).json()["status_from"] == "prusa-connect"

    klipper = api.post("/printers", json={"name": "VT 1190", "wired_ip": "10.0.6.21"}).json()
    assert "Only a Prusa printer" in api.patch(f"/printers/{klipper['id']}", json={"status_from": "prusa-connect"}).json()["detail"]

    back = api.patch(f"/printers/{p['id']}", json={"status_from": ""}).json()
    assert back["status_from"] is None and back["has_prusalink_password"]  # its PrusaLink login was kept


def test_a_plugin_without_the_permission_cannot_be_chosen_or_report(api, prusalink):
    auth = _install(api, permissions=["printers:read"])
    p = _core_one(api)
    assert api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"}).status_code == 409
    r = _report(api, auth, p["id"], PRINTING)
    assert r.status_code == 403 and "printers:report" in r.json()["detail"]


def test_only_printers_switched_to_the_plugin_take_its_reports(api, prusalink):
    auth = _install(api)
    p = _core_one(api)
    r = _report(api, auth, p["id"], PRINTING)
    assert r.status_code == 403 and "from its PrusaLink" in r.json()["detail"]
    listed = api.get("/plugin-api/v1/printers", headers=auth).json()["printers"]
    assert listed[0]["status_from"] is None

    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    cache.clear()
    assert api.get("/plugin-api/v1/printers", headers=auth).json()["printers"][0]["status_from"] == "prusa-connect"
    assert _report(api, auth, p["id"], PRINTING).json() == {"recorded": True, "error": None}
    assert _report(api, auth, 999, PRINTING).status_code == 404
    assert _report(api, auth, p["id"], {**PRINTING, "job": {"id": 1, "progress": 150}}).status_code == 422


def test_its_status_and_prints_come_from_the_reports(api, prusalink):
    auth = _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})

    out = api.get(f"/printers/{p['id']}/prusalink").json()
    assert not out["reachable"] and "hasn't said how Core One is" in out["error"]  # no report yet

    _report(api, auth, p["id"], PRINTING)
    out = api.get(f"/printers/{p['id']}/prusalink").json()
    assert out["reachable"] and out["state"] == "PRINTING" and out["temps"]["target_nozzle"] == 215
    assert out["printer_type"] == "COREONE" and out["firmware"] == "6.4.0"
    assert out["job"]["file"] == "Frog keychain.bgcode" and out["job"]["progress"] == 40
    assert out["status_from"] == {"id": "prusa-connect", "name": "Prusa Connect", "link": "http://192.168.10.93:8080/printers/abc"}
    # its own PrusaLink was only asked about the printed file (for its price), read only
    assert {m for m, _ in prusalink.requests} <= {"GET"} and all(p.startswith("/api/v1/files/") for _, p in prusalink.requests)

    done = {**PRINTING, "state": "FINISHED", "job": {**PRINTING["job"], "state": "FINISHED", "progress": 100, "time_printing": 3000}}
    _report(api, auth, p["id"], done)
    [job] = api.get(f"/printers/{p['id']}/print-jobs").json()["jobs"]
    assert job["filename"] == "Frog keychain.bgcode" and job["status"] == "completed"


def test_a_printer_the_plugin_cannot_hear_and_a_plugin_that_stopped_say_so(api, prusalink, monkeypatch):
    auth = _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    r = _report(api, auth, p["id"], {"reachable": False, "error": "Prusa Connect isn't hearing from Core One."})
    assert r.json() == {"recorded": False, "error": "Prusa Connect isn't hearing from Core One."}
    assert api.get(f"/printers/{p['id']}/prusalink").json()["error_kind"] == "unreachable"

    _report(api, auth, p["id"], PRINTING)
    monkeypatch.setattr(printer_reports, "STALE_SECONDS", -1)
    assert "hasn't said how Core One is" in api.get(f"/printers/{p['id']}/prusalink").json()["error"]


def test_removing_the_plugin_puts_its_printers_back_on_prusalink(api, prusalink):
    _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    assert api.delete("/plugins/prusa-connect?confirm=true").status_code in (200, 204)
    assert api.get(f"/printers/{p['id']}").json()["status_from"] is None


def test_the_printer_file_remembers_the_choice(api, prusalink, db_session):
    from app.services import records_service

    _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    printer = api.get(f"/printers/{p['id']}").json()
    assert printer["status_from"] == "prusa-connect"
    # the record is written from the same properties the API shows
    from app.models import Printer, PrinterStatusSource, PrusaLinkConnection

    row = Printer(name="Copy", wired_ip="10.0.6.41")
    db_session.add(row)
    db_session.flush()
    row.prusalink_row = PrusaLinkConnection(printer_id=row.id, username="maker")
    row.status_source_row = PrinterStatusSource(printer_id=row.id, plugin_id="prusa-connect")
    db_session.commit()
    [doc] = records_service.printer_documents(db_session).values()
    assert doc["printer"]["status_from"] == "prusa-connect"


# ------------------------------------------------------------------ prints sent through the plugin (printers:print)

PRINTING_MANIFEST = {**MANIFEST, "permissions": ["printers:read", "printers:report", "printers:print"], "print": {"path": "/farmhand/print"}}
READY = {**PRINTING, "state": "IDLE", "job": None}


def _plugin_that_prints(api, monkeypatch, answer=None):
    """The plugin added with printers:print, and a stand-in for it at its address that fetches each print it's handed."""
    import httpx

    from app.services.plugins import remote

    r = api.post("/plugins", json={"manifest": PRINTING_MANIFEST, "permissions": PRINTING_MANIFEST["permissions"]})
    assert r.status_code == 201, r.text
    auth = {"Authorization": f"Bearer {r.json()['token']}"}
    handed = []

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        got = api.get(f"/plugin-api/v1/prints/{body['ticket']}/file", headers=auth)
        again = api.get(f"/plugin-api/v1/prints/{body['ticket']}/file", headers=auth)
        handed.append({"url": str(request.url), "body": body, "status": got.status_code, "data": got.content,
                       "name": got.headers.get("x-farmhand-file"), "again": again.status_code})
        if answer:
            return httpx.Response(answer[0], json=answer[1])
        return httpx.Response(200, json={"sent": f"usb/{body['file']}"})

    monkeypatch.setattr(remote, "transport", httpx.MockTransport(handle))
    return auth, handed


def test_a_print_is_handed_to_the_plugin_and_prusalink_is_never_asked(api, prusalink, monkeypatch):
    auth, handed = _plugin_that_prints(api, monkeypatch)
    p = api.post("/printers", json={"name": "Core One", "connection_type": "prusalink", "status_from": "prusa-connect"}).json()
    assert p["status_from"] == "prusa-connect"  # connected through the plugin from the start, no IP or PrusaLink login
    _report(api, auth, p["id"], READY)
    listed = next(x for x in api.get("/printers").json() if x["id"] == p["id"])
    assert listed["status_from_name"] == "Prusa Connect" and listed["status_link"] == READY["link"]  # its page there
    r = api.post(f"/printers/{p['id']}/prusalink/print", files={"file": ("Frog keychain.bgcode", b"GCDE" + b"x" * 100)})
    assert r.status_code == 200 and r.json()["sent"] == "usb/Frog keychain.bgcode"
    [h] = handed
    assert h["url"] == "http://prusa-connect:8085/farmhand/print" and h["body"]["printer_id"] == p["id"] and h["body"]["size"] == 104
    assert h["status"] == 200 and h["data"] == b"GCDE" + b"x" * 100 and h["name"] == "Frog%20keychain.bgcode"
    assert h["again"] == 404  # a ticket is good once
    assert prusalink.uploads == []  # its PrusaLink was never sent anything


def test_a_busy_printer_or_a_refusal_is_said_plainly(api, prusalink, monkeypatch):
    auth, handed = _plugin_that_prints(api, monkeypatch, answer=(409, {"detail": "Prusa Connect says Core One is printing."}))
    p = api.post("/printers", json={"name": "Core One", "connection_type": "prusalink", "status_from": "prusa-connect"}).json()
    _report(api, auth, p["id"], PRINTING)
    r = api.post(f"/printers/{p['id']}/prusalink/print", files={"file": ("next.bgcode", b"GCDE")})
    assert r.status_code == 409 and handed == []  # Farmhand saw it printing: nothing handed over
    _report(api, auth, p["id"], READY)
    r = api.post(f"/printers/{p['id']}/prusalink/print", files={"file": ("next.bgcode", b"GCDE")})
    assert r.status_code == 409 and "Prusa Connect says Core One is printing." in r.json()["detail"]


def test_a_plugin_that_only_reports_cannot_be_sent_prints(api, prusalink):
    auth = _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    _report(api, auth, p["id"], READY)
    r = api.post(f"/printers/{p['id']}/prusalink/print", files={"file": ("next.bgcode", b"GCDE")})
    assert r.status_code >= 400 and "start the prints you send" in r.json()["detail"] and prusalink.uploads == []


def test_a_ticket_is_only_for_its_plugin(api):
    printer_reports._tickets["t"] = {"plugin_id": "other", "printer_id": 1, "name": "x.gcode", "data": b"x", "size": 1, "at": 0}
    assert printer_reports.take_ticket("t", "prusa-connect") is None
    assert printer_reports.take_ticket("t", "other")["name"] == "x.gcode"
    assert printer_reports.take_ticket("t", "other") is None


def test_a_manifest_with_print_needs_the_permission():
    from app.services.plugins import manifest

    with pytest.raises(ValueError, match="printers:print"):
        manifest.check({**MANIFEST, "print": {"path": "/farmhand/print"}})
    assert manifest.check(PRINTING_MANIFEST)["print"] == {"path": "/farmhand/print"}


# ------------------------------------------------------------------ beyond PrusaLink: the extras, and measured filament

EXTRAS = {"material": "PETG", "nozzle_diameter": 0.4, "nozzle_hardened": False, "nozzle_high_flow": False,
          "temp_chamber": 29.4, "target_chamber": 0, "print_fan_rpm": 0, "heatbreak_fan_rpm": 8003, "speed": 100,
          "flow": 100, "odometer_e": 236033.0, "dialog": None}


def _starting(odometer, time_printing=10, state="PRINTING", job_id=13, progress=1, path=None):
    return {**PRINTING, "state": state, "extras": {**EXTRAS, "odometer_e": odometer},
            "job": {**PRINTING["job"], "id": job_id, "state": state, "time_printing": time_printing, "progress": progress,
                    "path": path or PRINTING["job"]["path"]}}


def test_the_extras_are_shown(api, prusalink):
    auth = _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    dialog = {"code": "31819", "title": "Filament runout", "text": "Insert filament, then press Retry."}
    _report(api, auth, p["id"], {**READY, "state": "ATTENTION", "extras": {**EXTRAS, "dialog": dialog}})
    out = api.get(f"/printers/{p['id']}/prusalink").json()
    assert out["extras"]["material"] == "PETG" and out["extras"]["temp_chamber"] == 29.4 and out["extras"]["dialog"] == dialog
    assert out["extras"]["odometer_e"] == 236033.0  # the printer's own lifetime filament, shown on its page
    plain = _core_one(api, "MK4")
    assert api.get(f"/printers/{plain['id']}/prusalink").json()["extras"] is None  # a PrusaLink printer has none


def test_a_new_print_through_prusa_connect_has_its_filament_measured(api, prusalink):
    auth = _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    _report(api, auth, p["id"], _starting(236033.0))
    _report(api, auth, p["id"], _starting(237533.0, time_printing=600, progress=50))
    _report(api, auth, p["id"], _starting(238533.5, time_printing=1200, state="FINISHED", progress=100))
    [job] = api.get(f"/printers/{p['id']}/print-jobs").json()["jobs"]
    assert job["status"] == "completed" and job["filament_used"] == 2500.5 and not job["filament_estimated"]


def test_a_print_first_seen_part_way_or_from_prusalink_keeps_no_measured_figure(api, prusalink):
    auth = _install(api)
    p = _core_one(api)
    # a print Farmhand recorded through PrusaLink, before the switch: left as it was
    prusalink.start_job(7, "older.bgcode", progress=50, time_printing=600)
    api.get(f"/printers/{p['id']}/prusalink")
    [before] = api.get(f"/printers/{p['id']}/print-jobs").json()["jobs"]
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    _report(api, auth, p["id"], _starting(236033.0, time_printing=3600, job_id=21, progress=60))  # seen an hour in
    _report(api, auth, p["id"], _starting(240000.0, time_printing=4000, job_id=21, state="FINISHED", progress=100))
    jobs = {j["filename"]: j for j in api.get(f"/printers/{p['id']}/print-jobs").json()["jobs"]}
    assert jobs["older.bgcode"]["id"] == before["id"] and jobs["older.bgcode"]["filament_used"] == before["filament_used"]
    assert jobs["Frog keychain.bgcode"]["filament_used"] == 0  # not measured: its start wasn't seen


def _two_prints(api, prusalink, then_printing):
    """A print that finishes, then a new one whose first report still carries the first one's 1200 s of printing,
    then says it has printed then_printing; it finishes 600 s later. The jobs, oldest first."""
    auth = _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    _report(api, auth, p["id"], _starting(236033.0))
    _report(api, auth, p["id"], _starting(237233.0, time_printing=1200, state="FINISHED", progress=100))
    _report(api, auth, p["id"], _starting(237233.0, time_printing=1200, job_id=14))  # the number changed, not the time
    _report(api, auth, p["id"], _starting(237333.0, time_printing=then_printing, job_id=14, progress=2))
    _report(api, auth, p["id"], _starting(239233.0, time_printing=then_printing + 600, job_id=14, state="FINISHED", progress=100))
    return sorted(api.get(f"/printers/{p['id']}/print-jobs").json()["jobs"], key=lambda j: j["id"])


def test_a_new_print_reported_with_the_last_ones_time_starts_after_it_and_is_measured(api, prusalink):
    first, second = _two_prints(api, prusalink, then_printing=60)
    import datetime as dt

    early = dt.datetime.fromisoformat(first["end_time"]) - dt.datetime.fromisoformat(second["start_time"])
    assert early.total_seconds() < 120  # its own 60 s back (all here happens at once), not the first print's 1200 s
    assert second["print_duration"] == 660 and second["filament_used"] == 2000  # measured from when it was first seen
    assert second["status"] == "completed"


def test_a_print_found_well_under_way_once_its_time_comes_is_left_unmeasured(api, prusalink):
    first, second = _two_prints(api, prusalink, then_printing=2400)  # it had really been printing for 40 minutes
    assert second["print_duration"] == 3000 and second["filament_used"] == 0  # its start wasn't seen


# ------------------------------------------------------------------ filament through Prusa Connect: weight, material, totals, reminders


def test_a_measured_print_is_weighed_from_its_material_and_notes_it(api, prusalink):
    auth = _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    _report(api, auth, p["id"], _starting(236033.0))
    _report(api, auth, p["id"], _starting(237033.0, time_printing=1200, state="FINISHED", progress=100))  # 1 m of PETG
    [job] = api.get(f"/printers/{p['id']}/print-jobs").json()["jobs"]
    assert job["filament_used"] == 1000 and job["filament_type"] == "PETG" and not job["filament_estimated"]
    assert job["filament_grams"] == 3.1  # 1 m of 1.75 mm filament at PETG's 1.27 g/cm³
    assert job["filament_cost"] is None  # no price: no 3MF or G-code for it


def test_its_filament_total_is_the_printers_own_counter_and_holds_while_unheard(api, prusalink, monkeypatch):
    auth = _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    _report(api, auth, p["id"], {**READY, "extras": EXTRAS})
    totals = api.get(f"/printers/{p['id']}/prusalink").json()["totals"]
    assert totals["total_filament_used"] == 236033.0 and totals["filament_counter"]
    monkeypatch.setattr(printer_reports, "STALE_SECONDS", -1)  # the plugin stopped reporting
    api.get(f"/printers/{p['id']}/prusalink")
    assert api.get(f"/printers/{p['id']}/maintenance").json()["totals"]["total_filament_used"] == 236033.0  # kept
    plain = _core_one(api, "MK4")
    api.get(f"/printers/{plain['id']}/prusalink")
    assert api.get(f"/printers/{plain['id']}/maintenance").json()["totals"].get("total_filament_used") is None


def test_a_filament_reminder_counts_the_prusa_connect_printers_odometer(api, prusalink):
    auth = _install(api)
    p = _core_one(api)
    reminder = {"type": "repeat", "filament": {"bool": True, "value": 2}}  # every 2 m
    r = api.post(f"/printers/{p['id']}/maintenance", json={"name": "Clean the extruder", "reminder": reminder})
    assert r.status_code == 422 and "doesn't report how much filament" in r.json()["detail"]  # on PrusaLink: refused
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    _report(api, auth, p["id"], {**READY, "extras": EXTRAS})
    assert api.post(f"/printers/{p['id']}/maintenance", json={"name": "Clean the extruder", "reminder": reminder}).status_code in (200, 201)
    _report(api, auth, p["id"], {**READY, "extras": {**EXTRAS, "odometer_e": 238533.0}})  # 2.5 m fed since
    api.get(f"/printers/{p['id']}/prusalink")
    [entry] = api.get(f"/printers/{p['id']}/maintenance").json()["entries"]
    [check] = [c for c in entry["checks"] if c["kind"] == "filament"]
    assert check["used"] == 2.5 and check["due"]


# ------------------------------------------------------------------ a Prusa Connect print's price, from the printed file (as Mainsail's)

from app.parsers import gcode as gcode_parser  # noqa: E402
from app.services.prusalink import printed_filament  # noqa: E402

from .test_gcode_printer import _block  # noqa: E402

PRICE_INI = b"filament_cost = 27.82\nfilament_density = 1.27\nfilament_diameter = 1.75\nfilament_type = PETG\n"


def _priced_bgcode() -> bytes:
    import struct

    return (
        b"GCDE" + struct.pack("<IH", 1, 1)
        + _block(0, b"Producer=PrusaSlicer 2.9.6\n", struct.pack("<H", 0))
        + _block(3, b"filament used [g]=122.86\n", struct.pack("<H", 0))
        + _block(5, b"\x89PNG" + b"x" * 300, struct.pack("<HHH", 0, 16, 16))
        + _block(2, PRICE_INI.replace(b" = ", b"="), struct.pack("<H", 0), deflate=True)
        + _block(1, b"G28\n" * 5000, struct.pack("<H", 0), deflate=True)
    )


@pytest.fixture()
def inline_reads(monkeypatch):
    monkeypatch.setattr(printed_filament, "run_in_background", lambda work: work())
    printed_filament.forget_all()
    yield
    printed_filament.forget_all()


def test_the_settings_are_read_from_a_bgcode_and_its_start_is_enough():
    import io

    data = _priced_bgcode()
    found = gcode_parser.filament_settings(io.BytesIO(data), "x.bgcode")
    assert found == {"filament_cost": "27.82", "filament_density": "1.27", "filament_diameter": "1.75"}
    moves_at = data.index(b"\x01\x00\x01\x00")  # the G-code block's header
    assert gcode_parser.bgcode_settings_in(data[:moves_at]) and not gcode_parser.bgcode_settings_in(data[:200])
    gcode_text = b"G28\n" * 10 + b"; " + PRICE_INI.replace(b"\n", b"\n; ")
    assert gcode_parser.filament_settings(io.BytesIO(gcode_text), "x.gcode")["filament_cost"] == "27.82"


def test_a_print_started_on_a_prusa_connect_printer_is_priced_from_the_printed_file(api, prusalink, inline_reads):
    auth = _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    prusalink.files["Frog keychain.bgcode"] = (_priced_bgcode(), 1795000000)
    long = "/usb/Frog keychain.bgcode"  # as Prusa Connect reports it
    _report(api, auth, p["id"], _starting(236033.0, path=long))
    _report(api, auth, p["id"], _starting(237033.0, time_printing=1200, state="FINISHED", progress=100, path=long))  # 1 m PETG
    [job] = api.get(f"/printers/{p['id']}/print-jobs").json()["jobs"]
    assert job["filament_used"] == 1000 and job["filament_cost_detail"]["source"] == "gcode"
    assert job["filament_cost_detail"]["cost_per_kg"] == 27.82 and job["filament_grams"] == 3.1
    assert job["filament_cost"] == round(3.0538 / 1000 * 27.82, 2)
    assert prusalink.downloaded == ["Frog keychain.bgcode"]  # read once, read only: only GETs went to PrusaLink
    assert {m for m, _ in prusalink.requests} == {"GET"}

    _report(api, auth, p["id"], _starting(237033.0, job_id=14, path=long))  # the same file printed again: not read again
    assert prusalink.downloaded == ["Frog keychain.bgcode"]


def test_a_file_that_cant_be_read_now_is_tried_later_and_a_gone_one_is_noted(api, prusalink, inline_reads, db_session):
    auth = _install(api)
    p = _core_one(api)
    api.patch(f"/printers/{p['id']}", json={"status_from": "prusa-connect"})
    long = "/usb/Frog keychain.bgcode"
    _report(api, auth, p["id"], _starting(236033.0, path=long))  # its file isn't on the stick
    asked = [r for r in prusalink.requests if r[1].startswith("/api/v1/files/")]
    assert set(asked) == {("GET", "/api/v1/files/usb/Frog keychain.bgcode")} and prusalink.downloaded == []  # (login + ask)
    _report(api, auth, p["id"], _starting(236533.0, time_printing=60, path=long))
    assert [r for r in prusalink.requests if r[1].startswith("/api/v1/files/")] == asked  # noted gone: not asked again
    prusalink.down = True  # another print, while PrusaLink doesn't answer: tried, then left for RETRY_AFTER
    _report(api, auth, p["id"], _starting(236533.0, job_id=20, path="/usb/Other.bgcode"))
    prusalink.down = False
    _report(api, auth, p["id"], _starting(236633.0, job_id=20, time_printing=60, path="/usb/Other.bgcode"))
    assert ("GET", "/api/v1/files/usb/Other.bgcode") not in prusalink.requests


def test_a_print_farmhand_sends_is_priced_from_its_own_copy(api, prusalink, monkeypatch, inline_reads):
    auth, handed = _plugin_that_prints(api, monkeypatch)
    p = api.post("/printers", json={"name": "Core One", "connection_type": "prusalink", "status_from": "prusa-connect"}).json()
    _report(api, auth, p["id"], READY)
    data = _priced_bgcode()
    assert api.post(f"/printers/{p['id']}/prusalink/print", files={"file": ("Frog keychain.bgcode", data)}).status_code == 200
    long = "/usb/Frog keychain.bgcode"
    _report(api, auth, p["id"], _starting(236033.0, path=long))
    _report(api, auth, p["id"], _starting(237033.0, time_printing=1200, state="FINISHED", progress=100, path=long))
    [job] = api.get(f"/printers/{p['id']}/print-jobs").json()["jobs"]
    assert job["filament_cost_detail"]["cost_per_kg"] == 27.82
    assert prusalink.requests == []  # its PrusaLink was never asked
