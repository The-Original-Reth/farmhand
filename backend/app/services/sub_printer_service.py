"""
A printer's sub printers: its printer presets in PrusaSlicer (BOSS edition), the entries listed under a physical
printer in the Printers tab. Each 3MF version is linked to the one it was sliced with (printer_settings_id); a sub
printer it names that isn't known yet is added. They can be added, renamed and removed by hand too.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..errors import NotFound
from ..models import Bundle, BundleVersion, BundleVersionSubPrinter, Printer, SubPrinter, SubPrinterPart
from . import printer_service

logger = logging.getLogger("farmhand.sub_printers")

MAX_NAME = 120

# The parts every new sub printer starts with on its Printer parts page, to fill in (or remove), and whether each
# starts ticked "Add to name" (the Gantry only counts in the name when it's an AWD / 4WD / quad motor one)
DEFAULT_PARTS = (
    ("Toolhead", True), ("Hotend", True), ("Nozzle", True), ("Extruder", True), ("Gantry", True), ("XY motor", False),
)
DEFAULT_PART_NAMES = frozenset(name for name, _ in DEFAULT_PARTS)  # their names can't be changed


def _new(printer: Printer, name: str, *, default_parts: bool = True) -> SubPrinter:
    """A new sub printer on `printer`, starting with the default parts unless told otherwise."""
    sub = SubPrinter(printer_id=printer.id, name=name)
    if default_parts:
        sub.parts = [SubPrinterPart(part=p, in_name=ticked) for p, ticked in DEFAULT_PARTS]
    printer.sub_printers.append(sub)
    return sub


def _only_defaults(sub: SubPrinter) -> bool:
    """Its parts are just the defaults, none filled in or ticked differently: nothing has been written down yet."""
    return [(p.part, p.in_name) for p in sub.parts] == list(DEFAULT_PARTS) and not any(
        p.make or p.model or p.installed_on or p.note for p in sub.parts
    )


def _clean(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("A sub printer needs a name")
    if len(name) > MAX_NAME:
        raise ValueError(f"A sub printer's name can be at most {MAX_NAME} characters")
    return name


def _printer(db: Session, printer_id: int) -> Printer:
    printer = printer_service.get_printer(db, printer_id)
    if printer is None:
        raise NotFound(f"No printer with id {printer_id}")
    return printer


def _sub_printer(db: Session, printer_id: int, sub_printer_id: int) -> SubPrinter:
    sub = db.get(SubPrinter, sub_printer_id)
    if sub is None or sub.printer_id != printer_id:
        raise NotFound(f"No sub printer with id {sub_printer_id} on this printer")
    return sub


def _named(db: Session, printer_id: int, name: str) -> SubPrinter | None:
    return db.scalar(select(SubPrinter).where(SubPrinter.printer_id == printer_id, SubPrinter.name == name))


def _taken(printer: Printer, name: str) -> ValueError:
    return ValueError(f"{printer.name} already has a sub printer named {name!r}")


def add(db: Session, printer_id: int, name: str) -> Printer:
    """A sub printer added by hand. ValueError if the printer already has one by that name."""
    printer = _printer(db, printer_id)
    name = _clean(name)
    if _named(db, printer_id, name) is not None:
        raise _taken(printer, name)
    _new(printer, name)
    db.commit()
    db.refresh(printer)
    return printer


def rename(db: Session, printer_id: int, sub_printer_id: int, name: str) -> Printer:
    """Rename one: its 3MFs stay linked to it, and 3MFs sliced with the new name are linked to it from now on."""
    printer = _printer(db, printer_id)
    sub = _sub_printer(db, printer_id, sub_printer_id)
    name = _clean(name)
    other = _named(db, printer_id, name)
    if other is not None and other.id != sub.id:
        raise _taken(printer, name)
    sub.name = name
    db.commit()
    db.refresh(printer)
    return printer


def remove(db: Session, printer_id: int, sub_printer_id: int) -> Printer:
    """
    Remove one, and the parts written down for it. Its 3MFs stay, with no sub printer; one uploaded later that names it
    adds it again.
    """
    printer = _printer(db, printer_id)
    sub = _sub_printer(db, printer_id, sub_printer_id)
    db.execute(
        update(BundleVersionSubPrinter)
        .where(BundleVersionSubPrinter.sub_printer_id == sub.id)
        .values(sub_printer_id=None)
    )
    printer.sub_printers.remove(sub)
    db.commit()
    db.expire_all()  # the versions' links changed underneath the session
    return _printer(db, printer_id)


def parts(db: Session, printer_id: int, sub_printer_id: int) -> list[SubPrinterPart]:
    """The parts fitted to a sub printer, in the order they were added."""
    _printer(db, printer_id)
    return list(_sub_printer(db, printer_id, sub_printer_id).parts)


def add_part(db: Session, printer_id: int, sub_printer_id: int, fields: dict) -> list[SubPrinterPart]:
    """Write down a part fitted to a sub printer. `fields` are already checked (SubPrinterPartIn)."""
    _printer(db, printer_id)
    sub = _sub_printer(db, printer_id, sub_printer_id)
    sub.parts.append(SubPrinterPart(**fields))
    db.commit()
    db.refresh(sub)
    return list(sub.parts)


def _part(db: Session, printer_id: int, sub_printer_id: int, part_id: int) -> tuple[SubPrinter, SubPrinterPart]:
    _printer(db, printer_id)
    sub = _sub_printer(db, printer_id, sub_printer_id)
    part = db.get(SubPrinterPart, part_id)
    if part is None or part.sub_printer_id != sub.id:
        raise NotFound(f"No part with id {part_id} on this sub printer")
    return sub, part


def update_part(db: Session, printer_id: int, sub_printer_id: int, part_id: int, fields: dict) -> list[SubPrinterPart]:
    """
    Change a part: every field is replaced (a blank one is cleared). A default part (Toolhead, Hotend...) keeps its
    name: ValueError if it's changed.
    """
    sub, part = _part(db, printer_id, sub_printer_id, part_id)
    if part.part in DEFAULT_PART_NAMES and fields.get("part", part.part) != part.part:
        raise ValueError(f"{part.part} is one of the default parts, so its name can't be changed")
    for name, value in fields.items():
        setattr(part, name, value)
    db.commit()
    db.refresh(sub)
    return list(sub.parts)


def delete_part(db: Session, printer_id: int, sub_printer_id: int, part_id: int) -> list[SubPrinterPart]:
    sub, part = _part(db, printer_id, sub_printer_id, part_id)
    sub.parts.remove(part)
    db.commit()
    db.refresh(sub)
    return list(sub.parts)


def link(db: Session, version: BundleVersion, printer: Printer, preset_name: str | None) -> None:
    """
    Note which sub printer `version` was sliced with, adding it to `printer` if it isn't known yet. Doesn't commit:
    the caller does, with the version.
    """
    sub = None
    name = (preset_name or "").strip()[:MAX_NAME]
    if name:
        sub = _named(db, printer.id, name)
        if sub is None:
            sub = _new(printer, name)
    version.sub_printer_link = BundleVersionSubPrinter(bundle_version_id=version.id, sub_printer=sub)


def link_missing(db: Session) -> int:
    """
    3MF versions uploaded before sub printers existed: read the preset each was sliced with from its kept settings,
    and link it. Each version is only looked at once. Returns how many were linked to a sub printer.
    """
    linked = 0
    rows = db.execute(
        select(BundleVersion, Bundle.printer_id)
        .join(Bundle, Bundle.id == BundleVersion.bundle_id)
        .outerjoin(BundleVersionSubPrinter, BundleVersionSubPrinter.bundle_version_id == BundleVersion.id)
        .where(BundleVersionSubPrinter.bundle_version_id.is_(None))
        .order_by(BundleVersion.id)
    ).all()
    for version, printer_id in rows:
        name = (version.settings or {}).get("printer_settings_id")
        link(db, version, db.get(Printer, printer_id), name if isinstance(name, str) else None)
        db.flush()  # a name met twice is found the second time
        linked += version.sub_printer_id is not None
    db.commit()
    return linked


def record(printer: Printer) -> list[dict]:
    """A printer's sub printers and their parts, for its file in the settings copy."""
    return [
        {
            "name": s.name,
            "parts": [
                {
                    "part": p.part, "make": p.make, "model": p.model,
                    "installed_on": p.installed_on.isoformat() if p.installed_on else None, "note": p.note,
                    "in_name": p.in_name,
                }
                for p in s.parts
            ],
        }
        for s in printer.sub_printers
    ]


