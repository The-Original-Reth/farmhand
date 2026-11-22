"""
The filament price, density and diameter of what a Prusa printer connected through Prusa Connect prints, read from
the printed file itself, as Mainsail's G-codes are (GcodeFilament, services/filament_cost.py): so its prints are
costed the same way, sliced in Farmhand or not.

Prusa Connect can't read the files on a printer (the printer only tells it their names, sizes and pictures), so for
this alone the printer's PrusaLink is asked, read only: once per file (its name and when it was written), when a print
of it starts and Farmhand has no price for it; the file's details, then its start, stopped as soon as a .bgcode's
settings are in (client.printed_file_settings). In the background, so the report that saw the print start isn't kept
waiting. A print Farmhand sends is read from Farmhand's own copy first (from_sent_file), and the printer isn't asked.

The same read keeps the slicer's own estimate of the whole print's filament (PrintedFileEstimate), for the prints of
that file nobody measured (filament_estimate.py). A plain PrusaLink printer's file is read for that alone
(start_estimate), and only when no 3MF in Farmhand matches the printed file: the same read only, once per file.

A file that can't be read right now is tried again after RETRY_AFTER; one that's gone or holds no price (or names no
filament) is noted (GcodeFilament.problem, PrintedFileEstimate.problem) and not asked about again.
"""
from __future__ import annotations

import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import GcodeFilament, PrintedFileEstimate, Printer, PrintJob
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


def _estimated(db: Session, printer_id: int, filename: str) -> bool:
    return db.scalar(
        select(PrintedFileEstimate.id).where(
            PrintedFileEstimate.printer_id == printer_id, PrintedFileEstimate.filename == filename,
        ).limit(1)
    ) is not None


def start(db: Session, printer: Printer, row: PrintJob) -> None:
    """A print just started on a printer connected through Prusa Connect: read its file's price and the slicer's
    estimate, unless Farmhand has both for that file (or is reading it, or couldn't a short while ago)."""
    if printer.status_from:
        _start(db, printer, row, price=True)


def start_estimate(db: Session, printer: Printer, row: PrintJob) -> None:
    """A print with no filament figure from anywhere else, on any Prusa printer: read the slicer's estimate from its
    file, unless Farmhand has it (or is reading it, or couldn't a short while ago). A printer connected through Prusa
    Connect gets its price from the same read."""
    _start(db, printer, row, price=bool(printer.status_from))


def _start(db: Session, printer: Printer, row: PrintJob, price: bool) -> None:
    path = (row.job_metadata or {}).get("path")
    if not path or not row.filename.lower().endswith(gcode.GCODE_EXTENSIONS):
        return
    key = (printer.id, row.filename)
    with _lock:
        if key in _busy or time.monotonic() - _tried.get(key, -RETRY_AFTER) < RETRY_AFTER:
            return
        price = price and not _known(db, printer.id, row.filename)
        if not price and _estimated(db, printer.id, row.filename):
            return
        _busy.add(key)
    bind = db.get_bind()
    run_in_background(lambda: _read(bind, printer.id, row.filename, path, price))


def estimate_for(db: Session, printer_id: int, row: PrintJob) -> PrintedFileEstimate | None:
    """The slicer's estimate read from the file a print printed, with a figure: of several copies of it (sliced again
    under the same name), the newest written before the print started, else the newest."""
    copies = list(db.scalars(select(PrintedFileEstimate).where(
        PrintedFileEstimate.printer_id == printer_id, PrintedFileEstimate.filename == row.filename,
        PrintedFileEstimate.filament_mm.isnot(None),
    ).order_by(PrintedFileEstimate.modified.desc())))
    if not copies:
        return None
    start = row.start_time.timestamp() if row.start_time else None
    before = [c for c in copies if start is None or not c.modified or c.modified <= start + 60]
    return (before or copies)[0]


def _read(bind, printer_id: int, filename: str, path: str, price: bool = True) -> None:
    key = (printer_id, filename)
    try:
        with Session(bind=bind) as db:
            printer = db.get(Printer, printer_id)
            if printer is None:
                return
            entry = GcodeFilament(printer_id=printer_id, filename=filename, modified=0)
            estimate = PrintedFileEstimate(printer_id=printer_id, filename=filename, modified=0)
            try:
                found, slicer, modified = client.printed_file_details(printer, path, filename)
            except PrusaLinkError as e:
                if e.kind != "not_found":
                    with _lock:
                        _tried[key] = time.monotonic()  # can't ask right now: again later
                    return
                entry.problem = estimate.problem = "This file isn't on the printer any more."
            else:
                entry.modified = estimate.modified = modified
                _fill(entry, found)
                estimate.filament_mm, estimate.filament_g = slicer.get("filament_mm"), slicer.get("filament_g")
                if not estimate.filament_mm:
                    estimate.filament_mm, estimate.problem = None, "This G-code doesn't say how much filament it uses."
            if price and db.scalar(select(GcodeFilament.id).where(
                GcodeFilament.printer_id == printer_id, GcodeFilament.filename == filename,
                GcodeFilament.modified == entry.modified,
            )) is None:
                db.add(entry)
            if db.scalar(select(PrintedFileEstimate.id).where(
                PrintedFileEstimate.printer_id == printer_id, PrintedFileEstimate.filename == filename,
                PrintedFileEstimate.modified == estimate.modified,
            )) is None:
                db.add(estimate)
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
    """A print Farmhand is sending: its price and the slicer's estimate read from Farmhand's own copy (an open file or
    bytes), noted as of now, so the print it starts is costed from it without asking the printer."""
    import io

    f = io.BytesIO(data) if isinstance(data, bytes) else data
    try:
        found = gcode.filament_settings(f, name)
        slicer = gcode.slicer_filament(f, name)
    except Exception:  # noqa: BLE001 - only for its price: the print is sent regardless
        return
    now = time.time()
    if found:
        entry = GcodeFilament(printer_id=printer.id, filename=name, modified=now)
        _fill(entry, found)
        db.add(entry)
    if slicer.get("filament_mm"):
        db.add(PrintedFileEstimate(printer_id=printer.id, filename=name, modified=now,
                                   filament_mm=slicer["filament_mm"], filament_g=slicer.get("filament_g")))
    db.commit()
