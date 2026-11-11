"""
Plugins: the manifest checked, installing one (its token made, kept only as a hash, shown once, replaced), and the
plugin API v1 a plugin's container reads Farmhand through: 401 without a good token, 403 outside its permissions, and
each answer's shape, with nothing secret in it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from app.models import PluginToken
from app.services import go2rtc
from app.services.plugins import answers, cache, events, manifest

MANIFEST = {
    "id": "stream", "name": "Stream", "version": "1.0.0", "farmhand_api": "1", "port": 8080,
    "author": "Elves", "homepage": "https://example.com/stream",
    "page": {"menu": "Stream", "icon": "video", "path": "/"},
    "permissions": ["printers:read", "cameras:read", "prints:read", "farm:read"],
    "settings_page": "/settings", "health": "/health",
}
EVERYTHING = MANIFEST["permissions"]


@pytest.fixture(autouse=True)
def _fresh():
    cache.clear()
    events.reset()
    yield
    cache.clear()
    events.reset()


def install(api, permissions=EVERYTHING, **changes) -> str:
    r = api.post("/plugins", json={"manifest": {**MANIFEST, **changes}, "permissions": permissions, "image": "ghcr.io/elves/stream:1.0"})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ the manifest


def test_a_good_manifest_is_kept_as_checked():
    checked = manifest.check({**MANIFEST, "permissions": ["printers:read", "printers:read"], "extra": "ignored"})
    assert checked["id"] == "stream" and checked["permissions"] == ["printers:read"]
    assert checked["page"] == {"menu": "Stream", "icon": "video", "path": "/"}
    assert "extra" not in checked
    bare = manifest.check({"id": "hello-2", "name": "Hello", "version": "0.1", "farmhand_api": "1", "port": 80})
    assert bare["permissions"] == [] and bare["page"] is None and bare["health"] is None


@pytest.mark.parametrize("change, words", [
    ({"id": "Stream"}, "lower-case letters"),
    ({"id": "my_plugin"}, "lower-case letters"),
    ({"id": "-stream"}, "lower-case letters"),
    ({"id": None}, "lower-case letters"),
    ({"name": ""}, "name must be text"),
    ({"version": "one point oh"}, "version must be like"),
    ({"farmhand_api": "2"}, "plugin API version \"2\""),
    ({"farmhand_api": 1}, "plugin API version 1"),
    ({"port": 0}, "port must be a whole number"),
    ({"port": "8080"}, "port must be a whole number"),
    ({"port": True}, "port must be a whole number"),
    ({"permissions": ["printers:write"]}, "'printers:write', which this Farmhand doesn't know"),
    ({"permissions": "printers:read"}, "must be a list"),
    ({"health": "health"}, "health must be a path"),
    ({"page": {"path": "/"}}, "page menu must be text"),
    ({"page": "Stream"}, "page must be an object"),
])
def test_a_bad_manifest_says_what_is_wrong(change, words):
    with pytest.raises(ValueError, match=None) as e:
        manifest.check({**MANIFEST, **change})
    assert words in str(e.value)
    with pytest.raises(ValueError, match="isn't a JSON object"):
        manifest.check(["not", "a", "manifest"])


# ------------------------------------------------------------------ installing, for the operator


def test_installing_shows_the_token_once_and_keeps_only_its_hash(api):
    r = api.post("/plugins", json={"manifest": MANIFEST, "permissions": ["printers:read"], "image": "ghcr.io/elves/stream:1.0"})
    assert r.status_code == 201
    body = r.json()
    token = body["token"]
    assert len(token) >= 40
    plugin = body["plugin"]
    assert (plugin["id"], plugin["name"], plugin["version"], plugin["image"], plugin["farmhand_api"], plugin["enabled"]) == (
        "stream", "Stream", "1.0.0", "ghcr.io/elves/stream:1.0", "1", True)
    assert plugin["permissions"] == ["printers:read"]
    assert plugin["permissions_described"][0]["means"].startswith("see your printers")
    assert plugin["manifest"]["port"] == 8080 and plugin["token_created_at"] and plugin["token_last_used_at"] is None

    listed = api.get("/plugins").json()
    assert [p["id"] for p in listed["plugins"]] == ["stream"]
    assert listed["api_version"] == "1" and {p["permission"] for p in listed["permissions"]} == set(manifest.PERMISSIONS)
    assert token not in json.dumps(listed) and token not in api.get("/plugins/stream").text

    from app.database import get_db
    from app.main import app
    db = next(app.dependency_overrides[get_db]())
    rows = db.query(PluginToken).all()
    assert [r.token_hash for r in rows] == [hashlib.sha256(token.encode()).hexdigest()]


def test_installing_checks_what_is_granted(api):
    r = api.post("/plugins", json={"manifest": {**MANIFEST, "permissions": ["printers:read"]}, "permissions": ["cameras:read"]})
    assert r.status_code == 422 and "didn't ask for 'cameras:read'" in r.json()["detail"]
    r = api.post("/plugins", json={"manifest": {**MANIFEST, "farmhand_api": "9"}, "permissions": []})
    assert r.status_code == 422 and 'version "9"' in r.json()["detail"]
    install(api)
    r = api.post("/plugins", json={"manifest": MANIFEST, "permissions": []})
    assert r.status_code == 409 and "already installed" in r.json()["detail"]


def test_a_new_token_ends_the_old_one(api):
    old = install(api, permissions=["printers:read"])
    assert api.get("/plugin-api/v1/me", headers=bearer(old)).status_code == 200
    r = api.post("/plugins/stream/token")
    assert r.status_code == 200
    new = r.json()["token"]
    assert new != old and r.json()["plugin"]["permissions"] == ["printers:read"]  # the same permissions
    assert api.get("/plugin-api/v1/me", headers=bearer(old)).status_code == 401
    me = api.get("/plugin-api/v1/me", headers=bearer(new)).json()
    assert me == {"plugin_id": "stream", "permissions": ["printers:read"], "api_version": "1"}
    assert api.get("/plugins/stream").json()["token_last_used_at"] is not None
    assert api.post("/plugins/nothing/token").status_code == 404


def test_removing_needs_confirm_and_ends_the_token(api):
    token = install(api)
    r = api.delete("/plugins/stream")
    assert r.status_code == 409 and "confirm=true" in r.json()["detail"]
    assert api.get("/plugin-api/v1/me", headers=bearer(token)).status_code == 200
    assert api.delete("/plugins/stream?confirm=true").status_code == 204
    assert api.get("/plugins").json()["plugins"] == []
    assert api.get("/plugin-api/v1/me", headers=bearer(token)).status_code == 401
    assert api.delete("/plugins/stream?confirm=true").status_code == 404


def test_the_settings_copy_lists_plugins_but_never_tokens(api, db_session):
    from app import change_hooks
    from app.services import config_service
    from app.services.plugins import registry

    assert change_hooks._what_changed("/plugins") == config_service.MirrorScope()
    assert change_hooks._what_changed("/plugins/stream/token") == config_service.MirrorScope()
    _, token = registry.register(db_session, MANIFEST, ["printers:read"], "ghcr.io/elves/stream:1.0")
    doc = config_service.build_document(db_session)
    assert doc["plugins"] == [{"id": "stream", "name": "Stream", "version": "1.0.0", "image": "ghcr.io/elves/stream:1.0",
                               "enabled": True, "permissions": ["printers:read"]}]
    assert token not in json.dumps(doc) and registry.hash_token(token) not in json.dumps(doc)


# ------------------------------------------------------------------ the plugin API: tokens and permissions


@pytest.mark.parametrize("path", ["/me", "/printers", "/cameras", "/printers/1/print", "/events", "/farm"])
def test_no_token_or_a_bad_one_is_401(api, path):
    install(api)
    r = api.get(f"/plugin-api/v1{path}")
    assert r.status_code == 401 and "Authorization: Bearer" in r.json()["detail"]
    assert r.headers["www-authenticate"] == "Bearer"
    assert api.get(f"/plugin-api/v1{path}", headers={"Authorization": "Basic abc"}).status_code == 401
    r = api.get(f"/plugin-api/v1{path}", headers=bearer("not-a-real-token"))
    assert r.status_code == 401 and "isn't valid" in r.json()["detail"]


@pytest.mark.parametrize("path, permission", [
    ("/printers", "printers:read"), ("/cameras", "cameras:read"), ("/printers/1/print", "prints:read"),
    ("/events", "prints:read"), ("/farm", "farm:read"),
])
def test_a_call_outside_the_plugins_permissions_is_403_naming_the_one_needed(api, path, permission):
    others = [p for p in EVERYTHING if p != permission]
    token = install(api, permissions=others)
    r = api.get(f"/plugin-api/v1{path}", headers=bearer(token))
    assert r.status_code == 403
    assert f"the {permission} permission" in r.json()["detail"] and "\"stream\" plugin" in r.json()["detail"]


# ------------------------------------------------------------------ the plugin API: each answer


def test_printers_have_addresses_and_never_secrets(api, moonraker):
    token = install(api)
    api.post("/printers", json={"name": "VT 1190", "kind": "Voron", "wired_ip": "10.0.6.21", "wireless_ip": "10.0.7.21",
                                "moonraker_api_key": "moon-secret-key"})
    api.post("/printers", json={"name": "Core One", "connection_type": "prusalink", "wired_ip": "10.0.6.30",
                                "prusalink_password": "prusa-secret-pw", "camera_address": "10.0.6.40"})
    retired = api.post("/printers", json={"name": "Old", "wired_ip": "10.0.6.99"}).json()["id"]
    api.patch(f"/printers/{retired}", json={"decommissioned": True})
    r = api.get("/plugin-api/v1/printers", headers=bearer(token))
    assert r.status_code == 200
    assert "moon-secret-key" not in r.text and "prusa-secret-pw" not in r.text
    assert r.json() == {"printers": [
        {"id": 2, "name": "Core One", "kind": None, "connection_type": "prusalink", "addresses": {
            "wired_ip": "10.0.6.30", "wireless_ip": None, "moonraker_url": None, "mainsail_url": None,
            "prusalink_url": "http://10.0.6.30", "camera_address": "10.0.6.40"}},
        {"id": 1, "name": "VT 1190", "kind": "Voron", "connection_type": "moonraker", "addresses": {
            "wired_ip": "10.0.6.21", "wireless_ip": "10.0.7.21", "moonraker_url": "http://10.0.6.21:7125",
            "mainsail_url": "http://10.0.6.21/", "prusalink_url": None, "camera_address": None}},
    ]}


def test_answers_are_kept_a_few_seconds(api, moonraker):
    token = install(api)
    api.post("/printers", json={"name": "VT 1190", "wired_ip": "10.0.6.21"})
    assert len(api.get("/plugin-api/v1/printers", headers=bearer(token)).json()["printers"]) == 1
    api.post("/printers", json={"name": "VT 1191", "wired_ip": "10.0.6.22"})
    assert len(api.get("/plugin-api/v1/printers", headers=bearer(token)).json()["printers"]) == 1  # the kept answer
    cache.clear()
    assert len(api.get("/plugin-api/v1/printers", headers=bearer(token)).json()["printers"]) == 2


def test_cameras_with_a_stream_address_for_ffmpeg(api, moonraker, monkeypatch):
    monkeypatch.setattr(go2rtc, "register", lambda name, source: None)
    token = install(api)
    api.post("/printers", json={"name": "VT 1190", "wired_ip": "10.0.6.21"})
    api.post("/printers", json={"name": "Core One", "connection_type": "prusalink", "wired_ip": "10.0.6.30", "camera_address": "10.0.6.40"})
    moonraker.webcams = [
        {"name": "Bed", "enabled": True, "service": "mjpegstreamer", "stream_url": "/webcam/?action=stream",
         "snapshot_url": "/webcam/?action=snapshot", "rotation": 90, "flip_horizontal": True, "flip_vertical": False},
        {"name": "Nozzle", "enabled": True, "service": "webrtc-go2rtc", "stream_url": "http://10.0.6.21/go2rtc/webrtc.html?src=nozzle"},
        {"name": "Odd", "enabled": True, "service": "webrtc-janus", "stream_url": "http://10.0.6.21/janus"},
    ]
    r = api.get("/plugin-api/v1/cameras", headers=bearer(token))
    assert r.status_code == 200
    core, voron = r.json()["printers"]
    assert core["printer_name"] == "Core One" and core["error"] is None
    assert core["cameras"][0] | {"ffmpeg_input": None} == {
        "name": "Camera", "kind": "rtsp", "url": "rtsp://10.0.6.40/live", "ffmpeg_input": None, "rotation": 0,
        "flip_horizontal": False, "flip_vertical": False, "ffmpeg_filters": [], "aspect_ratio": "16:9", "target_fps": 15,
        "snapshot_url": None, "error": None}
    assert core["cameras"][0]["ffmpeg_input"][-2:] == ["-i", "rtsp://10.0.6.40/live"]
    bed, nozzle, odd = voron["cameras"]
    assert (bed["kind"], bed["url"]) == ("mjpeg", "http://10.0.6.21/webcam/?action=stream")
    assert bed["ffmpeg_input"][-4:] == ["-f", "mpjpeg", "-i", "http://10.0.6.21/webcam/?action=stream"]
    assert (bed["rotation"], bed["flip_horizontal"], bed["ffmpeg_filters"]) == (90, True, ["transpose=1", "hflip"])
    assert (nozzle["kind"], nozzle["url"]) == ("rtsp", "rtsp://10.0.6.21:8554/nozzle")
    assert odd["kind"] is None and odd["url"] is None and "only plays in a browser" in odd["error"]

    moonraker.down = True
    cache.clear()
    voron = api.get("/plugin-api/v1/cameras", headers=bearer(token)).json()["printers"][1]
    assert voron["cameras"] == [] and "Moonraker" in voron["error"]


def test_a_printers_print(api, moonraker):
    token = install(api)
    pid = api.post("/printers", json={"name": "V2Blue", "wired_ip": "10.0.6.21"}).json()["id"]
    url = f"/plugin-api/v1/printers/{pid}/print"
    assert api.get(url, headers=bearer(token)).json() == {"state": None, "progress": None, "file": None, "error": None}
    moonraker.print_state = "printing"
    moonraker.live = {"filename": "Frog.gcode", "print_duration": 1200.0, "progress": 0.4237}
    cache.clear()
    assert api.get(url, headers=bearer(token)).json() == {"state": "printing", "progress": 42.4, "file": "Frog.gcode", "error": None}
    r = api.get("/plugin-api/v1/printers/999/print", headers=bearer(token))
    assert r.status_code == 404 and r.json()["detail"] == "Printer not found"


def test_the_farms_colours_and_time_zone(api):
    token = install(api)
    r = api.get("/plugin-api/v1/farm", headers=bearer(token)).json()
    assert (r["scheme"], r["mode"], r["time_zone"]) == ("farmhand", "dark", None)
    assert r["colors"]["bg"] == "#1B1D1E" and r["colors"]["textMuted"] == "#CBCED0"
    api.put("/settings/config", json={"appearance": {"scheme": "farmhand", "contrast": 100, "file_name_color": "#112233"},
                                      "preferences": {"time_zone": "America/New_York"}})
    cache.clear()
    r = api.get("/plugin-api/v1/farm", headers=bearer(token)).json()
    assert r["time_zone"] == "America/New_York"
    assert r["colors"]["textMuted"] == "#FFFFFF" and r["colors"]["fileName"] == "#112233"  # as the pages draw them


def test_palette_mixes_text_like_the_pages():
    mode, colors = answers.palette("farmhand", 50)
    assert mode == "dark" and colors["textFaint"] == "#D1D3D5"  # #A3A7AA halfway to #FFFFFF, rounded as JavaScript does
    assert answers.palette("no-such-scheme", 0)[1]["bg"] == "#1B1D1E"  # an unknown scheme: the first


# ------------------------------------------------------------------ events


def _changes(steps: list[dict]) -> list[tuple]:
    """Each look at printer 1 in turn; the events heard, as (type, file)."""
    heard = []
    events._listeners.add((_Loop(heard), None))
    for step in steps:
        events.observe(1, "VT 1190", {"state": None, "progress": None, "file": None, "error": None, **step})
    return [(e["type"], e.get("file")) for e in heard]


class _Loop:
    """Stands in for a listener's event loop: what it's handed is heard at once."""

    def __init__(self, heard):
        self.heard = heard

    def call_soon_threadsafe(self, fn, queue, event):
        self.heard.append(event)


def test_events_are_changes_in_what_farmhand_sees():
    printing = {"state": "printing", "file": "Frog.gcode", "progress": 10.0}
    assert _changes([{}, printing, {**printing, "progress": 50.0}, {**printing, "state": "paused"}, printing, {}]) == [
        ("print.started", "Frog.gcode"), ("print.paused", "Frog.gcode"), ("print.resumed", "Frog.gcode"),
        ("print.finished", "Frog.gcode"),
    ]
    events.reset()
    assert _changes([printing]) == []  # the first look only notes how it is
    events.reset()
    off = {"error": "Couldn't reach Moonraker"}
    assert _changes([printing, off, off, printing, {**printing, "file": "Shark.gcode"}]) == [
        ("printer.unreachable", None), ("printer.reachable", None),  # unreachable isn't the print ending
        ("print.finished", "Frog.gcode"), ("print.started", "Shark.gcode"),
    ]


def test_an_event_on_the_wire():
    events.reset()
    events.publish("print.started", {"printer_id": 1, "printer_name": "VT 1190", "file": "Frog.gcode", "progress": 0.0})

    async def listen():
        stream = events.stream(keepalive=0.05)
        assert await stream.__anext__() == ": connected\n\n"
        assert events.listening()
        assert await stream.__anext__() == ": still here\n\n"
        events.observe(1, "VT 1190", {"state": None, "file": None, "progress": None, "error": None})
        events.observe(1, "VT 1190", {"state": "printing", "file": "Frog.gcode", "progress": 1.0, "error": None})
        line = await stream.__anext__()
        await stream.aclose()
        return line

    line = asyncio.run(listen())
    assert not events.listening()
    head, data = line.split("data: ")
    assert head.startswith("id: 2\nevent: print.started\n")
    event = json.loads(data)
    assert {k: event[k] for k in ("id", "type", "printer_id", "printer_name", "file", "progress")} == {
        "id": 2, "type": "print.started", "printer_id": 1, "printer_name": "VT 1190", "file": "Frog.gcode", "progress": 1.0}
    assert event["at"].endswith("+00:00")


def test_print_progress_feeds_events(api, moonraker):
    """What Monitor (and the poller) already ask is what plugins hear."""
    pid = api.post("/printers", json={"name": "V2Blue", "wired_ip": "10.0.6.21"}).json()["id"]
    heard = []
    events._listeners.add((_Loop(heard), None))
    api.get(f"/printers/{pid}/progress")
    moonraker.print_state = "printing"
    moonraker.live = {"filename": "Frog.gcode", "print_duration": 10.0, "progress": 0.01}
    api.get(f"/printers/{pid}/progress")
    assert [(e["type"], e["printer_name"], e["file"]) for e in heard] == [("print.started", "V2Blue", "Frog.gcode")]
