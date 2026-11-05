"""
A project's parts list (its bill of materials): what it needs that isn't printed. Each part has a name, a quantity, a
link to buy it and notes. Parts are added one at a time, or many at once from a BOM: a CSV file with a heading row
(Part, Quantity, Link, Notes; the template the Projects page offers), added to the list or replacing it.
"""
from __future__ import annotations

import csv
import io
import re
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from ..errors import NotFound
from ..models import ProjectPart
from .project_service import require_project

MAX_NAME_LENGTH = 200
MAX_NOTE_LENGTH = 1000
MAX_LINK_LENGTH = 1000
MAX_QUANTITY = 1_000_000
MAX_BOM_ROWS = 2000
MAX_BOM_BYTES = 2_000_000
_HAS_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:(?!\d)")  # "https:", but not the port in "shop.com:8080"

# A BOM's columns, by the headings they may have (any case, spaces ignored): the template's first
_HEADINGS = {
    "name": ("part", "partname", "name", "item", "description"),
    "quantity": ("quantity", "qty", "count", "amount"),
    "link": ("link", "purchaselink", "url", "buy", "buylink", "where"),
    "note": ("notes", "note", "comment", "comments"),
}


def clean_name(name: str | None) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("A part needs a name.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"A part's name can be at most {MAX_NAME_LENGTH} characters.")
    return name


def clean_quantity(quantity) -> int:
    try:
        n = int(str(quantity).strip()) if str(quantity).strip() else 1
    except ValueError:
        raise ValueError("The quantity must be a whole number.") from None
    if not 1 <= n <= MAX_QUANTITY:
        raise ValueError(f"The quantity must be from 1 to {MAX_QUANTITY}.")
    return n


def clean_link(link: str | None) -> str | None:
    """A web address to buy it from. One typed without http(s):// gets https:// ("amazon.com/..." works)."""
    link = (link or "").strip()
    if not link:
        return None
    if not _HAS_SCHEME.match(link):  # "mailto:", "javascript:"... keep theirs, and are refused below
        link = f"https://{link}"
    parts = urlsplit(link)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or " " in link:
        raise ValueError("The link must be a web address, like https://www.amazon.com/...")
    if len(link) > MAX_LINK_LENGTH:
        raise ValueError(f"A link can be at most {MAX_LINK_LENGTH} characters.")
    return link


def clean_note(note: str | None) -> str | None:
    note = (note or "").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise ValueError(f"A part's notes can be at most {MAX_NOTE_LENGTH} characters.")
    return note or None


def _require_part(db: Session, project_id: int, part_id: int) -> ProjectPart:
    part = db.get(ProjectPart, part_id)
    if part is None or part.project_id != project_id:
        raise NotFound("Part not found")
    return part


def add_part(db: Session, project_id: int, name: str, quantity=1, link: str | None = None, note: str | None = None):
    require_project(db, project_id)
    db.add(ProjectPart(
        project_id=project_id, name=clean_name(name), quantity=clean_quantity(quantity), link=clean_link(link),
        note=clean_note(note),
    ))
    db.commit()
    return require_project(db, project_id)


def update_part(db: Session, project_id: int, part_id: int, changes: dict):
    """changes: only the fields to change (name, quantity, link, note); a blank or null link or note clears it."""
    require_project(db, project_id)
    part = _require_part(db, project_id, part_id)
    if "name" in changes:
        part.name = clean_name(changes["name"])
    if changes.get("quantity") is not None:
        part.quantity = clean_quantity(changes["quantity"])
    if "link" in changes:
        part.link = clean_link(changes["link"])
    if "note" in changes:
        part.note = clean_note(changes["note"])
    db.commit()
    return require_project(db, project_id)


def delete_part(db: Session, project_id: int, part_id: int):
    require_project(db, project_id)
    db.delete(_require_part(db, project_id, part_id))
    db.commit()
    return require_project(db, project_id)


# ---- a BOM: many parts at once, from a CSV file ----


def _column(headings: list[str], field: str) -> int | None:
    keys = ["".join(h.lower().split()) for h in headings]
    for name in _HEADINGS[field]:
        if name in keys:
            return keys.index(name)
    return None


def read_bom(data: bytes) -> list[dict]:
    """
    The parts in a BOM: a CSV file whose first row names its columns (Part, Quantity, Link, Notes, in any order; only
    Part is needed). Blank rows are skipped. Every row is checked first, and a ValueError lists each one that's wrong
    ("Row 4: The quantity must be a whole number."), so a BOM goes in whole or not at all.
    """
    if len(data) > MAX_BOM_BYTES:
        raise ValueError("That BOM is too big: a CSV of at most 2 MB, please.")
    try:
        text = data.decode("utf-8-sig")  # Excel saves CSVs with a byte-order mark
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")  # an older Excel's own encoding
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")  # ";" from Excel set to a European language
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        raise ValueError("That BOM is empty: the template has the columns to fill in.")
    headings, body = rows[0], rows[1:]
    cols = {field: _column(headings, field) for field in _HEADINGS}
    if cols["name"] is None:
        raise ValueError("The BOM's first row needs a Part column (the template has Part, Quantity, Link and Notes).")

    def cell(row: list[str], field: str) -> str:
        i = cols[field]
        return row[i] if i is not None and i < len(row) else ""

    parts: list[dict] = []
    errors: list[str] = []
    for number, row in enumerate(body, start=2):  # row 1 is the headings
        if not any(c.strip() for c in row):
            continue
        try:
            parts.append({
                "name": clean_name(cell(row, "name")),
                "quantity": clean_quantity(cell(row, "quantity")),
                "link": clean_link(cell(row, "link")),
                "note": clean_note(cell(row, "note")),
            })
        except ValueError as e:
            errors.append(f"Row {number}: {e}")
    if errors:
        shown = errors[:10] + ([f"...and {len(errors) - 10} more."] if len(errors) > 10 else [])
        raise ValueError("Nothing was added. " + " ".join(shown))
    if not parts:
        raise ValueError("That BOM has no parts in it, only its heading row.")
    if len(parts) > MAX_BOM_ROWS:
        raise ValueError(f"A BOM can have at most {MAX_BOM_ROWS} parts.")
    return parts


def upload_bom(db: Session, project_id: int, data: bytes, replace: bool = False):
    """Add a BOM's parts to the project's list, or (replace) put them in its place. All or nothing."""
    require_project(db, project_id)
    parts = read_bom(data)
    if replace:
        for old in db.query(ProjectPart).filter(ProjectPart.project_id == project_id):
            db.delete(old)
    for p in parts:
        db.add(ProjectPart(project_id=project_id, **p))
    db.commit()
    return require_project(db, project_id), len(parts)
