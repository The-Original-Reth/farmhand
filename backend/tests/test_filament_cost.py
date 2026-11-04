"""
A print's filament cost in the print history: the filament the printer says it used, turned into grams with the 3MF's
filament diameter and density, times the 3MF's price per kg. The sample 3MFs say 1.75 mm, 1.23 g/cm³ and 16.99.
"""
from __future__ import annotations

import datetime as dt
import math

import httpx
import pytest

from app.models import PrintJob
from app.services import filament_cost
from app.services.moonraker import client as mr_client

from . import factories as make
from .fake_moonraker import FakeMoonraker

T0 = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
GRAMS_PER_M = math.pi * 0.875**2 * 1.23  # 1.75 mm PLA at 1.23 g/cm³: about 2.96 g a metre


def _job(db, printer, filename, *, mm=10_000.0, start=T0, job_id=None):
    j = PrintJob(printer_id=printer.id, job_id=job_id or filename, filename=filename, status="completed",
                 start_time=start, filament_used=mm)
    db.add(j)
    db.commit()
    return j


def test_grams_are_the_volume_of_the_filament_times_its_density():
    assert filament_cost.grams(1000, 1.75, 1.23) == pytest.approx(GRAMS_PER_M)
    assert filament_cost.grams(1000, 2.85, 1.0) == pytest.approx(math.pi * 1.425**2)


def test_a_print_sent_from_farmhand_is_costed_from_its_own_version(db_session, sample_3mf_paths):
    p = make.printer(db_session)
    b = make.bundle(db_session, sample_3mf_paths["frog_vt1190"], filename="Frog.3mf")
    v2 = make.add_version(db_session, b, sample_3mf_paths["frog_vt1190"], filename="Frog.3mf")
    v2.settings = {**v2.settings, "filament_cost": "30"}
    db_session.commit()
    j = _job(db_session, p, "Frog ver 2.gcode")  # the name Farmhand sends version 2 under

    cost = filament_cost.costs(db_session, [j])[j.id]
    assert cost["version_id"] == v2.id and cost["version"] == 2 and cost["cost_per_kg"] == 30
    assert cost["grams"] == round(10 * GRAMS_PER_M, 1)
    assert cost["cost"] == round(10 * GRAMS_PER_M / 1000 * 30, 2)


def test_a_gcode_from_the_slicer_uses_the_version_there_was_when_it_printed(db_session, sample_3mf_paths):
    p = make.printer(db_session)
    b = make.bundle(db_session, sample_3mf_paths["frog_vt1190"], filename="Frog.3mf")
    v2 = make.add_version(db_session, b, sample_3mf_paths["frog_vt1190"], filename="Frog.3mf")
    v1 = b.versions[-1]
    v1.uploaded_at, v2.uploaded_at = T0, T0 + dt.timedelta(days=10)
    v2.settings = {**v2.settings, "filament_cost": "30"}
    db_session.commit()
    before = _job(db_session, p, "gcodes/FROG.gcode", start=T0 - dt.timedelta(days=1), job_id="1")  # before either
    between = _job(db_session, p, "Frog.gcode", start=T0 + dt.timedelta(days=5), job_id="2")
    after = _job(db_session, p, "Frog.gcode", start=T0 + dt.timedelta(days=20), job_id="3")

    costs = filament_cost.costs(db_session, [before, between, after])
    assert [costs[j.id]["version"] for j in (before, between, after)] == [1, 1, 2]
    assert costs[before.id]["cost_per_kg"] == 16.99 and costs[after.id]["cost_per_kg"] == 30


def test_prusaslicers_own_gcode_name_finds_its_3mf(db_session, sample_3mf_paths):
    # PrusaSlicer names its G-code [input_filename_base]-[printer_settings_id]-[filament_settings_id], with the 3MF's
    # spaces; the 3MF in Farmhand may have come through a browser download with underscores instead
    p = make.printer(db_session)
    quokka = make.bundle(db_session, sample_3mf_paths["frog_vt1190"], filename="V2_BOG_-_Prusa_Slicer_-_MMMini_Quokka v01.3mf")
    make.bundle(db_session, sample_3mf_paths["frog_vt1190"], filename="V2 BOG.3mf")  # also fits, but shorter
    sliced = _job(db_session, p, "V2 BOG - Prusa Slicer - MMMini_Quokka v01-V2_BOG_Rapido_Ace_0.5_WC-Inland_PLA.gcode", job_id="1")
    other = _job(db_session, p, "V2 BOG-V2_BOG_Rapido_Ace_0.5_WC-Inland_PLA.gcode", job_id="2")
    not_a_suffix = _job(db_session, p, "V2 BOG - Prusa Slicer - MMMini_Quokka v012.gcode", job_id="3")

    costs = filament_cost.costs(db_session, [sliced, other, not_a_suffix])
    assert costs[sliced.id]["bundle_id"] == quokka.id
    assert costs[other.id]["filename"] == "V2 BOG ver 1.3mf"
    assert costs[not_a_suffix.id] is None  # "v012" isn't "v01-...", and "V2 BOG" isn't followed by a "-" here


