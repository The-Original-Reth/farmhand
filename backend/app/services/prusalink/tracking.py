"""
Print history for a PrusaLink printer, recorded by Farmhand itself: PrusaLink only knows the job running now.

Each look at the printer (the page asking for its status, or the background poller every minute) records the
current job as a PrintJob, updates it while it runs, and closes it once it has ended. A job that started and ended
entirely between two looks is missed, and one whose end wasn't seen is closed as "completed" if it was last seen at
99 % or more, else as "unknown". The printer's total print time (what the 1500-hour service and maintenance count
against) is the sum of the prints Farmhand has recorded.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Printer, PrinterServiceReminder, PrintJob
from ...timeutil import as_utc
from ..moonraker.history import _connection
from . import client
from .client import PrusaLinkError

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
        db.rollback()
        conn = _connection(printer)
        conn.last_sync_error = str(e)
        db.commit()
        raise
    now = dt.datetime.now(dt.timezone.utc)
    _record(db, printer, current, now)
    conn = _connection(printer)
    conn.totals = totals(db, printer.id)
    conn.last_sync_at = now
    conn.last_sync_error = None
    if printer.service_row is None:
        # the 1500-hour service count starts from the print time Farmhand has recorded so far
        printer.service_row = PrinterServiceReminder(
            printer_id=printer.id, start_printtime=float(conn.totals["total_print_time"]), history=[]
        )
    db.commit()
    return status, current


def _record(db: Session, printer: Printer, current: dict | None, now: dt.datetime) -> None:
    link = printer.prusalink_row
    job_id = current.get("id") if current else None
    status = JOB_STATUS.get(current.get("state"), "in_progress") if current else None
    row = db.get(PrintJob, link.current_print_id) if link.current_print_id else None

    if row is not None and (link.current_job_id != job_id or (row.end_time is not None and status == "in_progress")):
        # a different job now (or none, or the same id starting over after a restart): the one before has ended
        if row.end_time is None:
            row.status = "completed" if (link.last_progress or 0) >= 99 else "unknown"
            row.end_time = now
        link.current_job_id = link.current_print_id = link.last_progress = None
        row = None
    if current is None:
        return

    if row is None:
        start = now - dt.timedelta(seconds=float(current.get("time_printing") or 0))
        row = PrintJob(printer_id=printer.id, job_id=f"{job_id}@{start:%Y%m%dT%H%M%S}", filename="", status=status, start_time=start)
        db.add(row)
        db.flush()
        link.current_job_id, link.current_print_id = job_id, row.id
    if row.end_time is not None:
        return  # over, and the printer is still showing it until someone clears it

    file = current.get("file") or {}
    meta = file.get("meta") if isinstance(file.get("meta"), dict) else {}
    remaining = current.get("time_remaining")
    row.filename = file.get("display_name") or file.get("name") or row.filename or "(unnamed)"
    row.status = status
    row.print_duration = float(current.get("time_printing") or 0)
    row.total_duration = max(0.0, (now - as_utc(row.start_time)).total_seconds())
    row.job_metadata = {
        **meta,
        "path": file.get("path"),
        "estimated_time": row.print_duration + float(remaining) if isinstance(remaining, (int, float)) else meta.get("estimated_time"),
    }
    row.synced_at = now
    link.last_progress = current.get("progress")
    if status != "in_progress":
        row.end_time = now


def totals(db: Session, printer_id: int) -> dict:
    """Lifetime figures for a printer that keeps none itself: what Farmhand has recorded, in Moonraker's shape."""
    jobs, print_time, longest = db.execute(
        select(func.count(), func.sum(PrintJob.print_duration), func.max(PrintJob.print_duration)).where(PrintJob.printer_id == printer_id)
    ).one()
    return {"total_jobs": int(jobs or 0), "total_print_time": float(print_time or 0), "total_filament_used": None, "longest_print": float(longest or 0)}
