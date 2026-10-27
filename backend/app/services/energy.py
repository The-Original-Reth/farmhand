"""
A printer's energy use, totalled by month in the viewer's own time zone: what the page shows (a year is its months
added up). Done here rather than in the browser, so the page gets a row per month instead of every meter reading
ever taken (one every few minutes, for years).

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

from ..models import PrinterEnergyReading, PrintJob
from ..timeutil import as_utc

# {(printer id, time zone): (what the figures were made from, the months)}: a printer's readings only ever grow, so
# while they and its prints are as they were, the months are too
_cache: dict[tuple[int, str], tuple[tuple, list[dict]]] = {}
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
    tz = zone(tz_name)
    key = (printer_id, str(tz))
    made_from = _made_from(db, printer_id)
    with _cache_lock:
        cached = _cache.get(key)
    if cached and cached[0] == made_from:
        return cached[1]

    rows: dict[str, dict] = {}

    def row(at: dt.datetime) -> dict:
        local = as_utc(at).astimezone(tz)
        k = f"{local.year}-{local.month:02d}"
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

    months = sorted(rows.values(), key=lambda r: r["key"], reverse=True)
    with _cache_lock:
        _cache[key] = (made_from, months)
    return months
