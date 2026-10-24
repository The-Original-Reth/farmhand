"""
Talking to a printer's Moonraker (the API behind Mainsail): its print history and lifetime totals, copied into
Farmhand, and its maintenance reminders, which stay in Moonraker's own database exactly the way Mainsail keeps them
so the two apps share one list.

Everything here goes over the printer's local network with short timeouts, and every failure becomes a
MoonrakerError that says plainly what went wrong (no address, can't connect, needs an API key, ...).
"""
from __future__ import annotations

import datetime as dt
import uuid

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Printer, PrinterConnection, PrinterEnergyReading, PrinterServiceReminder, PrintJob

TIMEOUT = httpx.Timeout(6.0, connect=3.0)
PAGE = 100  # history entries asked for per request

# Tests swap this for an httpx.MockTransport that plays a fake Moonraker
transport: httpx.BaseTransport | None = None


class MoonrakerError(Exception):
    """kind: no_address | unreachable | unauthorized | not_found | bad_response"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# ------------------------------------------------------------------ the HTTP side


def _call(printer: Printer, method: str, path: str, *, params: dict | None = None, json: dict | None = None):
    """One Moonraker request; returns its "result"."""
    base = printer.moonraker_url
    if not base:
        raise MoonrakerError("no_address", "This printer has no IP address or Moonraker address set.")
    headers = {}
    if printer.connection_row and printer.connection_row.api_key:
        headers["X-Api-Key"] = printer.connection_row.api_key
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
            r = client.request(method, f"{base}{path}", params=params, json=json, headers=headers)
    except httpx.TimeoutException:
        raise MoonrakerError("unreachable", f"Moonraker at {base} didn't answer in time. Is the printer on?") from None
    except httpx.HTTPError as e:
        raise MoonrakerError("unreachable", f"Couldn't connect to Moonraker at {base} ({type(e).__name__}).") from None
    if r.status_code in (401, 403):
        raise MoonrakerError(
            "unauthorized",
            "Moonraker refused the request. Add this printer's Moonraker API key, or add Farmhand's address to "
            "[authorization] trusted_clients in moonraker.conf.",
        )
    if r.status_code == 404:
        raise MoonrakerError("not_found", "Not found on Moonraker.")
    if r.status_code >= 400:
        raise MoonrakerError("bad_response", f"Moonraker answered {r.status_code}: {_error_text(r)}")
    try:
        return r.json()["result"]
    except (ValueError, KeyError, TypeError):
        raise MoonrakerError("bad_response", f"{base} answered, but not like Moonraker does.") from None


def _error_text(r: httpx.Response) -> str:
    try:
        return str(r.json()["error"]["message"])
    except Exception:  # noqa: BLE001 - any shape at all: fall back to the raw text
        return r.text[:200]


def server_info(printer: Printer) -> dict:
    """Is it reachable, and what state is Klipper in (ready, startup, shutdown, error, disconnected)?"""
    info = _call(printer, "GET", "/server/info")
    return {"klippy_state": info.get("klippy_state"), "moonraker_version": info.get("moonraker_version")}


def job_totals(printer: Printer) -> dict:
    return _call(printer, "GET", "/server/history/totals").get("job_totals") or {}


def history_totals(printer: Printer) -> tuple[dict, list]:
    """(job_totals, auxiliary_totals): the second holds e.g. a power meter's energy summed over all prints."""
    result = _call(printer, "GET", "/server/history/totals")
    return result.get("job_totals") or {}, result.get("auxiliary_totals") or []


def meter_reading(printer: Printer) -> tuple[str, float] | None:
    """
    (sensor id, kWh) from the first Moonraker [sensor] that reports an "energy" value, e.g. a smart plug over MQTT.
    None if the printer has no such sensor (or no sensors at all).
    """
    try:
        sensors = _call(printer, "GET", "/server/sensors/list").get("sensors") or {}
    except MoonrakerError as e:
        if e.kind == "not_found":
            return None  # Moonraker's sensor component isn't set up
        raise
    for sensor_id, sensor in sensors.items():
        value = (sensor.get("values") or {}).get("energy")
        if isinstance(value, (int, float)):
            return sensor_id, float(value)
    return None


