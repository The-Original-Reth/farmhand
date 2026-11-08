"""A Klipper machine on cable and Wi-Fi: asked at whichever of its two IPs answers."""
from __future__ import annotations


import httpx
import pytest

from app.services import moonraker as mr
from app.services import printer_service
from app.services.moonraker import client as mr_client


# ------------------------------------------------------------------ a Klipper machine on cable and Wi-Fi: two IPs


def _two_ips(monkeypatch, moonraker, *, quiet=False):
    """Moonraker at both IPs, its wired one (10.0.6.21) unplugged, or `quiet` (it connects, then never answers)."""
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.host)
        if request.url.host == "10.0.6.21":
            if quiet:
                raise httpx.ReadTimeout("no answer", request=request)
            raise httpx.ConnectError("no route to host", request=request)
        return moonraker.handle(request)

    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(handle))
    return asked


def _on_both(db, name="V2 BOG"):
    return printer_service.create_printer(db, name=name, kind="Voron", wired_ip="10.0.6.21", wireless_ip="10.0.6.121")


def test_moonraker_is_asked_at_the_wired_ip_first(db_session, moonraker):
    p = _on_both(db_session)
    assert p.moonraker_urls == ["http://10.0.6.21:7125", "http://10.0.6.121:7125"]
    mr.server_info(p)
    assert mr.answered_at(p) == "http://10.0.6.21:7125"  # the cable, while it works


def test_moonraker_is_reached_at_its_wifi_ip_when_its_cable_is_out(db_session, moonraker, monkeypatch):
    p = _on_both(db_session)
    asked = _two_ips(monkeypatch, moonraker)
    assert mr.server_info(p)["moonraker_version"]
    assert mr.answered_at(p) == "http://10.0.6.121:7125"
    asked.clear()
    mr.server_info(p)
    assert set(asked) == {"10.0.6.121"}  # it remembers: the dead address isn't waited on every time


def test_a_moonraker_that_went_quiet_isnt_asked_again_elsewhere(db_session, moonraker, monkeypatch):
    # it connected, so the request may have been carried out (a print started): it must not be sent twice
    p = _on_both(db_session)
    asked = _two_ips(monkeypatch, moonraker, quiet=True)
    with pytest.raises(mr.MoonrakerError) as e:
        mr.server_info(p)
    assert e.value.kind == "unreachable" and "10.0.6.121" not in asked


def test_a_moonraker_address_set_by_hand_is_the_only_one_tried(db_session, moonraker, monkeypatch):
    p = printer_service.update_printer(db_session, _on_both(db_session).id, {"moonraker_url": "http://10.0.6.21:7125"})
    assert p.moonraker_urls == ["http://10.0.6.21:7125"]
    asked = _two_ips(monkeypatch, moonraker)
    with pytest.raises(mr.MoonrakerError):
        mr.server_info(p)
    assert set(asked) == {"10.0.6.21"}


def test_the_connection_and_cameras_follow_the_address_that_answered(api, moonraker, monkeypatch):
    pid = api.post("/printers", json={"name": "V2 BOG", "wired_ip": "10.0.6.21", "wireless_ip": "10.0.6.121"}).json()["id"]
    moonraker.webcams = [{"name": "Bed", "enabled": True, "service": "mjpegstreamer", "stream_url": "/webcam/?action=stream",
                     "snapshot_url": "/webcam/?action=snapshot"}]
    _two_ips(monkeypatch, moonraker)
    status = api.get(f"/printers/{pid}/moonraker").json()
    assert status["reachable"]
    assert (status["moonraker_url"], status["mainsail_url"]) == ("http://10.0.6.121:7125", "http://10.0.6.121/")
    cams = api.get(f"/printers/{pid}/webcams").json()["webcams"]
    assert cams[0]["stream_url"] == "http://10.0.6.121/webcam/?action=stream"  # the camera on the Wi-Fi side too


