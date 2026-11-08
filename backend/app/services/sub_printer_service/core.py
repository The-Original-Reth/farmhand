"""What a printer profile is, and adding, copying, renaming and removing one (see the package for what they are)."""
from __future__ import annotations

import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...errors import NotFound
from ...models import (
    BundleVersion, BundleVersionSubPrinter, DefaultSubPrinter, Printer, SubPrinter, SubPrinterAlias, SubPrinterPart, SubPrinterSettingsCopy,
)
from .. import printer_service

logger = logging.getLogger("farmhand.sub_printers")

MAX_NAME = 120

# The parts every new printer profile starts with on its Printer parts page, to fill in (or remove), and whether each
# starts ticked "Add to name" (the Gantry only counts in the name when it's an AWD / 4WD / quad motor one)
DEFAULT_PARTS = (
    ("Toolhead", True), ("Hotend", True), ("Nozzle", True), ("Extruder", True), ("Gantry", True), ("XY motor", False),
)
DEFAULT_PART_NAMES = frozenset(name for name, _ in DEFAULT_PARTS)  # their names can't be changed
# What's written down about a part (all of it but its id)
PART_FIELDS = ("part", "make", "model", "installed_on", "note", "in_name")


def _fields_of(part: SubPrinterPart) -> dict:
    return {name: getattr(part, name) for name in PART_FIELDS}


def _apply(part: SubPrinterPart, fields: dict) -> None:
    """Every field given replaces the part's own (a blank one clears it)."""
    for name, value in fields.items():
        setattr(part, name, value)


def _text(value, limit: int) -> str | None:
    """A saved record's text field, trimmed and cut to fit; None when it's blank or not text."""
    return (value.strip()[:limit] or None) if isinstance(value, str) else None


def _keep_default_name(part: SubPrinterPart, new_name: str) -> None:
    """A default part (Toolhead, Hotend...) keeps its name: ValueError if `new_name` changes it."""
    if part.part in DEFAULT_PART_NAMES and new_name != part.part:
        raise ValueError(f"{part.part} is one of the default parts, so its name can't be changed")


def _new(printer: Printer, name: str, *, default_parts: bool = True) -> SubPrinter:
    """A new printer profile on `printer`, starting with the default parts unless told otherwise."""
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
        raise ValueError("A printer profile needs a name")
    if len(name) > MAX_NAME:
        raise ValueError(f"A printer profile's name can be at most {MAX_NAME} characters")
    return name


_printer = printer_service.require_printer


def _sub_printer(db: Session, printer_id: int, sub_printer_id: int) -> SubPrinter:
    sub = db.get(SubPrinter, sub_printer_id)
    if sub is None or sub.printer_id != printer_id:
        raise NotFound(f"No printer profile with id {sub_printer_id} on this printer")
    return sub


def _printer_and_sub(db: Session, printer_id: int, sub_printer_id: int) -> tuple[Printer, SubPrinter]:
    """The printer, then its printer profile: NotFound for either (the printer is checked first)."""
    return _printer(db, printer_id), _sub_printer(db, printer_id, sub_printer_id)


def _saved(db: Session, printer: Printer) -> Printer:
    """Commit, and answer the printer as it now is."""
    db.commit()
    db.refresh(printer)
    return printer


def _saved_parts(db: Session, sub: SubPrinter) -> list[SubPrinterPart]:
    """Commit, and answer the printer profile's parts as they now are."""
    db.commit()
    db.refresh(sub)
    return list(sub.parts)


def _named(db: Session, printer_id: int, name: str) -> SubPrinter | None:
    return db.scalar(select(SubPrinter).where(SubPrinter.printer_id == printer_id, SubPrinter.name == name))


def known_as(db: Session, printer_id: int, preset_name: str) -> SubPrinter | None:
    """
    The printer's printer profile a 3MF with this preset goes to: one that has been known by that name (renamed from it,
    or given 3MFs with that preset by hand on upload: the last choice wins), else the one called that.
    """
    return db.scalar(
        select(SubPrinter)
        .join(SubPrinterAlias, SubPrinterAlias.sub_printer_id == SubPrinter.id)
        .where(SubPrinter.printer_id == printer_id, SubPrinterAlias.name == preset_name)
    ) or _named(db, printer_id, preset_name)


def _remember(db: Session, sub: SubPrinter, preset_name: str) -> None:
    """From now on a 3MF with this preset goes to `sub` (and no longer to another of the printer's that had it)."""
    if not preset_name or preset_name == sub.name or preset_name in sub.aliases:
        return
    for other in db.scalars(
        select(SubPrinterAlias)
        .join(SubPrinter, SubPrinter.id == SubPrinterAlias.sub_printer_id)
        .where(SubPrinter.printer_id == sub.printer_id, SubPrinterAlias.name == preset_name)
    ):
        other.sub_printer.alias_rows.remove(other)
    sub.alias_rows.append(SubPrinterAlias(name=preset_name[:MAX_NAME]))


def _taken(printer: Printer, name: str) -> ValueError:
    return ValueError(f"{printer.name} already has a printer profile named {name!r}")


