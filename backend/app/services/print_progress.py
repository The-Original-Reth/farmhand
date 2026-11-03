"""
How far along a printer's print is right now, for Monitor's cameras: from Klipper (as Mainsail shows it) or from
PrusaLink, whichever the printer talks. Asking never fails: a printer that can't be asked says why.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Printer
from . import moonraker as mr
from . import prusalink as pl

PRUSA_PRINTING = {"PRINTING": "printing", "PAUSED": "paused"}  # PrusaLink's job states that mean a print is under way


def progress(db: Session, printer: Printer) -> dict:
    """
    {state, progress, file, error}. state: "printing" | "paused" | None (nothing under way); progress: 0-100, through
    the file, as the printer says it; error: why it couldn't be asked, or None.
    """
    out = {"state": None, "progress": None, "file": None, "error": None}
    try:
        if printer.connection_type == "prusalink":
            _, job = pl.poll(db, printer)  # also brings Farmhand's record of its prints up to date
            state = PRUSA_PRINTING.get((job or {}).get("state"))
            if state:
                file = job.get("file") or {}
                out.update(state=state, progress=job.get("progress"), file=file.get("display_name") or file.get("name"))
        else:
            live = mr.live_print(printer)
            if live:
                out.update(state=live["state"], progress=live["progress"], file=live["file"])
    except (mr.MoonrakerError, pl.PrusaLinkError) as e:
        out["error"] = str(e)
    return out
