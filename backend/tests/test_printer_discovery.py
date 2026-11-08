from __future__ import annotations

import httpx
import pytest

from app.services.moonraker import client as mr_client
from app.services.prusalink import client as pl_client

from .fake_moonraker import FakeMoonraker
from .fake_prusalink import FakePrusaLink


@pytest.fixture()
def network(monkeypatch):
    """
    A stand-in network: {ip: FakeMoonraker (answering on port 7125) or FakePrusaLink (port 80), or a web page of
    something else (an httpx.Response handler, port 80)}. Every other address and port refuses the connection.
    """
    hosts: dict = {}
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.host)
        fake, port = hosts.get(request.url.host), request.url.port or 80
        if isinstance(fake, FakeMoonraker) and port == 7125 or isinstance(fake, FakePrusaLink) and port == 80:
            return fake.handle(request)
        if callable(fake) and port == 80:
            return fake(request)
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(handle))
    monkeypatch.setattr(pl_client, "transport", httpx.MockTransport(handle))
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
        "decommissioned_id": None, "decommissioned_name": None,
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


def test_a_prusa_is_found_by_its_prusalink_login(api, network):
    hosts, _ = network
    hosts["192.168.10.129"] = FakePrusaLink()  # wants its password, like a Core One: known by the login it asks for
    hosts["192.168.10.130"] = FakePrusaLink(password=None)  # one that asks for none says its name
    hosts["192.168.10.131"] = lambda request: httpx.Response(  # a router's page: also a login, but not Prusa's
        401, headers={"WWW-Authenticate": 'Basic realm="Router"'})
    hosts["192.168.10.132"] = lambda request: httpx.Response(200, text="<html>NAS</html>")  # a web page, not PrusaLink
    hosts["192.168.10.133"] = FakeMoonraker()  # a Klipper machine: Moonraker's, though it has a web page too

    found = api.get("/printers/discover", params={"cidr": "192.168.10.128/28"}).json()
    assert [(f["ip"], f["connection_type"], f["firmware"], f["needs_api_key"], f["hostname"]) for f in found] == [
        ("192.168.10.129", "prusalink", "Prusa", True, None),
        ("192.168.10.130", "prusalink", "Prusa", False, "prusa-coreone"),
        ("192.168.10.133", "moonraker", "Klipper", False, "mainsail"),
    ]
    assert found[0]["address"] == "http://192.168.10.129" and found[0]["web_url"] == "http://192.168.10.129/"


def test_a_prusa_already_in_farmhand_is_skipped(api, network):
    hosts, asked = network
    hosts["192.168.10.129"] = FakePrusaLink()
    api.post("/printers", json={"name": "Prusa_2", "wired_ip": "192.168.10.129", "connection_type": "prusalink"}).raise_for_status()
    assert api.get("/printers/discover", params={"cidr": "192.168.10.128/28"}).json() == []
    assert "192.168.10.129" not in asked


def test_a_decommissioned_printer_is_found_again_and_named(api, network):
    hosts, asked = network
    hosts["10.0.6.21"], hosts["10.0.6.30"] = FakeMoonraker(), FakeMoonraker()
    hosts["10.0.6.21"].interfaces = {"eth0": ["10.0.6.21"], "wlan0": ["10.0.6.121"]}
    old = api.post("/printers", json={"name": "Old V2", "wireless_ip": "10.0.6.121"}).json()  # known by its Wi-Fi IP
    api.patch(f"/printers/{old['id']}", json={"decommissioned": True}).raise_for_status()
    api.post("/printers", json={"name": "Active", "wired_ip": "10.0.6.30"}).raise_for_status()

    found = api.get("/printers/discover", params={"cidr": "10.0.6.0/24"}).json()
    assert [(f["ip"], f["decommissioned_id"], f["decommissioned_name"]) for f in found] == [("10.0.6.21", old["id"], "Old V2")]
    assert "10.0.6.30" not in asked  # an active printer's address is still skipped


def test_a_new_printer_isnt_tied_to_any_decommissioned_one(api, network):
    hosts, _ = network
    hosts["10.0.6.40"] = FakeMoonraker()
    found = api.get("/printers/discover", params={"cidr": "10.0.6.40/32"}).json()
    assert found[0]["decommissioned_id"] is None and found[0]["decommissioned_name"] is None


# ------------------------------------------------------------------ the range a scan starts with


def test_the_range_starts_as_the_servers_own_network(api, monkeypatch):
    from app.services import printer_discovery

    monkeypatch.setattr(printer_discovery.os.path, "exists", lambda path: False)  # not in a container
    monkeypatch.setattr(printer_discovery, "_own_address", lambda: "192.168.10.125")
    assert api.get("/printers/discover/range").json() == {"cidr": "192.168.10.0/24"}


def test_in_docker_the_range_is_where_the_farms_printers_are(api, monkeypatch):
    from app.services import printer_discovery

    monkeypatch.setattr(printer_discovery.os.path, "exists", lambda path: path == "/.dockerenv")
    monkeypatch.setattr(printer_discovery, "_own_address", lambda: "172.18.0.3")  # Docker's network: never used
    assert api.get("/printers/discover/range").json() == {"cidr": None}  # no printers yet: it can't tell
    for name, wired, wireless in (("A", "192.168.10.123", "192.168.10.122"), ("B", "192.168.10.133", None),
                                  ("C", "10.0.6.21", None), ("D", None, "8.8.8.8")):
        api.post("/printers", json={"name": name, "wired_ip": wired, "wireless_ip": wireless}).raise_for_status()
    assert api.get("/printers/discover/range").json() == {"cidr": "192.168.10.0/24"}  # most of them; not a public one


def test_a_server_whose_address_isnt_a_private_one_falls_back_to_the_printers(api, monkeypatch):
    from app.services import printer_discovery

    monkeypatch.setattr(printer_discovery.os.path, "exists", lambda path: False)
    monkeypatch.setattr(printer_discovery, "_own_address", lambda: "8.8.4.4")  # a public one: never scanned
    api.post("/printers", json={"name": "A", "wired_ip": "10.0.6.21"}).raise_for_status()
    assert api.get("/printers/discover/range").json() == {"cidr": "10.0.6.0/24"}
