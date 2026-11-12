"""
Going live: every camera through its own feeder, a camera off, going live again after a restart (on the same
YouTube broadcast), the words falling back to names, and never YouTube while being tried out.
"""
from __future__ import annotations

import json

import pytest

from streamer import config, farm, store
from streamer.live_stream import cameras, feeders, runner, stream

from .conftest import wait_until

from .conftest import KEY, grid

pytestmark = pytest.mark.usefixtures("stream_fresh")


# ------------------------------------------------------------------ going live


def test_going_live_reads_every_camera_through_its_own_feeder(api, ffmpeg, farmhand):
    grid(api, [{"camera": "1:Bed"}, {"camera": "2:Camera"}])
    assert api.post("/api/stream/start").status_code == 200
    assert wait_until(lambda: len(ffmpeg.commands) == 1 and len(ffmpeg.feeders) == 2)
    picture = ffmpeg.commands[0]
    assert "http://10.0.6.21/webcam/?action=stream" not in picture  # the picture never connects to a camera
    assert picture.count("image2pipe") == 2 and ffmpeg.senders[0][-1] == f"rtmps://a.rtmps.youtube.com/live2/{KEY}"
    assert wait_until(lambda: [x["state"] for x in api.get("/api/stream").json()["status"]["camera_states"]] == ["live", "live"])
    assert store.store().get(runner.LIVE_KEY) == "1"

    # a new layout: a new picture, the same feeders (no second connection to a camera)
    grid(api, [{"camera": "2:Camera"}, {"camera": "1:Bed"}, None, None], cols=2, rows=2)
    assert wait_until(lambda: len(ffmpeg.commands) == 2)
    assert len(ffmpeg.feeders) == 2 and len(ffmpeg.senders) == 1

    api.post("/api/stream/stop")
    assert store.store().get(runner.LIVE_KEY) is None
    assert wait_until(lambda: all(p.poll() is not None for p in ffmpeg.feeder_procs))


def test_going_live_with_a_camera_off_works_and_its_square_comes_back(api, ffmpeg, farmhand, monkeypatch):
    monkeypatch.setattr(feeders, "DOWN_AFTER", 0.3)
    monkeypatch.setattr(feeders, "RETRY_FIRST", 0.1)
    monkeypatch.setattr(feeders, "RETRY_MOST", 0.2)
    bed = "http://10.0.6.21/webcam/?action=stream"
    ffmpeg.down.add(bed)
    grid(api, [{"camera": "1:Bed"}, {"camera": "2:Camera"}])
    assert api.post("/api/stream/start").status_code == 200

    def states():
        return {x["key"]: x["state"] for x in api.get("/api/stream").json()["status"]["camera_states"]}

    assert wait_until(lambda: states() == {"1:Bed": "down", "2:Camera": "live"})
    assert len(ffmpeg.commands) == 1  # the picture isn't started again for it
    ffmpeg.down.discard(bed)
    assert wait_until(lambda: states() == {"1:Bed": "live", "2:Camera": "live"})
    assert len(ffmpeg.commands) == 1


def test_it_goes_live_again_by_itself_after_a_restart(api, ffmpeg, farmhand, plugin):
    grid(api, [{"camera": "1:Bed"}, None])
    api.post("/api/stream/start")
    assert wait_until(lambda: len(ffmpeg.commands) == 1)
    stream.stop(forget=False)  # the container stopping
    assert plugin.get(runner.LIVE_KEY) == "1"

    farmhand.down = True  # (and Farmhand isn't even up: the cameras as last heard)
    restarted = store.Store(plugin.path)
    store.use(restarted)
    stream.resume(restarted, store.session_factory)
    assert wait_until(lambda: len(ffmpeg.commands) == 2 and stream.status()["live"])
    assert stream.status()["farmhand"] and "Can't reach Farmhand" in stream.status()["farmhand"]
    # Farmhand back (or taking the plugin again, after its address changed): the note goes as soon as it answers
    farmhand.down = False
    assert farm.print_of(1) is not None
    assert stream.status()["live"] and stream.status()["farmhand"] is None


