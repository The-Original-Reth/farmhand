"""How far along a printer's print is, for Monitor's cameras: from Klipper or PrusaLink, and why when it can't say."""
from __future__ import annotations

import httpx
import pytest

from app.services.moonraker import client as mr_client
from app.services.prusalink import client as pl_client

from .fake_moonraker import FakeMoonraker
from .fake_prusalink import FakePrusaLink


@pytest.fixture()
def moonraker(monkeypatch):
    f = FakeMoonraker()
    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(f.handle))
    return f


@pytest.fixture()
def prusa(monkeypatch):
    f = FakePrusaLink()
    monkeypatch.setattr(pl_client, "transport", httpx.MockTransport(f.handle))
    return f


def test_a_klipper_printers_progress(api, moonraker):
    pid = api.post("/printers", json={"name": "V2Blue", "wired_ip": "10.0.6.21"}).json()["id"]
    nothing = {"state": None, "progress": None, "file": None, "error": None}
    assert api.get(f"/printers/{pid}/progress").json() == nothing
    moonraker.print_state = "printing"
    moonraker.live = {"filename": "Frog.gcode", "print_duration": 1200.0, "progress": 0.4237}
    assert api.get(f"/printers/{pid}/progress").json() == {"state": "printing", "progress": 42.4, "file": "Frog.gcode", "error": None}
    moonraker.print_state = "paused"
    assert api.get(f"/printers/{pid}/progress").json()["state"] == "paused"
    moonraker.print_state = "complete"
    assert api.get(f"/printers/{pid}/progress").json() == nothing
    moonraker.down = True
    r = api.get(f"/printers/{pid}/progress").json()
    assert r["state"] is None and "Moonraker" in r["error"]
    assert api.get("/printers/999/progress").status_code == 404


def test_a_prusas_progress(api, prusa):
    pid = api.post("/printers", json={
        "name": "Core One", "connection_type": "prusalink", "wired_ip": "10.0.6.30", "prusalink_password": prusa.password,
    }).json()["id"]
    assert api.get(f"/printers/{pid}/progress").json()["state"] is None
    prusa.start_job(7, "Frog.bgcode", progress=63.0)
    r = api.get(f"/printers/{pid}/progress").json()
    assert (r["state"], r["progress"], r["error"]) == ("printing", 63.0, None)
    prusa.advance(progress=100.0, time_printing=3600, state="FINISHED")
    assert api.get(f"/printers/{pid}/progress").json()["state"] is None
