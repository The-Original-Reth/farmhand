"""
A printer's energy use, totalled by month (or by day, for the Farm cost page) in the viewer's own time zone: what the
page shows (a year is its months added up). Done here rather than in the browser, so the page gets a row per month
instead of every meter reading ever taken (one every few minutes, for years).

Prints: each print's energy, in the month it started. Whole printer: the meter's rise between one reading and the
next, counted in the month of the later reading (a meter that went backwards was reset, so its new value is what it
used since). The month holding the first reading only covers part of it, and is marked partial.
"""
from __future__ import annotations

import datetime as dt
import threading
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Printer, PrinterEnergyReading, PrintJob
from ..timeutil import as_utc, utc_iso

# {(printer id, time zone, month or day): (what the figures were made from, the rows)}: a printer's readings only ever
# grow, so while they and its prints are as they were, the rows are too
_cache: dict[tuple[int, str, str], tuple[tuple, list[dict]]] = {}
_cache_lock = threading.Lock()


def zone(name: str | None) -> ZoneInfo | dt.timezone:
    """The viewer's time zone by its name ("Europe/London"); UTC when none is given or it isn't one."""
    try:
        return ZoneInfo(name) if name else dt.timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return dt.timezone.utc


def _made_from(db: Session, printer_id: int) -> tuple:
    readings = db.execute(
        select(func.count(), func.max(PrinterEnergyReading.taken_at)).where(PrinterEnergyReading.printer_id == printer_id)
    ).one()
    jobs = db.execute(
        select(func.count(), func.sum(PrintJob.energy_kwh), func.max(PrintJob.start_time))
        .where(PrintJob.printer_id == printer_id, PrintJob.energy_kwh.isnot(None))
    ).one()
    return tuple(readings) + tuple(jobs)


def by_month(db: Session, printer_id: int, tz_name: str | None) -> list[dict]:
    """[{key: "2026-10", prints, print_count, whole, partial}], newest first. whole is None for a month with no readings."""
    return _by_period(db, printer_id, tz_name, "%Y-%m")


def by_day(db: Session, printer_id: int, tz_name: str | None) -> list[dict]:
    """As by_month, a row per day: key "2026-10-05". The day of the first reading is the partial one."""
    return _by_period(db, printer_id, tz_name, "%Y-%m-%d")


def _by_period(db: Session, printer_id: int, tz_name: str | None, fmt: str) -> list[dict]:
    tz = zone(tz_name)
    key = (printer_id, str(tz), fmt)
    made_from = _made_from(db, printer_id)
    with _cache_lock:
        cached = _cache.get(key)
    if cached and cached[0] == made_from:
        return cached[1]

    rows: dict[str, dict] = {}

    def row(at: dt.datetime) -> dict:
        k = as_utc(at).astimezone(tz).strftime(fmt)
        return rows.setdefault(k, {"key": k, "prints": 0.0, "print_count": 0, "whole": None, "partial": False})

    for at, kwh in db.execute(
        select(PrintJob.start_time, PrintJob.energy_kwh)
        .where(PrintJob.printer_id == printer_id, PrintJob.energy_kwh.isnot(None), PrintJob.start_time.isnot(None))
    ):
        r = row(at)
        r["prints"] += kwh
        r["print_count"] += 1

    before = None
    first = True
    for at, now in db.execute(
        select(PrinterEnergyReading.taken_at, PrinterEnergyReading.energy_kwh)
        .where(PrinterEnergyReading.printer_id == printer_id)
        .order_by(PrinterEnergyReading.taken_at)
    ):
        r = row(at)
        if first:
            r["partial"] = True
            r["whole"] = r["whole"] or 0.0
            first = False
        else:
            r["whole"] = (r["whole"] or 0.0) + (now - before if now >= before else now)
        before = now

    out = sorted(rows.values(), key=lambda r: r["key"], reverse=True)
    with _cache_lock:
        _cache[key] = (made_from, out)
    return out


def printer_energy(db: Session, printer: Printer, tz_name: str | None) -> dict:
    """
    The printer's energy use, totalled by month in the viewer's time zone:
      meter: the power meter's latest reading (whole printer, idle included) | null
      print_total_kwh: the printer's own sum of energy over all prints, as of the last sync | null
      print_jobs_kwh: what the prints Farmhand has on record add up to
      months: [{key: "2026-10", prints, print_count, whole, partial}], newest first (see by_month)
    """
    conn = printer.connection_row
    aux = {(t.get("provider"), t.get("field")): t for t in (conn.auxiliary_totals or [])} if conn else {}
    print_total = next((t.get("total") for (_, field), t in aux.items() if field == "energy_consumption"), None)
    jobs_kwh = db.scalar(
        select(func.sum(PrintJob.energy_kwh)).where(PrintJob.printer_id == printer.id, PrintJob.energy_kwh.isnot(None))
    )
    latest = db.execute(
        select(PrinterEnergyReading.taken_at, PrinterEnergyReading.energy_kwh, PrinterEnergyReading.sensor)
        .where(PrinterEnergyReading.printer_id == printer.id)
        .order_by(PrinterEnergyReading.taken_at.desc())
        .limit(1)
    ).first()
    meter = None
    if latest:
        first_at = db.scalar(select(func.min(PrinterEnergyReading.taken_at)).where(PrinterEnergyReading.printer_id == printer.id))
        at, kwh, sensor = latest
        meter = {"sensor": sensor, "energy_kwh": kwh, "taken_at": utc_iso(at), "first_reading_at": utc_iso(first_at)}
    return {
        "meter": meter,
        "print_total_kwh": print_total,
        "print_jobs_kwh": jobs_kwh or 0.0,
        "months": by_month(db, printer.id, tz_name),
    }
