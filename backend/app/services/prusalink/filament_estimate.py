"""
The filament a PrusaLink print used, estimated: PrusaLink gives only the printed file's name and size (no filament
figure, even where its spec has one), so Farmhand finds the 3MF version that file was sliced from and takes the
slicer's own "filament used" from that version's stored G-code. Nothing more is read from the printer.

Which version: on the same printer, the one whose stored G-code has the printed file's name (ignoring case, and spaces
versus underscores); else the one whose 3MF name matches as filament_cost matches names. Of several, the newest one
uploaded before the print started. No match, or no stored G-code (pruned), and the print keeps no filament figure;
nor when the 3MF matched by name but its stored G-code is another of PrusaSlicer's names for it ("..._3h0m" printed,
"..._8h59m" stored): a different slicing, whose filament isn't this print's.

The print's filament_used (mm) is then the slicer's figure, times how far it got: all of it for a completed print, the
last progress seen for one that stopped part way (or is still running), or for a print recorded before progress was
kept, the time it printed over the time the printer expected. Its metadata says "filament_estimated", and
keeps what was found under "filament_estimate" ({version_id, checked, filament_mm, filament_g, filament_cost}), so
the G-code is read once per print, not on every look. A print with no match is looked at again only once another 3MF
version has been added to the printer (checked: the newest version id there was).

Two other sources of the slicer's figure come before and after it. First, Prusa Connect's: it reads the figures from a
file it sent to the printer, and the plugin passes them on ("connect_slicer"). Last, the printed file itself, read
through the printer's PrusaLink (printed_filament.py, once per file, read only): asked for a print Farmhand is
following when neither of the others has a figure ("file_estimate": "wanted", then what was found). Which one was used
is "filament_estimate_source": "prusa_connect", "3mf" or "printed_file". Older prints get a printed file's figure only
when one is asked for them (the one-off backfill), never on their own.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Bundle, BundleVersion, PrintedFileEstimate, Printer, PrintJob
from ...parsers import gcode
from ...parsers.gcode import slicer_filament
from .. import filament_cost as fc
from . import printed_filament

KEY = fc.ESTIMATE
FILE = "file_estimate"  # in a print's metadata: "wanted" (the printed file is to be read), then {id} of what was read
WANTED = "wanted"


def update(db: Session, printer: Printer, touched: list[PrintJob]) -> None:
    """
    Estimate the filament of the prints this look changed (`touched`), and of any print of this printer still without
    a filament figure (prints recorded before this, or whose 3MF was added since).
    """
    newest = db.scalar(
        select(func.max(BundleVersion.id)).join(Bundle, Bundle.id == BundleVersion.bundle_id).where(Bundle.printer_id == printer.id)
    ) or 0
    rows = {r.id: r for r in touched}
    fresh = set(rows)
    files = set(db.scalars(select(PrintedFileEstimate.filename).where(
        PrintedFileEstimate.printer_id == printer.id, PrintedFileEstimate.filament_mm.isnot(None),
    )))
    for r in db.scalars(select(PrintJob).where(
        # only the prints PrusaLink tracking recorded ("<job>@<start>"), not ones from when it was a Klipper printer
        PrintJob.printer_id == printer.id, PrintJob.filament_used == 0, PrintJob.job_id.contains("@"),
    )):
        if r.id not in rows and _worth_looking(r, newest, files):
            rows[r.id] = r
    for r in rows.values():
        if not (r.job_metadata or {}).get("filament_measured"):  # one measured by the printer keeps its figure
            estimate(db, printer.id, r, newest, fresh=r.id in fresh)


def read_files(db: Session, printer: Printer, touched: list[PrintJob]) -> None:
    """Read (once, in the background) the printed file of each print this look changed that has no figure from
    Prusa Connect or a 3MF: after the commit, as the prices are read."""
    for row in touched:
        if (row.job_metadata or {}).get(FILE) == WANTED:
            printed_filament.start_estimate(db, printer, row)


def _worth_looking(row: PrintJob, newest: int, files: set[str] = frozenset()) -> bool:
    if (row.job_metadata or {}).get(FILE) == WANTED and row.filename in files:
        return True  # its printed file has been read since
    found = (row.job_metadata or {}).get(KEY)
    if not isinstance(found, dict):
        return True
    if found.get("version_id") is None:
        return (found.get("checked") or 0) < newest  # another 3MF version since it was last looked for
    return bool(found.get("filament_mm")) and _fraction(row) is not None  # its figure can be worked out now


def estimate(db: Session, printer_id: int, row: PrintJob, newest: int, fresh: bool = False) -> None:
    """
    Find (once) the slicer's filament for this print, and set its filament_used from it and how far it got: Prusa
    Connect's figure, else the 3MF's, else the printed file's (asked for only when `fresh`: a print this look changed,
    or the backfill's).
    """
    meta = dict(row.job_metadata or {})
    found = meta.get(KEY)
    if not isinstance(found, dict) or (found.get("version_id") is None and (found.get("checked") or 0) < newest):
        found = _look_up(db, printer_id, row, newest)
        if found is None:
            return  # its G-code can't be read right now (a share not mounted): tried again next time
        meta[KEY] = found
    connect = meta.get("connect_slicer") if isinstance(meta.get("connect_slicer"), dict) else {}
    if _number(connect.get("filament_mm")):
        mm, grams, source = connect["filament_mm"], _number(connect.get("filament_g")), "prusa_connect"
    elif found.get("filament_mm"):
        mm, grams, source = found["filament_mm"], found.get("filament_g"), "3mf"
    else:
        mm = grams = source = None
        if fresh or meta.get(FILE) == WANTED:
            read = printed_filament.estimate_for(db, printer_id, row)
            if read is not None:
                mm, grams, source = read.filament_mm, read.filament_g, "printed_file"
                meta[FILE] = {"id": read.id}
            elif meta.get(FILE) is None and _readable(row):
                meta[FILE] = WANTED
    fraction = _fraction(row)
    if mm and fraction is not None:
        row.filament_used = round(mm * fraction, 2)
        meta["filament_estimated"] = True
        meta["filament_estimate_source"] = source
        if grams:
            # the slicer's weight per mm, for its grams when the 3MF has no density (filament_cost.grams_used)
            meta["filament_total"], meta["filament_weight_total"] = mm, grams
    if meta != (row.job_metadata or {}):
        row.job_metadata = meta


def _readable(row: PrintJob) -> bool:
    """Whether the print's file can be read on the printer: a G-code, where the printer said it is."""
    return bool((row.job_metadata or {}).get("path")) and (row.filename or "").lower().endswith(gcode.GCODE_EXTENSIONS)


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _fraction(row: PrintJob) -> float | None:
    """
    How much of the print was printed: all of a completed one, else the last progress seen; for a print recorded
    before the progress was kept, the time it printed over the time the printer expected it to take. None: not known.
    """
    if row.status == "completed":
        return 1.0
    meta = row.job_metadata or {}
    progress = _number(meta.get("progress"))
    if progress is not None:
        return min(max(progress, 0.0), 100.0) / 100
    expected = _number(meta.get("estimated_time"))
    if expected and expected > 0 and row.print_duration:
        return min(max(row.print_duration / expected, 0.0), 1.0)
    return None