# ------------------------------------------------------------------ print history: copied into Farmhand


def _ts(value) -> dt.datetime | None:
    return dt.datetime.fromtimestamp(value, dt.timezone.utc) if value else None


def _connection(printer: Printer) -> PrinterConnection:
    if printer.connection_row is None:
        printer.connection_row = PrinterConnection(printer_id=printer.id)
    return printer.connection_row


def sync_history(db: Session, printer: Printer) -> dict:
    """
    Copy the printer's job history and totals into Farmhand. Newest first, page by page, stopping at the first
    page with nothing new or still changing (older jobs are settled). Jobs the printer has since forgotten are kept.
    Returns {"added", "updated"}; on failure the error is recorded on the connection and raised.
    """
    conn = _connection(printer)
    known = {j.job_id: j for j in db.scalars(select(PrintJob).where(PrintJob.printer_id == printer.id))}
    added = updated = 0
    try:
        totals, aux_totals = history_totals(printer)
        reading = meter_reading(printer)
        start = 0
        while True:
            page = _call(printer, "GET", "/server/history/list", params={"limit": PAGE, "start": start, "order": "desc"})
            jobs = page.get("jobs") or []
            changed_here = 0
            for raw in jobs:
                fields = _job_fields(raw)
                existing = known.get(fields["job_id"])
                if existing is None:
                    job = PrintJob(printer_id=printer.id, **fields)
                    db.add(job)
                    known[job.job_id] = job
                    added += 1
                    changed_here += 1
                elif any(not _same(getattr(existing, k), v) for k, v in fields.items() if k not in ("job_metadata", "auxiliary")):
                    for k, v in fields.items():
                        setattr(existing, k, v)
                    existing.synced_at = dt.datetime.now(dt.timezone.utc)
                    updated += 1
                    changed_here += 1
            if len(jobs) < PAGE or changed_here == 0:
                break
            start += PAGE
    except MoonrakerError as e:
        db.rollback()
        conn = _connection(printer)
        conn.last_sync_error = str(e)
        db.commit()
        raise
    conn.totals = totals
    conn.auxiliary_totals = aux_totals
    conn.last_sync_at = dt.datetime.now(dt.timezone.utc)
    conn.last_sync_error = None
    if reading is not None:
        _record_reading(db, printer, *reading)
    if printer.service_row is None:
        # the 1500-hour service count starts from the print time the printer has now
        printer.service_row = PrinterServiceReminder(
            printer_id=printer.id, start_printtime=float(totals.get("total_print_time") or 0), history=[]
        )
    db.commit()
    return {"added": added, "updated": updated}


# ------------------------------------------------------------------ the 1500-hour service: kept in Farmhand


def service_done(db: Session, printer: Printer, *, note: str | None) -> None:
    """
    Mark the 1500-hour service done: the next 1500 hours count from the printer's print time now. That's asked of
    the printer if it answers (and kept as the latest totals), else taken from the last sync.
    """
    row = printer.service_row
    if row is None:
        raise ValueError("The service count starts once the printer has been synced at least once")
    conn = _connection(printer)
    try:
        conn.totals = job_totals(printer)
    except MoonrakerError:
        pass  # printer off: the last synced print time stands
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


class _ServiceNotes:
    """A printer's service notes, shaped the way app/notes.py expects an owner (id, note_row, notes_revision)."""

    def __init__(self, printer: Printer):
        self.printer = printer
        self.id = printer.id
        self.note_row = printer.service_note_row
        self.notes_revision = self.note_row.revision if self.note_row else 0


class ServiceNotesConflict(Exception):
    """The service notes were saved by someone else since the person started editing them."""

    def __init__(self, owner: _ServiceNotes):
        super().__init__("These notes were changed by someone else while you were editing.")
        self.printer = owner.printer


