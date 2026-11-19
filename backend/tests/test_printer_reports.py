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
    assert prusalink.requests == []  # its own PrusaLink was never asked

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
