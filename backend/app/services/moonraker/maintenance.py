"""
Maintenance reminders. A Moonraker printer's live in Moonraker's own database, in Mainsail's format, so both apps
share one list. A PrusaLink printer has nowhere like that, so Farmhand keeps its reminders (in the same format) and
counts them against the print time it has recorded for it.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.orm import object_session

from ...models import MaintenanceEntry, Printer
from .client import MoonrakerError, _call, job_totals

# Mainsail keeps each reminder as one item in Moonraker's database namespace "maintenance", keyed by a UUID:
#   name, note, perform_note, start_time / end_time (unix seconds), start_filament / end_filament (mm, from the job
#   totals), start_printtime / end_printtime (seconds, from the job totals), last_entry (the entry a repeat follows),
#   reminder: {type: null | "one-time" | "repeat", filament / printtime / date: {bool, value}}
# where a reminder's value is in metres of filament, hours of printing, or days. Writing exactly that keeps Mainsail
# showing and completing the same reminders.

NAMESPACE = "maintenance"
PLACEHOLDER = "MAINTENANCE_INIT"  # an item Mainsail writes to create the namespace; not a real reminder


def _in_farmhand(printer: Printer) -> bool:
    return printer.connection_type == "prusalink"


def _totals(printer: Printer) -> dict:
    """The printer's lifetime totals: asked of Moonraker, or (PrusaLink) what Farmhand has recorded."""
    if _in_farmhand(printer):
        return (printer.connection_row.totals if printer.connection_row else None) or {}
    return job_totals(printer)


def _entries(printer: Printer) -> dict[str, dict]:
    if _in_farmhand(printer):
        return {r.key: dict(r.entry) for r in printer.maintenance_rows}
    try:
        result = _call(printer, "GET", "/server/database/item", params={"namespace": NAMESPACE})
    except MoonrakerError as e:
        if e.kind == "not_found":
            return {}  # nobody has added a reminder on this printer yet
        raise
    value = result.get("value") or {}
    return {k: v for k, v in value.items() if isinstance(v, dict) and v.get("name") != PLACEHOLDER}


def _put(printer: Printer, key: str, value: dict) -> None:
    if _in_farmhand(printer):
        row = next((r for r in printer.maintenance_rows if r.key == key), None)
        if row is None:
            printer.maintenance_rows.append(MaintenanceEntry(key=key, entry=value))
        else:
            row.entry = dict(value)  # a new dict, so the JSON column sees the change
            row.updated_at = dt.datetime.now(dt.timezone.utc)
        object_session(printer).commit()
        return
    _call(printer, "POST", "/server/database/item", json={"namespace": NAMESPACE, "key": key, "value": value})


def _remove(printer: Printer, key: str) -> None:
    if _in_farmhand(printer):
        printer.maintenance_rows = [r for r in printer.maintenance_rows if r.key != key]
        object_session(printer).commit()
        return
    _call(printer, "DELETE", "/server/database/item", params={"namespace": NAMESPACE, "key": key})


def _check_parts(printer: Printer, reminder: dict) -> dict:
    if _in_farmhand(printer) and (reminder.get("filament") or {}).get("bool"):
        raise ValueError("This printer doesn't report how much filament it uses: pick print time or days for the reminder")
    return reminder


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
    totals = _totals(printer)
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
    reminder = _check_parts(printer, _clean_reminder(reminder))
    totals = _totals(printer)
    key = str(uuid.uuid4())
    _put(printer, key, _new_entry(name, (note or "").strip(), reminder, totals, last_entry=None))
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
        entry["reminder"] = _check_parts(printer, _clean_reminder(reminder))
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
    totals = _totals(printer)
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
    _remove(printer, key)
