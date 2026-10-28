from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Printer
from ..services import prusalink as pl
from ..services.send_print import PRUSALINK_FREE
from .common import require_printer, sync_state

# A PrusaLink printer (Prusa Core One, MK4, XL...): its live status and sending it a print. Its print history,
# statistics, 1500-hour service and maintenance use the same routes as a Moonraker printer's (routers/moonraker.py).
# A PrusaLinkError becomes a 502 with {"detail", "kind"} (see main.py).
router = APIRouter(prefix="/printers", tags=["prusalink"])

PRINTABLE = (".bgcode", ".gcode")  # what a Prusa printer can print: a sliced file, not a 3MF project
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024


def _printer(db: Session, printer_id: int) -> Printer:
    printer = require_printer(db, printer_id)
    if printer.connection_type != "prusalink":
        raise HTTPException(status_code=409, detail="This printer isn't set up for PrusaLink")
    return printer


def _job_out(current: dict | None) -> dict | None:
    if not current:
        return None
    file = current.get("file") or {}
    return {
        "id": current.get("id"),
        "state": current.get("state"),
        "file": file.get("display_name") or file.get("name"),
        "progress": current.get("progress"),
        "time_printing": current.get("time_printing"),
        "time_remaining": current.get("time_remaining"),
    }


@router.get("/{printer_id}/prusalink")
def live_status(printer_id: int, db: Session = Depends(get_db)):
    """
    What the printer is doing right now: its state, temperatures and current job. Asking also brings Farmhand's
    record of its prints up to date. Never fails: an unreachable printer says why.
    """
    printer = _printer(db, printer_id)
    out = {
        "prusalink_url": printer.prusalink_url,
        "has_password": printer.has_prusalink_password,
        "reachable": False, "error": None, "error_kind": None,
        "state": None, "printer_type": None, "firmware": None, "temps": None, "job": None,
    }
    try:
        status, current = pl.poll(db, printer)
        p = status.get("printer") or {}
        out.update(
            reachable=True,
            state=p.get("state"),
            temps={k: p.get(k) for k in ("temp_nozzle", "target_nozzle", "temp_bed", "target_bed")},
            job=_job_out(current),
        )
        try:
            v = pl.version(printer)
            out.update(printer_type=v.get("printer"), firmware=v.get("firmware"))
        except pl.PrusaLinkError:
            pass  # only for show
    except pl.PrusaLinkError as e:
        out.update(error=str(e), error_kind=e.kind)
    out.update(sync_state(printer))
    return out


@router.post("/{printer_id}/prusalink/print")
def send_print(printer_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Send a sliced file (.bgcode or .gcode) to the printer and start printing it. It goes on the printer's USB drive,
    replacing a file of the same name. Refused (409) while the printer is busy.

    A plain (not async) handler: it waits on the printer for a long time, so it runs in a worker thread rather than
    holding up every other request. The upload is streamed from where it was received, never held in memory whole.
    """
    printer = _printer(db, printer_id)
    name = os.path.basename((file.filename or "").replace("\\", "/")).strip()
    if not name.lower().endswith(PRINTABLE):
        raise HTTPException(status_code=422, detail="The printer can only print a sliced .bgcode or .gcode file. Slice the 3MF first.")
    size = file.file.seek(0, os.SEEK_END)
    file.file.seek(0)
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="That file is too large to send.")
    if not size:
        raise HTTPException(status_code=422, detail="That file is empty.")
    status, _ = pl.poll(db, printer)
    state = (status.get("printer") or {}).get("state")
    if state not in PRUSALINK_FREE:
        raise HTTPException(status_code=409, detail=f"The printer isn't ready for a new print (it says {state or 'nothing'}).")
    try:
        where = pl.upload_and_print(printer, name, file.file, size)
    except pl.PrusaLinkError as e:
        if e.kind == "busy":
            raise HTTPException(status_code=409, detail=str(e))
        raise
    try:
        pl.poll(db, printer)  # start recording it straight away
    except pl.PrusaLinkError:
        pass  # it was sent; the next look will pick it up
    return {"sent": where}
