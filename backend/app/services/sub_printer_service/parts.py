"""A printer profile's parts (Toolhead, Hotend...): what's fitted, edited one at a time or all at once."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...errors import NotFound
from ...models import SubPrinter, SubPrinterPart
from .core import _apply, _keep_default_name, _printer_and_sub, _saved_parts


def parts(db: Session, printer_id: int, sub_printer_id: int) -> list[SubPrinterPart]:
    """The parts fitted to a printer profile, in the order they were added."""
    _, sub = _printer_and_sub(db, printer_id, sub_printer_id)
    return list(sub.parts)


def add_part(db: Session, printer_id: int, sub_printer_id: int, fields: dict) -> list[SubPrinterPart]:
    """Write down a part fitted to a printer profile. `fields` are already checked (SubPrinterPartIn)."""
    _, sub = _printer_and_sub(db, printer_id, sub_printer_id)
    sub.parts.append(SubPrinterPart(**fields))
    return _saved_parts(db, sub)


def _part(db: Session, printer_id: int, sub_printer_id: int, part_id: int) -> tuple[SubPrinter, SubPrinterPart]:
    _, sub = _printer_and_sub(db, printer_id, sub_printer_id)
    part = db.get(SubPrinterPart, part_id)
    if part is None or part.sub_printer_id != sub.id:
        raise NotFound(f"No part with id {part_id} on this printer profile")
    return sub, part


def update_part(db: Session, printer_id: int, sub_printer_id: int, part_id: int, fields: dict) -> list[SubPrinterPart]:
    """
    Change a part: every field is replaced (a blank one is cleared). A default part (Toolhead, Hotend...) keeps its
    name: ValueError if it's changed.
    """
    sub, part = _part(db, printer_id, sub_printer_id, part_id)
    _keep_default_name(part, fields.get("part", part.part))
    _apply(part, fields)
    return _saved_parts(db, sub)


def parts_left_out(db: Session, printer_id: int, sub_printer_id: int, rows: list[dict]) -> list[SubPrinterPart]:
    """The parts written down now that `rows` (the whole list, as save_parts takes it) leaves out: saving removes them."""
    kept = {row.get("id") for row in rows}
    return [p for p in parts(db, printer_id, sub_printer_id) if p.id not in kept]


def save_parts(db: Session, printer_id: int, sub_printer_id: int, rows: list[dict]) -> list[SubPrinterPart]:
    """
    Save a printer profile's whole parts list at once, as its Printer parts page was edited: a row with an id changes that
    part, one without is added (after the rest), and a part the rows leave out is removed. All of it, or nothing:
    ValueError for a default part renamed or a part listed twice, NotFound for an id that isn't one of its parts.
    """
    _, sub = _printer_and_sub(db, printer_id, sub_printer_id)
    now = {p.id: p for p in sub.parts}
    ids = [row["id"] for row in rows if row.get("id") is not None]
    kept = set(ids)
    if len(ids) != len(kept):
        raise ValueError("The same part is in the list twice")
    for row in rows:
        rid = row.get("id")
        if rid is None:
            continue
        if rid not in now:
            raise NotFound(f"No part with id {rid} on this printer profile")
        _keep_default_name(now[rid], row["part"])

    for part in [p for p in sub.parts if p.id not in kept]:
        sub.parts.remove(part)
    for row in rows:
        fields = {k: v for k, v in row.items() if k != "id"}
        rid = row.get("id")
        if rid is None:
            sub.parts.append(SubPrinterPart(**fields))
        else:
            _apply(now[rid], fields)
    return _saved_parts(db, sub)


def delete_part(db: Session, printer_id: int, sub_printer_id: int, part_id: int) -> list[SubPrinterPart]:
    sub, part = _part(db, printer_id, sub_printer_id, part_id)
    sub.parts.remove(part)
    return _saved_parts(db, sub)
