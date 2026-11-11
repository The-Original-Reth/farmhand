"""
The Stream plugin: what it adds to the engine copied from Farmhand. Its settings in its own store (secrets never
answered), cameras from the plugin API (remembered for when Farmhand is down), a feeder per camera and the picture fed
from steady pipes ("Camera down" squares), going live again after a restart, the words falling back to names, the
one-off move of Farmhand's settings, and never YouTube while being tried out.
"""
from __future__ import annotations

import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

from streamer import config, farm, layouts, migrate, store
from streamer.app import app
from streamer.live_stream import feeders, runner, stream
import importlib
sources_module = importlib.import_module("streamer.live_stream.sources")
from streamer.live_stream.constants import SETTINGS_KEY, STREAM_KEY_KEY

from .conftest import wait_until
from .fake_ffmpeg import jpeg

pytestmark = pytest.mark.usefixtures("stream_fresh")
KEY = "farmtest-key"


@pytest.fixture()
def api(plugin):
    return TestClient(app)


def _grid(api, cells, cols=2, rows=1):
    r = api.put("/api/stream", json={"stream_key": KEY, "cols": cols, "rows": rows, "cells": cells})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ settings, kept by the plugin


def test_settings_live_in_the_plugins_own_store_and_secrets_never_come_back(api, plugin):
    page = _grid(api, [{"camera": "1:Bed"}, None])
    assert page["settings"]["key_set"] is True and KEY not in json.dumps(page)
    saved = json.loads(plugin.path.read_text(encoding="utf-8"))
    assert saved[STREAM_KEY_KEY] == KEY and json.loads(saved[SETTINGS_KEY])["cols"] == 2
    if sys.platform != "win32":
        assert oct(os.stat(plugin.path).st_mode & 0o777) == "0o600"  # only the plugin reads its key
    again = store.Store(plugin.path)  # (the plugin started again)
    assert again.get(STREAM_KEY_KEY) == KEY
    assert api.put("/api/stream", json={"clear_key": True}).json()["settings"]["key_set"] is False


def test_saved_layouts_are_kept_by_the_plugin(api):
    r = api.put("/api/layouts", json={"layouts": [{"name": "Morning", "cols": 1, "rows": 1, "cells": [{"camera": "1:Bed"}]}, "junk"]})
    assert r.status_code == 200 and [x["name"] for x in r.json()["layouts"]] == ["Morning"]
    assert api.get("/api/layouts").json()["layouts"][0]["cells"][0]["camera"] == "1:Bed"


def test_the_stream_folder_is_the_folder_the_container_is_given(api, plugin, tmp_path, monkeypatch):
    r = api.post("/api/stream/pictures", files={"files": ("logo.png", b"\x89PNG fake", "image/png")})
    assert r.status_code == 201 and r.json()["media"]["images"] == ["logo.png"]
    assert (tmp_path / "media" / "images" / "logo.png").is_file()
    monkeypatch.setattr(config.settings, "media_dir", tmp_path / "not-mounted")
    from streamer import stream_media
    stream_media.forget()
    r = api.post("/api/stream/pictures", files={"files": ("logo.png", b"x", "image/png")})
    assert r.status_code == 503 and "isn't there" in r.json()["detail"]


# ------------------------------------------------------------------ cameras, from the plugin API


def test_cameras_come_from_farmhand_and_are_remembered_for_when_it_is_down(plugin, farmhand):
    known, error = farm.cameras(plugin)
    assert error is None and known["1"]["cameras"][0]["name"] == "Bed"
    srcs = sources_module.sources(plugin, ["1:Bed", "2:Camera"], known)
    assert srcs[0].label == "VT 1190" and srcs[0].input_args[-1] == "http://10.0.6.21/webcam/?action=stream"
    assert srcs[1].label == "Core One · Camera"  # (two cameras: named)
    with pytest.raises(ValueError, match="WebRTC"):
        sources_module.sources(plugin, ["2:Nozzle"], known)
    with pytest.raises(ValueError, match="gone"):
        sources_module.sources(plugin, ["9:Bed"], known)

    # a printer that's off: its cameras as last heard
    farmhand.cameras[1] = {"printer_id": 1, "printer_name": "VT 1190", "error": "Moonraker didn't answer.", "cameras": []}
    known, _ = farm.cameras(plugin)
    assert sources_module.sources(plugin, ["1:Bed"], known)[0].input_args[-1].startswith("http://10.0.6.21")
    # Farmhand down: everything as last heard
    farmhand.down = True
    known, error = farm.cameras(plugin)
    assert error and "Can't reach Farmhand" in error
    assert sources_module.sources(plugin, ["2:Camera"], known)[0].input_args


