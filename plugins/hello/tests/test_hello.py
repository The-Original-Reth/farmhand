"""
The Hello plugin against a stand-in Farmhand (fake_farmhand.py): its manifest and health, the page and what it asks
for, Farmhand's refusals and absence shown in plain words, events, and its one setting kept in its own folder.
"""
from __future__ import annotations

import json
import re
import socket
import threading
import urllib.error
import urllib.request

import pytest

from hello.config import Config, Settings
from hello.farmhand import Farmhand, FarmhandError
from hello.server import PAGE, make_server, read_manifest
from hello.watcher import Watcher

from .conftest import wait_until
from .fake_farmhand import TOKEN, FakeFarmhand


@pytest.fixture()
def plugin(env):
    """The plugin running as its container would (watcher and web server), on a free port."""
    config = Config.from_env(env)
    settings = Settings(config.data_dir)
    watcher = Watcher(Farmhand(config.farmhand_url, config.farmhand_token), settings, refresh_seconds=60, retry_seconds=0.2)
    server = make_server(0, watcher, settings, host="127.0.0.1")
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    watcher.start()
    plugin = type("Plugin", (), {})()
    plugin.url, plugin.watcher, plugin.settings = f"http://127.0.0.1:{server.server_address[1]}", watcher, settings
    yield plugin
    watcher.stop()
    server.shutdown()
    server.server_close()


