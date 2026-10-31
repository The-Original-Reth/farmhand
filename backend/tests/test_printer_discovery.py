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
        "state": "ready", "needs_api_key": False, "link": None, "wired_ip": None, "wireless_ip": None,
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


def _links(found):
    return [(f["ip"], f["link"], f["wired_ip"], f["wireless_ip"]) for f in found]


@pytest.mark.parametrize("wired, wireless", [("eth0", "wlan0"), ("end0", "wlp2s0"), ("enx00e04c680001", "wlx001122334455")])
def test_a_printer_on_cable_and_wifi_is_listed_once_at_its_wired_ip(api, network, wired, wireless):
    hosts, _ = network
    fake = FakeMoonraker()
    fake.interfaces = {"lo": ["127.0.0.1"], wireless: ["10.0.0.3"], wired: ["10.0.0.5"], "docker0": ["172.17.0.1"]}
    hosts["10.0.0.3"] = hosts["10.0.0.5"] = fake  # the wireless address comes first in the range
    assert _links(api.get("/printers/discover", params={"cidr": "10.0.0.0/29"}).json()) == [
        ("10.0.0.5", "wired", "10.0.0.5", "10.0.0.3")]


def test_each_answer_says_whether_it_came_by_cable_or_wifi(api, network):
    hosts, _ = network
    hosts["10.0.0.2"], hosts["10.0.0.3"], hosts["10.0.0.4"] = FakeMoonraker(), FakeMoonraker(), FakeMoonraker()
    hosts["10.0.0.2"].interfaces = {"eth0": ["10.0.0.2"], "wlan0": []}  # Wi-Fi not joined
    hosts["10.0.0.3"].interfaces = {"wlan0": ["10.0.0.3"], "eth0": ["192.168.50.7"]}  # its cable is on another network
    hosts["10.0.0.4"].interfaces = None  # an older Moonraker: still found, just not known which
    assert _links(api.get("/printers/discover", params={"cidr": "10.0.0.0/29"}).json()) == [
        ("10.0.0.2", "wired", "10.0.0.2", None),
        ("10.0.0.3", "wireless", "192.168.50.7", "10.0.0.3"),
        ("10.0.0.4", None, None, None),
    ]


def test_a_printer_known_by_its_other_ip_is_skipped(api, network):
    hosts, _ = network
    hosts["10.0.0.3"] = FakeMoonraker()
    hosts["10.0.0.3"].interfaces = {"wlan0": ["10.0.0.3"], "eth0": ["192.168.50.7"]}
    api.post("/printers", json={"name": "V2", "wired_ip": "192.168.50.7"}).raise_for_status()
    assert api.get("/printers/discover", params={"cidr": "10.0.0.0/29"}).json() == []


@pytest.mark.parametrize("cidr", ["not-a-range", "10.0.0.0/21", "fd00::/120", "8.8.8.0/24", "1.1.1.1/32"])
def test_ranges_that_cant_be_scanned_are_refused(api, network, cidr):
    r = api.get("/printers/discover", params={"cidr": cidr})
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)


def test_only_the_farms_own_network_can_be_scanned(api, network):
    r = api.get("/printers/discover", params={"cidr": "8.8.8.0/24"})
    assert r.status_code == 422 and "your own network" in r.json()["detail"]
    for cidr in ("10.0.0.0/30", "172.16.0.0/30", "192.168.1.0/30"):
        assert api.get("/printers/discover", params={"cidr": cidr}).status_code == 200


def test_an_odd_answer_is_skipped_not_the_whole_scan(api, network, monkeypatch):
    hosts, _ = network
    hosts["10.0.0.2"] = FakeMoonraker()
    hosts["10.0.0.2"].network_as_said = {"eth0": ["not", "an", "interface"], "wlan0": "nor this"}  # read past
    hosts["10.0.0.3"] = FakeMoonraker()
    hosts["10.0.0.4"] = FakeMoonraker()

    from app.services.printer_discovery import moonraker as scanner
    real = scanner.probe
    monkeypatch.setattr(scanner, "probe", lambda ip: (_ for _ in ()).throw(RuntimeError("odd")) if ip == "10.0.0.4" else real(ip))

    r = api.get("/printers/discover", params={"cidr": "10.0.0.0/29"})
    assert r.status_code == 200
    assert [f["ip"] for f in r.json()] == ["10.0.0.2", "10.0.0.3"]  # .2's odd interfaces read past; .4 skipped
