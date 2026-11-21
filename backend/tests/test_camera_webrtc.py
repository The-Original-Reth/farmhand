"""A camera-streamer WebRTC camera's set-up, passed on through Farmhand's API (a Snapmaker U1's won't take it from
Farmhand's page itself)."""
from __future__ import annotations

import pytest

from app.services import camera_webrtc


@pytest.fixture(autouse=True)
def _forget_cameras():
    camera_webrtc._found.clear()
    yield
    camera_webrtc._found.clear()


def _cam(**kw):
    cam = {"name": "case", "enabled": True, "service": "webrtc-camerastreamer", "stream_url": "/webcam/webrtc",
           "snapshot_url": "/webcam/snapshot.jpg", "flip_horizontal": False, "flip_vertical": False, "rotation": 0}
    return {**cam, **kw}


def test_the_set_up_goes_to_the_camera_and_its_answer_comes_back(klipper, moonraker):
    c, pid = klipper
    moonraker.webcams = [_cam()]
    cam = c.get(f"/printers/{pid}/webcams").json()["webcams"][0]
    assert cam["signal_url"] == f"/printers/{pid}/webcams/webrtc?name=case"

    offer = c.post(cam["signal_url"], json={"type": "request", "res": None})
    assert offer.status_code == 200 and offer.json()["id"] == "3" and offer.json()["type"] == "offer"
    candidate = {"type": "remote_candidate", "id": "3", "candidates": [{"candidate": "candidate:1 1 UDP 1 10.0.6.5 5000 typ host"}]}
    assert c.post(cam["signal_url"], json=candidate).json() == {}  # the camera sends nothing back
    assert c.post(cam["signal_url"], json={"type": "answer", "id": "3", "sdp": "v=0"}).status_code == 200
    assert [m["type"] for m in moonraker.webrtc_asked] == ["request", "remote_candidate", "answer"]
    assert moonraker.webrtc_asked[1] == candidate  # passed on as it came


def test_only_a_camera_streamer_camera_the_printer_lists_can_be_reached(klipper, moonraker):
    c, pid = klipper
    moonraker.webcams = [_cam(), _cam(name="Bed", service="mjpegstreamer", stream_url="/webcam/?action=stream")]
    assert "signal_url" not in c.get(f"/printers/{pid}/webcams").json()["webcams"][1]
    for name in ("Bed", "elsewhere"):
        r = c.post(f"/printers/{pid}/webcams/webrtc", params={"name": name}, json={"type": "request"})
        assert r.status_code == 404 and "no WebRTC (camera-streamer) camera" in r.json()["detail"]
    assert moonraker.webrtc_asked == []
    assert c.post(f"/printers/{pid}/webcams/webrtc", params={"name": "case"}, content=b"not json").status_code == 422


def test_a_camera_that_cant_be_reached_says_so(klipper, moonraker):
    c, pid = klipper
    moonraker.webcams = [_cam()]
    c.post(f"/printers/{pid}/webcams/webrtc", params={"name": "case"}, json={"type": "request"}).raise_for_status()
    moonraker.down = True
    r = c.post(f"/printers/{pid}/webcams/webrtc", params={"name": "case"}, json={"type": "request"})
    assert r.status_code == 502 and "can't be reached" in r.json()["detail"]
