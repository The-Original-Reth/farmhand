from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..models import Printer, PrinterEnergyReading, PrintJob
from ..schemas.notes import NotesConflictOut, NotesUpdate
from ..schemas.printer import PrinterOut
from ..services import moonraker as mr
from ..services import energy as energy_service
from ..services import printer_service
from ..timeutil import utc_iso

# Everything a printer's Moonraker gives Farmhand: its connection, its print history (as copied into Farmhand),
# its statistics, and its maintenance reminders (kept in Moonraker, shared with Mainsail).
# A MoonrakerError anywhere becomes a 502 with {"detail", "kind"} (see main.py).
router = APIRouter(prefix="/printers", tags=["moonraker"])


def _printer(db: Session, printer_id: int) -> Printer:
    printer = printer_service.get_printer(db, printer_id)
    if printer is None:
        raise HTTPException(status_code=404, detail="Printer not found")
    return printer


def _sync_state(printer: Printer) -> dict:
    conn = printer.connection_row
    return {
        "last_sync_at": utc_iso(conn.last_sync_at) if conn else None,
        "last_sync_error": conn.last_sync_error if conn else None,
        "totals": conn.totals if conn else None,
    }


@router.get("/{printer_id}/moonraker")
def connection_status(printer_id: int, db: Session = Depends(get_db)):
    """Can Farmhand reach this printer's Moonraker right now, what state is Klipper in, and what is it printing? Never fails: says why."""
    printer = _printer(db, printer_id)
    out = {
        "moonraker_url": printer.moonraker_url,
        "mainsail_url": printer.mainsail_url,
        "has_api_key": printer.has_moonraker_api_key,
        "reachable": False,
        "klippy_state": None,
        "moonraker_version": None,
        "error": None,
        "error_kind": None,
        "print": None,  # the print running or paused right now, if any (see moonraker.live_print)
        **_sync_state(printer),
    }
    try:
        out.update(mr.server_info(printer), reachable=True)
    except mr.MoonrakerError as e:
        out.update(error=str(e), error_kind=e.kind)
        return out
    if out["klippy_state"] == "ready":
        try:
            out["print"] = mr.live_print(printer)
        except mr.MoonrakerError:
            pass  # connected, but Klipper didn't say: shown as not printing
    return out


@router.post("/{printer_id}/moonraker/sync")
def sync(printer_id: int, db: Session = Depends(get_db)):
    """Copy the printer's latest job history and totals into Farmhand."""
    printer = _printer(db, printer_id)
    counts = mr.sync_history(db, printer)
    return {**counts, **_sync_state(printer)}


def _job_out(j: PrintJob) -> dict:
    meta = j.job_metadata or {}
    return {
        "id": j.id,
        "job_id": j.job_id,
        "filename": j.filename,
        "status": j.status,
        "start_time": utc_iso(j.start_time),
        "end_time": utc_iso(j.end_time),
        "print_duration": j.print_duration,
        "total_duration": j.total_duration,
        "filament_used": j.filament_used,
        "slicer": meta.get("slicer"),
        "estimated_time": meta.get("estimated_time"),
        "layer_height": meta.get("layer_height"),
        "filament_type": meta.get("filament_type"),
        "energy_kwh": j.energy_kwh,  # null when the printer has no power meter set up in Moonraker
        "avg_power_w": j.avg_power_w,
        "max_power_w": j.max_power_w,
    }


@router.get("/{printer_id}/print-jobs")
def print_jobs(
    printer_id: int,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, description="completed | cancelled | error | ... ; 'failed' = anything not completed or running"),
    q: str | None = Query(None, description="words that must all appear in the file name"),
    db: Session = Depends(get_db),
):
    """This printer's print history as Farmhand has it (newest first), with how many match in all."""
    _printer(db, printer_id)
    where = [PrintJob.printer_id == printer_id]
    if status == "failed":
        where.append(PrintJob.status.notin_(["completed", "in_progress"]))
    elif status:
        where.append(PrintJob.status == status)
    for word in (q or "").lower().split():
        where.append(func.lower(PrintJob.filename).contains(word, autoescape=True))
    total = db.scalar(select(func.count()).select_from(PrintJob).where(*where))
    jobs = db.scalars(
        select(PrintJob).where(*where).order_by(PrintJob.start_time.desc().nullslast(), PrintJob.id.desc()).limit(limit).offset(offset)
    )
    return {"total": total, "jobs": [_job_out(j) for j in jobs]}


@router.get("/{printer_id}/print-stats")
def print_stats(printer_id: int, db: Session = Depends(get_db)):
    """The printer's own lifetime totals (as of the last sync), and what Farmhand's copy of its history adds up to."""
    printer = _printer(db, printer_id)
    return {**_sync_state(printer), "archive": mr.archive_stats(db, printer_id)}


