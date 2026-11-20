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

Prusa Connect can report a new print's job number before its printing time, so a new print's first report may still
say how long the print before it ran. Such a print counts from when it was first seen until the printer gives its own
time, which then puts its start right (_carried_over, _put_start_right).

A Prusa Connect that keeps its own record of each print (our build of it) says more, and what it says is used
outright: when the print started (which a printing time can't say, since it leaves out pauses), its id for the print,
and the filament it measured with the extruder's odometer from the start ("filament_source": "prusa_connect"). The
plugin also sends the prints that have ended there lately: each one's start, end, outcome and measured filament are
put on Farmhand's record of it (_settle_recent), and one Farmhand missed while it was down is recorded then, once
Farmhand has Prusa Connect's ids for that printer's prints. A print nobody measured gets the slicer's estimate
(filament_estimate.py): Prusa Connect's, for a file it sent, else the 3MF's in Farmhand, else the printed file's.
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
    touched += _settle_recent(db, printer, _recent(printer), now)
    filament_estimate.update(db, printer, touched)
    # the totals of the prints Farmhand has recorded so far; a Prusa Connect printer's filament is its own counter
    record_sync_ok(printer, totals(db, printer.id, counter=_counter(printer, odometer)), now)
    db.commit()
    if printer.status_from:
        _read_prices(db, printer, touched)
    filament_estimate.read_files(db, printer, touched)
    return status, current


def _recent(printer: Printer) -> list[dict]:
    """The prints that ended lately on a printer connected through Prusa Connect, newest first, as the plugin last
    reported them; [] otherwise."""
    if not printer.status_from:
        return []
    from .. import printer_reports

    return printer_reports.recent_prints(printer)


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
    before = row  # the print followed until now: a new one's first report may still carry its printing time

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
    started = _started(current, now)  # when Prusa Connect says it started: used as it is
    if row is None:
        printing = float(current.get("time_printing") or 0)
        carried = started is None and _carried_over(db, printer.id, printing, before, now)
        start = started or (now if carried else now - dt.timedelta(seconds=printing))
        row = PrintJob(printer_id=printer.id, job_id=f"{job_id}@{start:%Y%m%dT%H%M%S}", filename="", status=status, start_time=start)
        fresh = (now - started).total_seconds() <= MEASURE_FROM_START if started else (carried or printing <= MEASURE_FROM_START)
        if odometer is not None and fresh:
            row.job_metadata = {"odometer_start": odometer}  # its filament is measured from here
        if carried:  # its start is put right at the next look, once the printer says how long this print has run
            row.job_metadata = {**(row.job_metadata or {}), UNSURE: {"seen": now.timestamp(), "carried": printing}}
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
    kept = {k: v for k, v in (row.job_metadata or {}).items() if k in _KEPT}
    if started is not None:
        kept.pop(UNSURE, None)
        if as_utc(row.start_time) != started:
            row.start_time = started  # Prusa Connect's own record of when it started
    elif UNSURE in kept:
        _put_start_right(row, kept, row.print_duration, now)
    row.total_duration = max(0.0, (now - as_utc(row.start_time)).total_seconds())
    row.job_metadata = {
        **meta, **kept,
        "path": _file_path(file),
        "estimated_time": row.print_duration + float(remaining) if isinstance(remaining, (int, float)) else meta.get("estimated_time"),
        "progress": current.get("progress"),  # the last seen: how much of its filament an unfinished print used
    }
    if material and not row.job_metadata.get("filament_type"):
        row.job_metadata = {**row.job_metadata, "filament_type": material}
    _connect_facts(row, current)
    measured = _number(current.get("filament_used"))
    start_odo = row.job_metadata.get("odometer_start")
    if measured is not None:  # Prusa Connect measured it from the start, with the extruder's odometer
        row.filament_used = round(measured, 2)
        row.job_metadata = {**row.job_metadata, "filament_measured": True, "filament_source": "prusa_connect"}
    elif isinstance(start_odo, (int, float)) and odometer is not None and odometer >= start_odo:
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
         "modified",  # when its file was printed from, for its price (Prusa Connect)
         "start_unsure",  # its start, until the printer says how long it has really been printing
         "connect_id", "connect_slicer", "connect_final", "filament_source")  # what Prusa Connect said of it

