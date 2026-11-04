"""The Farm cost page's filament: each printer's grams and filament cost, added up by month."""
from __future__ import annotations

import datetime as dt

import httpx
import pytest

from app.services import filament_cost
from app.services.moonraker import client as mr_client

from .fake_moonraker import FakeMoonraker


def _ts(*args):
    return dt.datetime(*args, tzinfo=dt.timezone.utc).timestamp()


@pytest.fixture()
def farm(api, monkeypatch):
    fake = FakeMoonraker()
    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(fake.handle))
    pid = api.post("/printers", json={"name": "VT 1190", "kind": "Voron", "wired_ip": "10.0.6.21"}).json()["id"]
    other = api.post("/printers", json={"name": "Idle", "kind": "Voron", "wired_ip": None}).json()["id"]
    return api, fake, pid, other


def test_each_printers_filament_is_added_up_by_month(farm):
    c, fake, pid, other = farm
    priced = fake.add_gcode("Frog.gcode", cost="20", density="1.25")
    fake.add_job("000001", "Frog.gcode", start=_ts(2026, 10, 5), filament_mm=10_000, metadata=priced)
    fake.add_job("000002", "Frog.gcode", start=_ts(2026, 10, 20), filament_mm=5_000, metadata=priced)
    # no price, but the slicer's estimate: 3 g a metre
    fake.add_job("000003", "cube.gcode", start=_ts(2026, 11, 2), filament_mm=2_000,
                 metadata={**fake.add_gcode("cube.gcode", cost=None), "filament_total": 1000, "filament_weight_total": 3})
    fake.add_job("000004", "mystery.gcode", start=_ts(2026, 11, 3), filament_mm=1_000)  # nothing to go on
    fake.add_job("000005", "Frog.gcode", start=_ts(2026, 11, 4), filament_mm=0, metadata=priced)  # used none: left out
    c.post(f"/printers/{pid}/moonraker/sync")

    printers = {p["printer_id"]: p["months"] for p in c.get("/farm-cost").json()["printers"]}
    assert printers[other] == []
    nov, oct_ = printers[pid]
    g10, g5 = filament_cost.grams(10_000, 1.75, 1.25), filament_cost.grams(5_000, 1.75, 1.25)
    assert oct_["key"] == "2026-10" and oct_["prints"] == 2 and oct_["unweighed"] == 0 and oct_["uncosted"] == 0
    assert oct_["grams"] == pytest.approx(round(g10, 1) + round(g5, 1), abs=0.11)
    assert oct_["filament_cost"] == pytest.approx(round(g10 * 0.02, 2) + round(g5 * 0.02, 2), abs=0.011)
    assert nov == {"key": "2026-11", "prints": 2, "grams": 6.0, "filament_cost": 0.0, "unweighed": 1, "uncosted": 2}


def test_each_printers_filament_is_also_added_up_by_day(farm):
    c, fake, pid, other = farm
    priced = fake.add_gcode("Frog.gcode", cost="20", density="1.25")
    fake.add_job("000001", "Frog.gcode", start=_ts(2026, 10, 5, 9), filament_mm=10_000, metadata=priced)
    fake.add_job("000002", "Frog.gcode", start=_ts(2026, 10, 5, 18), filament_mm=5_000, metadata=priced)
    fake.add_job("000003", "Frog.gcode", start=_ts(2026, 10, 20), filament_mm=5_000, metadata=priced)
    c.post(f"/printers/{pid}/moonraker/sync")

    printers = {p["printer_id"]: p for p in c.get("/farm-cost").json()["printers"]}
    assert printers[other]["days"] == [] and printers[other]["energy_days"] == []
    days = printers[pid]["days"]
    assert [(d["key"], d["prints"]) for d in days] == [("2026-10-20", 1), ("2026-10-05", 2)]
    assert sum(d["filament_cost"] for d in days) == pytest.approx(printers[pid]["months"][0]["filament_cost"], abs=0.011)


def test_months_follow_the_viewers_time_zone(farm):
    c, fake, pid, _ = farm
    fake.add_job("000001", "Frog.gcode", start=_ts(2026, 11, 1, 2), metadata=fake.add_gcode("Frog.gcode"))
    c.post(f"/printers/{pid}/moonraker/sync")
    keys = lambda tz: [m["key"] for p in c.get("/farm-cost", params={"tz": tz} if tz else None).json()["printers"] for m in p["months"]]
    assert keys(None) == ["2026-11"] and keys("America/New_York") == ["2026-10"]


# ------------------------------------------------------------------ the record saved after each month


def _db():
    from app.database import get_db
    from app.main import app

    return next(app.dependency_overrides[get_db]())


