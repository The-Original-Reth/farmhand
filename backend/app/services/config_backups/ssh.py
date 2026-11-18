"""
Whether SSH to a printer has been tested and works, remembered for the printer backups page.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...models import Printer, PrinterSshCheck
from ...timeutil import utc_iso, utc_now
from .. import printer_ssh


def _record_ssh(db: Session, printer: Printer, t: "printer_ssh.Target | None") -> None:
    """Remember a good SSH login to the printer (`t`), or forget the last one (None). Committed by the caller."""
    row = db.get(PrinterSshCheck, printer.id)
    if t is None:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        row = PrinterSshCheck(printer_id=printer.id, user=t.user, host=t.host)
        db.add(row)
    row.tested_at, row.user, row.host = utc_now(), t.user, t.host


def ssh_status(db: Session, printer: Printer) -> dict | None:
    """The last good SSH login to the printer, {tested_at, user, host}, or None: never tested, or it failed since."""
    row = db.get(PrinterSshCheck, printer.id)
    return {"tested_at": utc_iso(row.tested_at), "user": row.user, "host": row.host} if row else None


def test_ssh(db: Session, printer: Printer) -> dict:
    """Test SSH (printer_ssh.check) and remember the answer: {ok, user, host, error, kind, tested_at}."""
    result = printer_ssh.check(printer)
    _record_ssh(db, printer, printer_ssh.Target(result["host"], result["user"], "") if result["ok"] else None)
    db.commit()
    status = ssh_status(db, printer)
    return {**result, "tested_at": status["tested_at"] if status else None}
