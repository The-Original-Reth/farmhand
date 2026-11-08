"""A Klipper printer's Moonraker: its address, its print history copied into Farmhand, and its status over the API."""
from __future__ import annotations


import pytest

from app.models import PrinterConnection, PrintJob
from app.schemas.printer import PrinterOut
from app.services import moonraker as mr
from app.services import printer_service
from app.services.moonraker import history as mr_history

from .factories import klipper_printer as _printer


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


def test_sync_copies_the_history_and_totals(db_session, moonraker):
    moonraker.add_job("000001", "frog.gcode", start=1_700_000_000)
    moonraker.add_job("000002", "shark.gcode", status="cancelled", start=1_700_100_000, print_s=600, filament_mm=300)
    p = _printer(db_session)
    assert mr.sync_history(db_session, p) == {"added": 2, "updated": 0}
    jobs = {j.job_id: j for j in db_session.query(PrintJob)}
    assert jobs["000002"].status == "cancelled" and jobs["000002"].filament_used == 300
    assert jobs["000001"].job_metadata["slicer"] == "PrusaSlicer"
    assert p.connection_row.totals["total_jobs"] == 2 and p.connection_row.last_sync_at and p.connection_row.last_sync_error is None


def test_a_second_sync_only_brings_what_changed(db_session, moonraker):
    moonraker.add_job("000001", "frog.gcode")
    moonraker.add_job("000002", "shark.gcode", status="in_progress", start=1_700_100_000)
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    assert mr.sync_history(db_session, p) == {"added": 0, "updated": 0}
    moonraker.jobs[1].update(status="completed", end_time=1_700_103_700)  # the print finished
    moonraker.add_job("000003", "frog.gcode", start=1_700_200_000)
    assert mr.sync_history(db_session, p) == {"added": 1, "updated": 1}
    assert db_session.query(PrintJob).filter_by(job_id="000002").one().status == "completed"


def test_a_long_history_is_fetched_page_by_page(db_session, moonraker, monkeypatch):
    monkeypatch.setattr(mr_history, "PAGE", 10)
    for i in range(35):
        moonraker.add_job(f"{i:06d}", f"part{i}.gcode", start=1_700_000_000 + i * 10_000)
    p = _printer(db_session)
    assert mr.sync_history(db_session, p)["added"] == 35
    assert [m for m, path in moonraker.requests if path == "/server/history/list"] == ["GET"] * 4


def test_jobs_the_printer_forgets_are_kept(db_session, moonraker):
    moonraker.add_job("000001", "frog.gcode")
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    moonraker.jobs.clear()  # history wiped on the printer
    mr.sync_history(db_session, p)
    assert db_session.query(PrintJob).count() == 1


def test_an_unreachable_printer_is_recorded_and_keeps_what_was_synced(db_session, moonraker):
    moonraker.add_job("000001", "frog.gcode")
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    moonraker.down = True
    with pytest.raises(mr.MoonrakerError) as caught:
        mr.sync_history(db_session, p)
    assert caught.value.kind == "unreachable"
    conn = db_session.get(PrinterConnection, p.id)
    assert "Couldn't connect" in conn.last_sync_error and conn.totals["total_jobs"] == 1
    assert db_session.query(PrintJob).count() == 1


def test_an_api_key_is_sent_and_a_missing_one_is_explained(db_session, moonraker):
    moonraker.api_key = "secret"
    p = _printer(db_session)
    with pytest.raises(mr.MoonrakerError) as caught:
        mr.server_info(p)
    assert caught.value.kind == "unauthorized" and "API key" in str(caught.value)
    printer_service.update_printer(db_session, p.id, {"moonraker_api_key": "secret"})
    assert mr.server_info(p)["klippy_state"] == "ready"


def test_no_address_is_explained(db_session, moonraker):
    p = printer_service.create_printer(db_session, name="C", kind=None, wired_ip=None, wireless_ip=None)
    with pytest.raises(mr.MoonrakerError) as caught:
        mr.server_info(p)
    assert caught.value.kind == "no_address"


def test_deleting_a_printer_deletes_its_history_and_connection(db_session, moonraker):
    moonraker.add_job("000001", "frog.gcode")
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    db_session.delete(p)
    db_session.commit()
    assert db_session.query(PrintJob).count() == 0 and db_session.query(PrinterConnection).count() == 0


# ------------------------------------------------------------------ over the API


def test_status_sync_history_and_stats_over_the_api(klipper, moonraker):
    c, pid = klipper
    status = c.get(f"/printers/{pid}/moonraker").json()
    assert status["reachable"] and status["klippy_state"] == "ready" and status["mainsail_url"] == "http://10.0.6.21/"
    assert status["last_sync_at"] is None

    moonraker.add_job("000001", "VT_1190_frog.gcode", start=1_700_000_000)
    moonraker.add_job("000002", "VT_1190_shark.gcode", status="cancelled", start=1_700_100_000)
    moonraker.add_job("000003", "VT_1190_frog.gcode", status="error", start=1_700_200_000)
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


def test_the_status_shows_the_print_running_now_with_its_progress_and_time_left(klipper, moonraker):
    c, pid = klipper
    assert c.get(f"/printers/{pid}/moonraker").json()["print"] is None  # standing by
    moonraker.print_state = "printing"
    moonraker.live = {"filename": "VT_1190_frog.gcode", "print_duration": 3600.0, "progress": 0.25}
    moonraker.temps = {"extruder": (239.6, 240.0), "heater_bed": (85.1, 85.0)}
    now = c.get(f"/printers/{pid}/moonraker").json()["print"]
    assert now["state"] == "printing" and now["file"] == "VT_1190_frog.gcode" and now["progress"] == 25.0
    assert now["print_duration"] == 3600 and now["time_remaining"] == 3 * 3600  # an hour for the first quarter
    assert now["extruder"] == {"temperature": 239.6, "target": 240.0} and now["heater_bed"]["target"] == 85.0
    moonraker.print_state = "paused"
    assert c.get(f"/printers/{pid}/moonraker").json()["print"]["state"] == "paused"
    moonraker.live = {"filename": "VT_1190_frog.gcode", "print_duration": 0.0, "progress": 0.0}  # only just started
    assert c.get(f"/printers/{pid}/moonraker").json()["print"]["time_remaining"] is None
    moonraker.print_state = "complete"
    assert c.get(f"/printers/{pid}/moonraker").json()["print"] is None


def test_an_unreachable_printer_answers_502_with_why(klipper, moonraker):
    c, pid = klipper
    moonraker.down = True
    status = c.get(f"/printers/{pid}/moonraker").json()
    assert status["reachable"] is False and status["error_kind"] == "unreachable"
    r = c.post(f"/printers/{pid}/moonraker/sync")
    assert r.status_code == 502 and r.json()["kind"] == "unreachable"
    assert c.get(f"/printers/{pid}/maintenance").status_code == 502
    assert c.get(f"/printers/{pid}/moonraker").json()["last_sync_error"]  # the failed sync is remembered


def test_maintenance_over_the_api(klipper, moonraker):
    c, pid = klipper
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


def test_the_printer_api_carries_the_moonraker_settings(klipper):
    c, pid = klipper
    r = c.patch(f"/printers/{pid}", json={"moonraker_url": "voron.local:7125", "moonraker_api_key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body["moonraker_url"] == "http://voron.local:7125" and body["moonraker_url_override"] == "http://voron.local:7125"
    assert body["has_moonraker_api_key"] is True and "moonraker_api_key" not in body
    assert c.patch(f"/printers/{pid}", json={"moonraker_url": "ftp://x"}).status_code == 422
