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
        _cam(name="Nozzle", service="webrtc-camerastreamer", stream_url="http://10.0.6.99/webrtc", snapshot_url="/webcam2/snapshot", rotation=180, flip_horizontal=True),
        _cam(name="Old", enabled=False),  # turned off in Mainsail: not shown
        _cam(name="Empty", stream_url="", snapshot_url=""),  # nothing to show
    ]
    r = api.get(f"/printers/{pid}/webcams").json()
    assert r["error"] is None
    assert r["webcams"] == [
        {"name": "Bed", "service": "mjpegstreamer", "mjpeg": True, "stream_url": "http://10.0.6.21/webcam/?action=stream",
         "snapshot_url": "http://10.0.6.21/webcam/?action=snapshot", "flip_horizontal": False, "flip_vertical": False,
         "rotation": 0, "aspect_ratio": "4:3"},
        {"name": "Nozzle", "service": "webrtc-camerastreamer", "mjpeg": False, "stream_url": "http://10.0.6.99/webrtc",
         "snapshot_url": "http://10.0.6.21/webcam2/snapshot", "flip_horizontal": True, "flip_vertical": False,
         "rotation": 180, "aspect_ratio": "4:3"},
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
    assert api.get(f"/printers/{core}/webcams").json() == {"webcams": [], "error": "PrusaLink doesn't share a camera feed"}
    assert api.get("/printers/999/webcams").status_code == 404
