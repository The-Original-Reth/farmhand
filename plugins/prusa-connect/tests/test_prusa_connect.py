"""The Prusa Connect plugin against stand-ins for Farmhand and Prusa Connect (tests/fakes.py)."""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "import prusa_connect" works from the plugin folder

from prusa_connect.config import Config, Settings, tidy_address  # noqa: E402
from prusa_connect.connect import PrusaConnect, report  # noqa: E402
from prusa_connect.farmhand import Farmhand  # noqa: E402
from prusa_connect.reporter import Reporter  # noqa: E402
from prusa_connect.server import make_server  # noqa: E402

from .fakes import DEVICE, TOKEN, FakeFarmhand, FakePrusaConnect  # noqa: E402


@pytest.fixture()
def farmhand():
    f = FakeFarmhand()
    yield f
    f.stop()


@pytest.fixture()
def connect():
    f = FakePrusaConnect()
    yield f
    f.stop()


@pytest.fixture()
def plugin(farmhand, connect, tmp_path):
    """The plugin's settings, reporter and web server (its address in .url), not started: tests call run_once()."""
    settings = Settings(tmp_path / "data", default_address=connect.url)
    reporter = Reporter(Farmhand(farmhand.url, TOKEN), PrusaConnect(settings), settings)
    server = make_server(0, reporter, settings, host="127.0.0.1")
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    reporter.url = f"http://127.0.0.1:{server.server_address[1]}"
    reporter.settings = settings
    yield reporter
    server.shutdown()
    server.server_close()


