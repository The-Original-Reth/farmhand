"""
The Stream plugin's cameras: from the plugin API (remembered for when Farmhand is down), each read by its own feeder,
the picture fed from steady pipes ("Camera down" squares), and the preview's pictures before going live.
"""
from __future__ import annotations

import importlib

import pytest

from streamer import farm
from streamer.live_stream import feeders, pacing, procs

# (the module itself: the package's own `sources` is the function of that name)
sources_module = importlib.import_module("streamer.live_stream.sources")

from .conftest import wait_until
from .fake_ffmpeg import jpeg

pytestmark = pytest.mark.usefixtures("stream_fresh")


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


def test_time_a_writer_was_held_up_is_made_up_once_its_reader_is_reading():
    step, slept = 1 / 15, []
    reading = int(pacing.STEADY_AFTER / step) + 1  # steps written: its reader has been reading
    # early: wait for it
    assert pacing.pace(10.0, reading, step, 9.9, slept.append) == 10.0 and slept == [pytest.approx(0.1)]
    # reading, then held up 5 s: carry on from where it was (no waiting) until caught up
    assert pacing.pace(10.0, reading, step, 15.0, slept.append) == 10.0 and len(slept) == 1
    # held up before it was reading (a new picture opening its inputs): that time is let go
    assert pacing.pace(10.0, 3, step, 15.0, slept.append) == 15.0
    # a moment behind before then is still made up
    assert pacing.pace(10.0, 3, step, 10.5, slept.append) == 10.0
    # held up for longer than is ever made up: a real gap
    assert pacing.pace(10.0, reading, step, 10.0 + pacing.CATCH_UP_MOST + 1, slept.append) == pytest.approx(131.0)


# ------------------------------------------------------------------ the preview before going live


def test_a_camera_without_a_working_snapshot_is_previewed_from_its_video(api, plugin, farmhand, monkeypatch):
    """An RTSP camera has no snapshot address, and one moved to go2rtc can keep a snapshot address that answers 502:
    before going live, the preview takes a frame from its video instead, kept a few seconds so the page's asks (twice a
    second) don't each open a connection to the camera."""
    import streamer.page_routes as app_module

    taken = []

    def take(args):
        taken.append(args)
        return jpeg()

    monkeypatch.setattr(procs, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(app_module, "take_frame", take)
    monkeypatch.setattr(app_module, "_frames", {})
    farmhand.cameras[1]["cameras"][0]["snapshot_url"] = "http://127.0.0.1:9/webcam/?action=snapshot"  # (nothing there)
    farm.cameras(plugin)

    r = api.get("/api/cameras/1/Bed/picture")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content == jpeg()
    assert taken[0][taken[0].index("-i") + 1] == "http://10.0.6.21/webcam/?action=stream" and "-frames:v" in taken[0]
    assert api.get("/api/cameras/1/Bed/picture").status_code == 200 and len(taken) == 1  # the same frame, kept

    monkeypatch.setattr(app_module, "VIDEO_FRAME_SECONDS", 0)
    def fails(args):
        raise RuntimeError("Connection refused")
    monkeypatch.setattr(app_module, "take_frame", fails)
    r = api.get("/api/cameras/1/Bed/picture")
    assert r.status_code == 502 and "Connection refused" in r.json()["detail"]
    assert api.get("/api/cameras/2/Nobody/picture").status_code == 404  # (two cameras: no guessing which)
    assert api.get("/api/cameras/1/Front/picture").status_code == 502  # a printer's only camera, renamed: followed


def test_preview_pictures_come_turned_as_the_stream_turns_them(api, plugin, farmhand, monkeypatch):
    """The page shows each picture as it comes (a feeder's frame is turned already), so a snapshot or a frame taken
    from the video is turned here the way Mainsail shows the camera: never twice, never not at all."""
    import io as _io

    from PIL import Image

    import streamer.page_routes as app_module

    # a picture red on its left half and blue on its right: flipped both ways, the blue is on the left
    im = Image.new("RGB", (40, 20), (220, 0, 0))
    im.paste((0, 0, 220), (20, 0, 40, 20))
    raw = _io.BytesIO()
    im.save(raw, "JPEG")
    out = Image.open(_io.BytesIO(app_module.turned(raw.getvalue(), ["hflip", "vflip"])))
    assert out.size == (40, 20) and out.getpixel((5, 10))[2] > 150 and out.getpixel((35, 10))[0] > 150
    assert Image.open(_io.BytesIO(app_module.turned(raw.getvalue(), ["transpose=1"]))).size == (20, 40)
    assert app_module.turned(raw.getvalue(), []) == raw.getvalue()
    assert app_module.turned(b"not a picture", ["hflip"]) == b"not a picture"

    taken = []
    monkeypatch.setattr(procs, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(app_module, "take_frame", lambda args: taken.append(args) or jpeg())
    monkeypatch.setattr(app_module, "_frames", {})
    farmhand.cameras[1]["cameras"][0]["ffmpeg_filters"] = ["hflip", "vflip"]
    farm.cameras(plugin)
    assert api.get("/api/cameras/1/Bed/picture").status_code == 200
    assert taken[0][taken[0].index("-vf") + 1] == "hflip,vflip"