def _look_up(db: Session, printer_id: int, row: PrintJob, newest: int) -> dict | None:
    """What's found for a print: {version_id, checked, filament_mm, filament_g, filament_cost}; version_id None when no
    3MF matches. None when the matched version's G-code can't be read right now."""
    rows = db.execute(
        select(BundleVersion.id, BundleVersion.filename, BundleVersion.gcode_path)
        .join(Bundle, Bundle.id == BundleVersion.bundle_id).where(Bundle.printer_id == printer_id)
    ).all()
    printed = fc._stem(row.filename)
    ids = [vid for vid, _, gcode in rows if gcode and fc._key(fc._stem(gcode)) == fc._key(printed)] if printed else []
    by_gcode = bool(ids)
    if not ids and printed:
        exact, by_base = fc.name_index((vid, name, printer_id) for vid, name, _ in rows)
        ids = fc._match(printed, exact.get(printer_id, {}), by_base.get(printer_id, {})) or []
    out = {"version_id": None, "checked": newest, "filament_mm": None, "filament_g": None, "filament_cost": None}
    if not ids:
        return out
    v = fc._pick([db.get(BundleVersion, i) for i in ids], row.start_time)
    out["version_id"] = v.id
    if not by_gcode and v.gcode_path and _another_slicing(v.gcode_path, printed):
        return out  # the right 3MF, but its stored G-code is a different slicing of it: its figure isn't this print's
    if v.gcode_path and v.full_files_retained:
        try:
            with open(v.gcode_path, "rb") as f:
                out.update(slicer_filament(f, v.gcode_path))
        except OSError:
            return None
    return out


def _another_slicing(gcode_path: str, printed: str) -> bool:
    """Whether the stored G-code and the printed file both have PrusaSlicer's own names ("..._0.4n_0.16mm_PLA_COREONE_
    8h59m" and "..._0.4n_0.16mm_PLA_COREONE_3h0m"), and different ones: then they were sliced differently."""
    stored = fc._key(fc._stem(gcode_path))
    return stored != fc._key(printed) and bool(fc._PRUSA_SUFFIX.search(stored)) and bool(fc._PRUSA_SUFFIX.search(fc._key(printed)))
