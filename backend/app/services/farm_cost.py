"""
The filament each printer used and what it cost, by month: what the Farm cost page adds up. Every print in Farmhand's
copy of the histories that used filament, each in the month it started (in the viewer's time zone), with its grams
and cost worked out as its print history row does (services/filament_cost.py).

And the record of each month: once a month is over, its Farm cost table is saved as a CSV (the page's Download CSV
for that month) in the farm cost folder: one chosen in Settings, or by default a "farm-cost" folder in the folder
above the STL / OBJ / STEP folder. See record_last_month.
"""
from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config_store, storage
from ..models import Bundle, BundleVersion, GcodeFilament, Printer, PrintJob
from ..timeutil import as_utc
from . import app_settings, config_service, energy, filament_cost
from .energy import zone

CHUNK = 500  # prints costed at a time, so a long history isn't all held at once

# {(printer id, time zone): (what its figures were made from, {"months", "days"})}: costing every print takes a while,
# so a printer's figures are kept until one of its prints, the G-codes read for it, or its 3MFs change (see _made_from)
_cache: dict[tuple[int, str], tuple[tuple, dict]] = {}
_cache_lock = threading.Lock()


def filament_by_month(db: Session, tz: str | None) -> dict:
    """
    {"printers": [{printer_id, months: [{key: "2026-10", prints, grams, filament_cost, unweighed, uncosted}], days,
    energy_days}]}, newest first. grams / filament_cost add up the prints whose weight / cost is known; unweighed /
    uncosted count the prints left out of them (no density or slicer estimate / no filament price). days: the same
    per day (key "2026-10-05"), and energy_days the printer's electricity per day (as energy.by_day): what the page
    shows when a printer is clicked while looking at a month.
    """
    where_tz = zone(tz)
    made_from = _made_from(db)
    out = []
    for printer_id in db.scalars(select(Printer.id).order_by(Printer.id)).all():
        key, now = (printer_id, str(where_tz)), made_from.get(printer_id)
        with _cache_lock:
            cached = _cache.get(key)
        if cached and cached[0] == now:
            figures = cached[1]
        else:
            figures = _printer_filament(db, printer_id, where_tz)
            with _cache_lock:
                _cache[key] = (now, figures)
        out.append({
            "printer_id": printer_id, **figures,
            "energy_days": [{"key": d["key"], "whole": d["whole"], "partial": d["partial"]} for d in energy.by_day(db, printer_id, tz)],
        })
    return {"printers": out}


def _made_from(db: Session) -> dict[int, tuple]:
    """
    For each printer, what its filament figures depend on, in a few numbers that change whenever any of it does: its
    prints (one added, removed, or changed by a sync: synced_at), the G-codes read for their price, and its 3MF versions.
    """
    jobs = db.execute(
        select(PrintJob.printer_id, func.count(), func.max(PrintJob.id), func.max(PrintJob.synced_at), func.sum(PrintJob.filament_used))
        .group_by(PrintJob.printer_id)
    ).all()
    gcodes = db.execute(
        select(GcodeFilament.printer_id, func.count(), func.max(GcodeFilament.id), func.max(GcodeFilament.read_at))
        .group_by(GcodeFilament.printer_id)
    ).all()
    versions = db.execute(
        select(Bundle.printer_id, func.count(), func.max(BundleVersion.id))
        .join(Bundle, Bundle.id == BundleVersion.bundle_id).group_by(Bundle.printer_id)
    ).all()
    out: dict[int, tuple] = {}
    for part, rows in enumerate((jobs, gcodes, versions)):
        for printer_id, *numbers in rows:
            out.setdefault(printer_id, [(), (), ()])[part] = tuple(numbers)
    return {pid: tuple(parts) for pid, parts in out.items()}


def _printer_filament(db: Session, printer_id: int, where_tz) -> dict:
    """One printer's {"months", "days"} (see filament_by_month), every print costed."""
    months: dict[str, dict] = {}
    days: dict[str, dict] = {}
    ids = db.scalars(
        select(PrintJob.id).where(PrintJob.printer_id == printer_id, PrintJob.filament_used > 0, PrintJob.start_time.isnot(None))
    ).all()
    for start in range(0, len(ids), CHUNK):
        jobs = list(db.scalars(select(PrintJob).where(PrintJob.id.in_(ids[start:start + CHUNK]))))
        costs = filament_cost.costs(db, jobs)
        for j in jobs:
            day = as_utc(j.start_time).astimezone(where_tz).strftime("%Y-%m-%d")
            grams = filament_cost.grams_used(j, costs[j.id])
            _count(months, day[:7], grams, costs[j.id])
            _count(days, day, grams, costs[j.id])
        db.expunge_all()  # done with these prints: don't keep them all in the session
    for m in (*months.values(), *days.values()):
        m["grams"], m["filament_cost"] = round(m["grams"], 1), round(m["filament_cost"], 2)
    return {"months": _newest_first(months), "days": _newest_first(days)}


