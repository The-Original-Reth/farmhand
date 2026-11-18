"""
Stream control, the plugin built into Farmhand: switched on and off on the Plugins page (off by default, and then its
API answers 404), the one stream's design checked and kept with a revision, its pictures and music in the stream
folder, the stream plugins started and stopped through their `stream_control` path, what a stream plugin reads with
stream:read, the schedule's starts and stops, and its place in the settings copy.
"""
from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import change_hooks
from app.services import config_service
from app.services.plugins import cache, limits, remote
from app.services.stream_control import music_sources, schedule, settings_copy

from .factories import api_db

CAMERA = "1:Nozzle"
STREAM_MANIFEST = {
    "id": "stream", "name": "YouTube Stream", "version": "1.2.0", "farmhand_api": "1", "port": 8080,
    "page": {"menu": "YouTube", "icon": "youtube", "path": "/"},
    "permissions": ["cameras:read", "stream:read"], "health": "/health",
    "stream_control": {"path": "/api/stream-control", "site": "YouTube"},
}


@pytest.fixture(autouse=True)
def _fresh():
    cache.clear()
    limits.reset()
    music_sources.forget()
    yield
    remote.transport = None


def switch(api, on=True):
    r = api.patch("/plugins/stream-control", json={"enabled": on})
    assert r.status_code == 200, r.text
    return r.json()