@router.get("/{printer_id}/energy")
def energy(printer_id: int, tz: str | None = Query(None, max_length=64), db: Session = Depends(get_db)):
    """
    The printer's energy use, totalled by month in the viewer's time zone (tz: its name, e.g. "Europe/London";
    UTC if left out):
      meter: the power meter's latest reading (whole printer, idle included) | null
      print_total_kwh: the printer's own sum of energy over all prints, as of the last sync | null
      print_jobs_kwh: what the prints Farmhand has on record add up to
      months: [{key: "2026-10", prints, print_count, whole, partial}], newest first (see services/energy.py)
    """
    printer = _printer(db, printer_id)
    conn = printer.connection_row
    aux = {(t.get("provider"), t.get("field")): t for t in (conn.auxiliary_totals or [])} if conn else {}
    print_total = next((t.get("total") for (_, field), t in aux.items() if field == "energy_consumption"), None)
    jobs_kwh = db.scalar(
        select(func.sum(PrintJob.energy_kwh)).where(PrintJob.printer_id == printer_id, PrintJob.energy_kwh.isnot(None))
    )
    latest = db.execute(
        select(PrinterEnergyReading.taken_at, PrinterEnergyReading.energy_kwh, PrinterEnergyReading.sensor)
        .where(PrinterEnergyReading.printer_id == printer_id)
        .order_by(PrinterEnergyReading.taken_at.desc())
        .limit(1)
    ).first()
    meter = None
    if latest:
        first_at = db.scalar(select(func.min(PrinterEnergyReading.taken_at)).where(PrinterEnergyReading.printer_id == printer_id))
        at, kwh, sensor = latest
        meter = {"sensor": sensor, "energy_kwh": kwh, "taken_at": utc_iso(at), "first_reading_at": utc_iso(first_at)}
    return {
        "meter": meter,
        "print_total_kwh": print_total,
        "print_jobs_kwh": jobs_kwh or 0.0,
        "months": energy_service.by_month(db, printer_id, tz),
    }


# ------------------------------------------------------------------ the 1500-hour service (kept in Farmhand)


class ServiceDone(BaseModel):
    note: str = Field("", max_length=5000)


class ServiceUpdate(BaseModel):
    enabled: bool


@router.post("/{printer_id}/service/done")
def service_done(printer_id: int, payload: ServiceDone, db: Session = Depends(get_db)):
    """The 1500-hour service was done: the next 1500 print hours count from now. Returns the printer."""
    printer = _printer(db, printer_id)
    with answer_errors():
        mr.service_done(db, printer, note=payload.note)
    return PrinterOut.model_validate(printer_service.get_printer(db, printer_id))


@router.put("/{printer_id}/service/notes", responses={409: {"model": NotesConflictOut}})
def service_notes(printer_id: int, payload: NotesUpdate, db: Session = Depends(get_db)):
    """
    Save the notes kept with the 1500-hour service. Send the revision the text was based on: if someone else has
    saved since, this answers 409 with their current notes (nothing is overwritten). Returns the printer.
    """
    printer = _printer(db, printer_id)
    with answer_errors():
        saved = mr.set_service_notes(db, printer, payload.notes, payload.base_revision)
    return PrinterOut.model_validate(saved)


@router.patch("/{printer_id}/service")
def service_update(printer_id: int, payload: ServiceUpdate, db: Session = Depends(get_db)):
    printer = _printer(db, printer_id)
    with answer_errors():
        mr.set_service_enabled(db, printer, payload.enabled)
    return PrinterOut.model_validate(printer_service.get_printer(db, printer_id))


# ------------------------------------------------------------------ maintenance (in Moonraker, shared with Mainsail)


class Reminder(BaseModel):
    type: str | None = None  # null | "one-time" | "repeat"
    filament: dict | None = None  # {"bool": true, "value": metres}
    printtime: dict | None = None  # {"bool": true, "value": hours}
    date: dict | None = None  # {"bool": true, "value": days}


class MaintenanceIn(BaseModel):
    name: str = Field(max_length=200)
    note: str = Field("", max_length=5000)
    reminder: Reminder | None = None


class MaintenanceUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    note: str | None = Field(None, max_length=5000)
    reminder: Reminder | None = None


class PerformIn(BaseModel):
    note: str = Field("", max_length=5000)



@router.get("/{printer_id}/maintenance")
def list_maintenance(printer_id: int, db: Session = Depends(get_db)):
    return mr.list_maintenance(_printer(db, printer_id))


@router.post("/{printer_id}/maintenance", status_code=201)
def add_maintenance(printer_id: int, payload: MaintenanceIn, db: Session = Depends(get_db)):
    printer = _printer(db, printer_id)
    reminder = payload.reminder.model_dump() if payload.reminder else None
    with answer_errors():
        key = mr.add_maintenance(printer, name=payload.name, note=payload.note, reminder=reminder)
    return {"id": key, **mr.list_maintenance(printer)}


@router.put("/{printer_id}/maintenance/{entry_id}")
def update_maintenance(printer_id: int, entry_id: str, payload: MaintenanceUpdate, db: Session = Depends(get_db)):
    printer = _printer(db, printer_id)
    reminder = payload.reminder.model_dump() if payload.reminder else None
    with answer_errors():
        mr.update_maintenance(printer, entry_id, name=payload.name, note=payload.note, reminder=reminder)
    return mr.list_maintenance(printer)


@router.post("/{printer_id}/maintenance/{entry_id}/done")
def perform_maintenance(printer_id: int, entry_id: str, payload: PerformIn, db: Session = Depends(get_db)):
    """Mark it done on the printer (Mainsail sees it too). A repeating reminder starts its next round."""
    printer = _printer(db, printer_id)
    with answer_errors():
        next_id = mr.perform_maintenance(printer, entry_id, note=payload.note)
    return {"next_id": next_id, **mr.list_maintenance(printer)}


@router.delete("/{printer_id}/maintenance/{entry_id}")
def delete_maintenance(printer_id: int, entry_id: str, confirm: bool = Query(False), db: Session = Depends(get_db)):
    if not confirm:
        raise HTTPException(status_code=409, detail="Deleting is permanent (in Mainsail too) — pass confirm=true to proceed")
    printer = _printer(db, printer_id)
    with answer_errors():
        mr.delete_maintenance(printer, entry_id)
    return mr.list_maintenance(printer)