def test_no_cost_without_a_matching_3mf_a_price_or_filament_used(db_session, sample_3mf_paths):
    p = make.printer(db_session)
    other = make.printer(db_session, name="V2 BOG")
    b = make.bundle(db_session, sample_3mf_paths["frog_vt1190"], filename="Frog.3mf")
    unknown = _job(db_session, p, "calibration_cube.gcode", job_id="1")
    elsewhere = _job(db_session, other, "Frog.gcode", job_id="2")  # a 3MF only counts on its own printer
    nothing_used = _job(db_session, p, "Frog.gcode", mm=0, job_id="3")
    assert set(filament_cost.costs(db_session, [unknown, elsewhere, nothing_used]).values()) == {None}

    v = b.versions[0]
    v.settings = {k: val for k, val in v.settings.items() if k != "filament_cost"}
    db_session.commit()
    j = _job(db_session, p, "Frog.gcode", job_id="4")
    assert filament_cost.costs(db_session, [j])[j.id] is None


def test_several_filaments_use_the_first_ones_values(db_session, sample_3mf_paths):
    p = make.printer(db_session)
    b = make.bundle(db_session, sample_3mf_paths["frog_vt1190"], filename="Frog.3mf")
    v = b.versions[0]
    v.settings = {**v.settings, "filament_cost": "20,40", "filament_density": "1.25;1.3", "filament_diameter": "1.75,1.75"}
    db_session.commit()
    j = _job(db_session, p, "Frog.gcode", mm=1000)
    cost = filament_cost.costs(db_session, [j])[j.id]
    assert cost["cost_per_kg"] == 20 and cost["density"] == 1.25


def test_the_print_history_shows_each_prints_filament_cost(api, sample_3mf_paths, monkeypatch):
    fake = FakeMoonraker()
    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(fake.handle))
    c = api
    pid = c.post("/printers", json={"name": "VT 1190", "kind": "Voron", "wired_ip": "10.0.6.21"}).json()["id"]
    mid = c.post("/source-models", data={"name": "Frog.stl", "file_type": "STL"}, files={"file": ("Frog.stl", b"x" * 64)}).json()["id"]
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        c.post("/bundles", data={"source_model_ids": f"[{mid}]", "printer_id": str(pid)}, files={"threemf": ("Frog.3mf", f.read())})
    fake.add_job("000001", "Frog ver 1.gcode", filament_mm=20_000)
    fake.add_job("000002", "benchy.gcode", start=1_700_100_000)
    c.post(f"/printers/{pid}/moonraker/sync")

    benchy, frog = c.get(f"/printers/{pid}/print-jobs").json()["jobs"]
    assert benchy["filament_cost"] is None and benchy["filament_cost_detail"] is None
    assert frog["filament_cost"] == round(20 * GRAMS_PER_M / 1000 * 16.99, 2)
    assert frog["filament_cost_detail"]["filename"] == "Frog ver 1.3mf" and frog["filament_cost_detail"]["density"] == 1.23


# ------------------------------------------------------------------ the price read from the printed G-code


@pytest.fixture()
def synced_printer(api, monkeypatch):
    fake = FakeMoonraker()
    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(fake.handle))
    pid = api.post("/printers", json={"name": "VT 1190", "kind": "Voron", "wired_ip": "10.0.6.21"}).json()["id"]
    return api, fake, pid