def _page(plugin, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(plugin.url + path, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, (json.loads(raw) if raw.startswith("{") else raw)


def _pair(plugin, connect):
    assert _page(plugin, "/api/pairing", {})[1]["user_code"] == "BCDF-GHJK"
    connect.pairing = "approved"
    assert _page(plugin, "/api/pairing/check", {})[1]["state"] == "paired"


# ------------------------------------------------------------------ the plugin's own settings


def test_config_and_addresses():
    cfg = Config.from_env({"FARMHAND_URL": "http://fh:4545/plugin-api/v1/", "FARMHAND_TOKEN": " t ", "PRUSA_CONNECT_DATA": "/x"})
    assert cfg.farmhand_url == "http://fh:4545/plugin-api/v1" and cfg.farmhand_token == "t" and cfg.port == 8085
    assert tidy_address("192.168.10.93:8080/") == "http://192.168.10.93:8080"
    assert tidy_address(" ") is None
    with pytest.raises(ValueError):
        tidy_address("ftp://nope")


def test_settings_are_kept_and_a_new_address_forgets_the_token(tmp_path):
    s = Settings(tmp_path, default_address="http://pc:8080")
    s.set_token("abc")
    s.link(2, DEVICE)
    s.link(3, DEVICE)  # a Prusa Connect printer is one Farmhand printer
    again = Settings(tmp_path)
    assert again.address == "http://pc:8080" and again.token == "abc" and again.links == {3: DEVICE}
    again.set_address("http://other:8080")
    assert again.token is None
    with pytest.raises(ValueError):
        again.link("3", DEVICE)


# ------------------------------------------------------------------ pairing


def test_pairing_with_a_short_code_never_shows_the_secret(plugin, connect):
    status, started = _page(plugin, "/api/pairing", {})
    assert status == 200 and started["user_code"] == "BCDF-GHJK" and "device_code" not in started
    assert connect.pairing_requests == [{"app_name": "Farmhand", "scopes": ["read", "operate"]}]
    assert _page(plugin, "/api/pairing/check", {})[1]["state"] == "pending"
    snap = _page(plugin, "/api/status")[1]
    assert snap["pairing"]["user_code"] == "BCDF-GHJK" and not snap["paired"]
    connect.pairing = "approved"
    assert _page(plugin, "/api/pairing/check", {})[1]["state"] == "paired"
    snap = _page(plugin, "/api/status")[1]
    assert snap["paired"] and snap["pairing"] is None and connect.token not in json.dumps(snap)


def test_a_pairing_turned_down_says_so(plugin, connect):
    _page(plugin, "/api/pairing", {})
    connect.pairing = "denied"
    out = _page(plugin, "/api/pairing/check", {})[1]
    assert out["state"] == "denied" and "turned the pairing down" in out["message"]


def test_a_bad_address_is_refused(plugin):
    status, out = _page(plugin, "/api/address", {"url": "ftp://x"})
    assert status == 400 and "http://" in out["detail"]


# ------------------------------------------------------------------ reporting


def test_a_printer_with_the_same_name_is_linked_and_reported(plugin, connect, farmhand):
    _pair(plugin, connect)
    connect.start_job(12, "/usb/Frog keychain.bgcode", progress=40, time_printing=1200)
    snap = plugin.run_once()
    assert snap["links"] == {"2": DEVICE}  # "Core One" on both sides
    [sent] = farmhand.reports[2]
    assert sent["reachable"] and sent["state"] == "PRINTING" and sent["printer_type"] == "COREONE"
    assert sent["temps"] == {"temp_nozzle": 24, "target_nozzle": 215, "temp_bed": 22, "target_bed": 60}
    assert sent["job"] == {"id": 12, "state": "PRINTING", "file": "Frog keychain.bgcode", "path": "/usb/Frog keychain.bgcode",
                           "progress": 40.0, "time_printing": 1200, "time_remaining": 1800}
    assert 3 not in farmhand.reports  # the MK4 takes its status from its PrusaLink: nothing sent for it
    assert sent["link"] == f"{connect.url}/printers/{DEVICE}"  # its own page on Prusa Connect
    [core] = [p for p in snap["printers"] if p["id"] == 2]
    assert core["last"]["recorded"] and [p["name"] for p in snap["printers"]] == ["Core One", "MK4"]  # Prusa printers only


def test_a_printer_not_linked_or_not_heard_is_reported_unreachable(plugin, connect, farmhand):
    farmhand.printers[1]["name"] = "Core One #2"  # no name match: not linked by itself
    _pair(plugin, connect)
    plugin.run_once()
    assert not farmhand.reports[2][-1]["reachable"] and "choose which one" in farmhand.reports[2][-1]["error"]

    _page(plugin, "/api/link", {"printer_id": 2, "device_id": DEVICE})
    connect.devices[DEVICE]["connected"] = False
    plugin.run_once()
    assert "isn't hearing from Core One" in farmhand.reports[2][-1]["error"]


def test_an_open_prusa_connect_needs_no_pairing(plugin, connect, farmhand):
    _page(plugin, "/api/pairing", {})
    connect.open = True
    plugin.connect._open = None  # asked again now, not in a minute
    connect.pairing_requests.clear()
    snap = plugin.run_once()
    assert snap["open"] and snap["paired"] and snap["connect"]["open"] and snap["pairing"] is None
    assert farmhand.reports[2][-1]["reachable"] and farmhand.reports[2][-1]["state"] == "IDLE"
    status, out = _page(plugin, "/api/pairing", {})
    assert status >= 400 and "needs no pairing" in out["detail"] and connect.pairing_requests == []


def test_before_pairing_its_printers_are_told_why(plugin, farmhand):
    plugin.settings.link(2, DEVICE)
    plugin.run_once()
    assert "isn't paired" in farmhand.reports[2][-1]["error"]


def test_health_says_when_farmhand_refuses_the_plugin(plugin, connect, farmhand, monkeypatch):
    assert _page(plugin, "/health") == (200, "ok")
    plugin.farmhand.token = "wrong"
    with pytest.raises(Exception):
        plugin.run_once()
    status, words = _page(plugin, "/health")
    assert status == 503 and "Farmhand refused this plugin's token" in words


def test_the_report_shape_from_a_device():
    assert report(None, None, "why")["reachable"] is False
    device = {"name": "X", "connected": True, "model": "MK4", "state": {"/state": "IDLE"}}
    assert report(device)["job"] is None and report(device)["state"] == "IDLE"


def test_manifest_and_page_are_served(plugin):
    status, manifest = _page(plugin, "/manifest")
    assert status == 200 and manifest["id"] == "prusa-connect"
    assert manifest["permissions"] == ["printers:read", "printers:report", "printers:print"] and manifest["print"] == {"path": "/farmhand/print"}
    status, page = _page(plugin, "/")
    assert status == 200 and "Built on Prusa Connect by Prusa Research" in page


# ------------------------------------------------------------------ prints Farmhand sends


def test_a_print_farmhand_hands_over_is_put_in_prusa_connect_and_started(plugin, connect, farmhand):
    _pair(plugin, connect)
    plugin.run_once()  # links Core One by its name
    gcode = b"GCDE" + bytes(range(256)) * 50
    farmhand.tickets["t1"] = gcode
    status, out = _page(plugin, "/farmhand/print", {"ticket": "t1", "printer_id": 2, "file": "Frog keychain.bgcode", "size": len(gcode)})
    assert status == 200 and out == {"sent": "usb/Frog keychain.bgcode"}
    assert connect.stored == {"tmp/Frog keychain.bgcode": gcode}
    assert connect.printed == [{"path": "usb/Frog keychain.bgcode", "storage": "local", "source": "tmp/Frog keychain.bgcode", "replace": True}]
    assert farmhand.tickets == {}  # fetched once


def test_a_print_is_refused_when_the_printer_is_busy_unlinked_or_the_ticket_is_wrong(plugin, connect, farmhand):
    _pair(plugin, connect)
    status, out = _page(plugin, "/farmhand/print", {"ticket": "t1", "printer_id": 2, "file": "a.bgcode", "size": 1})
    assert status == 409 and "isn't linked" in out["detail"]
    plugin.run_once()
    connect.start_job(12, "/usb/other.bgcode", progress=10, time_printing=60)
    status, out = _page(plugin, "/farmhand/print", {"ticket": "t1", "printer_id": 2, "file": "a.bgcode", "size": 1})
    assert status == 409 and "isn't ready" in out["detail"] and connect.printed == []
    connect.devices[DEVICE]["state"]["/state"] = "IDLE"
    status, out = _page(plugin, "/farmhand/print", {"ticket": "made-up", "printer_id": 2, "file": "a.bgcode", "size": 1})
    assert status == 502 and connect.printed == []  # only Farmhand's own tickets fetch anything
    assert _page(plugin, "/farmhand/print", {"printer_id": 2})[0] == 400
