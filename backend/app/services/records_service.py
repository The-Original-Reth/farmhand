"""
Building the per-printer and per-model files (see app/records_store.py) from the database, and putting them back.

Restoring only ever ADDS: a printer that isn't in Farmhand comes back whole; for one that is, anything it's missing
(notes, its 1500-hour service, prints, meter readings) is filled in, and nothing it already has is overwritten. Notes
on models and 3MF files go back onto the models and 3MF files that match by name, and only where they have none.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import records_store
from ..models import (
    BundleNote,
    BundleStar,
    Printer,
    PrinterConnection,
    PrinterEnergyReading,
    PrinterNote,
    PrinterServiceNote,
    PrinterServiceReminder,
    PrintJob,
    SourceModel,
    SourceModelNote,
)


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)).isoformat()


def _when(value) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _num(value, default=None):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _text(value, limit=20000) -> str:
    return value[:limit] if isinstance(value, str) else ""


# ------------------------------------------------------------------ building the files


def _job_record(j: PrintJob) -> dict:
    return {
        "job_id": j.job_id, "filename": j.filename, "status": j.status,
        "start_time": _iso(j.start_time), "end_time": _iso(j.end_time),
        "print_duration": j.print_duration, "total_duration": j.total_duration, "filament_used": j.filament_used,
        "energy_kwh": j.energy_kwh, "avg_power_w": j.avg_power_w, "max_power_w": j.max_power_w,
        "metadata": j.job_metadata, "auxiliary": j.auxiliary,
    }


def printer_documents(db: Session) -> dict[str, dict]:
    """{file stem: document} for every printer. Never includes the Moonraker API key."""
    out: dict[str, dict] = {}
    taken: set[str] = set()
    for p in db.scalars(select(Printer).order_by(Printer.id)):
        conn, svc = p.connection_row, p.service_row
        jobs = db.scalars(select(PrintJob).where(PrintJob.printer_id == p.id).order_by(PrintJob.start_time, PrintJob.job_id))
        readings = db.scalars(
            select(PrinterEnergyReading).where(PrinterEnergyReading.printer_id == p.id).order_by(PrinterEnergyReading.taken_at)
        )
        out[records_store.file_stem(p.name, taken)] = {
            **records_store.header(records_store.PRINTERS_DIR, p.name),
            "note": "Written by Farmhand whenever this printer changes. Its Moonraker API key is never stored here.",
            "printer": {
                "kind": p.kind, "wired_ip": p.wired_ip, "wireless_ip": p.wireless_ip,
                "decommissioned": p.decommissioned, "moonraker_url": p.moonraker_url_override,
            },
            "notes": p.notes,
            "service": None if svc is None else {
                "enabled": svc.enabled, "interval_hours": svc.interval_hours, "start_printtime": svc.start_printtime,
                "started_at": _iso(svc.started_at), "history": svc.history,
            },
            "service_notes": p.service_note_row.body if p.service_note_row else "",
            "moonraker_totals": conn.totals if conn else None,
            "auxiliary_totals": conn.auxiliary_totals if conn else None,
            "print_jobs": [_job_record(j) for j in jobs],
            "energy_readings": [[_iso(r.taken_at), r.sensor, r.energy_kwh] for r in readings],
        }
    return out


def model_documents(db: Session) -> dict[str, dict]:
    """{file stem: document} for every model: its notes, and each of its 3MF files' notes and starred version."""
    out: dict[str, dict] = {}
    taken: set[str] = set()
    for m in db.scalars(select(SourceModel).order_by(SourceModel.id)):
        threemf = []
        for link in sorted(m.bundle_links, key=lambda link: link.bundle_id):
            b = link.bundle
            starred = next((v for v in b.versions if b.starred_version_id == v.id), None)
            threemf.append({
                "printer": b.printer.name,
                "filenames": [v.filename for v in sorted(b.versions, key=lambda v: v.version)],
                "notes": b.notes,
                "starred": None if starred is None else {"version": starred.version, "filename": starred.filename},
            })
        out[records_store.file_stem(m.name, taken)] = {
            **records_store.header(records_store.MODELS_DIR, m.name),
            "note": "Written by Farmhand whenever this model's notes, or its 3MF files' notes or stars, change.",
            "file_type": m.file_type.value,
            "notes": m.notes,
            "threemf": threemf,
        }
    return out


