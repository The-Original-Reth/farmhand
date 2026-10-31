from __future__ import annotations

import json

import httpx
import pytest

from app import records_store as rs
from app.models import MaintenanceEntry, PrintJob, PrusaLinkConnection
from app.schemas.printer import PrinterOut
from app.services import moonraker as mr
from app.services import printer_service, records_service
from app.services import prusalink as pl
from app.services.prusalink import client as pl_client

from .fake_prusalink import FakePrusaLink


@pytest.fixture()
def fake(monkeypatch):
    f = FakePrusaLink()
    monkeypatch.setattr(pl_client, "transport", httpx.MockTransport(f.handle))
    monkeypatch.setattr(pl_client, "_answered_at", {})  # each test's database starts its ids over
    return f


def _core_one(db, name="Core One", password="secret123"):
    p = printer_service.create_printer(db, name=name, kind="Prusa Core One", wired_ip="10.0.6.40", wireless_ip=None)
    return printer_service.update_printer(db, p.id, {"connection_type": "prusalink", "prusalink_password": password})


def _jobs(db, printer_id):
    return list(db.query(PrintJob).filter_by(printer_id=printer_id).order_by(PrintJob.id))


# ------------------------------------------------------------------ setting a printer up for PrusaLink


def test_a_printer_switches_to_prusalink_and_back_without_losing_its_prints(db_session, fake):
    p = _core_one(db_session)
    out = PrinterOut.model_validate(p)
    assert out.connection_type == "prusalink" and out.prusalink_url == "http://10.0.6.40"
    assert out.prusalink_username == "maker" and out.has_prusalink_password
    assert "secret123" not in out.model_dump_json()  # the password never goes back out

    fake.start_job(1, "frog.bgcode", progress=10, time_printing=600)
    pl.poll(db_session, p)
    p = printer_service.update_printer(db_session, p.id, {"prusalink_url": "http://coreone.local", "prusalink_username": " maker "})
    assert p.prusalink_url == "http://coreone.local" and p.has_prusalink_password  # the password stays when not sent

    p = printer_service.update_printer(db_session, p.id, {"connection_type": "moonraker"})
    assert p.connection_type == "moonraker" and db_session.get(PrusaLinkConnection, p.id) is None
    assert len(_jobs(db_session, p.id)) == 1  # the prints it recorded stay


def test_a_wrong_password_is_reported_plainly(db_session, fake):
    p = _core_one(db_session, password="wrong")
    with pytest.raises(pl.PrusaLinkError) as caught:
        pl.poll(db_session, p)
    assert caught.value.kind == "unauthorized" and "Settings > Network > PrusaLink" in str(caught.value)
    assert p.connection_row.last_sync_error.startswith("PrusaLink refused")


def test_a_printer_that_is_off_is_reported_plainly(db_session, fake):
    p = _core_one(db_session)
    fake.down = True
    with pytest.raises(pl.PrusaLinkError) as caught:
        pl.poll(db_session, p)
    assert caught.value.kind == "unreachable"


# ------------------------------------------------------------------ the print history Farmhand records


def test_a_print_is_recorded_from_start_to_finish(db_session, fake):
    p = _core_one(db_session)
    pl.poll(db_session, p)  # idle: nothing to record
    assert _jobs(db_session, p.id) == []
    assert p.service_row is not None and p.service_row.start_printtime == 0  # the service count starts here

    fake.start_job(7, "Frog keychain.bgcode", progress=5, time_printing=300, time_remaining=5700)
    pl.poll(db_session, p)
    [job] = _jobs(db_session, p.id)
    assert job.status == "in_progress" and job.filename == "Frog keychain.bgcode" and job.print_duration == 300
    assert job.job_metadata["estimated_time"] == 6000 and job.job_metadata["filament_type"] == "PETG"

    fake.advance(progress=60, time_printing=3600)
    pl.poll(db_session, p)
    fake.advance(progress=100, time_printing=6000, state="FINISHED")
    pl.poll(db_session, p)
    pl.poll(db_session, p)  # still showing FINISHED until someone clears it: no second record
    [job] = _jobs(db_session, p.id)
    assert job.status == "completed" and job.end_time is not None and job.print_duration == 6000

    fake.clear_job()
    pl.poll(db_session, p)
    assert len(_jobs(db_session, p.id)) == 1
    assert p.connection_row.totals == {"total_jobs": 1, "total_print_time": 6000.0, "total_filament_used": None, "longest_print": 6000.0}
    assert p.service["hours_since"] == pytest.approx(6000 / 3600)