def get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def post(url: str, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def status(plugin) -> dict:
    return json.loads(get(plugin.url + "/api/status")[1])


# ------------------------------------------------------------------ the contract with Farmhand


def test_the_manifest_is_one_farmhand_takes(plugin):
    code, body = get(plugin.url + "/manifest")
    manifest = json.loads(body)
    assert code == 200 and manifest == read_manifest()
    assert manifest["id"] == "hello" and manifest["farmhand_api"] == "1" and manifest["port"] == 8080
    assert manifest["page"]["path"] == "/" and manifest["health"] == "/health"
    assert set(manifest["permissions"]) == {"printers:read", "prints:read", "farm:read"}
    assert re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?", manifest["id"])  # Farmhand's rule for an id


def test_health_is_ok_while_farmhand_answers(plugin):
    assert wait_until(lambda: status(plugin)["farmhand"]["ok"])
    assert get(plugin.url + "/health") == (200, "ok")


def test_the_page_only_uses_relative_addresses():
    """Behind Farmhand the page is at /plugins/hello/: "/api/..." would miss the plugin. Only Farmhand's helper is absolute."""
    page = PAGE.read_text(encoding="utf-8")
    absolute = re.findall(r"""(?:src|href|action)=["'](/[^"']*)""", page) + re.findall(r"""(?:fetch|EventSource)\(\s*["'](/[^"']*)""", page)
    assert absolute == ["/plugins/farmhand-plugin.js"]
    assert 'EventSource("api/events")' in page and 'fetch("api/settings"' in page


def test_the_page_is_served_at_the_root(plugin):
    code, body = get(plugin.url + "/")
    assert code == 200 and "<title>Hello</title>" in body
    assert get(plugin.url + "/nothing")[0] == 404


# ------------------------------------------------------------------ reading Farmhand


def test_it_shows_each_printer_and_its_print(plugin):
    assert wait_until(lambda: status(plugin)["farmhand"]["ok"])
    s = status(plugin)
    assert [(p["name"], p["state"], p["progress"], p["file"]) for p in s["printers"]] == [
        ("VT 1190", "printing", 42.4, "Frog.gcode"), ("Core One", None, None, None),
    ]
    assert s["farm"]["colors"]["amber"] == "#E39F3A"  # Farmhand's colours, for the page opened on its own
    assert s["farmhand"]["problem"] is None


def test_a_print_starting_shows_without_waiting_for_the_next_refresh(plugin, farmhand):
    assert wait_until(lambda: status(plugin)["farmhand"]["ok"] and status(plugin)["farmhand"]["live"])  # asked, and listening
    farmhand.prints[2] = {"state": "printing", "progress": 0.3, "file": "Benchy.gcode", "error": None}
    farmhand.push("print.started", printer_id=2, printer_name="Core One", file="Benchy.gcode", progress=0.3)
    # refresh_seconds is 60: only the event can have brought this in
    assert wait_until(lambda: status(plugin)["printers"][1]["state"] == "printing")
    s = status(plugin)
    assert s["printers"][1]["file"] == "Benchy.gcode"
    assert s["last_event"]["type"] == "print.started" and s["last_event"]["printer_name"] == "Core One"


def test_unknown_event_types_are_ignored(plugin, farmhand):
    assert wait_until(lambda: status(plugin)["farmhand"]["live"])
    farmhand.push("filament.changed", printer_id=1, printer_name="VT 1190")  # one v1 might gain later
    farmhand.push("print.finished", printer_id=1, printer_name="VT 1190", file="Frog.gcode", progress=None)
    assert wait_until(lambda: (status(plugin)["last_event"] or {}).get("type") == "print.finished")


def test_the_page_hears_each_change(plugin, farmhand):
    """GET /api/events: the snapshot as it is, then again each time it changes."""
    assert wait_until(lambda: status(plugin)["farmhand"]["live"])
    with urllib.request.urlopen(plugin.url + "/api/events", timeout=5) as stream:
        assert stream.headers["Content-Type"] == "text/event-stream"
        first = json.loads(_next_data(stream))
        farmhand.push("printer.unreachable", printer_id=1, printer_name="VT 1190", error="It's off.")
        second = json.loads(_next_data(stream))
    assert second["version"] > first["version"]


def _next_data(stream) -> str:
    for raw in stream:
        line = raw.decode().strip()
        if line.startswith("data: "):
            return line[len("data: "):]
    raise AssertionError("the stream ended")


# ------------------------------------------------------------------ when Farmhand says no, or isn't there


def test_a_refused_token_says_to_make_a_new_one(env, plugin):
    plugin.watcher.farmhand.token = "old-token"
    with pytest.raises(FarmhandError) as e:
        plugin.watcher.refresh()
    assert e.value.kind == "refused"
    assert "Farmhand refused this plugin's token: make a new one on Farmhand's Plugins page" in e.value.message
    assert "it was replaced by a new one" in e.value.message  # Farmhand's own words passed on
    # shown on the page, and on Farmhand's Plugins page through /health
    assert wait_until(lambda: (status(plugin)["farmhand"]["problem_kind"]) == "refused")
    code, body = get(plugin.url + "/health")
    assert code == 503 and "make a new one on Farmhand's Plugins page" in body
    assert "Farmhand said" not in body and len(body) < 200  # short enough for a line on Farmhand's Plugins page


def test_a_missing_permission_is_named(farmhand, tmp_path):
    farmhand.permissions = {"printers:read"}
    watcher = Watcher(Farmhand(farmhand.url, TOKEN), Settings(tmp_path))
    with pytest.raises(FarmhandError) as e:
        watcher.refresh()
    assert e.value.kind == "forbidden" and "prints:read" in e.value.message


def test_without_farm_read_the_page_keeps_its_own_colours(farmhand, tmp_path):
    farmhand.permissions = {"printers:read", "prints:read"}  # the operator unticked farm:read
    watcher = Watcher(Farmhand(farmhand.url, TOKEN), Settings(tmp_path))
    watcher.refresh()
    s = watcher.snapshot()
    assert s["farm"] is None and s["farmhand"]["ok"] and len(s["printers"]) == 2


def test_asking_too_often_waits_as_farmhand_says(farmhand, tmp_path):
    farmhand.busy_for = 1
    watcher = Watcher(Farmhand(farmhand.url, TOKEN), Settings(tmp_path))
    with pytest.raises(FarmhandError) as e:
        watcher.refresh()
    assert e.value.kind == "busy" and e.value.retry_after == 1.0 and "slow down" in e.value.message
    watcher.refresh()  # and the next try goes through
    assert watcher.snapshot()["farmhand"]["ok"]


def test_missing_environment_variables_are_said_plainly(tmp_path):
    for url, token, words in [("", TOKEN, "FARMHAND_URL isn't set"), ("http://x", "", "FARMHAND_TOKEN isn't set")]:
        with pytest.raises(FarmhandError) as e:
            Farmhand(url, token).printers()
        assert e.value.kind == "setup" and words in e.value.message and "Plugins page" in e.value.message


def test_while_farmhand_is_down_it_says_so_and_keeps_trying(tmp_path):
    port = _free_port()
    url = f"http://127.0.0.1:{port}/plugin-api/v1"
    watcher = Watcher(Farmhand(url, TOKEN), Settings(tmp_path), refresh_seconds=60, retry_seconds=0.2)
    watcher.start()
    try:
        assert wait_until(lambda: watcher.snapshot()["farmhand"]["problem_kind"] == "down")
        s = watcher.snapshot()
        assert s["farmhand"]["problem"].startswith(f"Can't reach Farmhand at {url}") and not s["farmhand"]["ok"]
        farmhand = FakeFarmhand(port)  # Farmhand comes back, at the same address
        try:
            assert wait_until(lambda: watcher.snapshot()["farmhand"]["ok"])
            assert wait_until(lambda: watcher.snapshot()["farmhand"]["live"])  # and the events reconnect
            assert len(watcher.snapshot()["printers"]) == 2
        finally:
            farmhand.stop()
    finally:
        watcher.stop()


def test_the_events_reconnect_when_farmhand_restarts(plugin, farmhand):
    assert wait_until(lambda: farmhand.listening() == 1)
    farmhand.push("print.finished", printer_id=1, printer_name="VT 1190", file="Frog.gcode", progress=None)
    with farmhand._lock:
        for q in farmhand._listeners:
            q.put(None)  # Farmhand ends the stream, as it does when it restarts
    assert wait_until(lambda: farmhand.listening() == 1 and status(plugin)["farmhand"]["live"])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ its own setting


def test_hidden_printers_are_kept_in_its_own_folder(plugin, env):
    assert wait_until(lambda: status(plugin)["farmhand"]["ok"])
    assert post(plugin.url + "/api/settings", {"hidden_printers": [1]}) == (200, {"hidden_printers": [1]})
    s = status(plugin)
    assert [p["name"] for p in s["printers"]] == ["Core One"]
    assert [p["name"] for p in s["all_printers"]] == ["VT 1190", "Core One"]  # still offered in "Choose printers"
    # kept in the volume, so a new container (same volume) remembers it
    assert Settings(Config.from_env(env).data_dir).hidden_printers == [1]


@pytest.mark.parametrize("body", [{"hidden_printers": "1"}, {"hidden_printers": [True]}, {}, ["x"]])
def test_a_bad_setting_is_refused_in_plain_words(plugin, body):
    code, answer = post(plugin.url + "/api/settings", body)
    assert code == 400 and "list of printer ids" in answer["detail"]


def test_an_unreadable_settings_file_starts_with_every_printer(tmp_path):
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    assert Settings(tmp_path).hidden_printers == []