def add(db: Session, printer_id: int, name: str) -> Printer:
    """A printer profile added by hand. ValueError if the printer already has one by that name."""
    printer = _printer(db, printer_id)
    name = _clean(name)
    if _named(db, printer_id, name) is not None:
        raise _taken(printer, name)
    _new(printer, name)
    return _saved(db, printer)


def copy_name(printer: Printer, name: str) -> str:
    """The name a copy of `name` gets unless told otherwise: "<name> - copy", or "- copy 2", 3... when that's taken."""
    taken = {s.name for s in printer.sub_printers}
    n = 1
    while True:
        tail = " - copy" if n == 1 else f" - copy {n}"
        candidate = name[: MAX_NAME - len(tail)].rstrip() + tail
        if candidate not in taken:
            return candidate
        n += 1


def _settings_of(db: Session, sub: SubPrinter) -> tuple[dict, str | None] | None:
    """
    A printer profile's printer settings as its Printer Settings window shows them: from the newest 3MF sliced with it,
    else, for a copy with none of its own yet, the ones it was copied with. (settings, where they're from); None for one
    no 3MF has been sliced with.
    """
    newest = db.scalar(
        select(BundleVersion)
        .join(BundleVersionSubPrinter, BundleVersionSubPrinter.bundle_version_id == BundleVersion.id)
        .where(BundleVersionSubPrinter.sub_printer_id == sub.id)
        .order_by(BundleVersion.uploaded_at.desc(), BundleVersion.id.desc())
        .limit(1)
    )
    if newest is not None:
        return dict(newest.settings), f"{newest.filename or newest.bundle.name} · v{newest.version}"[:255]
    if sub.settings_copy is not None:
        return dict(sub.settings_copy.settings), sub.settings_copy.from_file
    return None


def copy(db: Session, printer_id: int, sub_printer_id: int, name: str | None = None) -> Printer:
    """
    A new printer profile on the same printer, with a copy of its parts and of its printer settings (from its newest 3MF;
    see SubPrinterSettingsCopy). Its 3MFs, the names it was known by and being the default stay with the original.
    `name` defaults to copy_name; ValueError if the printer already has one by it.
    """
    printer, sub = _printer_and_sub(db, printer_id, sub_printer_id)
    name = _clean(name) if name is not None else copy_name(printer, sub.name)
    if _named(db, printer_id, name) is not None:
        raise _taken(printer, name)
    new = _new(printer, name, default_parts=False)
    new.parts = [SubPrinterPart(**_fields_of(p)) for p in sub.parts]
    found = _settings_of(db, sub)
    if found is not None:
        settings, from_file = found
        new.settings_copy = SubPrinterSettingsCopy(copied_from=sub.name, from_file=from_file, settings=settings)
    return _saved(db, printer)


def settings_copy(db: Session, printer_id: int, sub_printer_id: int) -> SubPrinterSettingsCopy:
    """A copied printer profile's printer settings. NotFound when it has none (it isn't a copy, or the original had none)."""
    _, sub = _printer_and_sub(db, printer_id, sub_printer_id)
    if sub.settings_copy is None:
        raise NotFound("This printer profile has no copied printer settings")
    return sub.settings_copy


def rename(db: Session, printer_id: int, sub_printer_id: int, name: str) -> Printer:
    """
    Rename one: its 3MFs stay linked to it, and 3MFs sliced with either name go to it from now on (the old one is
    remembered as a name it was known by).
    """
    printer, sub = _printer_and_sub(db, printer_id, sub_printer_id)
    name = _clean(name)
    other = _named(db, printer_id, name)
    if other is not None and other.id != sub.id:
        raise _taken(printer, name)
    old = sub.name
    sub.name = name
    sub.alias_rows = [a for a in sub.alias_rows if a.name != name]  # its name now, not a name it was known by
    _remember(db, sub, old)
    return _saved(db, printer)


def remove(db: Session, printer_id: int, sub_printer_id: int) -> Printer:
    """
    Remove one, and the parts written down for it. Its 3MFs stay, with no printer profile; one uploaded later that names it
    adds it again.
    """
    printer, sub = _printer_and_sub(db, printer_id, sub_printer_id)
    db.execute(
        update(BundleVersionSubPrinter)
        .where(BundleVersionSubPrinter.sub_printer_id == sub.id)
        .values(sub_printer_id=None)
    )
    if printer.default_sub_printer_id == sub.id:
        printer.default_sub_printer_row = None  # no default any more
    printer.sub_printers.remove(sub)
    db.commit()
    db.expire_all()  # the versions' links changed underneath the session
    return _printer(db, printer_id)


def set_default(db: Session, printer_id: int, sub_printer_id: int | None) -> Printer:
    """
    The printer profile the printer's uploads start on (None: no default, Farmhand guesses from the preset). NotFound for
    a printer profile that isn't the printer's.
    """
    printer = _printer(db, printer_id)
    if sub_printer_id is None:
        printer.default_sub_printer_row = None
    else:
        sub = _sub_printer(db, printer_id, sub_printer_id)
        if printer.default_sub_printer_row is None:
            printer.default_sub_printer_row = DefaultSubPrinter(printer_id=printer.id, sub_printer_id=sub.id)
        else:
            printer.default_sub_printer_row.sub_printer_id = sub.id
    return _saved(db, printer)
