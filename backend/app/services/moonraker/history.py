"""Print history and lifetime totals, copied into Farmhand on every sync, plus the energy meter's readings."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import GcodeFilament, Printer, PrinterEnergyReading, PrintJob
from ...timeutil import as_utc
from .. import filament_cost
from ..printer_service import ensure_connection, record_sync_error, record_sync_ok
from .client import MoonrakerError, call, gcode_tail, history_totals, meter_reading

PAGE = 100  # history entries asked for per request


def _ts(value) -> dt.datetime | None:
    return dt.datetime.fromtimestamp(value, dt.timezone.utc) if value else None


def sync_history(db: Session, printer: Printer) -> dict:
    """
    Copy the printer's job history and totals into Farmhand. Newest first, page by page, stopping at the first
    page with nothing new or still changing (older jobs are settled). Jobs the printer has since forgotten are kept.
    Returns {"added", "updated"}; on failure the error is recorded on the connection and raised.
    """
    conn = ensure_connection(printer)
    known: dict[str, PrintJob] = {}  # the jobs on the pages fetched so far (only those are looked up, not every job)
    added = updated = 0
    try:
        totals, aux_totals = history_totals(printer)
        reading = meter_reading(printer)
        start = 0
        while True:
            page = call(printer, "GET", "/server/history/list", params={"limit": PAGE, "start": start, "order": "desc"})
            jobs = page.get("jobs") or []
            ids = [str(raw.get("job_id")) for raw in jobs if raw.get("job_id") is not None]
            if ids:
                known.update((j.job_id, j) for j in db.scalars(
                    select(PrintJob).where(PrintJob.printer_id == printer.id, PrintJob.job_id.in_(ids))
                ))
            changed_here = 0
            for raw in jobs:
                fields = _job_fields(raw)
                existing = known.get(fields["job_id"])
                if existing is None:
                    job = PrintJob(printer_id=printer.id, **fields)
                    db.add(job)
                    known[job.job_id] = job
                    added += 1
                    changed_here += 1
                elif any(not _same(getattr(existing, k), v) for k, v in fields.items() if k not in ("job_metadata", "auxiliary")):
                    for k, v in fields.items():
                        setattr(existing, k, v)
                    existing.synced_at = dt.datetime.now(dt.timezone.utc)
                    updated += 1
                    changed_here += 1
            if len(jobs) < PAGE or changed_here == 0:
                break
            start += PAGE
    except MoonrakerError as e:
        record_sync_error(db, printer, e)
        raise
    conn.auxiliary_totals = aux_totals
    if reading is not None:
        _record_reading(db, printer, *reading)
    record_sync_ok(printer, totals, dt.datetime.now(dt.timezone.utc))  # the totals are the printer's own
    db.commit()
    read_gcode_filaments(db, printer, list(known.values()))
    return {"added": added, "updated": updated}


GCODE_READS_PER_SYNC = 10  # G-codes read for their filament price per sync; a long history is caught up over a few


def read_gcode_filaments(db: Session, printer: Printer, synced: list[PrintJob]) -> int:
    """
    Read the filament price, density and diameter from the end of G-codes in the history (see GcodeFilament): a file
    whose name hasn't been read yet, or one uploaded again since it was (a newer "modified" in a print's metadata:
    PrusaSlicer sends a fresh copy each time). The jobs just synced first, then the rest of the history, one read per
    name. At most GCODE_READS_PER_SYNC files; stops quietly if the printer stops answering (the next sync carries on).
    Returns how many were read.
    """
    latest: dict[str, float] = {}  # file name -> the newest copy of it read so far
    for f, m in db.execute(
        select(GcodeFilament.filename, GcodeFilament.modified).where(GcodeFilament.printer_id == printer.id)
    ):
        latest[f] = max(m, latest.get(f, m))
    todo: dict[str, dict] = {}  # file name -> the metadata of its newest copy not read yet
    for j in synced:
        meta = j.job_metadata or {}
        modified = filament_cost.file_modified(meta)
        if j.filament_used and modified > latest.get(j.filename, -1):
            if j.filename not in todo or modified > filament_cost.file_modified(todo[j.filename]):
                todo[j.filename] = meta
    names = db.scalars(
        select(PrintJob.filename).where(PrintJob.printer_id == printer.id, PrintJob.filament_used > 0).distinct()
    ).all()
    for name in names:
        if len(todo) >= GCODE_READS_PER_SYNC:
            break
        if name in latest or name in todo:
            continue
        newest = db.scalar(
            select(PrintJob).where(PrintJob.printer_id == printer.id, PrintJob.filename == name)
            .order_by(PrintJob.start_time.desc().nullslast()).limit(1)
        )
        todo[name] = newest.job_metadata or {}

    read = 0
    for name, meta in list(todo.items())[:GCODE_READS_PER_SYNC]:
        row = GcodeFilament(printer_id=printer.id, filename=name, modified=filament_cost.file_modified(meta))
        try:
            tail = gcode_tail(printer, name, meta.get("gcode_end_byte"), meta.get("size"))
        except MoonrakerError as e:
            if e.kind != "not_found":
                break  # can't ask right now: tried again next sync
            row.problem = "This G-code isn't on the printer any more."
        else:
            found = filament_cost.from_gcode(tail)
            row.cost_per_kg, row.density, row.diameter = found["cost_per_kg"], found["density"], found["diameter"]
            if row.cost_per_kg is None or row.density is None:
                row.problem = "This G-code has no filament price or density in its settings."
        db.add(row)
        db.commit()
        read += 1
    return read

def _same(stored, new) -> bool:
    """Equal, treating times as instants: SQLite hands back times without a timezone, Postgres with one."""
    if isinstance(stored, dt.datetime) and isinstance(new, dt.datetime):
        return as_utc(stored) == new
    return stored == new


READING_SPACING = dt.timedelta(minutes=5)  # a sync soon after another doesn't add a near-duplicate meter reading


def _record_reading(db: Session, printer: Printer, sensor: str, kwh: float) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    last = db.scalar(
        select(PrinterEnergyReading).where(PrinterEnergyReading.printer_id == printer.id)
        .order_by(PrinterEnergyReading.taken_at.desc()).limit(1)
    )
    if last is not None:
        if now - as_utc(last.taken_at) < READING_SPACING:
            return
    db.add(PrinterEnergyReading(printer_id=printer.id, taken_at=now, sensor=sensor, energy_kwh=kwh))


def _aux(raw: dict, name: str) -> float | None:
    """One of the values Moonraker recorded alongside a job (from a [sensor] with history fields), as a number."""
    for item in raw.get("auxiliary_data") or []:
        if item.get("name") == name and isinstance(item.get("value"), (int, float)):
            value = float(item["value"])
            return value / 1000 if name == "energy_consumption" and item.get("units") == "Wh" else value
    return None


def _job_fields(raw: dict) -> dict:
    return {
        "energy_kwh": _aux(raw, "energy_consumption"),
        "avg_power_w": _aux(raw, "average_power"),
        "max_power_w": _aux(raw, "max_power"),
        "auxiliary": raw.get("auxiliary_data") or [],
        "job_id": str(raw.get("job_id")),
        "filename": raw.get("filename") or "",
        "status": raw.get("status") or "unknown",
        "start_time": _ts(raw.get("start_time")),
        "end_time": _ts(raw.get("end_time")),
        "print_duration": float(raw.get("print_duration") or 0),
        "total_duration": float(raw.get("total_duration") or 0),
        "filament_used": float(raw.get("filament_used") or 0),
        "job_metadata": raw.get("metadata") or {},
    }


def archive_stats(db: Session, printer_id: int) -> dict:
    """What Farmhand's own copy of the history adds up to (it can hold jobs the printer no longer has)."""
    rows = db.execute(
        select(PrintJob.status, func.count(), func.sum(PrintJob.print_duration), func.sum(PrintJob.filament_used))
        .where(PrintJob.printer_id == printer_id)
        .group_by(PrintJob.status)
    ).all()
    by_status = {status: count for status, count, _, _ in rows}
    return {
        "jobs": sum(by_status.values()),
        "by_status": by_status,
        "print_time": float(sum(t or 0 for _, _, t, _ in rows)),
        "filament_used": float(sum(f or 0 for _, _, _, f in rows)),
    }
