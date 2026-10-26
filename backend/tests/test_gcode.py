"""
A 3MF version's G-code: its "ver N" name, uploading one for a version (replacing one it had), downloading it, and
sending it to the printer the 3MF was sliced for (PrusaLink or Moonraker), never while that printer is busy.
"""
from __future__ import annotations

import os
from urllib.parse import unquote

import httpx
import pytest

from app.names import with_version
from app.services.moonraker import client as mr_client
from app.services.prusalink import client as pl_client

from .fake_moonraker import FakeMoonraker
from .fake_prusalink import FakePrusaLink


# ------------------------------------------------------------------ "ver N" in a version's name


@pytest.mark.parametrize("uploaded, version, kept_as", [
    ("Goldfish.3mf", 1, "Goldfish ver 1.3mf"),
    ("Goldfish.3mf", 2, "Goldfish ver 2.3mf"),
    ("Goldfish ver 1.3mf", 2, "Goldfish ver 2.3mf"),  # a downloaded version uploaded again: replaced, not added to
    ("Goldfish VER3.3mf", 4, "Goldfish ver 4.3mf"),
    ("Goldfish_v2.3mf", 3, "Goldfish_v2 ver 3.3mf"),  # only "ver N" counts as a version number
    ("Fish ver.3mf", 1, "Fish ver ver 1.3mf"),
])
def test_a_new_version_is_kept_under_its_version_number(uploaded, version, kept_as):
    assert with_version(uploaded, version) == kept_as


# ------------------------------------------------------------------ over the API


@pytest.fixture()
def farm(api, sample_3mf_paths):
    """A model and a 3MF (two versions) on VT 1190, uploaded as "Goldfish.3mf"."""
    pid = api.post("/printers", json={"name": "VT 1190", "kind": "Voron", "wired_ip": "10.0.6.21"}).json()["id"]
    mid = api.post("/source-models", data={"name": "Goldfish.stl", "file_type": "STL"}, files={"file": ("Goldfish.stl", b"x" * 64)}).json()["id"]
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        data = f.read()
    bundle = api.post("/bundles", data={"source_model_ids": f"[{mid}]", "printer_id": str(pid)}, files={"threemf": ("Goldfish.3mf", data)}).json()
    bundle = api.post(f"/bundles/{bundle['id']}/versions", files={"threemf": ("Goldfish.3mf", data)}).json()
    return {"api": api, "printer": pid, "bundle": bundle}


def _versions(farm):
    b = farm["api"].get(f"/bundles/{farm['bundle']['id']}").json()
    return {v["version"]: v for v in b["versions"]}


def test_uploads_are_named_with_their_version(farm):
    v = _versions(farm)
    assert v[1]["filename"] == "Goldfish ver 1.3mf" and v[2]["filename"] == "Goldfish ver 2.3mf"
    assert v[1]["gcode_name"] is None  # no G-code yet


def test_a_gcode_uploaded_for_a_version_is_shown_and_downloads_under_its_3mfs_name(farm):
    c = farm["api"]
    v2 = _versions(farm)[2]["id"]
    r = c.put(f"/bundles/versions/{v2}/gcode", files={"gcode": ("whatever-the-slicer-called-it.gcode", b"G28\nG1 X10\n")})
    assert r.status_code == 200
    assert {v["version"]: v for v in r.json()["versions"]}[2]["gcode_name"] == "Goldfish ver 2.gcode"  # the whole 3MF comes back
    d = c.get(f"/bundles/versions/{v2}/download/gcode")
    assert d.status_code == 200 and d.content == b"G28\nG1 X10\n"
    assert "Goldfish ver 2.gcode" in unquote(d.headers["content-disposition"])


def test_a_new_gcode_replaces_the_old_one(farm):
    from app.models import BundleVersion
    from app.database import get_db
    from app.main import app

    c = farm["api"]
    v2 = _versions(farm)[2]["id"]
    c.put(f"/bundles/versions/{v2}/gcode", files={"gcode": ("first.gcode", b"old")})
    db = next(app.dependency_overrides[get_db]())
    old_path = db.get(BundleVersion, v2).gcode_path
    c.put(f"/bundles/versions/{v2}/gcode", files={"gcode": ("second.bgcode", b"GCDEnew")})
    assert _versions(farm)[2]["gcode_name"] == "Goldfish ver 2.bgcode"
    assert c.get(f"/bundles/versions/{v2}/download/gcode").content == b"GCDEnew"
    assert not os.path.exists(old_path)  # the replaced file is gone


def test_only_a_gcode_can_be_uploaded_as_one(farm):
    c = farm["api"]
    v2 = _versions(farm)[2]["id"]
    r = c.put(f"/bundles/versions/{v2}/gcode", files={"gcode": ("notes.txt", b"hello")})
    assert r.status_code == 422 and ".gcode or .bgcode" in r.json()["detail"]
    assert c.put("/bundles/versions/999/gcode", files={"gcode": ("a.gcode", b"G28")}).status_code == 404