def test_the_gcodes_own_price_is_read_once_and_used_first(synced_printer, sample_3mf_paths):
    c, fake, pid = synced_printer
    mid = c.post("/source-models", data={"name": "Frog.stl", "file_type": "STL"}, files={"file": ("Frog.stl", b"x" * 64)}).json()["id"]
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:  # its 3MF says 16.99
        c.post("/bundles", data={"source_model_ids": f"[{mid}]", "printer_id": str(pid)}, files={"threemf": ("Frog.3mf", f.read())})
    meta = fake.add_gcode("jobs/Frog-Trident-Inland_PLA.gcode", cost="25", density="1.25", diameter="1.75")
    fake.add_job("000001", "jobs/Frog-Trident-Inland_PLA.gcode", filament_mm=10_000, metadata=meta)
    fake.add_job("000002", "jobs/Frog-Trident-Inland_PLA.gcode", filament_mm=4_000, status="cancelled", start=1_700_100_000, metadata=meta)
    c.post(f"/printers/{pid}/moonraker/sync")
    assert fake.ranges == [f"bytes={meta['gcode_end_byte']}-"]  # only its settings block, and only once

    cancelled, done = c.get(f"/printers/{pid}/print-jobs").json()["jobs"]
    per_gram = 25 / 1000
    assert done["filament_cost_detail"]["source"] == "gcode" and done["filament_cost_detail"]["cost_per_kg"] == 25
    assert done["filament_cost"] == round(filament_cost.grams(10_000, 1.75, 1.25) * per_gram, 2)
    assert cancelled["filament_cost"] == round(filament_cost.grams(4_000, 1.75, 1.25) * per_gram, 2)  # what it used
    c.post(f"/printers/{pid}/moonraker/sync")
    assert len(fake.ranges) == 1  # not read again


def test_a_gcode_gone_from_the_printer_falls_back_to_the_3mf(synced_printer, sample_3mf_paths):
    c, fake, pid = synced_printer
    mid = c.post("/source-models", data={"name": "Frog.stl", "file_type": "STL"}, files={"file": ("Frog.stl", b"x" * 64)}).json()["id"]
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        c.post("/bundles", data={"source_model_ids": f"[{mid}]", "printer_id": str(pid)}, files={"threemf": ("Frog.3mf", f.read())})
    fake.add_job("000001", "Frog.gcode", filament_mm=10_000, metadata={"modified": 1.0, "size": 10, "gcode_end_byte": 5})
    meta = fake.add_gcode("cube.gcode", cost=None)  # no price in it
    fake.add_job("000002", "cube.gcode", start=1_700_100_000, metadata=meta)
    c.post(f"/printers/{pid}/moonraker/sync")
    c.post(f"/printers/{pid}/moonraker/sync")
    assert len(fake.ranges) == 2  # both asked for once; neither again

    cube, frog = c.get(f"/printers/{pid}/print-jobs").json()["jobs"]
    assert frog["filament_cost_detail"]["source"] == "3mf" and frog["filament_cost_detail"]["cost_per_kg"] == 16.99
    assert cube["filament_cost"] is None


def test_a_printer_that_stops_answering_is_asked_again_next_sync(synced_printer):
    c, fake, pid = synced_printer
    meta = fake.add_gcode("Frog.gcode")
    fake.add_job("000001", "Frog.gcode", metadata=meta)
    real = fake.handle

    def files_down(request):
        if request.url.path.startswith("/server/files/gcodes/"):
            raise httpx.ConnectError("connection refused", request=request)
        return real(request)

    mr_client.transport = httpx.MockTransport(files_down)
    assert c.post(f"/printers/{pid}/moonraker/sync").status_code == 200  # the sync itself still works
    assert c.get(f"/printers/{pid}/print-jobs").json()["jobs"][0]["filament_cost"] is None
    mr_client.transport = httpx.MockTransport(fake.handle)
    c.post(f"/printers/{pid}/moonraker/sync")
    assert c.get(f"/printers/{pid}/print-jobs").json()["jobs"][0]["filament_cost_detail"]["source"] == "gcode"


def test_a_long_history_is_read_a_few_files_per_sync(synced_printer, monkeypatch):
    from app.services.moonraker import history as mr_history

    c, fake, pid = synced_printer
    monkeypatch.setattr(mr_history, "GCODE_READS_PER_SYNC", 2)
    for i in range(5):
        fake.add_job(f"{i:06d}", f"part{i}.gcode", start=1_700_000_000 + i, metadata=fake.add_gcode(f"part{i}.gcode"))
    c.post(f"/printers/{pid}/moonraker/sync")
    assert len(fake.ranges) == 2
    for _ in range(3):
        c.post(f"/printers/{pid}/moonraker/sync")
    assert len(fake.ranges) == 5
    assert all(j["filament_cost_detail"]["source"] == "gcode" for j in c.get(f"/printers/{pid}/print-jobs").json()["jobs"])


