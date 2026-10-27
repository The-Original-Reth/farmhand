"""A printer's energy totalled by month in the viewer's time zone, on the server (services/energy.py)."""
from __future__ import annotations

import datetime as dt

from app.models import PrinterEnergyReading, PrintJob
from app.services import energy, printer_service

UTC = dt.timezone.utc


def _reading(db, printer, at, kwh):
    db.add(PrinterEnergyReading(printer_id=printer.id, taken_at=at, sensor="powermeter", energy_kwh=kwh))
    db.commit()


def _job(db, printer, job_id, at, kwh):
    db.add(PrintJob(printer_id=printer.id, job_id=job_id, filename=f"{job_id}.gcode", status="completed", start_time=at, energy_kwh=kwh))
    db.commit()


def _printer(db):
    return printer_service.create_printer(db, name="VT 1190", kind=None, wired_ip=None, wireless_ip=None)


def test_each_months_prints_and_meter_rise(db_session):
    p = _printer(db_session)
    _reading(db_session, p, dt.datetime(2026, 9, 20, tzinfo=UTC), 100.0)
    _reading(db_session, p, dt.datetime(2026, 9, 28, tzinfo=UTC), 104.0)
    _reading(db_session, p, dt.datetime(2026, 10, 3, tzinfo=UTC), 110.0)
    _reading(db_session, p, dt.datetime(2026, 10, 9, tzinfo=UTC), 2.0)  # the meter was reset: it used 2 since
    _job(db_session, p, "a", dt.datetime(2026, 9, 21, tzinfo=UTC), 1.5)
    _job(db_session, p, "b", dt.datetime(2026, 10, 4, tzinfo=UTC), 2.5)
    _job(db_session, p, "c", dt.datetime(2026, 10, 5, tzinfo=UTC), 0.5)
    months = energy.by_month(db_session, p.id, "UTC")
    assert months == [
        {"key": "2026-10", "prints": 3.0, "print_count": 2, "whole": 8.0, "partial": False},
        {"key": "2026-09", "prints": 1.5, "print_count": 1, "whole": 4.0, "partial": True},  # began part-way through
    ]


def test_months_follow_the_viewers_time_zone(db_session):
    p = _printer(db_session)
    _job(db_session, p, "late", dt.datetime(2026, 11, 1, 3, 0, tzinfo=UTC), 1.0)  # still 31 October in Chicago
    assert [m["key"] for m in energy.by_month(db_session, p.id, "UTC")] == ["2026-11"]
    assert [m["key"] for m in energy.by_month(db_session, p.id, "America/Chicago")] == ["2026-10"]
    assert [m["key"] for m in energy.by_month(db_session, p.id, "Not/A_Zone")] == ["2026-11"]  # unknown: UTC


def test_the_totals_are_kept_until_a_reading_or_print_changes_them(db_session, monkeypatch):
    p = _printer(db_session)
    _reading(db_session, p, dt.datetime(2026, 10, 1, tzinfo=UTC), 10.0)
    _reading(db_session, p, dt.datetime(2026, 10, 2, tzinfo=UTC), 11.0)
    first = energy.by_month(db_session, p.id, "UTC")
    assert energy.by_month(db_session, p.id, "UTC") is first  # nothing changed: the same answer, not worked out again
    _reading(db_session, p, dt.datetime(2026, 10, 3, tzinfo=UTC), 13.0)
    assert energy.by_month(db_session, p.id, "UTC")[0]["whole"] == 3.0
    _job(db_session, p, "a", dt.datetime(2026, 10, 3, tzinfo=UTC), 0.4)
    assert energy.by_month(db_session, p.id, "UTC")[0]["prints"] == 0.4
