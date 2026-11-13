"""A printer's cameras, as set up in Mainsail, for the Monitor page: whole addresses, and a reason when there are none."""
from __future__ import annotations

import httpx
import pytest

from app.services.moonraker import client as mr_client


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
    assert api.get(f"/printers/{pid}/webcams").json() == {"webcams": [], "error": None, "board": {"name": "Pi 4", "model": "Raspberry Pi 4 Model B Rev 1.5", "memory_gb": 4}}
    moonraker.down = True
    r = api.get(f"/printers/{pid}/webcams").json()
    assert r["webcams"] == [] and "Moonraker" in r["error"]
    nowhere = api.post("/printers", json={"name": "Shelf"}).json()["id"]
    assert "no IP address" in api.get(f"/printers/{nowhere}/webcams").json()["error"]
    core = api.post("/printers", json={"name": "Core One", "connection_type": "prusalink", "wired_ip": "10.0.6.30"}).json()["id"]
    r = api.get(f"/printers/{core}/webcams").json()
    assert r["webcams"] == [] and "camera address" in r["error"]
    assert api.get("/printers/999/webcams").status_code == 404


def test_the_board_a_printer_runs_on(api, moonraker):
    pid = api.post("/printers", json={"name": "V2Blue", "wired_ip": "10.0.6.21"}).json()["id"]
    moonraker.cpu_info = {"model": "Raspberry Pi Compute Module 4 Rev 1.1", "total_memory": 927824, "memory_units": "kB"}
    assert api.get(f"/printers/{pid}/webcams").json()["board"] == {"name": "CM4", "model": "Raspberry Pi Compute Module 4 Rev 1.1", "memory_gb": 1}
    moonraker.cpu_info = {"model": "", "processor": "x86_64", "total_memory": 8000000, "memory_units": "kB"}  # a PC
    assert api.get(f"/printers/{pid}/webcams").json()["board"]["name"] == "x86_64"
    moonraker.cpu_info = None  # won't say: no board, and the cameras all the same
    assert api.get(f"/printers/{pid}/webcams").json() == {"webcams": [], "error": None, "board": None}
    moonraker.down = True  # not reached: no board, and it isn't asked a second time
    asked = len(moonraker.requests)
    assert api.get(f"/printers/{pid}/webcams").json()["board"] is None
    assert len(moonraker.requests) == asked


@pytest.mark.parametrize("model, name", [
    ("Raspberry Pi 4 Model B Rev 1.5", "Pi 4"), ("Raspberry Pi 5 Model B Rev 1.0", "Pi 5"),
    ("Raspberry Pi Compute Module 4 Rev 1.1", "CM4"), ("Raspberry Pi Compute Module 5 Rev 1.0", "CM5"),
    ("Raspberry Pi 3 Model B Plus Rev 1.3", "Pi 3"), ("Raspberry Pi Zero 2 W Rev 1.0", "Pi Zero 2 W"),
    ("BigTreeTech CB1 Rev 1.0", "BigTreeTech CB1"), ("", None),
])
def test_board_names(model, name):
    assert mr_client.board_name(model) == name


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


# ------------------------------------------------------------------ go2rtc on the printer, found by itself


GO2RTC_LINE = "exec:ffmpeg -f v4l2 -input_format mjpeg -video_size 1280x720 -framerate 15 -i /dev/video0 -c:v h264_v4l2m2m -f h264 -"


def _go2rtc_cam(host, src, **kw):
    return {"service": "webrtc-go2rtc", "mjpeg": False, "stream_url": f"http://{host}:1984/stream.html?src={src}&mode=webrtc",
            "snapshot_url": f"http://{host}:1984/api/frame.jpeg?src={src}", "found": "go2rtc", **kw}


def test_a_camera_moved_from_crowsnest_to_go2rtc_is_played_from_go2rtc(api, moonraker, printer_go2rtc):
    """Crowsnest stopped and go2rtc running on the printer, with Mainsail still listing Crowsnest's camera: Farmhand
    plays it from go2rtc, under the name (and turned the way) Mainsail has it, without Mainsail being changed."""
    pid = api.post("/printers", json={"name": "VT 1026", "wired_ip": "10.0.6.21"}).json()["id"]
    moonraker.webcams = [_cam(name="Front", service="mjpegstreamer-adaptive", flip_horizontal=True, target_fps=10)]
    printer_go2rtc.streams = {"chamber": GO2RTC_LINE}

    # Crowsnest running: Mainsail's camera as it is, and go2rtc isn't asked
    assert api.get(f"/printers/{pid}/webcams").json()["webcams"][0]["service"] == "mjpegstreamer-adaptive"
    assert printer_go2rtc.asked == []

    moonraker.services["crowsnest"] = "inactive"
    [cam] = api.get(f"/printers/{pid}/webcams").json()["webcams"]
    assert cam == {"name": "Front", "flip_horizontal": True, "flip_vertical": False, "rotation": 0, "aspect_ratio": "4:3",
                   "target_fps": 10, **_go2rtc_cam("10.0.6.21", "chamber")}

    # what plugins are given to read it with: go2rtc's RTSP, under the same name
    from app.models import Printer
    from app.services import camera_streams
    address = camera_streams.stream_address(Printer(name="VT 1026"), cam)
    assert (address.kind, address.url) == ("rtsp", "rtsp://10.0.6.21:8554/chamber")


