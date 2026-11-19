"""
A Prusa printer's status as a plugin reports it (PUT /plugin-api/v1/printers/{id}/status, permission printers:report),
for a printer switched to take its status from that plugin (PrinterStatusSource) instead of its own PrusaLink.

The Prusa Connect plugin is the first such plugin: it asks the farm's Prusa Connect server and passes each printer's
state on. Each report is kept here, in memory (it's about now), in PrusaLink's own shapes, and prusalink/client.py
answers from it in place of asking the printer: so the printer page, Monitor, the print history Farmhand records and
plugins' events all work as they do for PrusaLink. Farmhand doesn't contact such a printer's PrusaLink at all: a print
sent to it is handed to the plugin (hand_over), when the plugin has printers:print, and the plugin starts it.

A report older than STALE_SECONDS, or none since Farmhand started, makes the printer unreachable, saying why.
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import BinaryIO

from sqlalchemy.orm import Session

from ..models import Printer, PrinterStatusSource
from .plugins import registry, remote
from .printer_http import UPLOAD_TIMEOUT

STALE_SECONDS = 120.0  # a plugin reports every few seconds: this long without one, it has stopped

_lock = threading.Lock()
_reports: dict[int, dict] = {}  # printer id -> {"at": monotonic, "plugin_id", "report"}


class NotReporter(Exception):
    """The printer doesn't take its status from this plugin (a 403 for the plugin)."""


def plugin_name(db: Session, plugin_id: str | None) -> str | None:
    if not plugin_id:
        return None
    try:
        return registry.get(db, plugin_id).name
    except Exception:  # noqa: BLE001 - removed since: its id is all there is
        return plugin_id


def reporters(db: Session) -> list[dict]:
    """The plugins a printer can take its status from: installed, switched on and granted printers:report."""
    return [
        {"id": p.id, "name": p.name}
        for p in registry.all_plugins(db)
        if p.enabled and "printers:report" in registry.granted(p)
    ]


def choose(db: Session, printer: Printer, plugin_id: str | None) -> None:
    """Take a Prusa printer's status from this plugin, or (None) from its own PrusaLink again. Doesn't commit."""
    if not plugin_id:
        printer.status_source_row = None
        forget(printer.id)
        return
    if printer.prusalink_row is None:
        raise ValueError("Only a Prusa printer (one set up for PrusaLink) can take its status from a plugin.")
    if plugin_id not in {r["id"] for r in reporters(db)}:
        raise ValueError(
            "That plugin can't report printers' status: it isn't installed and switched on with the \"report your "
            "printers' status\" permission. Check it on the Plugins page.",
        )
    if printer.status_source_row is None:
        printer.status_source_row = PrinterStatusSource(printer_id=printer.id, plugin_id=plugin_id)
    elif printer.status_source_row.plugin_id != plugin_id:
        printer.status_source_row.plugin_id = plugin_id
        forget(printer.id)


def accept(printer: Printer, plugin_id: str, report: dict) -> None:
    """Keep a plugin's report of a printer (already checked against its shape). NotReporter for a printer that doesn't
    take its status from this plugin."""
    if printer.status_from != plugin_id:
        raise NotReporter(
            f"Farmhand takes {printer.name}'s status from "
            + (f"the \"{printer.status_from}\" plugin" if printer.status_from else "its PrusaLink")
            + f", not this plugin. The operator can change that in Farmhand: Edit {printer.name}, Connection."
        )
    with _lock:
        _reports[printer.id] = {"at": time.monotonic(), "plugin_id": plugin_id, "report": report}


def forget(printer_id: int) -> None:
    with _lock:
        _reports.pop(printer_id, None)


def forget_all() -> None:
    """For tests."""
    with _lock:
        _reports.clear()


def latest(printer: Printer) -> dict | None:
    """The plugin's newest report of the printer, while it's fresh; None when there's none or it's old."""
    with _lock:
        kept = _reports.get(printer.id)
    if kept is None or kept["plugin_id"] != printer.status_from or time.monotonic() - kept["at"] > STALE_SECONDS:
        return None
    return kept["report"]


def extras(printer: Printer) -> dict | None:
    """What the plugin knows of the printer beyond PrusaLink (material, nozzle, chamber, fans, a message on its
    screen, the extruder's odometer), while its report is fresh and the printer reachable."""
    report = latest(printer)
    if not report or not report.get("reachable", True):
        return None
    return report.get("extras") or None


def odometer(printer: Printer) -> float | None:
    """The mm of filament the printer's extruder has fed, ever, as the plugin last reported it; None when unknown."""
    value = (extras(printer) or {}).get("odometer_e")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def link(printer: Printer) -> str | None:
    """Where the plugin says the printer can be seen (its page on Prusa Connect, say), while its report is fresh."""
    report = latest(printer)
    return report.get("link") if report else None


