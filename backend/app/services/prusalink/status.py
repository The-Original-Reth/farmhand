"""What the Printers page shows about a PrusaLink printer right now: its state, temperatures and current job. Asking
also brings Farmhand's record of its prints up to date. Never fails: an unreachable printer says why."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...models import Printer
from .client import PrusaLinkError, job_file_name, version
from .tracking import poll


def _job_out(current: dict | None) -> dict | None:
    if not current:
        return None
    return {
        "id": current.get("id"),
        "state": current.get("state"),
        "file": job_file_name(current),
        "progress": current.get("progress"),
        "time_printing": current.get("time_printing"),
        "time_remaining": current.get("time_remaining"),
    }


def live_status(db: Session, printer: Printer) -> dict:
    out = {
        "prusalink_url": printer.prusalink_url,
        "has_password": printer.has_prusalink_password,
        "reachable": False, "error": None, "error_kind": None,
        "state": None, "printer_type": None, "firmware": None, "temps": None, "job": None,
    }
    try:
        status, current = poll(db, printer)
        p = status.get("printer") or {}
        out.update(
            reachable=True,
            state=p.get("state"),
            temps={k: p.get(k) for k in ("temp_nozzle", "target_nozzle", "temp_bed", "target_bed")},
            job=_job_out(current),
        )
        try:
            v = version(printer)
            out.update(printer_type=v.get("printer"), firmware=v.get("firmware"))
        except PrusaLinkError:
            pass  # only for show
    except PrusaLinkError as e:
        out.update(error=str(e), error_kind=e.kind)
    out["prusalink_url"] = printer.prusalink_url  # the one of its IPs it answered at just now
    return out
