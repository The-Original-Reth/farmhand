"""
The filament price, density and diameter of what a Prusa printer connected through Prusa Connect prints, read from
the printed file itself, as Mainsail's G-codes are (GcodeFilament, services/filament_cost.py): so its prints are
costed the same way, sliced in Farmhand or not.

Prusa Connect can't read the files on a printer (the printer only tells it their names, sizes and pictures), so for
this alone the printer's PrusaLink is asked, read only: once per file (its name and when it was written), when a print
of it starts and Farmhand has no price for it; the file's details, then its start, stopped as soon as a .bgcode's
settings are in (client.printed_file_settings). In the background, so the report that saw the print start isn't kept
waiting. A print Farmhand sends is read from Farmhand's own copy first (from_sent_file), and the printer isn't asked.

A file that can't be read right now is tried again after RETRY_AFTER; one that's gone or holds no price is noted
(GcodeFilament.problem) and not asked about again.
"""
from __future__ import annotations

import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import GcodeFilament, Printer, PrintJob
from ...parsers import gcode
from .. import filament_cost
from . import client
from .client import PrusaLinkError

RETRY_AFTER = 1800.0  # seconds before a file that couldn't be read is tried again

_lock = threading.Lock()
_busy: set[tuple[int, str]] = set()
_tried: dict[tuple[int, str], float] = {}  # (printer id, file name) -> when it last couldn't be read


def run_in_background(work) -> None:
    """Tests swap this for one that runs the work at once."""
    threading.Thread(target=work, daemon=True, name="printed-filament").start()


def forget_all() -> None:
    """For tests."""
    with _lock:
        _busy.clear()
        _tried.clear()


def _known(db: Session, printer_id: int, filename: str) -> bool:
    return db.scalar(
        select(GcodeFilament.id).where(GcodeFilament.printer_id == printer_id, GcodeFilament.filename == filename).limit(1)
    ) is not None


def start(db: Session, printer: Printer, row: PrintJob) -> None:
    """A print just started on a printer connected through Prusa Connect: read its file's price, unless Farmhand has
    one for that file (or is reading it, or couldn't a short while ago)."""
    path = (row.job_metadata or {}).get("path")
    if not printer.status_from or not path or not row.filename.lower().endswith(gcode.GCODE_EXTENSIONS):
        return
    key = (printer.id, row.filename)
    with _lock:
        if key in _busy or time.monotonic() - _tried.get(key, -RETRY_AFTER) < RETRY_AFTER:
            return
        if _known(db, printer.id, row.filename):
            return
        _busy.add(key)
    bind = db.get_bind()
    run_in_background(lambda: _read(bind, printer.id, row.filename, path))


def _read(bind, printer_id: int, filename: str, path: str) -> None:
    key = (printer_id, filename)
    try:
        with Session(bind=bind) as db:
            printer = db.get(Printer, printer_id)
            if printer is None:
                return
            entry = GcodeFilament(printer_id=printer_id, filename=filename, modified=0)
            try:
                found, modified = client.printed_file_settings(printer, path, filename)
            except PrusaLinkError as e:
                if e.kind != "not_found":
                    with _lock:
                        _tried[key] = time.monotonic()  # can't ask right now: again later
                    return
                entry.problem = "This file isn't on the printer any more."
            else:
                entry.modified = modified
                _fill(entry, found)
            if db.scalar(select(GcodeFilament.id).where(
                GcodeFilament.printer_id == printer_id, GcodeFilament.filename == filename,
                GcodeFilament.modified == entry.modified,
            )) is None:
                db.add(entry)
                db.commit()
    finally:
        with _lock:
            _busy.discard(key)


def _fill(entry: GcodeFilament, found: dict) -> None:
    values = filament_cost.from_settings(found)
    entry.cost_per_kg, entry.density, entry.diameter = values["cost_per_kg"], values["density"], values["diameter"]
    if entry.cost_per_kg is None or entry.density is None:
        entry.problem = "This G-code has no filament price or density in its settings."


def from_sent_file(db: Session, printer: Printer, name: str, data) -> None:
    """A print Farmhand is sending: its price read from Farmhand's own copy (an open file or bytes), noted as of now,
    so the print it starts is costed from it without asking the printer."""
    import io

    f = io.BytesIO(data) if isinstance(data, bytes) else data
    try:
        found = gcode.filament_settings(f, name)
    except Exception:  # noqa: BLE001 - only for its price: the print is sent regardless
        return
    if not found:
        return
    entry = GcodeFilament(printer_id=printer.id, filename=name, modified=time.time())
    _fill(entry, found)
    db.add(entry)
    db.commit()