# A new print's first report that still says how long the print before it ran (Prusa Connect updates a printer's job
# number before its printing time): {"seen": when it was first seen, "carried": the time it said}
UNSURE = "start_unsure"


def _carried_over(db: Session, printer_id: int, printing: float, before: PrintJob | None, now: dt.datetime) -> bool:
    """
    Is a new print's first printing time really the print before's? It is when it's the time that print was last seen
    at, or when it would have the new print start before the one before ended (a printer runs one print at a time).
    """
    if printing <= MEASURE_FROM_START:
        return False
    if before is not None and before.print_duration and abs(printing - before.print_duration) <= 5:
        return True
    ended = db.scalar(select(func.max(PrintJob.end_time)).where(PrintJob.printer_id == printer_id, PrintJob.end_time < now))
    return ended is not None and now - dt.timedelta(seconds=printing) < as_utc(ended) - dt.timedelta(seconds=60)


def _put_start_right(row: PrintJob, kept: dict, printing: float, now: dt.datetime) -> None:
    """
    A print whose first report carried the print before's time (UNSURE): once the printer says another, how long this
    one has really been printing, its start is put right. Its filament stays measured from when it was first seen only
    if it had been printing no more than MEASURE_FROM_START by then; else it's left unmeasured, like any print first
    seen part way. Until then it counts as printing since it was first seen.
    """
    unsure = kept[UNSURE]
    if abs(printing - float(unsure.get("carried") or 0)) <= 5:
        row.print_duration = max(0.0, (now - as_utc(row.start_time)).total_seconds())
        return
    began = now - dt.timedelta(seconds=printing)
    row.start_time = began
    if float(unsure.get("seen") or 0) - began.timestamp() > MEASURE_FROM_START:
        for k in ("odometer_start", "odometer_last", "filament_measured"):
            kept.pop(k, None)
        row.filament_used = 0.0
    del kept[UNSURE]


def _file_path(file: dict) -> str | None:
    """Where the printed file is on the printer: PrusaLink's job gives its folder ("/usb") and its (short) name apart;
    a plugin's report gives the whole path."""
    path, name = file.get("path"), file.get("name")
    if path and name and not str(path).lower().endswith((".gcode", ".bgcode", ".gco", ".bgc")):
        return str(path).rstrip("/") + "/" + str(name)
    return path


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def _when(value) -> dt.datetime | None:
    """A time Prusa Connect gave (a datetime, or ISO 8601 text), in UTC; None when there's none."""
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, dt.datetime):
        return None
    return as_utc(value).replace(microsecond=0)


def _started(current: dict, now: dt.datetime) -> dt.datetime | None:
    """When Prusa Connect says the print shown started; None when it doesn't say (or says a time still to come)."""
    started = _when(current.get("started"))
    return started if started is not None and started <= now + dt.timedelta(minutes=1) else None


def _connect_facts(row: PrintJob, current: dict) -> None:
    """Prusa Connect's id for the print and the slicer's figures it read from the file it sent, kept on the record."""
    meta = dict(row.job_metadata or {})
    if current.get("print_id"):
        meta["connect_id"] = str(current["print_id"])
    slicer = current.get("slicer") if isinstance(current.get("slicer"), dict) else {}
    mm, grams = _number(slicer.get("filament_mm")), _number(slicer.get("filament_g"))
    if mm:
        meta["connect_slicer"] = {"filament_mm": mm, "filament_g": grams}
    if meta != (row.job_metadata or {}):
        row.job_metadata = meta


# How a print ended, in Prusa Connect's words, as Farmhand's history says it
OUTCOME = {"finished": "completed", "cancelled": "cancelled", "failed": "error"}


