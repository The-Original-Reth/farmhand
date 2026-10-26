"""The 1500-hour service reminder: kept in Farmhand, counted from the printer's total print time."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from ... import notes as notes_helper
from ...models import Printer, PrinterServiceNote
from ...notes import HasNotes, NotesConflict  # noqa: F401  (NotesConflict is raised by set_service_notes)
from .client import MoonrakerError, job_totals
from .history import _connection


def service_done(db: Session, printer: Printer, *, note: str | None) -> None:
    """
    Mark the 1500-hour service done: the next 1500 hours count from the printer's print time now. That's asked of
    the printer if it answers (and kept as the latest totals), else taken from the last sync.
    """
    row = printer.service_row
    if row is None:
        raise ValueError("The service count starts once the printer has been synced at least once")
    conn = _connection(printer)
    if printer.connection_type == "moonraker":
        try:
            conn.totals = job_totals(printer)
        except MoonrakerError:
            pass  # printer off: the last synced print time stands
    # (a PrusaLink printer's totals are what Farmhand has recorded, already current)
    printtime = float((conn.totals or {}).get("total_print_time") or 0)
    row.history = [*row.history, {
        "done_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "printtime": printtime,
        "hours": round(max(0.0, printtime - row.start_printtime) / 3600, 1),  # hours since the previous service
        "note": (note or "").strip() or None,
    }]
    row.start_printtime = printtime
    row.started_at = dt.datetime.now(dt.timezone.utc)
    db.commit()


class _ServiceNotes(HasNotes):
    """A printer's service notes, shaped the way app/notes.py expects an owner (id, note_row)."""

    def __init__(self, printer: Printer):
        self.printer = printer
        self.id = printer.id
        self.note_row = printer.service_note_row


def set_service_notes(db: Session, printer: Printer, notes: str, base_revision: int) -> Printer:
    """Save the notes kept with the 1500-hour service (conflict-safe, tidied, length-limited: app/notes.py)."""
    def reload():
        db.expire_all()
        return _ServiceNotes(db.get(Printer, printer.id))

    return notes_helper.save(
        db, owner=_ServiceNotes(printer), note_cls=PrinterServiceNote, owner_key="printer_id",
        base_revision=base_revision, notes=notes, reload=reload,
    ).printer


def set_service_enabled(db: Session, printer: Printer, enabled: bool) -> None:
    """Switch a printer's 1500-hour reminder off (it never comes due) or back on (the count carries on)."""
    if printer.service_row is None:
        raise ValueError("The service count starts once the printer has been synced at least once")
    printer.service_row.enabled = enabled
    db.commit()