def test_go2rtc_is_only_used_when_it_has_streams(api, moonraker, printer_go2rtc):
    pid = api.post("/printers", json={"name": "VT 1026", "wired_ip": "10.0.6.21"}).json()["id"]
    moonraker.webcams = [_cam(name="Front", service="mjpegstreamer-adaptive")]
    moonraker.services["crowsnest"] = "inactive"
    printer_go2rtc.down = True  # Crowsnest stopped, no go2rtc: Mainsail's camera as it is (it says why it's blank)
    assert api.get(f"/printers/{pid}/webcams").json()["webcams"][0]["service"] == "mjpegstreamer-adaptive"
    printer_go2rtc.down = False  # go2rtc there, but with no streams
    assert api.get(f"/printers/{pid}/webcams").json()["webcams"][0]["service"] == "mjpegstreamer-adaptive"


def test_a_camera_already_on_go2rtc_or_crowsnest_unknown_is_left_as_mainsail_has_it(api, moonraker, printer_go2rtc):
    pid = api.post("/printers", json={"name": "V2-250B", "wired_ip": "10.0.6.21"}).json()["id"]
    printer_go2rtc.streams = {"chamber": GO2RTC_LINE}
    moonraker.services = {"klipper": "active", "moonraker": "active", "crowsnest": "inactive"}
    set_up = _cam(name="Chamber", service="webrtc-go2rtc", stream_url="http://10.0.6.21:1984/stream.html?src=chamber&mode=webrtc",
                  snapshot_url="http://10.0.6.21:1984/api/frame.jpeg?src=chamber")
    moonraker.webcams = [set_up]
    [cam] = api.get(f"/printers/{pid}/webcams").json()["webcams"]
    assert cam["service"] == "webrtc-go2rtc" and "found" not in cam and printer_go2rtc.asked == []

    # Moonraker not watching Crowsnest: whether it runs isn't known, so nothing is guessed
    moonraker.services = {"klipper": "active", "moonraker": "active"}
    moonraker.webcams = [_cam(name="Front", service="mjpegstreamer-adaptive")]
    assert api.get(f"/printers/{pid}/webcams").json()["webcams"][0]["service"] == "mjpegstreamer-adaptive"
    assert printer_go2rtc.asked == []


def test_go2rtc_streams_are_matched_by_name_then_in_order(api, moonraker, printer_go2rtc):
    pid = api.post("/printers", json={"name": "VT 1190", "wired_ip": "10.0.6.21"}).json()["id"]
    moonraker.services["crowsnest"] = "inactive"
    moonraker.webcams = [_cam(name="Bed"), _cam(name="Nozzle", stream_url="/webcam2/?action=stream", snapshot_url="/webcam2/?action=snapshot")]
    printer_go2rtc.streams = {"top": GO2RTC_LINE, "nozzle": GO2RTC_LINE}
    bed, nozzle = api.get(f"/printers/{pid}/webcams").json()["webcams"]
    assert (bed["name"], bed["stream_url"]) == ("Bed", "http://10.0.6.21:1984/stream.html?src=top&mode=webrtc")
    assert (nozzle["name"], nozzle["stream_url"]) == ("Nozzle", "http://10.0.6.21:1984/stream.html?src=nozzle&mode=webrtc")

    # more Crowsnest cameras than streams: the one left over stays as Mainsail has it
    printer_go2rtc.streams = {"nozzle": GO2RTC_LINE}
    bed, nozzle = api.get(f"/printers/{pid}/webcams").json()["webcams"]
    assert bed["service"] == "mjpegstreamer" and nozzle["service"] == "webrtc-go2rtc"


def test_a_printer_with_no_camera_in_mainsail_gets_its_go2rtc_streams(api, moonraker, printer_go2rtc):
    pid = api.post("/printers", json={"name": "BOG", "wired_ip": "10.0.6.21"}).json()["id"]
    moonraker.services["crowsnest"] = "inactive"
    printer_go2rtc.streams = {"chamber": GO2RTC_LINE}
    [cam] = api.get(f"/printers/{pid}/webcams").json()["webcams"]
    assert cam == {"name": "chamber", "flip_horizontal": False, "flip_vertical": False, "rotation": 0, "aspect_ratio": "16:9",
                   "target_fps": 15, **_go2rtc_cam("10.0.6.21", "chamber")}
