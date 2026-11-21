"""A Klipper printer's web page, Mainsail or Fluidd: found on the printer, and followed by its buttons and links."""
from __future__ import annotations

import datetime as dt

from app.services.moonraker import web_ui

from .fake_moonraker import FakeMoonraker


def test_the_page_says_which_it_is():
    assert web_ui.name_in(b"<html><head><title>Fluidd</title></head></html>") == "Fluidd"
    assert web_ui.name_in(b"<html><head><TITLE>\n  Mainsail\n</TITLE></head></html>") == "Mainsail"
    # a title naming neither: the first one the page names
    assert web_ui.name_in(b"<title>Voron</title><script src='/fluidd.js'></script>mainsail") == "Fluidd"
    assert web_ui.name_in(b"<title>Router</title>") is None


def test_a_printer_is_mainsail_until_fluidd_is_found_at_sync(klipper, moonraker):
    c, pid = klipper
    assert c.get(f"/printers/{pid}").json()["web_ui"] == "Mainsail"
    moonraker.web_ui = "Fluidd"
    c.post(f"/printers/{pid}/moonraker/sync").raise_for_status()
    p = c.get(f"/printers/{pid}").json()
    assert p["web_ui"] == "Fluidd" and p["mainsail_url"] == "http://10.0.6.21/"  # the same page, port 80


def test_a_page_that_cant_be_read_keeps_what_was_found(klipper, moonraker):
    c, pid = klipper
    moonraker.web_ui = "Fluidd"
    c.post(f"/printers/{pid}/moonraker/sync").raise_for_status()
    moonraker.web_ui = None  # nothing on port 80 now
    c.post(f"/printers/{pid}/moonraker/sync").raise_for_status()
    assert c.get(f"/printers/{pid}").json()["web_ui"] == "Fluidd"


def test_the_printers_page_has_it_looked_at_again_now_and_then(klipper, moonraker, db_session, monkeypatch):
    c, pid = klipper
    status = c.get(f"/printers/{pid}/moonraker").json()
    assert status["web_ui"] == "Mainsail"  # found the first time
    moonraker.web_ui = "Fluidd"
    assert c.get(f"/printers/{pid}/moonraker").json()["web_ui"] == "Mainsail"  # not asked again straight away
    later = web_ui.utc_now() + web_ui.RECHECK + dt.timedelta(seconds=1)
    monkeypatch.setattr(web_ui, "utc_now", lambda: later)
    assert c.get(f"/printers/{pid}/moonraker").json()["web_ui"] == "Fluidd"


def test_a_prusa_has_none(api):
    p = api.post("/printers", json={"name": "Core One", "wired_ip": "10.0.6.50", "connection_type": "prusalink"}).json()
    assert p["web_ui"] is None


def test_a_scan_says_which_page_a_klipper_printer_has():
    import httpx

    from app.services.moonraker import client
    from app.services.printer_discovery import moonraker as scanner

    fake = FakeMoonraker()
    fake.web_ui = "Fluidd"
    old, client.transport = client.transport, httpx.MockTransport(fake.handle)
    try:
        found = scanner.probe("10.0.6.40")
    finally:
        client.transport = old
    assert found["web_url"] == "http://10.0.6.40/" and found["web_ui"] == "Fluidd"
