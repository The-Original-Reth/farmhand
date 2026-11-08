"""
A printer's print history as Farmhand has it (copied from Moonraker or PrusaLink), a page at a time: each print with
its filament and energy, and what they cost. A print's energy is priced at its month's price per kWh (the month it
started in, in the viewer's time zone; see config_store).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config_store
from ..models import PrintJob
from ..timeutil import as_utc, utc_iso
from . import config_service, filament_cost
from . import energy as energy_service


def jobs_page(db: Session, printer_id: int, *, limit: int, offset: int, status: str | None = None,
              q: str | None = None, tz: str | None = None) -> dict:
    """
    Newest first, with how many match in all. status: one status, or "failed" for anything not completed or
    running. q: words that must all appear in the file name.
    """
    where = [PrintJob.printer_id == printer_id]
    if status == "failed":
        where.append(PrintJob.status.notin_(["completed", "in_progress"]))
    elif status:
        where.append(PrintJob.status == status)
    for word in (q or "").lower().split():
        where.append(func.lower(PrintJob.filename).contains(word, autoescape=True))
    total = db.scalar(select(func.count()).select_from(PrintJob).where(*where))
    jobs = list(db.scalars(
        select(PrintJob).where(*where).order_by(PrintJob.start_time.desc().nullslast(), PrintJob.id.desc()).limit(limit).offset(offset)
    ))
    costs = filament_cost.costs(db, jobs)
    prefs = config_service.get_config(db)["preferences"]
    zone = energy_service.zone(tz)

    def month_price(j: PrintJob) -> float | None:
        started = as_utc(j.start_time) if j.start_time else dt.datetime.now(dt.timezone.utc)
        return config_store.energy_price_for(prefs, started.astimezone(zone).strftime("%Y-%m"))

    return {
        "total": total, "energy_price_per_kwh": prefs["energy_price_per_kwh"],
        "jobs": [job_out(j, costs[j.id], month_price(j)) for j in jobs],
    }


def job_out(j: PrintJob, cost: dict | None = None, kwh_price: float | None = None) -> dict:
    meta = j.job_metadata or {}
    # The print's energy at the average cost per kWh typed on the Power page; null without either
    energy_cost = round(j.energy_kwh * kwh_price, 2) if j.energy_kwh is not None and kwh_price is not None else None
    return {
        "id": j.id,
        "job_id": j.job_id,
        "filename": j.filename,
        "status": j.status,
        "start_time": utc_iso(j.start_time),
        "end_time": utc_iso(j.end_time),
        "print_duration": j.print_duration,
        "total_duration": j.total_duration,
        "filament_used": j.filament_used,
        "filament_grams": filament_cost.grams_used(j, cost),
        "slicer": meta.get("slicer"),
        "estimated_time": meta.get("estimated_time"),
        "layer_height": meta.get("layer_height"),
        "filament_type": meta.get("filament_type"),
        "energy_kwh": j.energy_kwh,  # null when the printer has no power meter set up in Moonraker
        "avg_power_w": j.avg_power_w,
        "max_power_w": j.max_power_w,
        # From filament_used and the 3MF it was sliced from (services/filament_cost.py); null when there's no match
        "filament_cost": cost["cost"] if cost else None,
        "filament_cost_detail": cost,
        "energy_price": kwh_price,  # $ per kWh for the month it started in
        "energy_cost": energy_cost,
        "total_cost": total_cost(cost["cost"] if cost else None, energy_cost),
    }


def total_cost(filament: float | None, energy: float | None) -> float | None:
    """Filament cost + energy cost. With no filament cost (none, or 0) the total is that filament cost; with no energy
    cost, the filament cost alone."""
    if not filament:
        return filament
    return round(filament + (energy or 0), 2)