# ------------------------------------------------------------------ PrusaLink's shapes, for prusalink/client.py


def _report(printer: Printer, error_type) -> dict:
    report = latest(printer)
    if report is None:
        raise error_type(
            "unreachable",
            f"The \"{printer.status_from}\" plugin hasn't said how {printer.name} is for a while. Is the plugin running? "
            f"(Its status comes from that plugin; the Plugins page says how it is.)",
        )
    if not report.get("reachable", True):
        raise error_type("unreachable", report.get("error") or f"The \"{printer.status_from}\" plugin can't reach {printer.name}.")
    return report


def status(printer: Printer, error_type) -> dict:
    report = _report(printer, error_type)
    temps = report.get("temps") or {}
    out = {"printer": {"state": report.get("state"), **{k: temps.get(k) for k in ("temp_nozzle", "target_nozzle", "temp_bed", "target_bed")}}}
    job = report.get("job")
    if job and job.get("id") is not None:
        out["job"] = {"id": job["id"]}
    return out


def job(printer: Printer, error_type) -> dict | None:
    job = _report(printer, error_type).get("job")
    if not job or job.get("id") is None:
        return None
    return {
        "id": job["id"], "state": job.get("state"), "progress": job.get("progress"),
        "time_printing": job.get("time_printing"), "time_remaining": job.get("time_remaining"),
        "file": {"name": job.get("file"), "display_name": job.get("display_name") or job.get("file"), "path": job.get("path")},
    }


def version(printer: Printer, error_type) -> dict:
    report = _report(printer, error_type)
    return {"printer": report.get("printer_type"), "firmware": report.get("firmware"), "text": plugin_name_from(printer)}


def plugin_name_from(printer: Printer) -> str | None:
    from sqlalchemy.orm import object_session

    db = object_session(printer)
    return plugin_name(db, printer.status_from) if db is not None else printer.status_from


# ------------------------------------------------------------------ prints sent through the plugin


TICKET_SECONDS = 900.0  # a ticket nobody fetched is dropped after this long (normally it goes when the hand-over ends)
_tickets: dict[str, dict] = {}  # ticket -> {plugin_id, printer_id, name, data, size, at}


def hand_over(printer: Printer, name: str, data: bytes | BinaryIO, size: int | None, error_type) -> str:
    """
    Send a print to a printer connected through a plugin, which starts it: Farmhand POSTs a one-time ticket to the
    plugin's print path and waits; the plugin fetches the G-code with the ticket and its token, sends it on and answers
    where it went. error_type(kind, words) for any problem, as from the printer itself.
    """
    from sqlalchemy.orm import object_session

    db = object_session(printer)
    plugin_id = printer.status_from
    try:
        plugin = registry.get(db, plugin_id)
    except Exception:  # noqa: BLE001 - removed since
        raise error_type("unreachable", f"{printer.name} is connected through the \"{plugin_id}\" plugin, which isn't added any more.") from None
    path = ((plugin.manifest or {}).get("print") or {}).get("path")
    if not plugin.enabled or not path or "printers:print" not in registry.granted(plugin):
        raise error_type(
            "unreachable",
            f"The {plugin.name} plugin can't start prints on {printer.name}: it needs a version that does, added with the "
            "\"start the prints you send\" permission (Plugins page).",
        )
    if size is None and isinstance(data, bytes):
        size = len(data)
    ticket = secrets.token_urlsafe(24)
    with _lock:
        now = time.monotonic()
        for old in [t for t, held in _tickets.items() if now - held["at"] > TICKET_SECONDS]:
            del _tickets[old]
        _tickets[ticket] = {"plugin_id": plugin.id, "printer_id": printer.id, "name": name, "data": data, "size": size, "at": now}
    try:
        status, answer = remote.hand_print(
            registry.connection_of(plugin).address, path,
            {"ticket": ticket, "printer_id": printer.id, "file": name, "size": size}, UPLOAD_TIMEOUT,
        )
    except ValueError as e:
        raise error_type("unreachable", str(e)) from None
    finally:
        with _lock:
            _tickets.pop(ticket, None)
    words = str(answer.get("detail") or "")[:500]
    if status == 409:
        raise error_type("busy", words or f"{printer.name} isn't ready for a new print.")
    if not 200 <= status < 300 or not answer.get("sent"):
        raise error_type("bad_response", words or f"The {plugin.name} plugin answered {status} and didn't start the print.")
    return str(answer["sent"])


def take_ticket(ticket: str, plugin_id: str) -> dict | None:
    """The print a ticket stands for, once, for the plugin it was given to; None otherwise."""
    with _lock:
        held = _tickets.get(ticket)
        if held is None or held["plugin_id"] != plugin_id or held.get("taken"):
            return None
        held["taken"] = True
        return dict(held)