@pytest.mark.parametrize("last_progress, expected", [(40, "unknown"), (99.5, "completed")])
def test_a_print_whose_end_was_missed_is_closed_by_how_far_it_got(db_session, fake, last_progress, expected):
    p = _core_one(db_session)
    fake.start_job(3, "shark.bgcode", progress=last_progress, time_printing=1200)
    pl.poll(db_session, p)
    fake.clear_job()  # it ended (or was cancelled at the printer) between two looks
    pl.poll(db_session, p)
    [job] = _jobs(db_session, p.id)
    assert job.status == expected and job.end_time is not None
    assert p.prusalink_row.current_print_id is None


def test_a_new_job_closes_the_one_before(db_session, fake):
    p = _core_one(db_session)
    fake.start_job(3, "one.bgcode", progress=50, time_printing=100)
    pl.poll(db_session, p)
    fake.start_job(4, "two.bgcode", progress=1, time_printing=10)
    pl.poll(db_session, p)
    first, second = _jobs(db_session, p.id)
    assert first.status == "unknown" and second.status == "in_progress" and second.filename == "two.bgcode"


def test_stopped_and_failed_prints_say_so(db_session, fake):
    p = _core_one(db_session)
    fake.start_job(5, "a.bgcode", progress=20, time_printing=100)
    pl.poll(db_session, p)
    fake.advance(progress=20, time_printing=100, state="STOPPED")
    pl.poll(db_session, p)
    fake.start_job(6, "b.bgcode", progress=20, time_printing=100)
    pl.poll(db_session, p)
    fake.advance(progress=20, time_printing=100, state="ERROR")
    pl.poll(db_session, p)
    assert [j.status for j in _jobs(db_session, p.id)] == ["cancelled", "error"]


# ------------------------------------------------------------------ maintenance kept in Farmhand


def test_maintenance_is_kept_in_farmhand_and_counts_recorded_print_time(db_session, fake):
    p = _core_one(db_session)
    pl.poll(db_session, p)
    key = mr.add_maintenance(p, name="Clean the nozzle", note="", reminder={"type": "repeat", "printtime": {"bool": True, "value": 1}})
    assert db_session.query(MaintenanceEntry).filter_by(printer_id=p.id).count() == 1
    assert fake.requests.count(("GET", "/api/v1/status")) == 2  # nothing about maintenance asked of the printer (1 login try + 1)

    [entry] = mr.list_maintenance(p)["entries"]
    assert entry["id"] == key and entry["state"] == "ok"

    fake.start_job(1, "long.bgcode", progress=100, time_printing=7200, state="FINISHED")
    pl.poll(db_session, p)
    [entry] = mr.list_maintenance(p)["entries"]
    assert entry["state"] == "due" and entry["checks"][0]["used"] == pytest.approx(2)

    next_key = mr.perform_maintenance(p, key, note="done")
    states = {e["id"]: e["state"] for e in mr.list_maintenance(p)["entries"]}
    assert states == {key: "done", next_key: "ok"}
    mr.delete_maintenance(p, key)
    assert [e["id"] for e in mr.list_maintenance(p)["entries"]] == [next_key]


def test_a_filament_reminder_is_refused_for_a_printer_that_does_not_report_filament(db_session, fake):
    p = _core_one(db_session)
    with pytest.raises(ValueError, match="filament"):
        mr.add_maintenance(p, name="Dry the spool", note="", reminder={"type": "one-time", "filament": {"bool": True, "value": 500}})


def test_the_service_can_be_marked_done(db_session, fake):
    p = _core_one(db_session)
    fake.start_job(1, "x.bgcode", progress=100, time_printing=3600, state="FINISHED")
    pl.poll(db_session, p)
    mr.service_done(db_session, p, note="new belts")
    assert p.service_row.start_printtime == 3600 and p.service["hours_since"] == 0


# ------------------------------------------------------------------ over the API


@pytest.fixture()
def client(api, fake):
    printer = api.post("/printers", json={"name": "Core One", "kind": "Prusa Core One", "wired_ip": "10.0.6.40"}).json()
    api.patch(f"/printers/{printer['id']}", json={"connection_type": "prusalink", "prusalink_password": "secret123"})
    return api, printer["id"]


def test_live_status_over_the_api(client, fake):
    c, pid = client
    fake.start_job(9, "Frog.bgcode", progress=42.5, time_printing=1200, time_remaining=1600)
    s = c.get(f"/printers/{pid}/prusalink").json()
    assert s["reachable"] and s["state"] == "PRINTING" and s["printer_type"] == "COREONE" and s["firmware"] == "6.2.0"
    assert s["temps"]["temp_nozzle"] == 215.2 and s["job"]["file"] == "Frog.bgcode" and s["job"]["progress"] == 42.5
    assert s["totals"]["total_jobs"] == 1
    history = c.get(f"/printers/{pid}/print-jobs").json()
    assert history["total"] == 1 and history["jobs"][0]["status"] == "in_progress"
    printer = c.get(f"/printers/{pid}").json()
    assert printer["connection_type"] == "prusalink" and printer["has_prusalink_password"] and "prusalink_password" not in printer