def test_settings_are_read_from_a_gcodes_end():
    tail = b"G1 X1\n; total filament cost = 3.01\n; filament_cost = 16.99\n; filament_density = 1.23;1.25\n"
    assert filament_cost.from_gcode(tail) == {"cost_per_kg": 16.99, "density": 1.23, "diameter": None}
    assert filament_cost.from_gcode(b"G28\n") == {"cost_per_kg": None, "density": None, "diameter": None}


def test_a_file_sent_for_every_print_is_read_once_per_new_price(synced_printer):
    # PrusaSlicer sends a fresh copy for each print: the same name, a newer "modified"
    c, fake, pid = synced_printer
    old = fake.add_gcode("Frog.gcode", cost="16.99", modified=1_000.0)
    for i in range(3):
        fake.add_job(f"00000{i}", "Frog.gcode", start=1_700_000_000 + i, metadata=old)
    c.post(f"/printers/{pid}/moonraker/sync")
    assert len(fake.ranges) == 1  # three prints, one read

    new = fake.add_gcode("Frog.gcode", cost="30", modified=2_000.0)  # sliced again with a new price
    fake.add_job("000009", "Frog.gcode", start=1_700_100_000, metadata=new)
    c.post(f"/printers/{pid}/moonraker/sync")
    c.post(f"/printers/{pid}/moonraker/sync")
    assert len(fake.ranges) == 2
    prices = [j["filament_cost_detail"]["cost_per_kg"] for j in c.get(f"/printers/{pid}/print-jobs").json()["jobs"]]
    assert prices == [30, 16.99, 16.99, 16.99]  # the older prints keep the price they were printed at


def test_the_total_cost_is_filament_plus_energy(synced_printer):
    c, fake, pid = synced_printer
    c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": 0.2}})
    priced = fake.add_gcode("Frog.gcode", cost="25", density="1.25")
    fake.add_job("000001", "Frog.gcode", filament_mm=10_000, energy_kwh=1.5, metadata=priced)
    fake.add_job("000002", "Frog.gcode", filament_mm=10_000, start=1_700_100_000, metadata=priced)  # no energy figure
    fake.add_job("000003", "cube.gcode", energy_kwh=1.0, start=1_700_200_000, metadata=fake.add_gcode("cube.gcode", cost=None))
    free = fake.add_gcode("free.gcode", cost="0")  # a price of 0 isn't a price: no filament cost
    fake.add_job("000004", "free.gcode", energy_kwh=1.0, start=1_700_300_000, metadata=free)
    c.post(f"/printers/{pid}/moonraker/sync")

    free_job, cube, no_energy, both = c.get(f"/printers/{pid}/print-jobs").json()["jobs"]
    assert both["total_cost"] == round(both["filament_cost"] + 0.3, 2) and both["energy_cost"] == 0.3
    assert no_energy["energy_cost"] is None and no_energy["total_cost"] == no_energy["filament_cost"]
    assert cube["filament_cost"] is None and cube["energy_cost"] == 0.2 and cube["total_cost"] is None
    assert free_job["total_cost"] is None


def test_the_filament_used_is_also_given_in_grams(synced_printer):
    c, fake, pid = synced_printer
    priced = fake.add_gcode("Frog.gcode", cost="25", density="1.25")
    fake.add_job("000001", "Frog.gcode", filament_mm=10_000, metadata=priced)
    # no price anywhere, but the slicer's estimate says 30 g for 10 m: 3 g a metre
    fake.add_job("000002", "cube.gcode", filament_mm=4_000, start=1_700_100_000,
                 metadata={**fake.add_gcode("cube.gcode", cost=None), "filament_total": 10_000, "filament_weight_total": 30})
    fake.add_job("000003", "mystery.gcode", start=1_700_200_000)  # nothing to go on
    c.post(f"/printers/{pid}/moonraker/sync")

    mystery, cube, frog = c.get(f"/printers/{pid}/print-jobs").json()["jobs"]
    assert frog["filament_grams"] == frog["filament_cost_detail"]["grams"] == round(filament_cost.grams(10_000, 1.75, 1.25), 1)
    assert cube["filament_grams"] == 12.0
    assert mystery["filament_grams"] is None
