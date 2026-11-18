"""Bringing in: the other Farmhands' models and 3MFs this one hasn't got, from their records, their files used where
they are; and Load all settings' whole library step."""
from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import storage
from ...models import (
    Bundle, BundleNote, BundleSourceModel, BundleStar, BundleVersion, BundleVersionSubPrinter, Printer, SourceFileType,
    SourceModel, SourceModelNote, SourceModelVersion, SubPrinter,
)
from .. import sub_printer_service
from ...record_files import parse_iso, resolve_from
from ..app_settings import instance_id
from .moved import drop_doubles, relink_moved_models
from .reading import MODEL_PREFIX, THREEMF_PREFIX, _records, log


# ------------------------------------------------------------------ bringing in


def _known(paths) -> set[str]:
    return {os.path.realpath(p) for p in paths if p}


def import_models(db: Session) -> dict:
    """The other Farmhand's models this one hasn't got, from their records, their files used where they are."""
    root = storage.ready_root("stl")
    me = instance_id(db)
    known = _known(db.scalars(select(SourceModelVersion.file_path)))
    brought, skipped = [], []
    for _, doc in _records(root, MODEL_PREFIX, "farmhand_model"):
        if doc.get("instance") == me or not isinstance(doc.get("name"), str):
            continue
        versions = [v for v in (doc.get("versions") or []) if isinstance(v, dict)]
        here = [(v, resolve_from(root, v.get("path"))) for v in sorted(versions, key=lambda v: v.get("version") or 0)]
        here = [(v, p) for v, p in here if p and p.is_file()]
        if not here or any(os.path.realpath(p) in known for _, p in here):
            continue  # nothing there any more, or here already
        try:
            file_type = SourceFileType(doc.get("file_type"))
        except ValueError:
            skipped.append({"name": doc["name"], "reason": f"Its file type ({doc.get('file_type')}) isn't one Farmhand knows."})
            continue
        model = SourceModel(name=doc["name"][:255], file_type=file_type)
        db.add(model)
        db.flush()
        for n, (v, path) in enumerate(here, start=1):
            preview = resolve_from(root, v.get("preview"))
            db.add(SourceModelVersion(
                source_model_id=model.id, version=n, file_path=str(path), thumbnail_path=str(preview) if preview and preview.is_file() else None,
                note=v.get("note"), **({"uploaded_at": when} if (when := parse_iso(v.get("uploaded_at"))) else {}),
            ))
            known.add(os.path.realpath(path))
        if isinstance(doc.get("notes"), str) and doc["notes"].strip():
            model.note_row = SourceModelNote(source_model_id=model.id, body=doc["notes"], revision=1)
        db.commit()
        brought.append(model.name)
    return {"brought": brought, "skipped": skipped}


def import_bundles(db: Session) -> dict:
    """The other Farmhand's 3MFs this one hasn't got, from their records: for their printer (by name, it has to be
    here), with the models they were sliced from (by name, the ones here), every version with its settings."""
    root = storage.ready_root("threemf")
    me = instance_id(db)
    known = _known([*db.scalars(select(BundleVersion.threemf_path)), *db.scalars(select(BundleVersion.thumbnail_path))])
    brought, skipped = [], []
    for _, doc in _records(root, THREEMF_PREFIX, "farmhand_3mf"):
        if doc.get("instance") == me:
            continue
        versions = sorted([v for v in (doc.get("versions") or []) if isinstance(v, dict)], key=lambda v: v.get("version") or 0)
        found = [resolve_from(root, v.get("threemf")) or resolve_from(root, v.get("preview")) for v in versions]
        found = [p for p in found if p and p.is_file()]
        if not versions or not found or any(os.path.realpath(p) in known for p in found):
            continue  # nothing of it there any more, or here already
        label = versions[-1].get("filename") or "a 3MF"
        printer = db.scalar(select(Printer).where(Printer.name == doc.get("printer")))
        if printer is None:
            skipped.append({"name": label, "reason": f"It's for the printer {doc.get('printer')}, which isn't here: add that printer, then Load all settings again."})
            continue
        bundle = Bundle(printer_id=printer.id)
        db.add(bundle)
        db.flush()
        for name in doc.get("models") or []:
            model = db.scalar(select(SourceModel).where(SourceModel.name == name).order_by(SourceModel.id))
            if model is not None and db.get(BundleSourceModel, (bundle.id, model.id)) is None:
                db.add(BundleSourceModel(bundle_id=bundle.id, source_model_id=model.id))
        starred = None
        for v in versions:
            threemf, gcode, preview = (resolve_from(root, v.get(k)) for k in ("threemf", "gcode", "preview"))
            threemf = threemf if threemf and threemf.is_file() else None
            row = BundleVersion(
                bundle_id=bundle.id, version=int(v.get("version") or 1), filename=str(v.get("filename") or "")[:255],
                slicer_family=str(v.get("slicer_family") or "prusaslicer")[:50],
                slicer_display_name=str(v.get("slicer_display_name") or "")[:100],
                printer_profile_name=(str(v["printer_profile_name"])[:120] if v.get("printer_profile_name") else None),
                monument=bool(v.get("monument")), monument_note=v.get("monument_note"),
                full_files_retained=threemf is not None, threemf_path=str(threemf) if threemf else None,
                gcode_path=str(gcode) if threemf and gcode and gcode.is_file() else None,
                thumbnail_path=str(preview) if preview and preview.is_file() else None,
                settings=v.get("settings") if isinstance(v.get("settings"), dict) else {},
                **({"uploaded_at": when} if (when := parse_iso(v.get("uploaded_at"))) else {}),
            )
            db.add(row)
            db.flush()
            _link_sub_printer(db, printer, row, v)
            if v.get("version") == doc.get("starred_version"):
                starred = row
        if starred is not None:
            bundle.star_row = BundleStar(bundle_id=bundle.id, version_id=starred.id)
        if isinstance(doc.get("notes"), str) and doc["notes"].strip():
            bundle.note_row = BundleNote(bundle_id=bundle.id, body=doc["notes"], revision=1)
        db.commit()
        known.update(os.path.realpath(p) for p in found)
        brought.append(label)
    return {"brought": brought, "skipped": skipped}