def test_live_status_says_why_it_cannot_reach_the_printer(client, fake):
    c, pid = client
    fake.down = True
    s = c.get(f"/printers/{pid}/prusalink").json()
    assert s["reachable"] is False and s["error_kind"] == "unreachable"


def test_a_moonraker_printer_has_no_prusalink_status(api):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    assert api.get(f"/printers/{pid}/prusalink").status_code == 409


def test_sending_a_print(client, fake):
    c, pid = client
    r = c.post(f"/printers/{pid}/prusalink/print", files={"file": ("Frog keychain.bgcode", b"GCDE" + b"x" * 100)})
    assert r.status_code == 200 and r.json()["sent"] == "usb/Frog keychain.bgcode"
    [up] = fake.uploads
    assert up["path"] == "/api/v1/files/usb/Frog%20keychain.bgcode" and up["size"] == 104
    assert up["headers"]["print-after-upload"] == "?1" and up["headers"]["overwrite"] == "?1"
    assert c.get(f"/printers/{pid}/print-jobs").json()["jobs"][0]["filename"] == "Frog keychain.bgcode"  # recorded at once


def test_a_big_print_is_streamed_whole_with_its_length_up_front(client, fake):
    import inspect

    from app.routers import prusalink as router

    assert not inspect.iscoroutinefunction(router.send_print)  # runs in a worker thread, not on the event loop
    c, pid = client
    body = bytes(range(256)) * (3 * 1024 * 16 + 7)  # ~12 MB: several pieces, and not a whole number of them
    assert c.post(f"/printers/{pid}/prusalink/print", files={"file": ("big.bgcode", body)}).status_code == 200
    [up] = fake.uploads
    assert up["size"] == len(body) and up["headers"]["content-length"] == str(len(body))
    assert "transfer-encoding" not in up["headers"]


def test_only_a_sliced_file_can_be_sent(client, fake):
    c, pid = client
    r = c.post(f"/printers/{pid}/prusalink/print", files={"file": ("frog.3mf", b"PK..")})
    assert r.status_code == 422 and "Slice the 3MF first" in r.json()["detail"]
    assert fake.uploads == []


def test_a_busy_printer_is_not_sent_a_print(client, fake):
    c, pid = client
    fake.start_job(1, "running.bgcode", progress=30, time_printing=100)
    r = c.post(f"/printers/{pid}/prusalink/print", files={"file": ("next.bgcode", b"GCDE")})
    assert r.status_code == 409 and "PRINTING" in r.json()["detail"]
    assert fake.uploads == []


def test_maintenance_over_the_api(client, fake):
    c, pid = client
    c.get(f"/printers/{pid}/prusalink")
    r = c.post(f"/printers/{pid}/maintenance", json={"name": "Clean the bed", "reminder": {"type": "repeat", "date": {"bool": True, "value": 7}}})
    assert r.status_code == 201 and r.json()["entries"][0]["name"] == "Clean the bed"
    bad = c.post(f"/printers/{pid}/maintenance", json={"name": "Dry", "reminder": {"type": "repeat", "filament": {"bool": True, "value": 5}}})
    assert bad.status_code == 422


# ------------------------------------------------------------------ the copy on the NAS


def test_the_nas_copy_keeps_the_prusalink_setup_and_maintenance_but_never_the_password(db_session, fake, tmp_path):
    p = _core_one(db_session)
    fake.start_job(1, "x.bgcode", progress=100, time_printing=3600, state="FINISHED")
    pl.poll(db_session, p)
    mr.add_maintenance(p, name="Clean the nozzle", note="", reminder=None)
    records_service.write_all(db_session, tmp_path)
    text = (tmp_path / "printers" / "Core One.json").read_text(encoding="utf-8")
    assert "secret123" not in text
    doc = json.loads(text)
    assert doc["printer"]["connection_type"] == "prusalink" and doc["printer"]["prusalink_username"] == "maker"
    assert doc["maintenance"][0]["entry"]["name"] == "Clean the nozzle"

    # into an empty Farmhand: it comes back as a PrusaLink printer, needing its password typed in again
    from .test_records import _fresh_session

    db = _fresh_session()
    out = records_service.restore_all(db, tmp_path)
    assert out["printers_added"] == ["Core One"] and out["prints_added"] == 1
    restored = printer_service.find_by_name(db, "Core One")
    assert restored.connection_type == "prusalink" and not restored.has_prusalink_password
    assert [r.entry["name"] for r in restored.maintenance_rows] == ["Clean the nozzle"]
    assert rs.PRINTERS_DIR == "printers"