class FakeStreams:
    """Stream plugins where they run: each answers its stream_control path with how it's doing, and start / stop."""

    def __init__(self):
        self.live: dict[str, bool] = {}
        self.refuse: dict[str, str] = {}  # host -> why it won't go live
        self.down: set[str] = set()
        self.asked: list[str] = []
        # the YouTube plugin's own layout, as its own page's API gives it (Copy layout)
        self.own_layout = {
            "cols": 3, "rows": 1, "layout": "cycle", "seconds_each": 15, "title": "Our farm", "font": "roboto",
            "border_color": "#112233", "music": True, "music_volume": 20, "key_set": True,
            "cells": [{"camera": "2:Bed"}, {"image": "logo.png", "text": "Hi", "layers": [{"type": "picture", "image": "gone.png"}]},
                      {"slideshow": "Prints", "seconds": 5}],
            "holding": {"text": "Back soon", "image": "logo.png"},
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        self.asked.append(f"{request.method} {host}{path}")
        if host in self.down:
            raise httpx.ConnectError("Connection refused", request=request)
        if path.startswith(("/api/stream/pictures/", "/api/stream/slideshows/", "/api/stream/music/")):  # its own stream folder
            name = path.rsplit("/", 1)[1]
            return httpx.Response(200, content=b"picture:" + name.encode()) if name != "gone.png" else httpx.Response(404)
        if path.startswith("/api/stream") and not path.startswith("/api/stream-control"):  # a plugin from before Stream control
            if path == "/api/stream/start":
                if host in self.refuse:
                    return httpx.Response(422, json={"detail": self.refuse[host]})
                self.live[host] = True
            elif path == "/api/stream/stop":
                self.live[host] = False
            live = self.live.get(host, False)
            return httpx.Response(200, json={
                "settings": {"channel": "printfarm"} if host == "twitch" else self.own_layout,
                "media": {"images": ["logo.png"], "slideshows": [{"name": "Prints", "images": ["a.png", "blank:1", "b.png"]}], "music": ["beat.mp3"]},
                "status": {
                    "live": live, "error": None,
                    "youtube": {"watch_url": "https://youtu.be/x", "studio_url": "https://studio.youtube.com/video/x/livestreaming", "viewers": 7}
                    if live and host == "stream" else None,
                    "camera_states": [{"key": "1:Nozzle", "label": "Voron", "state": "live", "since": 1},
                                      {"key": "2:Bed", "label": "Prusa", "state": "down", "since": 2}] if live else [],
                },
            })
        if path == "/api/stream-control/start":
            if host in self.refuse:
                return httpx.Response(422, json={"detail": self.refuse[host]})
            self.live[host] = True
        elif path == "/api/stream-control/stop":
            self.live[host] = False
        elif path != "/api/stream-control":
            return httpx.Response(404, text="not here")
        return httpx.Response(200, json={"live": self.live.get(host, False), "following": True, "error": None,
                                         "watch_url": f"https://example.com/{host}" if self.live.get(host) else None})


def add_stream_plugin(api, plugin_id="stream", site="YouTube", permissions=("cameras:read", "stream:read")):
    manifest = {**STREAM_MANIFEST, "id": plugin_id, "name": f"{site} Stream", "stream_control": {"path": "/api/stream-control", "site": site}}
    r = api.post("/plugins", json={"manifest": manifest, "permissions": list(permissions)})
    assert r.status_code == 201, r.text
    return r.json()["token"]


# ------------------------------------------------------------------ on and off


def test_it_is_listed_with_the_plugins_switched_off_until_switched_on(api):
    listed = api.get("/plugins").json()
    assert listed["builtin"] == [{
        "id": "stream-control", "name": "Stream control", "builtin": True, "enabled": False,
        "description": listed["builtin"][0]["description"], "page": {"menu": "Stream control", "icon": "video", "path": "/"},
    }]
    r = api.get("/stream-control")
    assert r.status_code == 404 and "switched off" in r.json()["detail"]
    assert switch(api)["enabled"] is True
    assert api.get("/plugins").json()["builtin"][0]["enabled"] is True
    assert api.get("/plugins/stream-control").json()["enabled"] is True
    assert api.get("/stream-control").status_code == 200
    switch(api, False)
    assert api.get("/stream-control").status_code == 404
    assert api.put("/stream-control", json={"title": "x"}).status_code == 404


def test_no_added_plugin_can_take_its_id(api):
    r = api.post("/plugins", json={"manifest": {**STREAM_MANIFEST, "id": "stream-control"}, "permissions": []})
    assert r.status_code == 422 and "Stream control" in r.json()["detail"]


def test_the_manifest_s_stream_control_entry_is_checked():
    from app.services.plugins import manifest

    assert manifest.check(STREAM_MANIFEST)["stream_control"] == {"path": "/api/stream-control", "site": "YouTube", "settings": None}
    assert manifest.check({**STREAM_MANIFEST, "stream_control": {"path": "/s", "settings": "/?view=x"}})["stream_control"]["settings"] == "/?view=x"
    assert manifest.check({**STREAM_MANIFEST, "stream_control": None})["stream_control"] is None
    for bad in ({"path": "api"}, {"site": "YouTube"}, "yes"):
        with pytest.raises(ValueError):
            manifest.check({**STREAM_MANIFEST, "stream_control": bad})


# ------------------------------------------------------------------ the design


def test_the_design_is_saved_checked_and_counted(api):
    switch(api)
    first = api.get("/stream-control").json()
    assert first["design"]["revision"] == 0 and first["design"]["cols"] == 1 and first["design"]["cells"] == [None]
    assert any(f["key"] == "play" for f in first["fonts"]) and [r["key"] for r in first["resolutions"]] == ["720p", "1080p", "1440p"]
    cells = [{"camera": CAMERA, "show_words": False}, {"background": "#112233", "text": " Hello ", "image": "logo.png"}]
    r = api.put("/stream-control", json={"cols": 2, "rows": 1, "cells": cells, "title": "The farm, live", "border_color": "#ff0000",
                                         "music_volume": 30, "layout": "cycle", "holding": {"text": "Back soon"}})
    assert r.status_code == 200, r.text
    d = r.json()["design"]
    assert d["revision"] == 1 and d["saved_at"]
    assert d["cameras"] == [CAMERA] and d["cells"][0] == {"camera": CAMERA, "show_words": False}
    assert d["cells"][1]["text"] == "Hello" and d["cells"][1]["image"] == "logo.png"
    assert (d["title"], d["border_color"], d["music_volume"], d["layout"]) == ("The farm, live", "#FF0000", 30, "cycle")
    assert d["holding"]["text"] == "Back soon"
    assert api.put("/stream-control", json={"description": "Printers printing"}).json()["design"]["revision"] == 2
    for bad, words in [
        ({"cols": 2, "rows": 1, "cells": [{"camera": CAMERA}, {"camera": CAMERA}]}, "one square"),
        ({"cols": 6, "rows": 1, "cells": [None] * 6}, "1 to 5"),
        ({"border_color": "red"}, "colour picker"),
        ({"font": "wingdings"}, "fonts listed"),
        ({"delay": 500}, "delay"),
        ({"title": "x" * 101}, "up to 100"),
    ]:
        r = api.put("/stream-control", json=bad)
        assert r.status_code == 422 and words in r.json()["detail"], (bad, r.text)
    assert api.get("/stream-control").json()["design"]["revision"] == 2  # nothing refused was kept


def test_cameras_alone_make_a_grid_just_big_enough(api):
    switch(api)
    d = api.put("/stream-control", json={"cameras": ["1:A", "2:B", "3:C"]}).json()["design"]
    assert (d["cols"], d["rows"]) == (2, 2) and d["cameras"] == ["1:A", "2:B", "3:C"] and d["cells"][3] is None


def test_saved_layouts(api):
    switch(api)
    r = api.put("/stream-control/layouts", json=[{"name": "Night", "cols": 1, "rows": 1, "cells": [{"camera": CAMERA}]}, {"name": ""}])
    assert r.status_code == 200
    assert [lay["name"] for lay in r.json()["layouts"]] == ["Night"]
    assert api.get("/stream-control").json()["layouts"][0]["cells"] == [{"camera": CAMERA}]


# ------------------------------------------------------------------ the stream folder


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def test_pictures_slideshows_and_music_in_the_stream_folder(api, tmp_path):
    switch(api)
    r = api.post("/stream-control/pictures", files=[("files", ("logo.png", PNG, "image/png"))])
    assert r.status_code == 201, r.text
    found = r.json()["media"]
    assert found["images"] == ["logo.png"] and found["error"] is None
    assert found["path"].replace("\\", "/").endswith("/stream")
    assert api.get("/stream-control/pictures/logo.png").content == PNG
    assert api.post("/stream-control/pictures", files=[("files", ("notes.txt", b"hi", "text/plain"))]).status_code == 422
    assert api.delete("/stream-control/pictures/logo.png").status_code == 409  # needs confirm=true
    assert api.delete("/stream-control/pictures/logo.png?confirm=true").json()["media"]["images"] == []

    api.post("/stream-control/slideshows", json={"name": "Prints"})
    api.post("/stream-control/slideshows/Prints/pictures", files=[("files", ("a.png", PNG, "image/png"))])
    api.post("/stream-control/slideshows/Prints/blanks")
    api.put("/stream-control", json={"cols": 1, "rows": 1, "cells": [{"slideshow": "Prints", "text": "Hi"}]})
    r = api.put("/stream-control/slideshows/Prints", json={"name": "Done"})
    assert r.json()["media"]["slideshows"] == [{"name": "Done", "images": ["a.png", "blank:1"]}]
    assert r.json()["design"]["cells"][0]["slideshow"] == "Done"  # the square follows the new name
    assert api.get("/stream-control/slideshows/Done/pictures/a.png").content == PNG

    r = api.post("/stream-control/music", files=[("files", ("song.mp3", b"ID3...", "audio/mpeg"))])
    assert r.json()["media"]["music"] == ["song.mp3"]
    assert r.json()["media"]["windows_path"] is None  # (Farmhand's own storage, not a network share)
    assert api.post("/stream-control/music", files=[("files", ("song.wav", b"RIFF", "audio/wav"))]).status_code == 422


# ------------------------------------------------------------------ the stream plugins


def test_stream_plugins_are_listed_started_and_stopped(api):
    fake = FakeStreams()
    remote.transport = httpx.MockTransport(fake.handle)
    switch(api)
    add_stream_plugin(api, "stream", "YouTube")
    add_stream_plugin(api, "twitch", "Twitch", permissions=("cameras:read",))
    api.post("/plugins", json={"manifest": {**STREAM_MANIFEST, "id": "hello", "stream_control": None}, "permissions": []})

    listed = {s["id"]: s for s in api.get("/stream-control/streams").json()["streams"]}
    assert set(listed) == {"stream", "twitch"}  # only plugins that say they're stream plugins
    assert listed["stream"]["site"] == "YouTube" and listed["stream"]["live"] is False and listed["stream"]["reachable"] is True
    assert listed["stream"]["can_read_design"] is True and listed["twitch"]["can_read_design"] is False

    r = api.post("/stream-control/streams/stream/start")
    assert r.status_code == 200 and r.json()["live"] is True and r.json()["watch_url"] == "https://example.com/stream"
    assert "POST stream/api/stream-control/start" in fake.asked

    fake.refuse["twitch"] = "There's no stream key yet."
    both = {s["id"]: s for s in api.post("/stream-control/start-all").json()["streams"]}
    assert both["stream"]["live"] is True and both["twitch"]["error"] == "There's no stream key yet."
    assert all(not s["live"] for s in api.post("/stream-control/stop-all").json()["streams"])

    api.patch("/plugins/twitch", json={"enabled": False})
    fake.asked.clear()
    listed = {s["id"]: s for s in api.get("/stream-control/streams").json()["streams"]}
    assert listed["twitch"]["enabled"] is False and listed["twitch"]["reachable"] is None
    assert not any("twitch" in a for a in fake.asked)  # a switched-off plugin isn't asked
    r = api.post("/stream-control/streams/twitch/start")
    assert r.status_code == 422 and "switched off" in r.json()["detail"]
    assert api.post("/stream-control/streams/hello/start").status_code == 422
    assert api.post("/stream-control/streams/nobody/start").status_code == 404
    assert api.post("/stream-control/streams/stream/pause").status_code == 404

    fake.down.add("stream")
    s = next(s for s in api.get("/stream-control/streams").json()["streams"] if s["id"] == "stream")
    assert s["reachable"] is False and "couldn't reach" in s["error"]


def test_the_youtube_and_twitch_plugins_from_before_stream_control_start_and_stop_through_their_own_page(api):
    fake = FakeStreams()
    remote.transport = httpx.MockTransport(fake.handle)
    switch(api)
    for plugin_id, name in (("stream", "YouTube Stream"), ("twitch", "Twitch Stream")):
        old = {k: v for k, v in STREAM_MANIFEST.items() if k != "stream_control"}
        r = api.post("/plugins", json={"manifest": {**old, "id": plugin_id, "name": name, "permissions": ["cameras:read"]}, "permissions": ["cameras:read"]})
        assert r.status_code == 201
    fake.asked.clear()
    listed = {s["id"]: s for s in api.get("/stream-control/streams").json()["streams"]}
    assert fake.asked.count("GET stream/api/stream") == 1  # (its page answers both how it's doing and what it shows)
    assert {k: (s["site"], s["needs_update"], s["live"], s["following"]) for k, s in listed.items()} == {
        "stream": ("YouTube", True, False, False), "twitch": ("Twitch", True, False, False)}

    r = api.post("/stream-control/streams/stream/start")
    assert r.json()["live"] is True and r.json()["watch_url"] == "https://youtu.be/x"
    assert "POST stream/api/stream/start" in fake.asked
    fake.refuse["twitch"] = "There's no stream key yet."
    both = {s["id"]: s for s in api.post("/stream-control/start-all").json()["streams"]}
    assert both["twitch"]["error"] == "There's no stream key yet." and both["stream"]["live"] is True
    del fake.refuse["twitch"]
    assert api.post("/stream-control/streams/twitch/start").json()["watch_url"] == "https://www.twitch.tv/printfarm"

    # each stream's own links and cameras, as its own page shows them
    listed = {s["id"]: s for s in api.get("/stream-control/streams").json()["streams"]}
    assert [link["label"] for link in listed["stream"]["links"]] == ["Watch", "Chat and analytics"]
    assert (listed["stream"]["settings_page"], listed["twitch"]["settings_page"]) == ("/?view=youtube-settings", "/?view=twitch-settings")
    assert listed["stream"]["viewers"] == 7
    assert [link["label"] for link in listed["twitch"]["links"]] == ["Watch", "Chat", "Stream Manager", "Analytics"]
    assert listed["twitch"]["links"][1]["url"] == "https://www.twitch.tv/popout/printfarm/chat?popout="
    assert [(c["label"], c["state"]) for c in listed["stream"]["cameras"]] == [("Voron", "live"), ("Prusa", "down")]

    stopped = api.post("/stream-control/stop-all").json()["streams"]
    assert all(not s["live"] for s in stopped) and all(s["cameras"] == [] for s in stopped)


def test_copy_layout_makes_one_stream_s_own_layout_stream_control_s_with_its_pictures(api, tmp_path):
    fake = FakeStreams()
    remote.transport = httpx.MockTransport(fake.handle)
    switch(api)
    add_stream_plugin(api, "stream", "YouTube")
    before = api.get("/stream-control").json()["design"]["revision"]

    r = api.post("/stream-control/streams/stream/copy-layout")
    assert r.status_code == 200, r.text
    got = r.json()
    d = got["design"]
    assert (d["cols"], d["rows"], d["layout"], d["seconds_each"], d["title"], d["font"], d["border_color"]) == (3, 1, "cycle", 15, "Our farm", "roboto", "#112233")
    assert d["cameras"] == ["2:Bed"] and d["cells"][2]["slideshow"] == "Prints" and d["holding"]["text"] == "Back soon"
    assert d["revision"] == before + 1
    # its pictures and slideshow, copied into Farmhand's stream folder (a picture it no longer has: said so)
    assert got["media"]["images"] == ["logo.png"]
    assert got["media"]["slideshows"] == [{"name": "Prints", "images": ["a.png", "blank:1", "b.png"]}]
    assert api.get("/stream-control/pictures/logo.png").content == b"picture:logo.png"
    assert any("gone.png" in p for p in got["problems"]) and any("music" in p for p in got["problems"])
    assert "the picture “logo.png”" in got["copied"]
    assert change_hooks._what_changed("/stream-control/streams/stream/copy-layout") is not None

    # copied again: the pictures there already are kept
    assert "the picture “logo.png”" not in api.post("/stream-control/streams/stream/copy-layout").json()["copied"]
    fake.down.add("stream")
    r = api.post("/stream-control/streams/stream/copy-layout")
    assert r.status_code == 422 and "couldn't reach" in r.json()["detail"]
    assert api.post("/stream-control/streams/nobody/copy-layout").status_code == 404


def test_music_plays_from_the_folders_chosen_without_copying(api):
    fake = FakeStreams()
    remote.transport = httpx.MockTransport(fake.handle)
    switch(api)
    token = add_stream_plugin(api, "stream", "YouTube")
    add_stream_plugin(api, "twitch", "Twitch")
    api.post("/stream-control/music", files=[("files", ("own.mp3", b"ID3own", "audio/mpeg"))])
    first = api.get("/stream-control").json()
    assert first["design"]["music_from"] == ["stream-control"] and first["media"]["music"] == ["own.mp3"]
    assert [(s["id"], s["chosen"], s["tracks"]) for s in first["media"]["music_sources"]] == [
        ("stream-control", True, 1), ("twitch", False, 1), ("stream", False, 1)]

    # YouTube's folder and Twitch's, both: their tracks (each name once), passed on from where they are
    r = api.put("/stream-control", json={"music_from": ["stream", "twitch"]})
    m = r.json()["media"]
    assert m["music"] == ["beat.mp3"] and m["own_music"] == ["own.mp3"]
    assert api.get("/stream-control/music/beat.mp3").content == b"picture:beat.mp3"
    assert api.get("/stream-control/music/own.mp3").status_code == 404  # (its folder isn't chosen now)
    headers = {"Authorization": f"Bearer {token}"}
    got = api.get("/plugin-api/v1/stream/design", headers=headers).json()["media"]
    assert got["music"] == ["beat.mp3"] and got["stamps"]["music/beat.mp3"] == "stream:beat.mp3"
    assert "music/own.mp3" not in got["stamps"]
    assert api.get("/plugin-api/v1/stream/music/beat.mp3", headers=headers).content == b"picture:beat.mp3"
    # nothing was copied into Stream control's own music folder
    assert api.get("/stream-control").json()["media"]["own_music"] == ["own.mp3"]

    # both kinds at once
    m = api.put("/stream-control", json={"music_from": ["stream-control", "stream"]}).json()["media"]
    assert m["music"] == ["own.mp3", "beat.mp3"]
    assert api.put("/stream-control", json={"music_from": []}).status_code == 422


def test_only_the_streams_brought_in_are_started_stopped_or_sent_the_design(api):
    fake = FakeStreams()
    remote.transport = httpx.MockTransport(fake.handle)
    switch(api)
    youtube = add_stream_plugin(api, "stream", "YouTube")
    twitch = add_stream_plugin(api, "twitch", "Twitch")
    assert all(s["chosen"] for s in api.get("/stream-control/streams").json()["streams"])  # none chosen yet: all of them

    r = api.put("/stream-control/streams", json={"chosen": ["stream"]})
    assert r.status_code == 200
    listed = {s["id"]: s for s in r.json()["streams"]}
    assert listed["stream"]["chosen"] is True and listed["twitch"]["chosen"] is False
    assert change_hooks._what_changed("/stream-control/streams") is not None  # kept in the settings copy

    fake.asked.clear()
    started = api.post("/stream-control/start-all").json()["streams"]
    assert [s["id"] for s in started] == ["stream"] and fake.live == {"stream": True}
    assert not any("twitch" in a and "start" in a for a in fake.asked)
    r = api.post("/stream-control/streams/twitch/start")
    assert r.status_code == 422 and "isn't brought into Stream control" in r.json()["detail"]

    design = lambda token: api.get("/plugin-api/v1/stream/design", headers={"Authorization": f"Bearer {token}"}).json()  # noqa: E731
    assert design(youtube)["enabled"] is True
    assert design(twitch) == {"enabled": False}  # left out: it keeps its own layout

    db = api_db(api)
    schedule._do(db, "stop", schedule._entry({"days": [0], "stop": "18:00"}))
    assert [r["name"] for r in schedule.happened()[0]["results"]] == ["YouTube Stream"]

    assert api.put("/stream-control/streams", json={"chosen": ["nobody"]}).status_code == 422
    assert settings_copy.entry(db)["streams"] == ["stream"]


# ------------------------------------------------------------------ what a stream plugin reads (stream:read)


def test_a_stream_plugin_reads_the_design_and_its_files(api):
    token = add_stream_plugin(api)
    headers = {"Authorization": f"Bearer {token}"}
    assert api.get("/plugin-api/v1/stream/design", headers=headers).json() == {"enabled": False}
    switch(api)
    api.post("/stream-control/pictures", files=[("files", ("logo.png", PNG, "image/png"))])
    api.put("/stream-control", json={"cols": 1, "rows": 1, "cells": [{"image": "logo.png", "text": "Live"}]})
    got = api.get("/plugin-api/v1/stream/design", headers=headers).json()
    assert got["enabled"] is True and got["design"]["revision"] == 1 and got["design"]["cells"][0]["image"] == "logo.png"
    assert got["media"]["images"] == ["logo.png"]
    stamp = got["media"]["stamps"]["images/logo.png"]
    assert stamp.startswith(f"{len(PNG)}-")  # size and modified time: a plugin fetches a file only when it changed
    r = api.get("/plugin-api/v1/stream/pictures/logo.png", headers=headers)
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert api.get("/plugin-api/v1/stream/pictures/gone.png", headers=headers).status_code == 404

    # every picture copied at once (a stream with dozens of sponsors' logos): never told to slow down, though other calls are
    assert all(api.get("/plugin-api/v1/stream/pictures/logo.png", headers=headers).status_code == 200 for _ in range(100))
    assert any(api.get("/plugin-api/v1/stream/design", headers=headers).status_code == 429 for _ in range(100))
    limits.reset()

    other = add_stream_plugin(api, "twitch", "Twitch", permissions=("cameras:read",))
    r = api.get("/plugin-api/v1/stream/design", headers={"Authorization": f"Bearer {other}"})
    assert r.status_code == 403 and "stream:read" in r.json()["detail"]


# ------------------------------------------------------------------ the schedule


UTC = dt.timezone.utc
WEEKDAYS = [0, 1, 2, 3, 4]


def test_the_schedule_is_checked(api):
    switch(api)
    r = api.put("/stream-control/schedule", json={"on": True, "entries": [{"days": [4, 0, 0], "start": "08:00", "stop": "18:30", "streams": "all"}]})
    assert r.status_code == 200
    assert r.json()["schedule"] == {"on": True, "entries": [{"days": [0, 4], "start": "08:00", "stop": "18:30", "streams": "all"}]}
    for bad, words in [
        ({"days": [], "start": "08:00"}, "at least one day"),
        ({"days": [1], "start": "8am"}, "time of day"),
        ({"days": [1]}, "a time to go live, a time to stop"),
        ({"days": [1], "start": "09:00", "stop": "09:00"}, "same moment"),
        ({"days": [1], "start": "09:00", "streams": []}, "which streams"),
    ]:
        r = api.put("/stream-control/schedule", json={"on": True, "entries": [bad]})
        assert r.status_code == 422 and words in r.json()["detail"], (bad, r.text)


def test_starts_and_stops_come_round_once_in_the_farm_s_time_zone():
    tz = ZoneInfo("America/New_York")
    entries = [schedule._entry({"days": WEEKDAYS, "start": "08:00", "stop": "18:00"})]
    monday_8 = dt.datetime(2026, 11, 16, 8, 0, tzinfo=tz)
    just_before, just_after = monday_8 - dt.timedelta(seconds=20), monday_8 + dt.timedelta(seconds=10)
    assert [a for a, _ in schedule.due(entries, just_before, just_after, tz)] == ["start"]
    assert schedule.due(entries, just_after, just_after + dt.timedelta(seconds=30), tz) == []  # once
    saturday_8 = dt.datetime(2026, 11, 21, 8, 0, tzinfo=tz)
    assert schedule.due(entries, saturday_8 - dt.timedelta(minutes=1), saturday_8, tz) == []  # not a weekday
    # the same moment in UTC: 13:00
    assert [a for a, _ in schedule.due(entries, dt.datetime(2026, 11, 16, 12, 59, tzinfo=UTC), dt.datetime(2026, 11, 16, 13, 0, tzinfo=UTC), tz)] == ["start"]


def test_a_stop_before_its_start_is_the_next_morning():
    entries = [schedule._entry({"days": [4], "start": "20:00", "stop": "02:00"})]  # Friday night
    saturday_2 = dt.datetime(2026, 11, 21, 2, 0, tzinfo=UTC)
    assert [a for a, _ in schedule.due(entries, saturday_2 - dt.timedelta(minutes=1), saturday_2, UTC)] == ["stop"]
    friday_2 = dt.datetime(2026, 11, 20, 2, 0, tzinfo=UTC)
    assert schedule.due(entries, friday_2 - dt.timedelta(minutes=1), friday_2, UTC) == []


def test_the_schedule_starts_the_streams_it_names(api, monkeypatch):
    fake = FakeStreams()
    remote.transport = httpx.MockTransport(fake.handle)
    switch(api)
    add_stream_plugin(api, "stream", "YouTube")
    add_stream_plugin(api, "twitch", "Twitch")
    db = api_db(api)
    schedule._do(db, "start", schedule._entry({"days": [0], "start": "08:00", "streams": ["twitch"]}))
    assert fake.live == {"twitch": True}
    assert schedule.happened()[0]["action"] == "start" and schedule.happened()[0]["results"][0]["name"] == "Twitch Stream"


# ------------------------------------------------------------------ the settings copy


def test_the_settings_copy_has_it_and_load_all_puts_it_back_only_where_there_is_none(api):
    switch(api)
    api.put("/stream-control", json={"title": "Farm", "cols": 1, "rows": 1, "cells": [{"camera": CAMERA}]})
    api.put("/stream-control/schedule", json={"on": True, "entries": [{"days": [0], "start": "08:00"}]})
    db = api_db(api)
    copy = json.loads(json.dumps(config_service.build_document(db)["stream_control"]))
    assert copy["enabled"] is True and copy["design"]["title"] == "Farm" and copy["schedule"]["entries"][0]["start"] == "08:00"
    assert settings_copy.restore(db, copy) is False  # this Farmhand has its own

    from app.services import app_settings
    for key in ("stream_control_enabled", "stream_control_design", "stream_control_layouts", "stream_control_schedule"):
        app_settings.put(db, key, None)
    db.commit()
    assert settings_copy.restore(db, copy) is True
    d = api.get("/stream-control").json()
    assert d["design"]["title"] == "Farm" and d["design"]["cameras"] == [CAMERA] and d["schedule"]["on"] is True


def test_the_stream_folder_as_windows_reaches_it_on_a_share(api, monkeypatch, tmp_path):
    from app import mounts
    from app.models import NetworkShare
    from app.services.stream_control import media

    db = api_db(api)
    db.add(NetworkShare(name="TrueNas", protocol="smb", server="192.168.10.240", share="3d_Printing_Elves/Farmhand"))
    db.commit()
    monkeypatch.setattr(mounts, "mount_point_for", lambda name: tmp_path / "nas" / name.lower())
    assert media.shown_as(db, tmp_path / "nas" / "truenas" / "stream") == "\\\\192.168.10.240\\3d_Printing_Elves\\Farmhand\\stream"
    assert media.shown_as(db, tmp_path / "elsewhere" / "stream") is None


def test_which_changes_rewrite_the_settings_copy():
    assert change_hooks._what_changed("/stream-control") is not None
    assert change_hooks._what_changed("/stream-control/schedule") is not None
    assert change_hooks._what_changed("/stream-control/slideshows/Prints") is not None  # a rename: squares follow
    assert change_hooks._what_changed("/stream-control/start-all") is None
    assert change_hooks._what_changed("/stream-control/streams/stream/start") is None
    assert change_hooks._what_changed("/stream-control/pictures") is None
