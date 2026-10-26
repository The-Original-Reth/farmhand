"""
Sending a 3MF version's G-code to the printer it was sliced for, and starting it: through PrusaLink (a Prusa Core One,
MK4...) or Moonraker (Klipper). Never while the printer is busy.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ..errors import NotFound
from ..models import BundleVersion
from . import moonraker as mr
from . import prusalink as pl

PRUSALINK_FREE = ("IDLE", "READY", "FINISHED", "STOPPED")  # states a Prusa printer takes a new print in
KLIPPER_BUSY = ("printing", "paused")


class PrinterBusy(Exception):
    """The printer is printing (or waiting for someone at it): nothing was sent."""


def send_gcode(db: Session, version_id: int) -> dict:
    """Send the version's G-code to its printer and start it. Returns {sent: where it went, printer: its name}."""
    version = db.get(BundleVersion, version_id)
    if version is None:
        raise NotFound(f"No bundle version with id {version_id}")
    name = version.gcode_name
    if not name:
        raise ValueError("This version has no G-code to send. Upload one first.")
    printer = version.bundle.printer

    if printer.connection_type == "prusalink":
        status, _ = pl.poll(db, printer)
        state = (status.get("printer") or {}).get("state")
        if state not in PRUSALINK_FREE:
            raise PrinterBusy(f"{printer.name} isn't ready for a new print (it says {state or 'nothing'}).")
        where = pl.upload_and_print(printer, name, _read(version))
        try:
            pl.poll(db, printer)  # start recording the print straight away
        except pl.PrusaLinkError:
            pass  # it was sent; the next look will pick it up
    else:
        if name.lower().endswith(".bgcode"):
            raise ValueError(f"{printer.name} runs Klipper, which can't print a .bgcode (Prusa's binary G-code). Slice a plain .gcode for it.")
        state = mr.print_state(printer)
        if state in KLIPPER_BUSY:
            raise PrinterBusy(f"{printer.name} is {state}, so a new print can't be started.")
        where = mr.upload_and_print(printer, name, _read(version))
    return {"sent": where, "printer": printer.name}


def _read(version: BundleVersion) -> bytes:
    try:
        return Path(version.gcode_path).read_bytes()
    except OSError as e:
        raise ValueError(f"The G-code file can't be read ({e.strerror}). Is its storage folder available?") from None