def test_last_months_record_is_saved_once_beside_the_model_folder(farm, tmp_path):
    from app import storage
    from app.services import farm_cost

    c, fake, pid, _ = farm
    fake.add_job("000001", "Frog.gcode", start=_ts(2026, 10, 5), filament_mm=10_000, energy_kwh=1.0,
                 metadata=fake.add_gcode("Frog.gcode", cost="20", density="1.25"))
    c.post(f"/printers/{pid}/moonraker/sync")
    c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": 0.2, "energy_price_from": "2026-10", "time_zone": "UTC"}})

    written = farm_cost.record_last_month(_db(), now=dt.datetime(2026, 11, 3, tzinfo=dt.timezone.utc))
    assert written == storage.effective_root("stl").parent / "farm cost" / "farmhand - farm cost - oct 2026.csv"
    text = written.read_bytes().decode("utf-8")
    assert "\r\n" in text and "\r\r" not in text  # Excel's line ends, exactly
    lines = text.lstrip("﻿").splitlines()
    assert text.startswith("﻿") and lines[0].startswith("Period,Printer,Prints,Filament (g),Filament cost ($)")
    assert [line.split(",")[1] for line in lines[1:]] == ["Idle", "VT 1190", "Whole farm"]  # by name, then the farm
    vt = lines[2].split(",")
    assert vt[0] == "2026-10" and vt[2] == "1" and vt[4] == f"{filament_cost.grams(10_000, 1.75, 1.25) * 0.02:.2f}"

    assert farm_cost.record_last_month(_db(), now=dt.datetime(2026, 11, 20, tzinfo=dt.timezone.utc)) is None  # once
    assert c.get("/farm-cost").json()["records"]["saved"] == ["farmhand - farm cost - oct 2026.csv"]


def test_the_record_lists_the_printers_as_dragged_on_the_page(farm):
    from app.services import farm_cost

    c, _, pid, _ = farm
    c.post("/printers", json={"name": "Apex", "kind": "Voron", "wired_ip": None})
    c.put("/settings/config", json={"preferences": {"farm_cost_order": [pid, 999], "time_zone": "UTC"}})
    rows = farm_cost.month_rows(_db(), "2026-10", "UTC")
    assert [r["name"] for r in rows] == ["VT 1190", "Apex", "Idle", "Whole farm"]  # as dragged, then the rest by name


def test_no_record_is_written_while_the_model_folder_is_unavailable(farm, tmp_path):
    from app import storage
    from app.services import farm_cost

    c, *_ = farm
    unmounted = tmp_path / "nas" / "stl"
    unmounted.mkdir(parents=True)  # the empty folder under a share that isn't mounted: no marker
    storage.configure(stl_path=str(unmounted))
    with pytest.raises(storage.StorageUnavailableError):
        farm_cost.record_last_month(_db(), now=dt.datetime(2026, 11, 3, tzinfo=dt.timezone.utc))
    assert not (tmp_path / "nas" / "farm cost").exists()
    records = c.get("/farm-cost").json()["records"]
    assert records["folder"] is None and "marker" in records["problem"]


def test_the_farms_time_zone_decides_when_a_month_ends(farm):
    c, *_ = farm
    p = c.put("/settings/config", json={"preferences": {"time_zone": "America/New_York"}}).json()["config"]["preferences"]
    assert p["time_zone"] == "America/New_York"
    assert c.put("/settings/config", json={"preferences": {"time_zone": "Mars/Base"}}).json()["config"]["preferences"]["time_zone"] is None
    from app.services import farm_cost

    assert farm_cost.last_month(dt.datetime(2026, 11, 1, 2, tzinfo=dt.timezone.utc), "America/New_York") == "2026-09"
    assert farm_cost.last_month(dt.datetime(2026, 11, 1, 2, tzinfo=dt.timezone.utc), None) == "2026-10"


def test_the_records_folder_can_be_chosen_in_settings(farm, tmp_path):
    from app import storage
    from app.services import farm_cost

    c, *_ = farm
    loc = c.get("/farm-cost/location").json()
    assert loc["is_default"] and loc["path"] == str(storage.effective_root("stl").parent / "farm cost")

    chosen = storage.local_root() / "accounts"  # inside Farmhand's own storage: a folder that lasts
    chosen.mkdir()
    loc = c.put("/farm-cost/location", json={"path": str(chosen)}).json()
    assert not loc["is_default"] and loc["status"]["ready"] and (chosen / storage.MARKER_NAME).is_file()
    written = farm_cost.record_last_month(_db(), now=dt.datetime(2026, 11, 3, tzinfo=dt.timezone.utc))
    assert written.parent == chosen and c.get("/farm-cost").json()["records"]["folder"] == str(chosen)

    (chosen / storage.MARKER_NAME).unlink()  # as if the share under it weren't mounted
    with pytest.raises(storage.StorageUnavailableError):
        farm_cost.record_last_month(_db(), now=dt.datetime(2026, 12, 3, tzinfo=dt.timezone.utc))

    r = c.put("/farm-cost/location", json={"path": str(tmp_path / "nowhere")})
    assert r.status_code == 422 and "isn't an existing folder" in r.json()["detail"]
    assert c.put("/farm-cost/location", json={"path": None}).json()["is_default"] is True
