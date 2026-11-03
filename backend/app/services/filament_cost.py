"""
What a print's filament cost: the length the printer says it pushed through (Moonraker's filament_used, in mm, which
is what Mainsail shows as "Filament used"), turned into grams with the filament's diameter and density, times its
price per kg, as the slicer's filament profile wrote them (filament_diameter, filament_density, filament_cost). The
price has no currency: it's whatever was typed in the slicer.

Where those come from: first the printed G-code itself, whose settings block at the end has them (read from the
printer once per file when its history is synced, see GcodeFilament and moonraker/history.py). Failing that (the file
was gone from the printer before Farmhand read it, or has no price), the 3MF it was sliced from.

Which 3MF: one on the same printer whose name matches the printed file's, ignoring folder, extension, case, and
spaces versus underscores (a 3MF downloaded through a browser often has "_" where the slicer's name had " "). A
G-code Farmhand sent is named after its version ("Frog ver 2.gcode" <- "Frog ver 2.3mf"), so that version is used.
Otherwise the names are matched without the "ver N": "Frog.gcode", or PrusaSlicer's own G-code name, which adds the
printer and filament presets ("Frog-V2_BOG_Rapido_0.5-Inland_PLA.gcode", from [input_filename_base]-[printer_settings_id]
-[filament_settings_id]); where several 3MF names fit that way, the longest one. Of those versions, the newest one
uploaded before the print started is used, so a print keeps the price it was printed at; one uploaded later only when
there's none before. A project with several filaments is costed with the first one's values.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from ..models import Bundle, BundleVersion, GcodeFilament, PrintJob
from ..names import without_version
from ..timeutil import as_utc

DEFAULT_DIAMETER = 1.75  # mm, when a 3MF doesn't say


def _stem(filename: str | None) -> str:
    """ "gcodes/Frog v2.gcode" -> "frog v2": the name without folder or extension, compared ignoring case """
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    return os.path.splitext(name)[0].strip().lower()


def _key(stem: str) -> str:
    """ "v2 bog - frog v01" -> "v2_bog_-_frog_v01": spaces and underscores count as the same """
    return re.sub(r"[\s_]+", "_", stem)


def _match(job_stem: str, exact: dict[str, list[int]], by_base: dict[str, list[int]]) -> list[int] | None:
    """The versions (ids) a printed file's name belongs to: see the top of this file."""
    if _key(job_stem) in exact:
        return exact[_key(job_stem)]
    base = _key(without_version(job_stem))
    if base in by_base:
        return by_base[base]
    fits = [b for b in by_base if base.startswith(b + "-")]  # the slicer added -printer-filament
    return by_base[max(fits, key=len)] if fits else None


def _first_number(value) -> float | None:
    """The first filament's value from a setting ("16.99", or "16.99,24.5" with several filaments); None if not a number > 0."""
    if value is None:
        return None
    try:
        n = float(str(value).replace(";", ",").split(",")[0].strip())
    except ValueError:
        return None
    return n if n > 0 and math.isfinite(n) else None


def grams(filament_mm: float, diameter_mm: float, density_g_cm3: float) -> float:
    """The weight of that length of filament: its volume (mm³, a cylinder) times density (g/cm³ = g per 1000 mm³)."""
    return filament_mm * math.pi * (diameter_mm / 2) ** 2 * density_g_cm3 / 1000


def _pick(versions: list[BundleVersion], started: dt.datetime | None) -> BundleVersion:
    """The newest version uploaded before the print started; the oldest one if they all came later."""
    by_age = sorted(versions, key=lambda v: as_utc(v.uploaded_at))
    if started is not None:
        before = [v for v in by_age if as_utc(v.uploaded_at) <= as_utc(started)]
        if before:
            return before[-1]
    return by_age[0]


def file_modified(meta: dict | None) -> float:
    """Which copy of a G-code a print used: the time it was written, from Moonraker's metadata (0 when not given)."""
    try:
        return float((meta or {}).get("modified") or 0)
    except (TypeError, ValueError):
        return 0.0


_GCODE_SETTING_RE = re.compile(rb"^;\s*(filament_cost|filament_density|filament_diameter)\s*=\s*(.*?)\s*$", re.MULTILINE)