def write_all(db: Session, folder) -> dict:
    """Bring the printers/ and models/ files in the settings folder up to date."""
    return {
        "printers": records_store.write_records(folder, records_store.PRINTERS_DIR, printer_documents(db)),
        "models": records_store.write_records(folder, records_store.MODELS_DIR, model_documents(db)),
    }


# ------------------------------------------------------------------ putting them back (only ever adds)


def _fill_note(row, make, text: str) -> bool:
    """Give an owner its notes back if it has none. `row` is its note row (or None); `make()` creates one."""
    text = _text(text).strip("\n").rstrip()
    if not text:
        return False
    if row is None:
        make(text)
        return True
    if row.body:
        return False  # it has notes of its own: never overwritten
    row.body, row.revision, row.updated_at = text, row.revision + 1, dt.datetime.now(dt.timezone.utc)
    return True


def restore_printers(db: Session, records: list[dict]) -> dict:
    out = {"printers_added": [], "printers_filled": [], "prints_added": 0, "readings_added": 0, "warnings": []}
    for rec in records:
        name = rec["name"].strip()[:120]
        cfg = rec.get("printer") if isinstance(rec.get("printer"), dict) else {}
        printer = db.scalar(select(Printer).where(Printer.name == name))
        added = printer is None
        if added:
            printer = Printer(
                name=name, kind=_text(cfg.get("kind"), 200) or None,
                wired_ip=_text(cfg.get("wired_ip"), 45) or None, wireless_ip=_text(cfg.get("wireless_ip"), 45) or None,
                decommissioned=bool(cfg.get("decommissioned")),
            )
            db.add(printer)
            db.flush()
            url = _text(cfg.get("moonraker_url"), 255)
            if url.lower().startswith(("http://", "https://")):
                printer.connection_row = PrinterConnection(printer_id=printer.id, moonraker_url=url)
        filled = False

        filled |= _fill_note(printer.note_row, lambda t: setattr(printer, "note_row", PrinterNote(printer_id=printer.id, body=t, revision=1)), rec.get("notes"))
        filled |= _fill_note(
            printer.service_note_row,
            lambda t: setattr(printer, "service_note_row", PrinterServiceNote(printer_id=printer.id, body=t, revision=1)),
            rec.get("service_notes"),
        )

        svc = rec.get("service")
        if printer.service_row is None and isinstance(svc, dict) and _num(svc.get("start_printtime")) is not None:
            printer.service_row = PrinterServiceReminder(
                printer_id=printer.id, enabled=bool(svc.get("enabled", True)),
                interval_hours=_num(svc.get("interval_hours"), 1500.0), start_printtime=_num(svc.get("start_printtime")),
                started_at=_when(svc.get("started_at")) or dt.datetime.now(dt.timezone.utc),
                history=[h for h in (svc.get("history") or []) if isinstance(h, dict)][:1000],
            )
            filled = True

        if isinstance(rec.get("moonraker_totals"), dict) and (printer.connection_row is None or printer.connection_row.totals is None):
            conn = printer.connection_row or PrinterConnection(printer_id=printer.id)
            printer.connection_row = conn
            conn.totals = rec["moonraker_totals"]
            conn.auxiliary_totals = rec.get("auxiliary_totals") if isinstance(rec.get("auxiliary_totals"), list) else None
            filled = True

        known = set(db.scalars(select(PrintJob.job_id).where(PrintJob.printer_id == printer.id)))
        for j in rec.get("print_jobs") or []:
            if not isinstance(j, dict) or not isinstance(j.get("job_id"), str) or j["job_id"] in known:
                continue
            known.add(j["job_id"])
            db.add(PrintJob(
                printer_id=printer.id, job_id=j["job_id"][:64], filename=_text(j.get("filename"), 500),
                status=_text(j.get("status"), 32) or "unknown",
                start_time=_when(j.get("start_time")), end_time=_when(j.get("end_time")),
                print_duration=_num(j.get("print_duration"), 0.0), total_duration=_num(j.get("total_duration"), 0.0),
                filament_used=_num(j.get("filament_used"), 0.0), energy_kwh=_num(j.get("energy_kwh")),
                avg_power_w=_num(j.get("avg_power_w")), max_power_w=_num(j.get("max_power_w")),
                job_metadata=j.get("metadata") if isinstance(j.get("metadata"), dict) else {},
                auxiliary=j.get("auxiliary") if isinstance(j.get("auxiliary"), list) else [],
            ))
            out["prints_added"] += 1
            filled = True

        have = {_iso(t) for t in db.scalars(select(PrinterEnergyReading.taken_at).where(PrinterEnergyReading.printer_id == printer.id))}
        for r in rec.get("energy_readings") or []:
            if not (isinstance(r, list) and len(r) == 3):
                continue
            at, sensor, kwh = _when(r[0]), r[1], _num(r[2])
            if at is None or kwh is None or not isinstance(sensor, str) or at.isoformat() in have:
                continue
            have.add(at.isoformat())
            db.add(PrinterEnergyReading(printer_id=printer.id, taken_at=at, sensor=sensor[:120], energy_kwh=kwh))
            out["readings_added"] += 1
            filled = True

        db.commit()
        if added:
            out["printers_added"].append(name)
        elif filled:
            out["printers_filled"].append(name)
    return out