def set_service_notes(db: Session, printer: Printer, notes: str, base_revision: int) -> Printer:
    """Save the notes kept with the 1500-hour service (conflict-safe, tidied, length-limited: app/notes.py)."""
    from .. import notes as notes_helper
    from ..models import PrinterServiceNote

    def reload():
        db.expire_all()
        return _ServiceNotes(db.get(Printer, printer.id))

    return notes_helper.save(
        db, owner=_ServiceNotes(printer), note_cls=PrinterServiceNote, owner_key="printer_id",
        base_revision=base_revision, notes=notes, conflict=ServiceNotesConflict, reload=reload,
    ).printer


def set_service_enabled(db: Session, printer: Printer, enabled: bool) -> None:
    """Switch a printer's 1500-hour reminder off (it never comes due) or back on (the count carries on)."""
    if printer.service_row is None:
        raise ValueError("The service count starts once the printer has been synced at least once")
    printer.service_row.enabled = enabled
    db.commit()


def _same(stored, new) -> bool:
    """Equal, treating times as instants: SQLite hands back times without a timezone, Postgres with one."""
    if isinstance(stored, dt.datetime) and isinstance(new, dt.datetime):
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=dt.timezone.utc)
        return stored == new
    return stored == new


READING_SPACING = dt.timedelta(minutes=5)  # a sync soon after another doesn't add a near-duplicate meter reading


def _record_reading(db: Session, printer: Printer, sensor: str, kwh: float) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    last = db.scalar(
        select(PrinterEnergyReading).where(PrinterEnergyReading.printer_id == printer.id)
        .order_by(PrinterEnergyReading.taken_at.desc()).limit(1)
    )
    if last is not None:
        last_at = last.taken_at if last.taken_at.tzinfo else last.taken_at.replace(tzinfo=dt.timezone.utc)
        if now - last_at < READING_SPACING:
            return
    db.add(PrinterEnergyReading(printer_id=printer.id, taken_at=now, sensor=sensor, energy_kwh=kwh))


def _aux(raw: dict, name: str) -> float | None:
    """One of the values Moonraker recorded alongside a job (from a [sensor] with history fields), as a number."""
    for item in raw.get("auxiliary_data") or []:
        if item.get("name") == name and isinstance(item.get("value"), (int, float)):
            value = float(item["value"])
            return value / 1000 if name == "energy_consumption" and item.get("units") == "Wh" else value
    return None


def _job_fields(raw: dict) -> dict:
    return {
        "energy_kwh": _aux(raw, "energy_consumption"),
        "avg_power_w": _aux(raw, "average_power"),
        "max_power_w": _aux(raw, "max_power"),
        "auxiliary": raw.get("auxiliary_data") or [],
        "job_id": str(raw.get("job_id")),
        "filename": raw.get("filename") or "",
        "status": raw.get("status") or "unknown",
        "start_time": _ts(raw.get("start_time")),
        "end_time": _ts(raw.get("end_time")),
        "print_duration": float(raw.get("print_duration") or 0),
        "total_duration": float(raw.get("total_duration") or 0),
        "filament_used": float(raw.get("filament_used") or 0),
        "job_metadata": raw.get("metadata") or {},
    }


def archive_stats(db: Session, printer_id: int) -> dict:
    """What Farmhand's own copy of the history adds up to (it can hold jobs the printer no longer has)."""
    rows = db.execute(
        select(PrintJob.status, func.count(), func.sum(PrintJob.print_duration), func.sum(PrintJob.filament_used))
        .where(PrintJob.printer_id == printer_id)
        .group_by(PrintJob.status)
    ).all()
    by_status = {status: count for status, count, _, _ in rows}
    return {
        "jobs": sum(by_status.values()),
        "by_status": by_status,
        "print_time": float(sum(t or 0 for _, _, t, _ in rows)),
        "filament_used": float(sum(f or 0 for _, _, _, f in rows)),
    }