def test_a_camera_never_heard_of_whose_printer_is_off_is_a_down_square(plugin, farmhand):
    farmhand.cameras[1] = {"printer_id": 1, "printer_name": "VT 1190", "error": "Moonraker didn't answer.", "cameras": []}
    known, _ = farm.cameras(plugin)
    src = sources_module.sources(plugin, ["1:Bed"], known)[0]
    assert src.input_args == [] and src.name == "VT 1190"


# ------------------------------------------------------------------ feeders and pumps


def test_frames_are_cut_from_what_a_feeder_puts_out():
    a, b = jpeg((255, 0, 0)), jpeg((0, 0, 255), (32, 24))
    buffer = bytearray(a + b + b[:10])
    assert feeders.frames_in(buffer) == [a, b] and bytes(buffer) == b[:10]
    assert feeders.jpeg_size(a) == (64, 48) and feeders.jpeg_size(b) == (32, 24)
    assert feeders.fit("4:3", 1280, 720) == (960, 720) and feeders.fit("16:9", 1280, 720) == (1280, 720)
    assert feeders.fit("16:9", 1280, 720, turned=True) == (404, 720)


def test_the_camera_down_square_is_drawn_at_the_cameras_size():
    frame = feeders.down_frame((320, 240), "#112233", "/no/such/font.ttf", "#FFFFFF", "VT 1190")
    assert frame[:2] == b"\xff\xd8" and feeders.jpeg_size(frame) == (320, 240)
    downs = feeders.DownFrames("#112233", "/no/such/font.ttf", "#FFFFFF", "VT 1190")
    assert downs.at((64, 48)) is downs.at((64, 48))


def test_a_feeder_keeps_the_latest_frame_and_says_when_its_camera_is_down(ffmpeg, monkeypatch):
    monkeypatch.setattr(feeders, "DOWN_AFTER", 0.3)
    monkeypatch.setattr(feeders, "RETRY_FIRST", 0.1)
    monkeypatch.setattr(feeders, "RETRY_MOST", 0.2)
    url = "http://10.0.6.21/webcam/?action=stream"
    f = feeders.Feeder("ffmpeg", "1:Bed", ["-f", "mpjpeg", "-i", url], ["transpose=1"], (1280, 720), ffmpeg, aspect="4:3").start()
    try:
        assert wait_until(lambda: f.state()["state"] == "live")
        assert "transpose=1" in ffmpeg.feeders[0][ffmpeg.feeders[0].index("-vf") + 1]
        assert f.guess == (540, 720)  # (4:3, turned on its side)
        ffmpeg.down.add(url)
        assert wait_until(lambda: f.state()["state"] == "down")
        assert f.latest()[0] is None and f.latest()[1] == (64, 48)  # (its size, for its "Camera down" square)
        tries = len(ffmpeg.feeders)
        assert wait_until(lambda: len(ffmpeg.feeders) > tries + 1)  # started again, and again
        ffmpeg.down.discard(url)
        assert wait_until(lambda: f.state()["state"] == "live")  # back by itself
    finally:
        f.stop()


def test_a_pump_writes_the_latest_frame_or_camera_down_steadily(ffmpeg, tmp_path, monkeypatch):
    monkeypatch.setattr(feeders, "DOWN_AFTER", 0.3)
    f = feeders.Feeder("ffmpeg", "1:Bed", [], [], (1280, 720), ffmpeg, aspect="16:9")  # no address: always down
    downs = feeders.DownFrames("#000000", "/no/font.ttf", "#FFFFFF", "VT 1190")
    pump = feeders.Pump([(f, downs)], [str(tmp_path / "cam.mjpeg")])
    assert feeders.jpeg_size(pump.frame_for(f, downs)) == (1280, 720)
    pump.start()
    try:
        assert wait_until(lambda: (tmp_path / "cam.mjpeg").stat().st_size > 3 * len(downs.at((1280, 720))))
    finally:
        pump.stop()


# ------------------------------------------------------------------ going live


