"""
Sending a G-code to the printer it was sliced for, and starting it: through PrusaLink (a Prusa Core One, MK4...) or
Moonraker (Klipper). Never while the printer is busy. A 3MF version's G-code (send_gcode), or any G-code file for a
printer (send_file: a project's own 3MF's).
"""
from __future__ import annotations

import contextlib
import os
from typing import BinaryIO, Callable, ContextManager, Iterator

from sqlalchemy.orm import Session

from ..models import Printer
from . import bundle_service
from . import moonraker as mr
from . import prusalink as pl

PRUSALINK_FREE = ("IDLE", "READY", "FINISHED", "STOPPED")  # states a Prusa printer takes a new print in
KLIPPER_BUSY = ("printing", "paused")


class PrinterBusy(Exception):
    """The printer is printing (or waiting for someone at it): nothing was sent."""


def send_gcode(db: Session, version_id: int) -> dict:
    """Send the version's G-code to its printer and start it. Returns {sent: where it went, printer: its name}."""
    version = bundle_service.require_version(db, version_id)
    name = version.gcode_name
    if not name:
        raise ValueError("This version has no G-code to send. Upload one first.")
    return send_file(db, version.bundle.printer, name, version.gcode_path)


def send_file(db: Session, printer: Printer, name: str, path: str) -> dict:
    """Send the G-code file at `path` to `printer` as `name`, and start it. Returns {sent: where it went, printer}."""
    if printer.connection_type == "prusalink":
        where = send_to_prusalink(db, printer, name, lambda: _opened(path), who=printer.name)
    else:
        if name.lower().endswith(".bgcode"):
            raise ValueError(f"{printer.name} runs Klipper, which can't print a .bgcode (Prusa's binary G-code). Slice a plain .gcode for it.")
        state = mr.print_state(printer)
        if state in KLIPPER_BUSY:
            raise PrinterBusy(f"{printer.name} is {state}, so a new print can't be started.")
        with _opened(path) as (gcode, _size):
            where = mr.upload_and_print(printer, name, gcode)
    return {"sent": where, "printer": printer.name}


def send_to_prusalink(
    db: Session, printer: Printer, name: str, opened: Callable[[], ContextManager[tuple[BinaryIO, int]]], *, who: str,
) -> str:
    """
    Send a G-code to a PrusaLink printer and start it, once it says it's ready for one (else PrinterBusy, which names
    it as `who`). `opened()` gives the file and its size, opened only once the printer is ready. Returns where it went.
    """
    status, _ = pl.poll(db, printer)
    state = (status.get("printer") or {}).get("state")
    if state not in PRUSALINK_FREE:
        raise PrinterBusy(f"{who} isn't ready for a new print (it says {state or 'nothing'}).")
    with opened() as (gcode, size):
        where = pl.upload_and_print(printer, name, gcode, size)
    try:
        pl.poll(db, printer)  # start recording the print straight away
    except pl.PrusaLinkError:
        pass  # it was sent; the next look will pick it up
    return where


@contextlib.contextmanager
def _opened(path: str) -> Iterator[tuple[BinaryIO, int]]:
    """The G-code file, open, and its size: it's streamed to the printer from where it is, never read in whole."""
    try:
        f = open(path, "rb")
    except OSError as e:
        raise ValueError(f"The G-code file can't be read ({e.strerror}). Is its storage folder available?") from None
    with f:
        yield f, os.fstat(f.fileno()).st_size
