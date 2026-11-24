"""
Clips on Stream control: each stream plugin's own clips (its page's /api/clips) asked through Farmhand, for the stream
(the last stretch of what went to its site) or a camera (the next stretch, recorded by the plugin), with the length,
the latest clips to download, and the plugin's own words when it can't.
"""
from __future__ import annotations

import json
from urllib.parse import unquote

import httpx
import pytest

from app import change_hooks
from app.services.plugins import remote

from .test_stream_control import FakeStreams, _fresh, add_stream_plugin, switch  # noqa: F401  (_fresh: autouse)

CLIP = b"\x00\x00\x00\x18ftypmp42" + b"x" * 300_000  # (a few chunks' worth)


class FakeClips(FakeStreams):
    """The stream plugins, with the clips their own page's API keeps (Twitch's from before clips: it has none)."""

    def __init__(self):
        super().__init__()
        self.seconds = 3
        self.held = 0.0
        self.recording: list[dict] = []
        self.files = {"2026-11-17 16-06-05 (4 s).mp4": CLIP}
        self.bodies: list[dict] = []

    def page(self, host: str) -> dict:
        return {
            "seconds": self.seconds, "least": 1, "most": 300, "held": self.held,
            "sources": [{"key": "stream", "label": "Stream"}, {"key": "1:Nozzle", "label": "Voron"}, {"bad": True}],
            "recording": self.recording, "ended": [],
            "folder": {"path": "/clips", "shown_as": r"\\nas\share\YouTube clips", "problem": None},
            "clips": [{"name": n, "size": len(b), "made": "2026-11-18T00:06:05+00:00"} for n, b in self.files.items()],
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if not path.startswith("/api/clips"):
            return super().handle(request)
        self.asked.append(f"{request.method} {host}{path}")
        if host in self.down:
            raise httpx.ConnectError("Connection refused", request=request)
        if host == "twitch":
            return httpx.Response(404, json={"detail": "Not Found"})
        if path == "/api/clips" and request.method == "GET":
            return httpx.Response(200, json=self.page(host))
        if path == "/api/clips" and request.method == "PUT":
            seconds = json.loads(request.content)["seconds"]
            if seconds > 300:
                return httpx.Response(422, json={"detail": "A clip is 1 second to 5 minutes long."})
            self.seconds = seconds
            return httpx.Response(200, json=self.page(host))
        if path == "/api/clips" and request.method == "POST":
            body = json.loads(request.content)
            self.bodies.append(body)
            if body["source"] == "stream":
                if self.held <= 0:
                    return httpx.Response(409, json={"detail": "Nothing has gone to YouTube yet: go live first."})
                name = "2026-11-24 10-00-00 (4 s).mp4"
                self.files = {name: b"new", **self.files}
                return httpx.Response(201, json={"name": name, "seconds": 4.0, "size": 3})
            if any(r["source"] == body["source"] for r in self.recording):
                return httpx.Response(409, json={"detail": "Voron is being recorded already."})
            job = {"source": body["source"], "label": "Voron", "until": 1e10}
            self.recording.append(job)
            return httpx.Response(202, json={"recording": job})
        name = path.rsplit("/", 1)[1]
        name = unquote(name)
        if name in self.files:
            return httpx.Response(200, content=self.files[name], headers={"content-type": "video/mp4"})
        return httpx.Response(404, json={"detail": "No such clip."})


@pytest.fixture
def fake(api):
    f = FakeClips()
    remote.transport = httpx.MockTransport(f.handle)
    switch(api)
    add_stream_plugin(api, "stream", "YouTube")
    add_stream_plugin(api, "twitch", "Twitch")
    return f


def test_a_stream_plugin_s_clips_are_shown_as_it_keeps_them(api, fake):
    r = api.get("/stream-control/streams/stream/clips")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["plugin"] == "stream" and got["site"] == "YouTube"
    assert (got["seconds"], got["least"], got["most"], got["held"]) == (3, 1, 300, 0.0)
    assert got["sources"] == [{"key": "stream", "label": "Stream"}, {"key": "1:Nozzle", "label": "Voron"}]  # (one without a key left out)
    assert got["folder"] == {"path": "/clips", "shown_as": r"\\nas\share\YouTube clips", "problem": None}
    assert got["clips"] == [{"name": "2026-11-17 16-06-05 (4 s).mp4", "size": len(CLIP), "made": "2026-11-18T00:06:05+00:00"}]


def test_the_stream_is_clipped_once_it_has_gone_out(api, fake):
    r = api.post("/stream-control/streams/stream/clips", json={"source": "stream", "tz": "America/Los_Angeles"})
    assert r.status_code == 422 and r.json()["detail"] == "Nothing has gone to YouTube yet: go live first."

    fake.held = 120.0
    r = api.post("/stream-control/streams/stream/clips", json={"source": "stream", "tz": "America/Los_Angeles"})
    assert r.status_code == 201, r.text
    assert r.json()["saved"] == {"name": "2026-11-24 10-00-00 (4 s).mp4", "seconds": 4.0, "size": 3}
    assert r.json()["clips"]["clips"][0]["name"] == "2026-11-24 10-00-00 (4 s).mp4"
    assert fake.bodies[-1] == {"source": "stream", "tz": "America/Los_Angeles"}  # (the length as set on the plugin)


def test_a_camera_is_recorded_by_the_plugin_once_at_a_time(api, fake):
    r = api.post("/stream-control/streams/stream/clips", json={"source": "1:Nozzle", "seconds": 30})
    assert r.status_code == 201, r.text
    assert r.json()["recording"]["source"] == "1:Nozzle" and r.json()["recording"]["label"] == "Voron"
    assert r.json()["clips"]["recording"][0]["until"] == 1e10
    assert fake.bodies[-1]["seconds"] == 30
    r = api.post("/stream-control/streams/stream/clips", json={"source": "1:Nozzle"})
    assert r.status_code == 422 and r.json()["detail"] == "Voron is being recorded already."


def test_the_length_is_kept_by_the_plugin_which_checks_it(api, fake):
    r = api.put("/stream-control/streams/stream/clips", json={"seconds": 45})
    assert r.status_code == 200 and r.json()["seconds"] == 45 and fake.seconds == 45
    r = api.put("/stream-control/streams/stream/clips", json={"seconds": 600})
    assert r.status_code == 422 and r.json()["detail"] == "A clip is 1 second to 5 minutes long."
    assert api.put("/stream-control/streams/stream/clips", json={"seconds": 0}).status_code == 422


def test_a_clip_is_downloaded_through_farmhand(api, fake):
    r = api.get("/stream-control/streams/stream/clips/2026-11-17 16-06-05 (4 s).mp4")
    assert r.status_code == 200
    assert r.content == CLIP and r.headers["content-type"] == "video/mp4"
    assert "attachment" in r.headers["content-disposition"]
    r = api.get("/stream-control/streams/stream/clips/gone.mp4")
    assert r.status_code == 404 and "hasn't got a clip called" in r.json()["detail"]


def test_a_plugin_without_clips_or_away_or_left_out_says_so(api, fake):
    r = api.get("/stream-control/streams/twitch/clips")
    assert r.status_code == 422 and r.json()["detail"] == "Twitch's stream plugin doesn't take clips. Update it to a version that does."

    fake.down.add("stream")
    r = api.get("/stream-control/streams/stream/clips")
    assert r.status_code == 422 and r.json()["detail"].startswith("YouTube: ")
    fake.down.clear()

    api.put("/stream-control/streams", json={"chosen": ["twitch"]})
    fake.asked.clear()
    r = api.get("/stream-control/streams/stream/clips")
    assert r.status_code == 422 and "isn't brought into Stream control" in r.json()["detail"]
    assert not fake.asked  # (not asked at all)
    assert api.get("/stream-control/streams/nobody/clips").status_code == 404


def test_clips_stay_out_of_the_settings_copy_and_go_with_stream_control(api, fake):
    assert change_hooks._what_changed("/stream-control/streams/stream/clips") is None
    switch(api, on=False)
    assert api.get("/stream-control/streams/stream/clips").status_code == 404