def _restored_part(rec) -> SubPrinterPart | None:
    if not isinstance(rec, dict) or not isinstance(rec.get("part"), str) or not rec["part"].strip():
        return None
    text = lambda v, n: (v.strip()[:n] or None) if isinstance(v, str) else None  # noqa: E731
    try:
        installed = dt.date.fromisoformat(rec["installed_on"]) if isinstance(rec.get("installed_on"), str) else None
    except ValueError:
        installed = None
    return SubPrinterPart(
        part=rec["part"].strip()[:120], make=text(rec.get("make"), 120), model=text(rec.get("model"), 200),
        installed_on=installed, note=text(rec.get("note"), 2000), in_name=rec.get("in_name") is True,
    )


def restore(db: Session, printer: Printer, saved) -> bool:
    """
    Sub printers from a saved printer record that this printer doesn't have yet, and the parts of any that have nothing
    written down (no parts, or only the untouched defaults; never mixed into a list someone filled in). Each is a
    name, or {name, parts} (records from before parts were names, and come back with the default parts). True if
    anything was added.
    """
    by_name = {s.name: s for s in printer.sub_printers}
    added = False
    for rec in saved if isinstance(saved, list) else []:
        name = rec if isinstance(rec, str) else rec.get("name") if isinstance(rec, dict) else None
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()[:MAX_NAME]
        saved_parts = rec.get("parts") if isinstance(rec, dict) and isinstance(rec.get("parts"), list) else None
        sub = by_name.get(name)
        if sub is None:
            sub = by_name[name] = _new(printer, name, default_parts=saved_parts is None)
            added = True
        if saved_parts is not None and (not sub.parts or _only_defaults(sub)):
            restored = list(filter(None, map(_restored_part, saved_parts[:500])))
            fields = lambda ps: [(p.part, p.make, p.model, p.installed_on, p.note, p.in_name) for p in ps]  # noqa: E731
            if fields(restored) != fields(sub.parts):
                sub.parts = restored
                added = True
    return added


def run_link_missing(session_factory) -> None:
    """At startup: link the 3MF versions from before sub printers. Never stops the API from coming up."""
    try:
        with session_factory() as db:
            linked = link_missing(db)
        if linked:
            logger.info("Linked %d 3MF version(s) to their sub printers", linked)
    except Exception:  # noqa: BLE001 - a version that can't be read stays unlinked; the rest of Farmhand carries on
        logger.exception("Linking 3MF versions to their sub printers failed")