def test_back_on_the_cable_once_it_works_again(db_session, moonraker, monkeypatch):
    from app import printer_links

    p = _on_both(db_session)
    _two_ips(monkeypatch, moonraker)  # the cable's out
    mr.server_info(p)
    assert mr.answered_at(p) == "http://10.0.6.121:7125"
    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(moonraker.handle))  # plugged back in
    mr.server_info(p)
    assert mr.answered_at(p) == "http://10.0.6.121:7125"  # still on Wi-Fi for a while: no need to check every time
    monkeypatch.setattr(printer_links, "RECHECK_WIRED", 0.0)  # that while is over
    mr.server_info(p)
    assert mr.answered_at(p) == "http://10.0.6.21:7125"  # wired again


def test_the_mainsail_button_follows_the_address_that_answered(api, moonraker, monkeypatch):
    pid = api.post("/printers", json={"name": "V2 BOG", "wired_ip": "10.0.6.21", "wireless_ip": "10.0.6.121"}).json()["id"]
    printer = lambda: next(p for p in api.get("/printers").json() if p["id"] == pid)  # noqa: E731
    assert printer()["mainsail_url"] == "http://10.0.6.21/"  # wired, to begin with
    _two_ips(monkeypatch, moonraker)
    api.get(f"/printers/{pid}/moonraker")
    assert (printer()["moonraker_url"], printer()["mainsail_url"]) == ("http://10.0.6.121:7125", "http://10.0.6.121/")


def test_a_camera_written_out_with_the_printers_wired_ip_follows_it_to_wifi(api, moonraker, monkeypatch):
    pid = api.post("/printers", json={"name": "V2 BOG", "wired_ip": "10.0.6.21", "wireless_ip": "10.0.6.121"}).json()["id"]
    moonraker.webcams = [
        {"name": "Bed", "enabled": True, "service": "webrtc-camerastreamer", "stream_url": "http://10.0.6.21:8080/webrtc",
         "snapshot_url": "http://10.0.6.21/webcam/?action=snapshot"},
        {"name": "Room", "enabled": True, "service": "mjpegstreamer", "stream_url": "http://10.0.6.99/stream"},  # its own
    ]
    _two_ips(monkeypatch, moonraker)
    cams = api.get(f"/printers/{pid}/webcams").json()["webcams"]
    assert [(c["stream_url"], c["snapshot_url"]) for c in cams] == [
        ("http://10.0.6.121:8080/webrtc", "http://10.0.6.121/webcam/?action=snapshot"),
        ("http://10.0.6.99/stream", None),
    ]


def test_back_on_the_cable_even_while_it_keeps_being_asked_over_wifi(db_session, moonraker, monkeypatch):
    # The server asks each printer about every minute. Those answers over Wi-Fi mustn't put off trying the cable: two
    # minutes after it fell back, the cable is tried first. While it's still out, it stays on Wi-Fi without waiting
    # on the cable at every request.
    from app import printer_links

    clock = [1000.0]
    monkeypatch.setattr(printer_links.time, "monotonic", lambda: clock[0])
    p = _on_both(db_session)
    asked = _two_ips(monkeypatch, moonraker)  # the cable's out
    mr.server_info(p)  # falls back to Wi-Fi at 1000
    for t in (1060, 1110):  # asked every minute or so, over Wi-Fi: the cable isn't tried
        clock[0] = t
        asked.clear()
        mr.server_info(p)
        assert asked == ["10.0.6.121"]
    clock[0] = 1125  # two minutes on: the cable is tried first, it's still out, so Wi-Fi again for two more minutes
    asked.clear()
    mr.server_info(p)
    assert asked == ["10.0.6.21", "10.0.6.121"]
    clock[0] = 1185
    asked.clear()
    mr.server_info(p)
    assert asked == ["10.0.6.121"]  # not waited on again a minute later
    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(moonraker.handle))  # plugged back in
    clock[0] = 1250  # two minutes after the last fall back
    mr.server_info(p)
    assert mr.answered_at(p) == "http://10.0.6.21:7125"  # on the cable again
