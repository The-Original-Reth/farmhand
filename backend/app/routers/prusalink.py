from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..models import Printer
from ..services import prusalink as pl
from ..services.send_print import FileTooLarge, send_upload_to_prusalink
from .common import require_printer, sync_state

# A PrusaLink printer (Prusa Core One, MK4, XL...): its live status and sending it a print. Its print history,
# statistics, 1500-hour service and maintenance use the same routes as a Moonraker printer's (routers/moonraker.py).
# A PrusaLinkError becomes a 502 with {"detail", "kind"} (see main.py).
router = APIRouter(prefix="/printers", tags=["prusalink"])


def _printer(db: Session, printer_id: int) -> Printer:
    printer = require_printer(db, printer_id)
    if printer.connection_type != "prusalink":
        raise HTTPException(status_code=409, detail="This printer isn't set up for PrusaLink")
    return printer


@router.get("/{printer_id}/prusalink/password")
def saved_password(printer_id: int, db: Session = Depends(get_db)):
    """The PrusaLink password saved for it ({"password": null} when none is), asked for on its own to be shown."""
    printer = _printer(db, printer_id)
    return {"password": printer.prusalink_row.password if printer.prusalink_row else None}


@router.get("/{printer_id}/prusalink")
def live_status(printer_id: int, db: Session = Depends(get_db)):
    """
    What the printer is doing right now: its state, temperatures and current job. Asking also brings Farmhand's
    record of its prints up to date. Never fails: an unreachable printer says why.
    """
    printer = _printer(db, printer_id)
    return {**pl.live_status(db, printer), **sync_state(printer)}


@router.post("/{printer_id}/prusalink/print")
def send_print(printer_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Send a sliced file (.bgcode or .gcode) to the printer and start printing it. It goes on the printer's USB drive,
    replacing a file of the same name. Refused (409) while the printer is busy.

    A plain (not async) handler: it waits on the printer for a long time, so it runs in a worker thread rather than
    holding up every other request. The upload is streamed from where it was received, never held in memory whole.
    """
    printer = _printer(db, printer_id)
    with answer_errors(codes={FileTooLarge: 413}):
        return {"sent": send_upload_to_prusalink(db, printer, file.filename, file.file)}