# ------------------------------------------------------------------ maintenance: lives in Moonraker, Mainsail's format
#
# Mainsail keeps each reminder as one item in Moonraker's database namespace "maintenance", keyed by a UUID:
#   name, note, perform_note, start_time / end_time (unix seconds), start_filament / end_filament (mm, from the job
#   totals), start_printtime / end_printtime (seconds, from the job totals), last_entry (the entry a repeat follows),
#   reminder: {type: null | "one-time" | "repeat", filament / printtime / date: {bool, value}}
# where a reminder's value is in metres of filament, hours of printing, or days. Writing exactly that keeps Mainsail
# showing and completing the same reminders.

NAMESPACE = "maintenance"
PLACEHOLDER = "MAINTENANCE_INIT"  # an item Mainsail writes to create the namespace; not a real reminder


def _entries(printer: Printer) -> dict[str, dict]:
    try:
        result = _call(printer, "GET", "/server/database/item", params={"namespace": NAMESPACE})
    except MoonrakerError as e:
        if e.kind == "not_found":
            return {}  # nobody has added a reminder on this printer yet
        raise
    value = result.get("value") or {}
    return {k: v for k, v in value.items() if isinstance(v, dict) and v.get("name") != PLACEHOLDER}


def _put(printer: Printer, key: str, value: dict) -> None:
    _call(printer, "POST", "/server/database/item", json={"namespace": NAMESPACE, "key": key, "value": value})


def _now() -> float:
    return dt.datetime.now(dt.timezone.utc).timestamp()


def _clean_reminder(reminder: dict | None) -> dict:
    reminder = reminder or {}
    kind = reminder.get("type")
    if kind not in (None, "one-time", "repeat"):
        raise ValueError("A reminder repeats, happens once, or isn't set")
    out = {"type": kind}
    for part in ("filament", "printtime", "date"):
        p = reminder.get(part) or {}
        on = bool(p.get("bool"))
        value = p.get("value")
        if on:
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"Give a number for the {_PART_NAMES[part]} reminder") from None
            if value <= 0:
                raise ValueError(f"The {_PART_NAMES[part]} reminder must be more than 0")
        out[part] = {"bool": on, "value": value if on else None}
    if kind is not None and not any(out[p]["bool"] for p in ("filament", "printtime", "date")):
        raise ValueError("Pick at least one of filament, print time or days for the reminder")
    return out


_PART_NAMES = {"filament": "filament", "printtime": "print time", "date": "days"}


def _status(entry: dict, totals: dict, now: float) -> dict:
    """Mainsail's rule: an open entry with a reminder is due once ANY of its enabled thresholds is reached."""
    if entry.get("end_time") is not None:
        return {"state": "done", "checks": []}
    reminder = entry.get("reminder") or {}
    if reminder.get("type") is None:
        return {"state": "no_reminder", "checks": []}
    filament = float(totals.get("total_filament_used") or 0)
    printtime = float(totals.get("total_print_time") or 0)
    checks = []
    if (reminder.get("filament") or {}).get("bool"):
        limit = float(reminder["filament"].get("value") or 0) * 1000  # metres -> mm
        used = filament - float(entry.get("start_filament") or 0)
        checks.append({"kind": "filament", "used": used / 1000, "limit": limit / 1000, "unit": "m", "due": used >= limit})
    if (reminder.get("printtime") or {}).get("bool"):
        limit = float(reminder["printtime"].get("value") or 0) * 3600  # hours -> seconds
        used = printtime - float(entry.get("start_printtime") or 0)
        checks.append({"kind": "printtime", "used": used / 3600, "limit": limit / 3600, "unit": "h", "due": used >= limit})
    if (reminder.get("date") or {}).get("bool"):
        limit = float(reminder["date"].get("value") or 0) * 86400  # days -> seconds
        used = now - float(entry.get("start_time") or now)
        checks.append({"kind": "date", "used": used / 86400, "limit": limit / 86400, "unit": "days", "due": used >= limit})
    return {"state": "due" if any(c["due"] for c in checks) else "ok", "checks": checks}


