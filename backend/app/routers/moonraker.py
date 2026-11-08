from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..schemas.maintenance import MaintenanceIn, MaintenanceUpdate, PerformIn, ServiceDone, ServiceUpdate
from ..schemas.notes import NotesConflictOut, NotesUpdate
from ..schemas.printer import PrinterOut
from ..services import cameras, print_history, printer_service
from ..services import energy as energy_service
from ..services import moonraker as mr
from .common import require_confirm, require_printer, sync_state

# Everything a printer's Moonraker gives Farmhand: its connection, its print history (as copied into Farmhand),
# its statistics, its energy and cameras, and its maintenance reminders (kept in Moonraker, shared with Mainsail).
# A MoonrakerError anywhere becomes a 502 with {"detail", "kind"} (see main.py).
router = APIRouter(prefix="/printers", tags=["moonraker"])


@router.get("/{printer_id}/moonraker")
def connection_status(printer_id: int, db: Session = Depends(get_db)):
    """Can Farmhand reach this printer's Moonraker right now, what state is Klipper in, and what is it printing? Never fails: says why."""
    printer = require_printer(db, printer_id)
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
        **sync_state(printer),
    }
    try:
        out.update(mr.server_info(printer), reachable=True)
    except mr.MoonrakerError as e:
        out.update(error=str(e), error_kind=e.kind)
        return out
    # the one of its IPs it answered at just now (its Wi-Fi one when its cable is out)
    out.update(moonraker_url=printer.moonraker_url, mainsail_url=printer.mainsail_url)
    if out["klippy_state"] == "ready":
        try:
            out["print"] = mr.live_print(printer)
        except mr.MoonrakerError:
            pass  # connected, but Klipper didn't say: shown as not printing
    return out


@router.get("/{printer_id}/webcams")
def webcams(printer_id: int, db: Session = Depends(get_db)):
    """
    The printer's cameras for the Monitor page: as set up in Mainsail, plus one Farmhand plays itself through go2rtc
    (a Buddy3D's). Never fails: says why there are none. board: the computer a Klipper printer runs on, shown in the
    corner of its cameras ({name: "Pi 4", model, memory_gb}, see moonraker.board), or null.
    """
    return cameras.printer_cameras(require_printer(db, printer_id))


@router.post("/{printer_id}/moonraker/sync")
def sync(printer_id: int, db: Session = Depends(get_db)):
    """Copy the printer's latest job history and totals into Farmhand."""
    printer = require_printer(db, printer_id)
    counts = mr.sync_history(db, printer)
    return {**counts, **sync_state(printer)}


@router.get("/{printer_id}/print-jobs")
def print_jobs(
    printer_id: int,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, description="completed | cancelled | error | ... ; 'failed' = anything not completed or running"),
    q: str | None = Query(None, description="words that must all appear in the file name"),
    tz: str | None = Query(None, max_length=64, description="the viewer's time zone: which month a print's energy is priced in"),
    db: Session = Depends(get_db),
):
    """
    This printer's print history as Farmhand has it (newest first), with how many match in all. A print's energy is
    priced at its month's price per kWh (the month it started in, in the viewer's time zone; see config_store).
    """
    require_printer(db, printer_id)
    return print_history.jobs_page(db, printer_id, limit=limit, offset=offset, status=status, q=q, tz=tz)


@router.get("/{printer_id}/print-stats")
def print_stats(printer_id: int, db: Session = Depends(get_db)):
    """The printer's own lifetime totals (as of the last sync), and what Farmhand's copy of its history adds up to."""
    printer = require_printer(db, printer_id)
    return {**sync_state(printer), "archive": mr.archive_stats(db, printer_id)}


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
    return energy_service.printer_energy(db, require_printer(db, printer_id), tz)


# ------------------------------------------------------------------ the 1500-hour service (kept in Farmhand)


@router.post("/{printer_id}/service/done")
def service_done(printer_id: int, payload: ServiceDone, db: Session = Depends(get_db)):
    """The 1500-hour service was done: the next 1500 print hours count from now. Returns the printer."""
    printer = require_printer(db, printer_id)
    with answer_errors():
        mr.service_done(db, printer, note=payload.note)
    return PrinterOut.model_validate(printer_service.get_printer(db, printer_id))


@router.put("/{printer_id}/service/notes", responses={409: {"model": NotesConflictOut}})
def service_notes(printer_id: int, payload: NotesUpdate, db: Session = Depends(get_db)):
    """
    Save the notes kept with the 1500-hour service. Send the revision the text was based on: if someone else has
    saved since, this answers 409 with their current notes (nothing is overwritten). Returns the printer.
    """
    printer = require_printer(db, printer_id)
    with answer_errors():
        saved = mr.set_service_notes(db, printer, payload.notes, payload.base_revision)
    return PrinterOut.model_validate(saved)


@router.patch("/{printer_id}/service")
def service_update(printer_id: int, payload: ServiceUpdate, db: Session = Depends(get_db)):
    printer = require_printer(db, printer_id)
    with answer_errors():
        mr.set_service_enabled(db, printer, payload.enabled)
    return PrinterOut.model_validate(printer_service.get_printer(db, printer_id))


# ------------------------------------------------------------------ maintenance (in Moonraker, shared with Mainsail)


@router.get("/{printer_id}/maintenance")
def list_maintenance(printer_id: int, db: Session = Depends(get_db)):
    return mr.list_maintenance(require_printer(db, printer_id))


@router.post("/{printer_id}/maintenance", status_code=201)
def add_maintenance(printer_id: int, payload: MaintenanceIn, db: Session = Depends(get_db)):
    printer = require_printer(db, printer_id)
    reminder = payload.reminder.model_dump() if payload.reminder else None
    with answer_errors():
        key = mr.add_maintenance(printer, name=payload.name, note=payload.note, reminder=reminder)
    return {"id": key, **mr.list_maintenance(printer)}


@router.put("/{printer_id}/maintenance/{entry_id}")
def update_maintenance(printer_id: int, entry_id: str, payload: MaintenanceUpdate, db: Session = Depends(get_db)):
    printer = require_printer(db, printer_id)
    reminder = payload.reminder.model_dump() if payload.reminder else None
    with answer_errors():
        mr.update_maintenance(printer, entry_id, name=payload.name, note=payload.note, reminder=reminder)
    return mr.list_maintenance(printer)


@router.post("/{printer_id}/maintenance/{entry_id}/done")
def perform_maintenance(printer_id: int, entry_id: str, payload: PerformIn, db: Session = Depends(get_db)):
    """Mark it done on the printer (Mainsail sees it too). A repeating reminder starts its next round."""
    printer = require_printer(db, printer_id)
    with answer_errors():
        next_id = mr.perform_maintenance(printer, entry_id, note=payload.note)
    return {"next_id": next_id, **mr.list_maintenance(printer)}


@router.delete("/{printer_id}/maintenance/{entry_id}")
def delete_maintenance(printer_id: int, entry_id: str, confirm: bool = Query(False), db: Session = Depends(get_db)):
    require_confirm(confirm, "Deleting is permanent (in Mainsail too) — pass confirm=true to proceed")
    printer = require_printer(db, printer_id)
    with answer_errors():
        mr.delete_maintenance(printer, entry_id)
    return mr.list_maintenance(printer)