def restore_models(db: Session, records: list[dict]) -> dict:
    out = {"model_notes": 0, "threemf_notes": 0, "stars": 0, "models_missing": []}
    for rec in records:
        model = db.scalar(select(SourceModel).where(SourceModel.name == rec["name"]).order_by(SourceModel.id))
        if model is None:
            out["models_missing"].append(rec["name"])
            continue
        if _fill_note(model.note_row, lambda t: setattr(model, "note_row", SourceModelNote(source_model_id=model.id, body=t, revision=1)), rec.get("notes")):
            out["model_notes"] += 1
        for entry in rec.get("threemf") or []:
            if not isinstance(entry, dict):
                continue
            names = {f for f in entry.get("filenames") or [] if isinstance(f, str)}
            bundle = next(
                (link.bundle for link in model.bundle_links
                 if link.bundle.printer.name == entry.get("printer") and names & {v.filename for v in link.bundle.versions}),
                None,
            )
            if bundle is None:
                continue
            if _fill_note(bundle.note_row, lambda t, b=bundle: setattr(b, "note_row", BundleNote(bundle_id=b.id, body=t, revision=1)), entry.get("notes")):
                out["threemf_notes"] += 1
            star = entry.get("starred")
            if bundle.star_row is None and isinstance(star, dict):
                version = next(
                    (v for v in bundle.versions if v.version == star.get("version") and v.filename == star.get("filename")), None
                )
                if version is not None and version.version != 1:  # the initial version is never starred
                    bundle.star_row = BundleStar(bundle_id=bundle.id, version_id=version.id)
                    out["stars"] += 1
        db.commit()
    return out


def restore_all(db: Session, folder) -> dict:
    printers, warnings = records_store.read_records(folder, records_store.PRINTERS_DIR)
    models, model_warnings = records_store.read_records(folder, records_store.MODELS_DIR)
    out = {**restore_printers(db, printers), **restore_models(db, models)}
    out["warnings"] = out.get("warnings", []) + warnings + model_warnings
    return out


def count_records(folder) -> dict:
    """How many printer and model files a folder holds (for describing a folder before it's chosen)."""
    from pathlib import Path

    return {kind: len(list((Path(folder) / kind).glob("*.json"))) if (Path(folder) / kind).is_dir() else 0
            for kind in (records_store.PRINTERS_DIR, records_store.MODELS_DIR)}