def list_maintenance(printer: Printer) -> dict:
    """Every reminder on the printer, with whether it's due, worked out against the printer's current totals."""
    entries = _entries(printer)
    totals = job_totals(printer)
    now = _now()
    out = []
    for key, e in entries.items():
        out.append({
            "id": key,
            "name": e.get("name") or "",
            "note": e.get("note") or "",
            "perform_note": e.get("perform_note"),
            "start_time": e.get("start_time"),
            "end_time": e.get("end_time"),
            "last_entry": e.get("last_entry"),
            "reminder": e.get("reminder") or {"type": None},
            **_status(e, totals, now),
        })
    out.sort(key=lambda x: (x["end_time"] is not None, -(x["end_time"] or x["start_time"] or 0)))
    return {"entries": out, "totals": totals}


def add_maintenance(printer: Printer, *, name: str, note: str, reminder: dict | None) -> str:
    """A new reminder, counted from now (and from the printer's current filament and print-time totals)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the maintenance a name")
    totals = job_totals(printer)
    key = str(uuid.uuid4())
    _put(printer, key, _new_entry(name, (note or "").strip(), _clean_reminder(reminder), totals, last_entry=None))
    return key


def _new_entry(name: str, note: str, reminder: dict, totals: dict, *, last_entry: str | None) -> dict:
    return {
        "name": name,
        "note": note,
        "perform_note": None,
        "start_time": _now(),
        "end_time": None,
        "start_filament": float(totals.get("total_filament_used") or 0),
        "end_filament": None,
        "start_printtime": float(totals.get("total_print_time") or 0),
        "end_printtime": None,
        "last_entry": last_entry,
        "reminder": reminder,
    }


def _get_entry(printer: Printer, key: str) -> dict:
    entry = _entries(printer).get(key)
    if entry is None:
        raise LookupError("That maintenance entry isn't on the printer any more. It may have been deleted in Mainsail.")
    return entry


def update_maintenance(printer: Printer, key: str, *, name: str | None, note: str | None, reminder: dict | None) -> None:
    """Change a reminder's name, note or thresholds; when it started (and anything already done) stays as it was."""
    entry = _get_entry(printer, key)
    if name is not None:
        if not name.strip():
            raise ValueError("Give the maintenance a name")
        entry["name"] = name.strip()
    if note is not None:
        entry["note"] = note.strip()
    if reminder is not None:
        entry["reminder"] = _clean_reminder(reminder)
    _put(printer, key, entry)


def perform_maintenance(printer: Printer, key: str, *, note: str | None) -> str | None:
    """
    Mark a reminder done, as Mainsail does: it's closed with the time and the printer's totals now, plus an optional
    note. A repeating reminder starts its next round straight away (a new entry pointing back at this one).
    Returns the new entry's id for a repeat, else None.
    """
    entry = _get_entry(printer, key)
    if entry.get("end_time") is not None:
        raise ValueError("That maintenance has already been marked done")
    totals = job_totals(printer)
    entry["end_time"] = _now()
    entry["end_filament"] = float(totals.get("total_filament_used") or 0)
    entry["end_printtime"] = float(totals.get("total_print_time") or 0)
    entry["perform_note"] = (note or "").strip() or None
    _put(printer, key, entry)
    reminder = entry.get("reminder") or {}
    if reminder.get("type") == "repeat":
        new_key = str(uuid.uuid4())
        _put(printer, new_key, _new_entry(entry["name"], entry.get("note") or "", dict(reminder), totals, last_entry=key))
        return new_key
    return None


def delete_maintenance(printer: Printer, key: str) -> None:
    _get_entry(printer, key)
    _call(printer, "DELETE", "/server/database/item", params={"namespace": NAMESPACE, "key": key})