def _count(rows: dict[str, dict], key: str, grams: float | None, cost: dict | None) -> None:
    """One print, in the month or day `key`: its grams and cost when known, else counted as left out of them."""
    m = rows.setdefault(key, {"key": key, "prints": 0, "grams": 0.0, "filament_cost": 0.0, "unweighed": 0, "uncosted": 0})
    m["prints"] += 1
    if grams is None:
        m["unweighed"] += 1
    else:
        m["grams"] += grams
    if cost is None:
        m["uncosted"] += 1
    else:
        m["filament_cost"] += cost["cost"]


def _newest_first(rows: dict[str, dict]) -> list[dict]:
    return sorted(rows.values(), key=lambda m: m["key"], reverse=True)


# ------------------------------------------------------------------ the record saved after each month

RECORDS_FOLDER = storage.FARM_COST_FOLDER  # the default: in the folder above the STL / OBJ / STEP folder
KEY_LOCATION = app_settings.FARM_COST_DIR_KEY  # the folder chosen in Settings; none = the default
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
CSV_HEAD = (
    "Period", "Printer", "Prints", "Filament (g)", "Filament cost ($)", "Electricity (kWh)", "Electricity cost ($)",
    "Total cost ($)", "Prints without a weight", "Prints without a filament price",
)
_QUOTE = '"'


def default_folder() -> Path:
    """The farm cost folder when none is chosen: "farm-cost" in the folder above the STL / OBJ / STEP folder (one still
    called "farm cost" there until it's renamed when next written to)."""
    return storage.named_folder(storage.effective_root("stl").parent, RECORDS_FOLDER)


def _chosen(db: Session, rename: bool = False) -> str | None:
    """The folder chosen in Settings, where it is now (see app_settings.current_folder)."""
    return app_settings.current_folder(db, KEY_LOCATION, rename=rename)


def records_folder(db: Session) -> Path:
    """
    Where a month's record goes: the folder chosen in Settings, else the default (see default_folder). Only while it
    can be written: a chosen folder still has its marker, the default's STL folder is ready. So an unmounted share
    never gets a record on the local disk underneath it: StorageUnavailableError otherwise.
    """
    chosen = _chosen(db, rename=True)
    if chosen:
        return storage.ensure_ready_folder(chosen, "farm cost folder")
    return storage.named_folder(storage.ready_root("stl").parent, RECORDS_FOLDER, rename=True)


def location_info(db: Session) -> dict:
    """For Settings: {path, is_default, default_path, status: {exists, writable, marker_ok, ready}}."""
    chosen = _chosen(db)
    default = default_folder()
    if chosen:
        return {"path": chosen, "is_default": False, "default_path": str(default), "status": storage.folder_status(Path(chosen))}
    try:
        storage.ready_root("stl")
        ready = True
    except storage.StorageUnavailableError:
        ready = False
    status = {"exists": default.is_dir(), "writable": ready, "marker_ok": ready, "ready": ready}  # made when first used
    return {"path": str(default), "is_default": True, "default_path": str(default), "status": status}


def set_location(db: Session, raw: str | None) -> dict:
    """
    Choose the farm cost folder (None or "" = back to the default). A chosen folder must be one that lasts (on a
    connected share or in Farmhand's own storage) and can be written; it gets Farmhand's marker, so records are only
    written while it's really there. ValueError says why one can't be used. Records already saved stay where they are.
    """
    if raw and raw.strip():
        real = storage.validate_location(raw.strip())
        storage.mark_location(real)
        app_settings.put(db, KEY_LOCATION, str(real))
    else:
        app_settings.put(db, KEY_LOCATION, None)
    db.commit()
    return location_info(db)


def record_name(month: str) -> str:
    """ "2026-10" -> "farmhand - farm cost - oct 2026.csv", as the page's Download CSV names it """
    return f"farmhand - farm cost - {_MONTHS[int(month[5:]) - 1]} {month[:4]}.csv"


