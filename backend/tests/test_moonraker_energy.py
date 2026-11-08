"""A Klipper printer's energy: each print's, the power meter's readings, and what it costs."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import sessionmaker

from app.models import PrinterConnection, PrinterEnergyReading, PrintJob
from app.services import moonraker as mr
from app.services import printer_service
from app.services.moonraker import history as mr_history

from .factories import klipper_printer as _printer


# ------------------------------------------------------------------ energy


def test_sync_brings_each_prints_energy_and_the_totals(db_session, moonraker):
    moonraker.add_job("000001", "a.gcode", print_s=2 * 3600, energy_kwh=0.5)
    moonraker.add_job("000002", "b.gcode", start=1_700_100_000)  # no power meter back then
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    jobs = {j.job_id: j for j in db_session.query(PrintJob)}
    assert jobs["000001"].energy_kwh == 0.5 and jobs["000001"].avg_power_w == 250 and jobs["000001"].max_power_w == 650
    assert jobs["000002"].energy_kwh is None
    assert p.connection_row.auxiliary_totals[0]["total"] == 0.5


def test_jobs_synced_before_energy_was_stored_get_it_on_the_next_sync(db_session, moonraker):
    moonraker.add_job("000001", "a.gcode", energy_kwh=1.2)
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    job = db_session.query(PrintJob).one()
    job.energy_kwh = None  # as an older copy would have it
    db_session.commit()
    assert mr.sync_history(db_session, p)["updated"] == 1
    assert db_session.query(PrintJob).one().energy_kwh == 1.2


def test_an_energy_value_in_wh_is_converted():
    assert mr_history._aux({"auxiliary_data": [{"name": "energy_consumption", "value": 1500, "units": "Wh"}]}, "energy_consumption") == 1.5


def test_each_sync_records_a_meter_reading_but_not_twice_in_a_row(db_session, moonraker, monkeypatch):
    p = _printer(db_session)
    mr.sync_history(db_session, p)
    assert db_session.query(PrinterEnergyReading).count() == 0  # no meter: nothing recorded, and no error
    moonraker.meter_kwh = 2070.38
    mr.sync_history(db_session, p)
    mr.sync_history(db_session, p)  # straight after: skipped
    readings = db_session.query(PrinterEnergyReading).all()
    assert len(readings) == 1 and readings[0].energy_kwh == 2070.38 and readings[0].sensor == "powermeter"
    monkeypatch.setattr(mr_history, "READING_SPACING", dt.timedelta(0))
    moonraker.meter_kwh = 2071.0
    mr.sync_history(db_session, p)
    assert [r.energy_kwh for r in db_session.query(PrinterEnergyReading).order_by(PrinterEnergyReading.id)] == [2070.38, 2071.0]


def test_the_energy_endpoint(klipper, moonraker, monkeypatch):
    c, pid = klipper
    assert c.get(f"/printers/{pid}/energy").json() == {"meter": None, "print_total_kwh": None, "print_jobs_kwh": 0.0, "months": []}
    monkeypatch.setattr(mr_history, "READING_SPACING", dt.timedelta(0))
    moonraker.meter_kwh = 100.0
    moonraker.add_job("000001", "a.gcode", start=1_700_000_000, energy_kwh=0.5)
    moonraker.add_job("000002", "b.gcode", start=1_702_600_000, energy_kwh=0.7)
    c.post(f"/printers/{pid}/moonraker/sync")
    moonraker.meter_kwh = 101.5
    c.post(f"/printers/{pid}/moonraker/sync")
    e = c.get(f"/printers/{pid}/energy").json()
    assert e["meter"]["energy_kwh"] == 101.5 and e["meter"]["sensor"] == "powermeter"
    assert e["print_total_kwh"] == 1.2
    assert e["print_jobs_kwh"] == 1.2
    # by month (UTC when no time zone is given): Nov 2023 and Dec 2023 for the prints, the meter's rise this month
    months = {m["key"]: m for m in e["months"]}
    assert months["2023-11"]["prints"] == 0.5 and months["2023-12"]["print_count"] == 1
    this_month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    assert months[this_month]["whole"] == 1.5 and months[this_month]["partial"] is True  # the first reading's month
    assert [m["key"] for m in e["months"]] == sorted(months, reverse=True)  # newest first
    assert c.get(f"/printers/{pid}/print-jobs").json()["jobs"][0]["energy_kwh"] == 0.7


def test_the_poller_syncs_every_active_printer_and_survives_one_being_off(db_session, moonraker, monkeypatch):
    from app import printer_poller

    on = _printer(db_session, "On", "10.0.6.21")
    printer_service.create_printer(db_session, name="No address", kind=None, wired_ip=None, wireless_ip=None)
    retired = _printer(db_session, "Retired", "10.0.6.22")
    printer_service.set_decommissioned(db_session, retired.id, True)
    monkeypatch.setattr(printer_poller, "SessionLocal", sessionmaker(bind=db_session.get_bind(), future=True))
    moonraker.add_job("000001", "a.gcode")
    printer_poller.PrinterPoller().run_once()
    db_session.expire_all()
    assert db_session.get(PrinterConnection, on.id).last_sync_at is not None
    assert db_session.get(PrinterConnection, retired.id) is None  # decommissioned: left alone
    moonraker.down = True
    printer_poller.PrinterPoller().run_once()  # must not raise
    db_session.expire_all()
    assert "Couldn't connect" in db_session.get(PrinterConnection, on.id).last_sync_error


# ------------------------------------------------------------------ what it costs


def test_each_prints_energy_cost_uses_the_average_price_per_kwh(klipper, moonraker):
    c, pid = klipper
    moonraker.meter_kwh = 100.0
    moonraker.add_job("000001", "frog.gcode", energy_kwh=1.25)
    moonraker.add_job("000002", "shark.gcode", start=1_700_100_000)  # no power meter reading for this one
    c.post(f"/printers/{pid}/moonraker/sync")
    r = c.get(f"/printers/{pid}/print-jobs").json()
    assert r["energy_price_per_kwh"] is None and [j["energy_cost"] for j in r["jobs"]] == [None, None]  # no price yet

    c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": 0.16321}})
    r = c.get(f"/printers/{pid}/print-jobs").json()
    assert r["energy_price_per_kwh"] == 0.16321
    assert [j["energy_cost"] for j in r["jobs"]] == [None, round(1.25 * 0.16321, 2)]


def test_a_prints_energy_is_priced_at_its_months_price(klipper, moonraker):
    c, pid = klipper
    moonraker.add_job("000001", "frog.gcode", start=dt.datetime(2026, 9, 10, tzinfo=dt.timezone.utc).timestamp(), energy_kwh=1.0)
    moonraker.add_job("000002", "shark.gcode", start=dt.datetime(2026, 11, 2, tzinfo=dt.timezone.utc).timestamp(), energy_kwh=1.0)
    # just after midnight on the 1st in UTC: still October in New York
    moonraker.add_job("000003", "cube.gcode", start=dt.datetime(2026, 11, 1, 2, tzinfo=dt.timezone.utc).timestamp(), energy_kwh=1.0)
    c.post(f"/printers/{pid}/moonraker/sync")
    c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": 0.1, "energy_price_from": "2026-09"}})
    c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": 0.2, "energy_price_from": "2026-11"}})
    c.put("/settings/config", json={"preferences": {"energy_price_months": {"2026-10": 0.5}}})

    jobs = {j["job_id"]: j for j in c.get(f"/printers/{pid}/print-jobs").json()["jobs"]}
    assert {k: j["energy_cost"] for k, j in jobs.items()} == {"000001": 0.1, "000002": 0.2, "000003": 0.2}
    jobs = {j["job_id"]: j for j in c.get(f"/printers/{pid}/print-jobs", params={"tz": "America/New_York"}).json()["jobs"]}
    assert jobs["000003"]["energy_cost"] == 0.5 and jobs["000003"]["energy_price"] == 0.5