def test_going_live_reads_every_camera_through_its_own_feeder(api, ffmpeg, farmhand):
    _grid(api, [{"camera": "1:Bed"}, {"camera": "2:Camera"}])
    assert api.post("/api/stream/start").status_code == 200
    assert wait_until(lambda: len(ffmpeg.commands) == 1 and len(ffmpeg.feeders) == 2)
    picture = ffmpeg.commands[0]
    assert "http://10.0.6.21/webcam/?action=stream" not in picture  # the picture never connects to a camera
    assert picture.count("image2pipe") == 2 and ffmpeg.senders[0][-1] == f"rtmps://a.rtmps.youtube.com/live2/{KEY}"
    assert wait_until(lambda: [x["state"] for x in api.get("/api/stream").json()["status"]["camera_states"]] == ["live", "live"])
    assert store.store().get(runner.LIVE_KEY) == "1"

    # a new layout: a new picture, the same feeders (no second connection to a camera)
    _grid(api, [{"camera": "2:Camera"}, {"camera": "1:Bed"}, None, None], cols=2, rows=2)
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
    _grid(api, [{"camera": "1:Bed"}, {"camera": "2:Camera"}])
    assert api.post("/api/stream/start").status_code == 200

    def states():
        return {x["key"]: x["state"] for x in api.get("/api/stream").json()["status"]["camera_states"]}

    assert wait_until(lambda: states() == {"1:Bed": "down", "2:Camera": "live"})
    assert len(ffmpeg.commands) == 1  # the picture isn't started again for it
    ffmpeg.down.discard(bed)
    assert wait_until(lambda: states() == {"1:Bed": "live", "2:Camera": "live"})
    assert len(ffmpeg.commands) == 1


def test_it_goes_live_again_by_itself_after_a_restart(api, ffmpeg, farmhand, plugin):
    _grid(api, [{"camera": "1:Bed"}, None])
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


def test_the_words_fall_back_to_the_printers_name_while_farmhand_is_down(api, ffmpeg, farmhand, monkeypatch):
    monkeypatch.setattr(runner, "STATUS_EVERY", 0.2)
    _grid(api, [{"camera": "1:Bed"}, None])
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
    _grid(api, [{"camera": "1:Bed"}, None])
    page = api.post("/api/stream/start").json()
    assert page["test_destination"] == "rtmp://127.0.0.1:1935/live"
    assert wait_until(lambda: len(ffmpeg.senders) == 1)
    assert ffmpeg.senders[0][-1] == f"rtmp://127.0.0.1:1935/live/{KEY}"


# ------------------------------------------------------------------ Farmhand's settings, brought over once


def test_farmhands_stream_settings_are_brought_over_once(api, plugin, farmhand):
    assert api.get("/api/migrate").json() == {"done": None, "own_settings": False}
    r = api.post("/api/migrate", json={})
    assert r.status_code == 200 and r.json()["done"]["stream_folder"] == "/data/nas/farmhand/stream"
    page = api.get("/api/stream").json()
    assert page["settings"]["title"] == "The farm" and page["settings"]["key_set"] is True
    assert page["youtube"]["signed_in"] is True and page["youtube"]["client_id"] == "123-abc.apps.googleusercontent.com"
    assert "GOCSPX-secret" not in json.dumps(page) and "1//refresh" not in json.dumps(page) and "abcd-efgh" not in json.dumps(page)
    assert [x["name"] for x in layouts.layouts(plugin)] == ["Morning"]
    # settings of its own now: not over them unless asked, and Farmhand hands over only once
    assert "settings of its own" in api.post("/api/migrate", json={}).json()["detail"]
    assert "only once" in api.post("/api/migrate", json={"replace": True}).json()["detail"]


def test_at_first_start_it_brings_them_over_only_with_the_permission(plugin, farmhand):
    farmhand.permissions.discard("stream:migrate")
    migrate.at_start(plugin)
    assert wait_until(lambda: "/plugin-api/v1/me" in farmhand.calls)
    assert not any(c.startswith("POST") for c in farmhand.calls)
    farmhand.permissions.add("stream:migrate")
    migrate.at_start(plugin)
    assert wait_until(lambda: plugin.get(migrate.MIGRATED_KEY) is not None)
    assert plugin.get(STREAM_KEY_KEY) == "abcd-efgh-ijkl"


# ------------------------------------------------------------------ what Farmhand asks of a plugin


def test_manifest_and_health(api, farmhand):
    m = api.get("/manifest").json()
    assert m["id"] == "stream" and set(m["permissions"]) == {"cameras:read", "prints:read", "stream:migrate"}
    assert api.get("/health").text == "ok"
    farm.cameras(store.store())
    config.settings.farmhand_token = "wrong"
    try:
        farm.cameras(store.store())
        r = api.get("/health")
        assert r.status_code == 503 and "refused this plugin's token" in r.text
    finally:
        from .fake_farmhand import TOKEN
        config.settings.farmhand_token = TOKEN