def test_a_printer_can_be_added_as_a_prusalink_printer_straight_away(api, fake):
    r = api.post("/printers", json={
        "name": "Core One 2", "wired_ip": "10.0.6.41", "connection_type": "prusalink",
        "prusalink_username": "maker", "prusalink_password": "secret123", "prusalink_url": "coreone2.local",
    })
    assert r.status_code == 201
    p = r.json()
    assert p["connection_type"] == "prusalink" and p["has_prusalink_password"] and p["prusalink_url"] == "http://coreone2.local"
    assert "secret123" not in r.text


def test_a_printer_added_as_mainsail_keeps_its_moonraker_details(api):
    r = api.post("/printers", json={"name": "VT 1190", "connection_type": "moonraker", "moonraker_url": "10.0.6.21:7125", "moonraker_api_key": "KEY"})
    p = r.json()
    assert r.status_code == 201 and p["connection_type"] == "moonraker"
    assert p["moonraker_url"] == "http://10.0.6.21:7125" and p["has_moonraker_api_key"] and "KEY" not in r.text
    plain = api.post("/printers", json={"name": "Plain"}).json()
    assert plain["connection_type"] == "moonraker" and plain["has_moonraker_api_key"] is False


# ------------------------------------------------------------------ a Prusa on cable and Wi-Fi: two IPs


def _two_ips(monkeypatch, fake, *, wired_down=True, quiet=False):
    """The fake at both IPs: the wired one unplugged (no connection), or `quiet` (it connects, then never answers)."""
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.host)
        if request.url.host == "10.0.6.40" and wired_down:
            if quiet:
                raise httpx.ReadTimeout("no answer", request=request)
            raise httpx.ConnectError("no route to host", request=request)
        return fake.handle(request)

    monkeypatch.setattr(pl_client, "transport", httpx.MockTransport(handle))
    return asked


def test_a_prusa_is_reached_at_its_wifi_ip_when_its_cable_is_out(db_session, fake, monkeypatch):
    p = printer_service.update_printer(db_session, _core_one(db_session).id, {"wireless_ip": "10.0.6.41"})
    assert p.prusalink_urls == ["http://10.0.6.40", "http://10.0.6.41"]  # wired first
    asked = _two_ips(monkeypatch, fake)

    assert pl.version(p)["text"] == "PrusaLink"  # through the Wi-Fi, after the cable didn't connect
    assert pl.answered_at(p) == "http://10.0.6.41"
    asked.clear()
    pl.version(p)
    assert set(asked) == {"10.0.6.41"}  # it remembers: the dead address isn't tried every time


def test_a_prusa_that_went_quiet_isnt_asked_again_elsewhere(db_session, fake, monkeypatch):
    # it connected, so the request may have been carried out (a print started): it must not be sent twice
    p = printer_service.update_printer(db_session, _core_one(db_session, name="Quiet").id, {"wireless_ip": "10.0.6.41"})
    asked = _two_ips(monkeypatch, fake, quiet=True)
    with pytest.raises(pl.PrusaLinkError) as e:
        pl.version(p)
    assert e.value.kind == "unreachable" and "10.0.6.41" not in asked


def test_a_prusalink_address_set_by_hand_is_the_only_one_tried(db_session, fake, monkeypatch):
    p = _core_one(db_session, name="By hand")
    p = printer_service.update_printer(db_session, p.id, {"wireless_ip": "10.0.6.41", "prusalink_url": "http://10.0.6.40"})
    assert p.prusalink_urls == ["http://10.0.6.40"]
    asked = _two_ips(monkeypatch, fake)
    with pytest.raises(pl.PrusaLinkError):
        pl.version(p)
    assert set(asked) == {"10.0.6.40"}


def test_the_live_status_says_the_address_that_answered(api, fake, monkeypatch):
    p = api.post("/printers", json={"name": "Prusa_2", "wired_ip": "10.0.6.40", "wireless_ip": "10.0.6.41",
                                    "connection_type": "prusalink", "prusalink_password": "secret123"}).json()
    _two_ips(monkeypatch, fake)
    out = api.get(f"/printers/{p['id']}/prusalink").json()
    assert out["reachable"] and out["prusalink_url"] == "http://10.0.6.41"