def _settle_recent(db: Session, printer: Printer, prints: list[dict], now: dt.datetime) -> list[PrintJob]:
    """
    The prints Prusa Connect says ended lately: each one's start, end, outcome and measured filament put on Farmhand's
    record of it, once (connect_final). Which record: the one with Prusa Connect's id for it, else the one with its job
    number that Farmhand started recording between six hours before its start and its end. One with no record is
    recorded now. Both only from the first print Farmhand has Prusa Connect's id for on this printer: a print from
    before Farmhand followed Prusa Connect's record is left as it is (it was down then, or older). Returns the records
    changed.
    """
    ended = []
    for p in prints:
        started, finished = _when(p.get("started")), _when(p.get("ended"))
        if p.get("print_id") and started and finished and started <= finished <= now + dt.timedelta(minutes=1):
            ended.append((p, started, finished))
    if not ended:
        return []
    oldest = min(s for _, s, _ in ended)
    rows = list(db.scalars(select(PrintJob).where(
        PrintJob.printer_id == printer.id, PrintJob.job_id.contains("@"),
        PrintJob.start_time >= oldest - dt.timedelta(hours=12),
    )))
    by_id = {str((r.job_metadata or {}).get("connect_id")): r for r in rows if (r.job_metadata or {}).get("connect_id")}
    followed = [as_utc(r.start_time) for r in by_id.values()]
    since = min(followed) if followed else None
    touched = []
    for p, started, finished in ended:
        row = by_id.get(str(p["print_id"]))
        if row is None and since is not None and started > since:
            row = _by_number(rows, by_id, p.get("id"), started, finished, since)
        if row is None:
            if since is None or started <= since or p.get("id") is None:
                continue
            row = PrintJob(printer_id=printer.id, job_id=f"{p['id']}@{started:%Y%m%dT%H%M%S}", status="in_progress",
                           filename=str(p.get("file") or (str(p.get("path") or "").rsplit("/", 1)[-1]) or "(unnamed)"),
                           start_time=started, print_duration=(finished - started).total_seconds())
            db.add(row)
            rows.append(row)
        elif (row.job_metadata or {}).get("connect_final"):
            continue
        by_id[str(p["print_id"])] = row
        _settle(row, p, started, finished, now)
        touched.append(row)
    if touched:
        db.flush()
    return touched


def _by_number(rows: list[PrintJob], linked: dict, number, started: dt.datetime, finished: dt.datetime,
               since: dt.datetime) -> PrintJob | None:
    if number is None:
        return None
    taken = {id(r) for r in linked.values()}
    near = [r for r in rows if id(r) not in taken and r.job_id.startswith(f"{number}@") and as_utc(r.start_time) > since
            and started - dt.timedelta(hours=6) <= as_utc(r.start_time) <= finished]
    return min(near, key=lambda r: abs((as_utc(r.start_time) - started).total_seconds()), default=None)


def _settle(row: PrintJob, p: dict, started: dt.datetime, finished: dt.datetime, now: dt.datetime) -> None:
    """One ended print as Prusa Connect recorded it, put on Farmhand's record."""
    row.start_time, row.end_time = started, finished
    row.status = OUTCOME.get(p.get("outcome")) or (row.status if row.status != "in_progress" else "unknown")
    row.total_duration = (finished - started).total_seconds()
    meta = {**(row.job_metadata or {}), "connect_id": str(p["print_id"]), "connect_final": True}
    meta.pop(UNSURE, None)
    if _number(p.get("progress")) is not None:
        meta["progress"] = _number(p.get("progress"))
    if p.get("path") and not meta.get("path"):
        meta["path"] = p["path"]
    measured = _number(p.get("filament_used"))
    if measured is not None:
        row.filament_used = round(measured, 2)
        meta.update(filament_measured=True, filament_source="prusa_connect")
        meta.pop("filament_estimated", None)
    row.job_metadata = meta
    _connect_facts(row, p)
    row.synced_at = now


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