def month_rows(db: Session, month: str, tz: str | None) -> list[dict]:
    """
    One month's table as the Farm cost page shows it: a row per active printer (in the page's order: as dragged, then
    the rest by name), then the whole farm, each
    {name, prints, grams, filament_cost, kwh, energy_cost, total, unweighed, uncosted}; None where the page shows "—".
    """
    filament = {p["printer_id"]: p["months"] for p in filament_by_month(db, tz)["printers"]}
    prefs = config_service.get_config(db)["preferences"]
    price = config_store.energy_price_for(prefs, month)
    rows = []
    for printer in in_page_order(db.scalars(select(Printer).where(Printer.decommissioned.is_(False)).order_by(Printer.name)).all(),
                                 prefs.get("farm_cost_order") or []):
        f = next((m for m in filament.get(printer.id, []) if m["key"] == month), None)
        e = next((m for m in energy.by_month(db, printer.id, tz) if m["key"] == month), None)
        kwh = e["whole"] if e else None
        row = {
            "name": printer.name, "prints": f["prints"] if f else 0,
            "grams": f["grams"] if f and f["prints"] > f["unweighed"] else None,
            "filament_cost": f["filament_cost"] if f and f["prints"] > f["uncosted"] else None,
            "kwh": kwh, "energy_cost": kwh * price if kwh is not None and price is not None else None,
            "unweighed": f["unweighed"] if f else 0, "uncosted": f["uncosted"] if f else 0,
        }
        row["total"] = None if row["filament_cost"] is None and row["energy_cost"] is None \
            else (row["filament_cost"] or 0) + (row["energy_cost"] or 0)
        rows.append(row)
    farm = {"name": "Whole farm", "prints": sum(r["prints"] for r in rows),
            "unweighed": sum(r["unweighed"] for r in rows), "uncosted": sum(r["uncosted"] for r in rows)}
    for k in ("grams", "filament_cost", "kwh", "energy_cost", "total"):
        known = [r[k] for r in rows if r[k] is not None]
        farm[k] = sum(known) if known else None
    return [*rows, farm]


def in_page_order(printers: list, order: list[int]) -> list:
    """The printers as the Farm cost page lists them: those in `order` (as dragged) first, then the rest as they come."""
    place = {pid: i for i, pid in enumerate(order)}
    return sorted(printers, key=lambda p: place.get(p.id, len(order)))  # sorted keeps the rest in their order


def csv_text(period: str, rows: list[dict]) -> str:
    """The rows as the page's Download CSV writes them: plain numbers, blank for "—", a byte-order mark for Excel."""
    def cell(v) -> str:
        s = "" if v is None else str(round(v, 3)) if isinstance(v, float) else str(v)
        if any(ch in s for ch in (",", _QUOTE, "\r", "\n")):
            return _QUOTE + s.replace(_QUOTE, _QUOTE * 2) + _QUOTE
        return s

    def money(v):
        return None if v is None else f"{v:.2f}"

    lines = [",".join(CSV_HEAD)]
    for r in rows:
        lines.append(",".join(cell(v) for v in (
            period, r["name"], r["prints"], r["grams"], money(r["filament_cost"]), r["kwh"], money(r["energy_cost"]),
            money(r["total"]), r["unweighed"] or None, r["uncosted"] or None,
        )))
    return "﻿" + "\r\n".join(lines) + "\r\n"


def last_month(now: dt.datetime, tz: str | None) -> str:
    """The month before the one it is now in that time zone: "2026-10" on any day of November."""
    first = now.astimezone(zone(tz)).replace(day=1)
    return (first - dt.timedelta(days=1)).strftime("%Y-%m")


def record_last_month(db: Session, now: dt.datetime | None = None) -> Path | None:
    """
    Save the month that just ended as a record (see records_folder), unless it's there already: a record is written
    once and never replaced. Months end in the time zone the farm's browser last told the server (UTC until it has).
    Returns the file written, or None when it was there already. StorageUnavailableError when the folder can't be
    written right now (it's tried again later).
    """
    tz = config_service.get_config(db)["preferences"].get("time_zone")
    month = last_month(now or dt.datetime.now(dt.timezone.utc), tz)
    target = records_folder(db) / record_name(month)
    if target.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    storage.write_bytes_atomically(target, csv_text(month, month_rows(db, month, tz)).encode("utf-8"))
    return target


def records_status(db: Session) -> dict:
    """For the page: {folder, problem, saved: [file names, newest month first]}."""
    try:
        folder = records_folder(db)
    except storage.StorageUnavailableError as e:
        return {"folder": None, "problem": str(e), "saved": []}
    names = [p.name for p in folder.glob("farmhand - farm cost - *.csv")] if folder.is_dir() else []
    return {"folder": str(folder), "problem": None, "saved": sorted(names, key=_record_month, reverse=True)}


def _record_month(name: str) -> str:
    """ "farmhand - farm cost - oct 2026.csv" -> "2026-10", so records sort by month """
    parts = name.removesuffix(".csv").split(" ")
    try:
        return f"{parts[-1]}-{_MONTHS.index(parts[-2]) + 1:02d}"
    except (ValueError, IndexError):
        return name
