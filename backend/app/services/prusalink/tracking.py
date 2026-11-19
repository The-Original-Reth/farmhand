"""
Print history for a PrusaLink printer, recorded by Farmhand itself: PrusaLink only knows the job running now.

Each look at the printer (the page asking for its status, or the background poller every minute) records the
current job as a PrintJob, updates it while it runs, and closes it once it has ended. A job that started and ended
entirely between two looks is missed, and one whose end wasn't seen is closed as "completed" if it was last seen at
99 % or more, else as "unknown". The printer's total print time (what the 1500-hour service and maintenance count
against) is the sum of the prints Farmhand has recorded.

PrusaLink says nothing of the filament a print uses: each print's filament is estimated from the 3MF it was sliced
from (filament_estimate.py), and says so. A printer connected through Prusa Connect reports its extruder's odometer
(the mm of filament it has ever fed): a print Farmhand sees start there is measured instead, as the odometer now less
what it was at the start ("filament_measured"). Prints recorded before, through PrusaLink, keep their estimates.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Printer, PrintJob
from ...timeutil import as_utc
from ..printer_service import record_sync_error, record_sync_ok
from . import client, filament_estimate, printed_filament
from .client import PrusaLinkError, job_file_name

# PrusaLink's job states, as Farmhand's history says them
JOB_STATUS = {"PRINTING": "in_progress", "PAUSED": "in_progress", "FINISHED": "completed", "STOPPED": "cancelled", "ERROR": "error"}


def poll(db: Session, printer: Printer) -> tuple[dict, dict | None]:
    """
    Look at the printer once and bring its history up to date. Returns (status, current job or None) as PrusaLink
    gave them. On failure the error is noted on the printer's connection and raised.
    """
    try:
        status = client.status(printer)
        current = client.job(printer) if (status.get("job") or {}).get("id") is not None else None
    except PrusaLinkError as e:
        record_sync_error(db, printer, e)
        raise
    now = dt.datetime.now(dt.timezone.utc)
    odometer = _odometer(printer)
    touched = _record(db, printer, current, now, odometer, _material(printer))
    filament_estimate.update(db, printer, touched)
    # the totals of the prints Farmhand has recorded so far; a Prusa Connect printer's filament is its own counter
    record_sync_ok(printer, totals(db, printer.id, counter=_counter(printer, odometer)), now)
    db.commit()
    if printer.status_from:
        _read_prices(db, printer, touched)
    return status, current


def _odometer(printer: Printer) -> float | None:
    if not printer.status_from:
        return None
    from .. import printer_reports

    return printer_reports.odometer(printer)


def _read_prices(db: Session, printer: Printer, touched: list[PrintJob]) -> None:
    """The price of what a printer connected through Prusa Connect is printing, read from the printed file once
    (printed_filament): after the commit, in the background."""
    for row in touched:
        if row.end_time is None:
            printed_filament.start(db, printer, row)


def _material(printer: Printer) -> str | None:
    """The filament loaded (PETG, PLA...), as a printer connected through Prusa Connect says; None otherwise."""
    if not printer.status_from:
        return None
    from .. import printer_reports

    found = (printer_reports.extras(printer) or {}).get("material")
    return str(found) if found else None


def _counter(printer: Printer, odometer: float | None) -> float | None:
    """A Prusa Connect printer's lifetime filament (mm): its extruder's odometer now, or while that isn't reported (no
    fresh report), the last one Farmhand noted, so a filament maintenance reminder never jumps back. None for a printer
    that keeps none (PrusaLink)."""
    if not printer.status_from:
        return None
    if odometer is not None:
        return odometer
    kept = (printer.connection_row.totals if printer.connection_row else None) or {}
    return kept.get("total_filament_used") if kept.get("filament_counter") else None


# A print first seen this far in (seconds printing) or less counts as seen from its start, for measuring its filament
MEASURE_FROM_START = 300.0


def _record(
    db: Session, printer: Printer, current: dict | None, now: dt.datetime, odometer: float | None = None,
    material: str | None = None,
) -> list[PrintJob]:
    """Bring the history up to date with what the printer shows now. Returns the prints that changed."""
    touched: list[PrintJob] = []
    link = printer.prusalink_row
    job_id = current.get("id") if current else None
    status = JOB_STATUS.get(current.get("state"), "in_progress") if current else None
    row = db.get(PrintJob, link.current_print_id) if link.current_print_id else None

    if row is not None and (link.current_job_id != job_id or (row.end_time is not None and status == "in_progress")):
        # a different job now (or none, or the same id starting over after a restart): the one before has ended
        if row.end_time is None:
            row.status = "completed" if (link.last_progress or 0) >= 99 else "unknown"
            row.end_time = now
            touched.append(row)
        link.current_job_id = link.current_print_id = link.last_progress = None
        row = None
    if current is None:
        touched += _close_left_open(db, printer.id, None, now)
        return touched

    file = current.get("file") or {}
    if row is None:
        # the same print already on record but not followed here (brought in by Load all from the Farmhand that was
        # watching it): carried on, not counted a second time. Its start can't be worked out again from the printer,
        # which only says how long it has been printing, not how long it was paused.
        row = _open_record(db, printer.id, job_id, job_file_name(current))
    if row is None:
        start = now - dt.timedelta(seconds=float(current.get("time_printing") or 0))
        row = PrintJob(printer_id=printer.id, job_id=f"{job_id}@{start:%Y%m%dT%H%M%S}", filename="", status=status, start_time=start)
        if odometer is not None and float(current.get("time_printing") or 0) <= MEASURE_FROM_START:
            row.job_metadata = {"odometer_start": odometer}  # its filament is measured from here
        if material:
            row.job_metadata = {**(row.job_metadata or {}), "filament_type": material}  # loaded as it started
        if printer.status_from:  # which copy of its file was printed: the one written before this (filament_cost)
            row.job_metadata = {**(row.job_metadata or {}), "modified": start.timestamp()}
        db.add(row)
        db.flush()
    link.current_job_id, link.current_print_id = job_id, row.id
    touched += _close_left_open(db, printer.id, row.id, now)
    if row.end_time is not None:
        return touched  # over, and the printer is still showing it until someone clears it

    meta = file.get("meta") if isinstance(file.get("meta"), dict) else {}
    remaining = current.get("time_remaining")
    row.filename = job_file_name(current) or row.filename or "(unnamed)"
    row.status = status
    row.print_duration = float(current.get("time_printing") or 0)
    row.total_duration = max(0.0, (now - as_utc(row.start_time)).total_seconds())
    kept = {k: v for k, v in (row.job_metadata or {}).items() if k in _KEPT}
    row.job_metadata = {
        **meta, **kept,
        "path": file.get("path"),
        "estimated_time": row.print_duration + float(remaining) if isinstance(remaining, (int, float)) else meta.get("estimated_time"),
        "progress": current.get("progress"),  # the last seen: how much of its filament an unfinished print used
    }
    if material and not row.job_metadata.get("filament_type"):
        row.job_metadata = {**row.job_metadata, "filament_type": material}
    start_odo = row.job_metadata.get("odometer_start")
    if isinstance(start_odo, (int, float)) and odometer is not None and odometer >= start_odo:
        row.filament_used = round(odometer - start_odo, 2)  # measured by the printer, not estimated
        row.job_metadata = {**row.job_metadata, "filament_measured": True, "odometer_last": odometer}
    row.synced_at = now
    link.last_progress = current.get("progress")
    if status != "in_progress":
        row.end_time = now
    return [*touched, row]


# What a print's metadata keeps from one look to the next: its filament estimate (filament_estimate.py)
_KEPT = (filament_estimate.KEY, "filament_estimated", "filament_total", "filament_weight_total",
         "odometer_start", "odometer_last", "filament_measured",  # and its measured filament (Prusa Connect)
         "filament_type",  # the material loaded when it started (Prusa Connect)
         "modified")  # when its file was printed from, for its price (Prusa Connect)


def _open_record(db: Session, printer_id: int, job_id, filename: str | None) -> PrintJob | None:
    """The newest print on record for this printer that hasn't ended, with PrusaLink's job number `job_id` (and the
    same file, when both say one)."""
    if job_id is None:
        return None
    rows = db.scalars(
        select(PrintJob).where(
            PrintJob.printer_id == printer_id, PrintJob.end_time.is_(None), PrintJob.job_id.like(f"{job_id}@%"),
        ).order_by(PrintJob.start_time.desc())
    )
    return next((r for r in rows if not filename or not r.filename or r.filename == filename), None)


def _close_left_open(db: Session, printer_id: int, keep: int | None, now: dt.datetime) -> list[PrintJob]:
    """A PrusaLink printer runs one print at a time: any other print on record as still running (one brought in by
    Load all that ended before this Farmhand saw it) is over, and closed as "unknown"."""
    closed = []
    for row in db.scalars(select(PrintJob).where(PrintJob.printer_id == printer_id, PrintJob.end_time.is_(None))):
        if row.id != keep:
            row.status, row.end_time = "unknown", now
            closed.append(row)
    return closed


def totals(db: Session, printer_id: int, counter: float | None = None) -> dict:
    """
    Lifetime figures for a printer that keeps none itself: what Farmhand has recorded, in Moonraker's shape. counter: a
    Prusa Connect printer's own lifetime filament (its extruder's odometer, mm), given as total_filament_used with
    filament_counter: True; a PrusaLink printer has none (null).
    """
    jobs, print_time, longest = db.execute(
        select(func.count(), func.sum(PrintJob.print_duration), func.max(PrintJob.print_duration)).where(PrintJob.printer_id == printer_id)
    ).one()
    out = {"total_jobs": int(jobs or 0), "total_print_time": float(print_time or 0), "total_filament_used": None, "longest_print": float(longest or 0)}
    if counter is not None:
        out.update(total_filament_used=float(counter), filament_counter=True)
    return out
