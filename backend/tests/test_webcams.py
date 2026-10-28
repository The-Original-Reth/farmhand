"""A printer's cameras, as set up in Mainsail, for the Monitor page: whole addresses, and a reason when there are none."""
from __future__ import annotations

import httpx
import pytest

from app.services.moonraker import client as mr_client

from .fake_moonraker import FakeMoonraker


@pytest.fixture()
def moonraker(monkeypatch):
    f = FakeMoonraker()
    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(f.handle))
    return f


def _cam(**kw):
    cam = {"name": "Bed", "enabled": True, "service": "mjpegstreamer", "stream_url": "/webcam/?action=stream",
           "snapshot_url": "/webcam/?action=snapshot", "flip_horizontal": False, "flip_vertical": False, "rotation": 0,
           "aspect_ratio": "4:3"}
    return {**cam, **kw}


def test_a_printers_cameras_with_whole_addresses(api, moonraker):
    pid = api.post("/printers", json={"name": "VT 1190", "wired_ip": "10.0.6.21"}).json()["id"]
    moonraker.webcams = [
        _cam(),
        _cam(name="Nozzle", service="webrtc-camerastreamer", stream_url="http://10.0.6.99/webrtc", snapshot_url="/webcam2/snapshot", rotation=180, flip_horizontal=True, target_fps=10),
        _cam(name="Old", enabled=False),  # turned off in Mainsail: not shown
        _cam(name="Empty", stream_url="", snapshot_url=""),  # nothing to show
    ]
    r = api.get(f"/printers/{pid}/webcams").json()
    assert r["error"] is None
    assert r["webcams"] == [
        {"name": "Bed", "service": "mjpegstreamer", "mjpeg": True, "stream_url": "http://10.0.6.21/webcam/?action=stream",
         "snapshot_url": "http://10.0.6.21/webcam/?action=snapshot", "flip_horizontal": False, "flip_vertical": False,
         "rotation": 0, "aspect_ratio": "4:3", "target_fps": 15},
        {"name": "Nozzle", "service": "webrtc-camerastreamer", "mjpeg": False, "stream_url": "http://10.0.6.99/webrtc",
         "snapshot_url": "http://10.0.6.21/webcam2/snapshot", "flip_horizontal": True, "flip_vertical": False,
         "rotation": 180, "aspect_ratio": "4:3", "target_fps": 10},
    ]


def test_no_cameras_says_why(api, moonraker):
    pid = api.post("/printers", json={"name": "VT 1190", "wired_ip": "10.0.6.21"}).json()["id"]
    assert api.get(f"/printers/{pid}/webcams").json() == {"webcams": [], "error": None}
    moonraker.down = True
    r = api.get(f"/printers/{pid}/webcams").json()
    assert r["webcams"] == [] and "Moonraker" in r["error"]
    nowhere = api.post("/printers", json={"name": "Shelf"}).json()["id"]
    assert "no IP address" in api.get(f"/printers/{nowhere}/webcams").json()["error"]
    core = api.post("/printers", json={"name": "Core One", "connection_type": "prusalink", "wired_ip": "10.0.6.30"}).json()["id"]
    r = api.get(f"/printers/{core}/webcams").json()
    assert r["webcams"] == [] and "camera address" in r["error"]
    assert api.get("/printers/999/webcams").status_code == 404


class FakeGo2rtc:
    """go2rtc's stream API, as far as Farmhand uses it: PUT /api/streams?name=&src="""

    def __init__(self):
        self.streams: dict[str, str] = {}
        self.down = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused")
        assert request.method == "PUT" and request.url.path == "/api/streams"
        self.streams[request.url.params["name"]] = request.url.params["src"]
        return httpx.Response(200)


@pytest.fixture()
def relay(monkeypatch):
    from app.services import go2rtc

    f = FakeGo2rtc()
    monkeypatch.setattr(go2rtc, "transport", httpx.MockTransport(f.handle))
    return f


def test_a_buddy3d_camera_is_played_through_go2rtc(api, relay):
    core = api.post("/printers", json={
        "name": "Core One", "connection_type": "prusalink", "wired_ip": "10.0.6.30", "camera_address": " 192.168.10.131 ",
    }).json()
    assert core["camera_address"] == "192.168.10.131"
    r = api.get(f"/printers/{core['id']}/webcams").json()
    assert r["error"] is None
    assert [(c["service"], c["stream_url"]) for c in r["webcams"]] == [("farmhand-go2rtc", f"/go2rtc/api/ws?src=farmhand_{core['id']}")]
    assert relay.streams == {f"farmhand_{core['id']}": "rtsp://192.168.10.131/live"}  # where a Buddy3D streams

    # a whole rtsp:// address is used as it is; a blank one takes the camera away
    api.patch(f"/printers/{core['id']}", json={"camera_address": "rtsp://cam.local:8554/front"})
    api.get(f"/printers/{core['id']}/webcams")
    assert relay.streams[f"farmhand_{core['id']}"] == "rtsp://cam.local:8554/front"
    assert api.patch(f"/printers/{core['id']}", json={"camera_address": ""}).json()["camera_address"] is None
    assert api.get(f"/printers/{core['id']}/webcams").json()["webcams"] == []


def test_a_camera_address_is_checked(api):
    pid = api.post("/printers", json={"name": "Core One", "connection_type": "prusalink"}).json()["id"]
    for bad in ("http://192.168.10.131", "192.168.10.131/live; rm", "x" * 300, "exec:ffmpeg -i x"):
        assert api.patch(f"/printers/{pid}", json={"camera_address": bad}).status_code == 422, bad


def test_go2rtc_not_answering_says_so(api, relay):
    relay.down = True
    pid = api.post("/printers", json={"name": "Core One", "connection_type": "prusalink", "camera_address": "192.168.10.131"}).json()["id"]
    r = api.get(f"/printers/{pid}/webcams").json()
    assert r["webcams"] == [] and "go2rtc" in r["error"]