def from_gcode(tail: bytes) -> dict:
    """{cost_per_kg, density, diameter} (None where missing) from the settings block at the end of a G-code."""
    found = {k.decode(): v.decode("utf-8", "replace") for k, v in _GCODE_SETTING_RE.findall(tail)}
    return {
        "cost_per_kg": _first_number(found.get("filament_cost")),
        "density": _first_number(found.get("filament_density")),
        "diameter": _first_number(found.get("filament_diameter")),
    }


def _priced(filament_mm: float, price: float, density: float, diameter: float | None, **source) -> dict:
    diameter = diameter or DEFAULT_DIAMETER
    g = grams(filament_mm, diameter, density)
    return {
        "cost": round(g / 1000 * price, 2), "grams": round(g, 1),
        "cost_per_kg": price, "density": density, "diameter": diameter, **source,
    }


def costs(db: Session, jobs: list[PrintJob]) -> dict[int, dict | None]:
    """
    {job id: {cost, grams, cost_per_kg, density, diameter, source, filename, bundle_id, version_id, version} | None}
    for each job. source "gcode": the values were read from the printed G-code itself (filename is the G-code's,
    bundle_id / version_id / version are null); "3mf": from the 3MF it matched (filename is the 3MF version's). None:
    neither has a price and density, or the printer reported no filament used.
    """
    out: dict[int, dict | None] = {j.id: None for j in jobs}
    jobs = [j for j in jobs if j.filament_used and j.filament_used > 0 and _stem(j.filename)]
    if not jobs:
        return out

    # The G-code first: what was actually printed. Each print uses the newest copy of its file read at or before its
    # own (the file is read once per upload, not once per print), or the oldest read if they all came later
    read: dict[tuple[int, str], list[GcodeFilament]] = {}
    for f in db.scalars(
        select(GcodeFilament).where(
            GcodeFilament.printer_id.in_({j.printer_id for j in jobs}),
            GcodeFilament.filename.in_({j.filename for j in jobs}),
            GcodeFilament.cost_per_kg.isnot(None), GcodeFilament.density.isnot(None),
        ).order_by(GcodeFilament.modified)
    ):
        read.setdefault((f.printer_id, f.filename), []).append(f)
    rest = []
    for j in jobs:
        copies = read.get((j.printer_id, j.filename))
        if not copies:
            rest.append(j)
            continue
        mine = file_modified(j.job_metadata)
        f = ([c for c in copies if c.modified <= mine] or copies[:1])[-1]
        out[j.id] = _priced(j.filament_used, f.cost_per_kg, f.density, f.diameter, source="gcode", filename=j.filename,
                            bundle_id=None, version_id=None, version=None)
    jobs = rest
    if not jobs:
        return out

    # Then the 3MF. Only the names are read for every 3MF on these printers; settings (often 30-60 KB) only for the
    # ones matched
    rows = db.execute(
        select(BundleVersion.id, BundleVersion.filename, BundleVersion.uploaded_at, Bundle.printer_id)
        .join(Bundle, Bundle.id == BundleVersion.bundle_id)
        .where(Bundle.printer_id.in_({j.printer_id for j in jobs}))
    ).all()
    exact: dict[int, dict[str, list[int]]] = {}  # printer id -> {name: version ids}
    by_base: dict[int, dict[str, list[int]]] = {}  # ...the same without "ver N"
    for vid, filename, _, pid in rows:
        exact.setdefault(pid, {}).setdefault(_key(_stem(filename)), []).append(vid)
        by_base.setdefault(pid, {}).setdefault(_key(without_version(_stem(filename))), []).append(vid)
    matches = {j.id: _match(_stem(j.filename), exact.get(j.printer_id, {}), by_base.get(j.printer_id, {})) for j in jobs}
    ids = {vid for vids in matches.values() if vids for vid in vids}
    if not ids:
        return out
    versions = {
        v.id: v for v in db.scalars(select(BundleVersion).where(BundleVersion.id.in_(ids)).options(undefer(BundleVersion.settings)))
    }

    for j in jobs:
        if matches[j.id]:
            v = _pick([versions[i] for i in matches[j.id]], j.start_time)
            s = v.settings or {}
            price, density = _first_number(s.get("filament_cost")), _first_number(s.get("filament_density"))
            if price is None or density is None:
                continue
            out[j.id] = _priced(j.filament_used, price, density, _first_number(s.get("filament_diameter")), source="3mf",
                                filename=v.filename, bundle_id=v.bundle_id, version_id=v.id, version=v.version)
    return out