def test_the_words_fall_back_to_the_printers_name_while_farmhand_is_down(api, ffmpeg, farmhand, monkeypatch):
    monkeypatch.setattr(cameras, "STATUS_EVERY", 0.2)
    grid(api, [{"camera": "1:Bed"}, None])
    api.post("/api/stream/start")
    assert wait_until(lambda: len(ffmpeg.commands) == 1)
    graph = ffmpeg.commands[0][ffmpeg.commands[0].index("-filter_complex") + 1]
    words = graph.split("textfile=")[1].split(":reload")[0].replace("\\:", ":")

    def said():
        try:
            return open(words, encoding="utf-8").read()
        except OSError:
            return ""

    assert wait_until(lambda: said() == "VT 1190 · Printing 42% · Frog.gcode")
    farmhand.down = True
    assert wait_until(lambda: said() == "VT 1190")
    assert stream.status()["live"]  # the stream carries on


def test_while_tried_out_the_stream_never_goes_to_youtube(api, ffmpeg, plugin, monkeypatch):
    monkeypatch.setattr(config.settings, "test_destination", "rtmp://127.0.0.1:1935/live")
    plugin.put("youtube_client", json.dumps({"client_id": "x.apps.googleusercontent.com", "client_secret": "secretsecret"}))
    plugin.put("youtube_refresh_token", "1//refresh")  # (signed in: still not YouTube)
    grid(api, [{"camera": "1:Bed"}, None])
    page = api.post("/api/stream/start").json()
    assert page["test_destination"] == "rtmp://127.0.0.1:1935/live"
    assert wait_until(lambda: len(ffmpeg.senders) == 1)
    assert ffmpeg.senders[0][-1] == f"rtmp://127.0.0.1:1935/live/{KEY}"


# ------------------------------------------------------------------ the YouTube broadcast across restarts


def test_going_live_again_carries_on_with_the_broadcast_still_live_on_the_stream(monkeypatch):
    """After the plugin's own restart the broadcast it sent to is still live on YouTube (and goes on once the video is
    back): it's carried on with, not a new one made that would wait "ready" behind it; one that never started is deleted."""
    from streamer import youtube_live
    from streamer.live_stream.broadcast import Broadcast

    calls = []
    listed = {
        "active": [{"id": "other", "contentDetails": {"boundStreamId": "someone-else"}},
                   {"id": "J4aj", "contentDetails": {"boundStreamId": "own"}}],
        "upcoming": [{"id": "aHYU", "contentDetails": {"boundStreamId": "own"}}],
    }

    def api(method, path, token, params, body=None):
        calls.append((method, path, params.get("id") or params.get("broadcastStatus")))
        if method == "GET" and path == "/liveBroadcasts":
            return {"items": listed[params["broadcastStatus"]]}
        if method == "POST" and path == "/liveBroadcasts":
            return {"id": "new"}
        return {}

    monkeypatch.setattr(youtube_live, "_access_token", lambda creds: "token")
    monkeypatch.setattr(youtube_live, "_api", api)
    chosen = {"youtube": {"privacy": "public"}, "title": "Printing", "description": ""}

    b = Broadcast.start({}, {"id": "own"}, chosen)
    assert b.id == "J4aj" and b.status()["watch_url"].endswith("v=J4aj")
    assert ("DELETE", "/liveBroadcasts", "aHYU") in calls and not any(c[:2] == ("POST", "/liveBroadcasts") for c in calls)

    listed["active"], listed["upcoming"] = [], []  # nothing live on it: a new one
    assert Broadcast.start({}, {"id": "own"}, chosen).id == "new"


def test_the_plugin_shutting_down_leaves_the_youtube_broadcast_live():
    """A new image or a reboot stops the container: the broadcast is left live on YouTube, and the plugin carries on with
    it when it's back. Only Stop (and going live afresh) ends it."""
    ended = []

    class Fake:
        def __init__(self, name):
            self.name, self.ended = name, False

        def end(self):
            ended.append(self.name)

    stream._broadcast = Fake("kept")
    stream.stop(forget=False, end_broadcast=False)
    assert ended == [] and stream._broadcast is None
    stream._broadcast = Fake("stopped")
    stream.stop()
    assert ended == ["stopped"]