def test_a_pruned_version_cannot_be_given_a_gcode(farm):
    from app.database import get_db
    from app.main import app
    from app.models import BundleVersion

    c = farm["api"]
    v1 = _versions(farm)[1]["id"]
    db = next(app.dependency_overrides[get_db]())
    db.get(BundleVersion, v1).full_files_retained = False
    db.commit()
    r = c.put(f"/bundles/versions/{v1}/gcode", files={"gcode": ("a.gcode", b"G28")})
    assert r.status_code == 422 and "pruned" in r.json()["detail"]


# ------------------------------------------------------------------ sending it to a Moonraker (Klipper) printer


@pytest.fixture()
def moonraker(monkeypatch):
    f = FakeMoonraker()
    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(f.handle))
    return f


def test_sending_a_gcode_to_a_klipper_printer_uploads_it_and_starts_it(farm, moonraker):
    c = farm["api"]
    v2 = _versions(farm)[2]["id"]
    c.put(f"/bundles/versions/{v2}/gcode", files={"gcode": ("a.gcode", b"G28\nG1 X10\n")})
    r = c.post(f"/bundles/versions/{v2}/print")
    assert r.status_code == 200 and r.json() == {"sent": "gcodes/Goldfish ver 2.gcode", "printer": "VT 1190"}
    assert moonraker.uploads == [{"filename": "Goldfish ver 2.gcode", "size": 11, "root": "gcodes", "print": "true"}]


def test_a_busy_klipper_printer_is_not_sent_anything(farm, moonraker):
    c = farm["api"]
    v2 = _versions(farm)[2]["id"]
    c.put(f"/bundles/versions/{v2}/gcode", files={"gcode": ("a.gcode", b"G28")})
    moonraker.print_state = "printing"
    r = c.post(f"/bundles/versions/{v2}/print")
    assert r.status_code == 409 and "printing" in r.json()["detail"]
    assert moonraker.uploads == []


def test_a_klipper_printer_is_not_sent_a_bgcode(farm, moonraker):
    c = farm["api"]
    v2 = _versions(farm)[2]["id"]
    c.put(f"/bundles/versions/{v2}/gcode", files={"gcode": ("a.bgcode", b"GCDE")})
    r = c.post(f"/bundles/versions/{v2}/print")
    assert r.status_code == 422 and "Klipper" in r.json()["detail"]
    assert moonraker.uploads == []


def test_nothing_is_sent_for_a_version_without_a_gcode(farm, moonraker):
    r = farm["api"].post(f"/bundles/versions/{_versions(farm)[1]['id']}/print")
    assert r.status_code == 422 and "no G-code" in r.json()["detail"]
    assert farm["api"].post("/bundles/versions/999/print").status_code == 404


def test_a_printer_that_is_off_says_so(farm, moonraker):
    c = farm["api"]
    v2 = _versions(farm)[2]["id"]
    c.put(f"/bundles/versions/{v2}/gcode", files={"gcode": ("a.gcode", b"G28")})
    moonraker.down = True
    r = c.post(f"/bundles/versions/{v2}/print")
    assert r.status_code == 502 and r.json()["kind"] == "unreachable"


# ------------------------------------------------------------------ sending it to a PrusaLink printer (Core One)


@pytest.fixture()
def prusalink(monkeypatch):
    f = FakePrusaLink()
    monkeypatch.setattr(pl_client, "transport", httpx.MockTransport(f.handle))
    return f


def test_sending_a_gcode_to_a_prusalink_printer(farm, prusalink):
    c = farm["api"]
    c.patch(f"/printers/{farm['printer']}", json={"connection_type": "prusalink", "prusalink_password": "secret123"})
    v2 = _versions(farm)[2]["id"]
    c.put(f"/bundles/versions/{v2}/gcode", files={"gcode": ("a.bgcode", b"GCDE" + b"x" * 20)})
    r = c.post(f"/bundles/versions/{v2}/print")
    assert r.status_code == 200 and r.json() == {"sent": "usb/Goldfish ver 2.bgcode", "printer": "VT 1190"}
    [up] = prusalink.uploads
    assert up["path"] == "/api/v1/files/usb/Goldfish%20ver%202.bgcode" and up["size"] == 24 and up["headers"]["print-after-upload"] == "?1"
    jobs = c.get(f"/printers/{farm['printer']}/print-jobs").json()["jobs"]
    assert jobs[0]["filename"] == "Goldfish ver 2.bgcode"  # recorded at once


def test_a_busy_prusalink_printer_is_not_sent_anything(farm, prusalink):
    c = farm["api"]
    c.patch(f"/printers/{farm['printer']}", json={"connection_type": "prusalink", "prusalink_password": "secret123"})
    v2 = _versions(farm)[2]["id"]
    c.put(f"/bundles/versions/{v2}/gcode", files={"gcode": ("a.bgcode", b"GCDE")})
    prusalink.start_job(1, "running.bgcode", progress=30, time_printing=100)
    r = c.post(f"/bundles/versions/{v2}/print")
    assert r.status_code == 409 and "PRINTING" in r.json()["detail"]
    assert prusalink.uploads == []