def _link_sub_printer(db: Session, printer: Printer, row: BundleVersion, v: dict) -> bool:
    """A version brought in gets the printer's preset its record names (they come back with the printer's settings),
    else the one its slicer preset is known as here. Answers whether it got one."""
    name = v.get("sub_printer")
    sub = db.scalar(select(SubPrinter).where(SubPrinter.printer_id == printer.id, SubPrinter.name == name)) if isinstance(name, str) and name else None
    if sub is None and row.printer_profile_name:
        sub = sub_printer_service.known_as(db, printer.id, row.printer_profile_name)
    if sub is None:
        return False
    if row.sub_printer_link is None:
        row.sub_printer_link = BundleVersionSubPrinter(bundle_version_id=row.id, sub_printer_id=sub.id)
    else:
        row.sub_printer_link.sub_printer_id = sub.id
    return True


def fill_sub_printers(db: Session) -> int:
    """3MF versions brought in from records before they said the printer's preset (or before the printer had its
    presets back): given the one the newest record of their 3MF file names, where they have none. Answers how many."""
    root = storage.ready_root("threemf")
    named: dict[str, str] = {}
    for _, doc in _records(root, THREEMF_PREFIX, "farmhand_3mf"):
        for v in doc.get("versions") or []:
            p = resolve_from(root, v.get("threemf")) if isinstance(v, dict) else None
            if p and isinstance(v.get("sub_printer"), str) and v["sub_printer"]:
                named.setdefault(os.path.realpath(p), v["sub_printer"])
    if not named:
        return 0
    filled = 0
    for row in db.scalars(select(BundleVersion).where(BundleVersion.threemf_path.isnot(None))):
        if row.sub_printer_id is not None:
            continue
        name = named.get(os.path.realpath(row.threemf_path))
        if name and row.bundle.printer and _link_sub_printer(db, row.bundle.printer, row, {"sub_printer": name}):
            filled += 1
    if filled:
        db.commit()
    return filled


def import_library(db: Session) -> dict:
    """Models, then 3MFs (they name the models): {models: [names], threemfs: [names], skipped: [{name, reason}]}. A folder
    that's away is passed over. Models whose files another Farmhand moved are found again first (and the doubles that
    left behind taken out), so they aren't brought in a second time."""
    out = {"models": [], "threemfs": [], "skipped": []}
    try:
        relinked = relink_moved_models(db)
        dropped = drop_doubles(db)
        if relinked or dropped:
            log.info("Models found where another Farmhand moved them: %s; doubles taken out: %s", relinked, dropped)
    except storage.StorageUnavailableError:
        pass
    try:
        r = import_models(db)
        out["models"], out["skipped"] = r["brought"], out["skipped"] + r["skipped"]
    except storage.StorageUnavailableError:
        pass
    try:
        r = import_bundles(db)
        out["threemfs"], out["skipped"] = r["brought"], out["skipped"] + r["skipped"]
        fill_sub_printers(db)
    except storage.StorageUnavailableError:
        pass
    return out
