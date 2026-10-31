from __future__ import annotations

import httpx
import pytest

from app.services.moonraker import client as mr_client

from .fake_moonraker import FakeMoonraker


@pytest.fixture()
def network(monkeypatch):
    """A stand-in network: {ip: FakeMoonraker}. Every other address refuses the connection, like nothing's there."""
    hosts: dict[str, FakeMoonraker] = {}
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.host)
        fake = hosts.get(request.url.host)
        if fake is None:
            raise httpx.ConnectError("connection refused", request=request)
        return fake.handle(request)

    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(handle))
    return hosts, asked


def test_finds_the_moonrakers_in_the_range_and_skips_known_printers(api, network):
    hosts, asked = network
    hosts["10.0.6.21"] = FakeMoonraker()  # already in Farmhand
    hosts["10.0.6.22"] = FakeMoonraker()  # already in Farmhand, by its wireless IP
    hosts["10.0.6.40"] = FakeMoonraker()
    hosts["10.0.6.40"].hostname = "trident"
    api.post("/printers", json={"name": "VT 1190", "wired_ip": "10.0.6.21"}).raise_for_status()
    api.post("/printers", json={"name": "V2", "wireless_ip": "10.0.6.22"}).raise_for_status()

    r = api.get("/printers/discover", params={"cidr": "10.0.6.0/24"})
    assert r.status_code == 200
    assert r.json() == [{
        "ip": "10.0.6.40", "connection_type": "moonraker", "address": "http://10.0.6.40:7125",
        "web_url": "http://10.0.6.40/", "hostname": "trident", "firmware": "Klipper", "version": "v0.9.3-fake",
        "state": "ready", "needs_api_key": False,
    }]
    assert "10.0.6.21" not in asked and "10.0.6.22" not in asked  # known printers aren't even asked
    assert len(api.get("/printers").json()) == 2  # nothing was added


def test_a_moonraker_that_wants_an_api_key_is_still_found(api, network):
    hosts, _ = network
    hosts["192.168.1.5"] = FakeMoonraker()
    hosts["192.168.1.5"].api_key = "secret"

    found = api.get("/printers/discover", params={"cidr": "192.168.1.0/28"}).json()
    assert [(f["ip"], f["needs_api_key"], f["firmware"]) for f in found] == [("192.168.1.5", True, None)]


def test_kalico_is_told_apart_from_klipper(api, network):
    hosts, _ = network
    hosts["10.0.0.2"], hosts["10.0.0.3"] = FakeMoonraker(), FakeMoonraker()
    hosts["10.0.0.3"].app = "Kalico"
    found = api.get("/printers/discover", params={"cidr": "10.0.0.0/29"}).json()
    assert [(f["ip"], f["firmware"]) for f in found] == [("10.0.0.2", "Klipper"), ("10.0.0.3", "Kalico")]


def test_each_address_goes_to_the_first_scanner_that_knows_it(api, network, monkeypatch):
    from app.services import printer_discovery

    class OctoPrint:  # a later kind of scanner, the way one plugs in
        @staticmethod
        def probe(ip):
            return {"connection_type": "octoprint", "address": f"http://{ip}"} if ip in ("10.0.0.2", "10.0.0.3") else None

    hosts, _ = network
    hosts["10.0.0.2"] = FakeMoonraker()
    monkeypatch.setattr(printer_discovery, "SCANNERS", [*printer_discovery.SCANNERS, OctoPrint])
    found = api.get("/printers/discover", params={"cidr": "10.0.0.0/29"}).json()
    assert [(f["ip"], f["connection_type"]) for f in found] == [("10.0.0.2", "moonraker"), ("10.0.0.3", "octoprint")]


def test_a_single_address_can_be_scanned(api, network):
    hosts, _ = network
    hosts["10.0.0.9"] = FakeMoonraker()
    assert [f["ip"] for f in api.get("/printers/discover", params={"cidr": "10.0.0.9/32"}).json()] == ["10.0.0.9"]


@pytest.mark.parametrize("cidr", ["not-a-range", "10.0.0.0/21", "fd00::/120"])
def test_ranges_that_cant_be_scanned_are_refused(api, network, cidr):
    r = api.get("/printers/discover", params={"cidr": cidr})
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
