from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..errors import NotFound
from .. import notes as notes_helper
from ..notes import NotesConflict  # noqa: F401  (raised by set_notes)
from ..models import (
    Bundle, BundleVersion, Printer, PrinterCamera, PrinterConnection, PrinterNote, PrinterServiceReminder,
    PrusaLinkConnection, SubPrinter,
)


def list_printers(db: Session) -> list[Printer]:
    rows = (
        Printer.note_row, Printer.connection_row, Printer.service_row, Printer.service_note_row, Printer.prusalink_row,
        Printer.camera_row,
    )
    return list(db.scalars(
        select(Printer).order_by(Printer.name).options(
            *(selectinload(r) for r in rows), selectinload(Printer.sub_printers).selectinload(SubPrinter.alias_rows),
            selectinload(Printer.default_sub_printer_row),
        )
    ))  # a batch, not 5 per printer


def get_printer(db: Session, printer_id: int) -> Printer | None:
    return db.get(Printer, printer_id)


def find_by_name(db: Session, name: str) -> Printer | None:
    return db.scalar(select(Printer).where(Printer.name == name))


def create_printer(
    db: Session, *, name: str, kind: str | None, wired_ip: str | None, wireless_ip: str | None
) -> Printer:
    if find_by_name(db, name):
        raise ValueError(f"A printer named {name!r} already exists — name is the unique key, not IP")
    printer = Printer(name=name, kind=kind, wired_ip=wired_ip, wireless_ip=wireless_ip)
    db.add(printer)
    db.commit()
    db.refresh(printer)
    return printer


def require_printer(db: Session, printer_id: int) -> Printer:
    """The printer, or NotFound."""
    printer = get_printer(db, printer_id)
    if printer is None:
        raise NotFound(f"No printer with id {printer_id}")
    return printer


def set_decommissioned(db: Session, printer_id: int, decommissioned: bool) -> Printer:
    printer = require_printer(db, printer_id)
    printer.decommissioned = decommissioned
    db.commit()
    db.refresh(printer)
    return printer


def delete_printer(db: Session, printer_id: int) -> None:
    """
    Remove a decommissioned printer for good, with its print history, notes, connection, sub printers and maintenance.
    Refused while 3MF files are kept for it: they'd be left without a printer.
    """
    printer = require_printer(db, printer_id)
    if not printer.decommissioned:
        raise ValueError(f"{printer.name} is still in use. Decommission it first (Edit), then it can be deleted.")
    if printer.bundles:
        n = len(printer.bundles)
        raise ValueError(
            f"{printer.name} still has {n} 3MF file{'s' if n != 1 else ''}. Delete {'them' if n != 1 else 'it'} from its page "
            "first, then the printer can be deleted."
        )
    db.delete(printer)
    db.commit()


def find_by_profile_name(db: Session, profile_name: str) -> Printer | None:
    """
    Which printer does a 3MF's embedded profile name refer to? Exact printer
    name first. Failing that, a printer that has already received files
    sliced under that profile name — so renaming a printer here doesn't
    break matching for files still sliced under its old name, and a printer
    picked by hand for a file keeps being matched for that profile later.
    """
    printer = find_by_name(db, profile_name)
    if printer is not None:
        return printer
    return db.scalar(
        select(Printer)
        .join(Bundle, Bundle.printer_id == Printer.id)
        .join(BundleVersion, BundleVersion.bundle_id == Bundle.id)
        .where(BundleVersion.printer_profile_name == profile_name)
        .order_by(BundleVersion.uploaded_at.desc())
        .limit(1)
    )


def ensure_connection(printer: Printer) -> PrinterConnection:
    """The printer's connection row (how it's reached, and how its last sync went), made if it hasn't one yet."""
    if printer.connection_row is None:
        printer.connection_row = PrinterConnection(printer_id=printer.id)
    return printer.connection_row


def record_sync_ok(printer: Printer, totals: dict, now: dt.datetime) -> None:
    """
    Syncing the printer went through: note when, with its lifetime totals. The 1500-hour service count starts from the
    print time in them, the first time.
    """
    conn = ensure_connection(printer)
    conn.totals = totals
    conn.last_sync_at = now
    conn.last_sync_error = None
    if printer.service_row is None:
        printer.service_row = PrinterServiceReminder(
            printer_id=printer.id, start_printtime=float(totals.get("total_print_time") or 0), history=[]
        )


def record_sync_error(db: Session, printer: Printer, error: Exception) -> None:
    """Syncing the printer (or looking at it) failed: drop what that had changed, and note why on its connection."""
    db.rollback()
    ensure_connection(printer).last_sync_error = str(error)
    db.commit()


def update_printer(db: Session, printer_id: int, changes: dict) -> Printer:
    printer = require_printer(db, printer_id)

    new_name = changes.get("name")
    if new_name is not None and new_name != printer.name:
        if find_by_name(db, new_name):
            raise ValueError(f"A printer named {new_name!r} already exists — name is the unique key")
        printer.name = new_name

    for field in ("kind", "wired_ip", "wireless_ip"):
        if field in changes:
            value = changes[field]
            if isinstance(value, str):
                value = value.strip() or None
            setattr(printer, field, value)

    if changes.get("decommissioned") is not None:
        printer.decommissioned = changes["decommissioned"]

    if "moonraker_url" in changes or "moonraker_api_key" in changes:
        conn = ensure_connection(printer)
        if "moonraker_url" in changes:
            conn.moonraker_url = changes["moonraker_url"]  # already tidied; None = the default address
        if changes.get("moonraker_api_key") is not None:
            conn.api_key = changes["moonraker_api_key"].strip() or None

    if changes.get("connection_type") == "moonraker":
        printer.prusalink_row = None  # the login goes; the prints Farmhand recorded stay
    elif changes.get("connection_type") == "prusalink" or (
        printer.prusalink_row is not None and {"prusalink_url", "prusalink_username", "prusalink_password"} & changes.keys()
    ):
        link = printer.prusalink_row or PrusaLinkConnection(printer_id=printer.id, username="maker")
        printer.prusalink_row = link
        if "prusalink_url" in changes:
            link.url = changes["prusalink_url"]  # already tidied; None = the default address
        if changes.get("prusalink_username") is not None:
            link.username = changes["prusalink_username"].strip()[:120] or "maker"
        if changes.get("prusalink_password") is not None:
            link.password = changes["prusalink_password"] or None

    if "camera_address" in changes:
        address = changes["camera_address"]  # already checked; None = no camera
        if address is None:
            printer.camera_row = None
        elif printer.camera_row is None:
            printer.camera_row = PrinterCamera(printer_id=printer.id, address=address)
        else:
            printer.camera_row.address = address

    db.commit()
    db.refresh(printer)
    return printer


# ------------------------------------------------------------------ notes about a printer


def set_notes(db: Session, printer_id: int, notes: str, base_revision: int) -> Printer:
    """Save the notes for a printer (the rules are in app/notes.py: conflict-safe, tidied, length-limited)."""
    printer = require_printer(db, printer_id)
    return notes_helper.save(
        db, owner=printer, note_cls=PrinterNote, owner_key="printer_id", base_revision=base_revision,
        notes=notes, reload=lambda: get_printer(db, printer_id),
    )
