"""A printer's printer profiles and their parts in its file in the settings copy, and brought back by Load all."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from ... import record_files
from ...models import DefaultSubPrinter, Printer, SubPrinterPart, SubPrinterSettingsCopy
from .core import MAX_NAME, _fields_of, _new, _only_defaults, _remember, _text


def record(printer: Printer) -> list[dict]:
    """A printer's printer profiles and their parts, for its file in the settings copy."""
    return [
        {
            "name": s.name,
            "default": s.id == printer.default_sub_printer_id,  # the one its uploads start on
            "aliases": s.aliases,  # preset names that also mean it
            "parts": [
                {**_fields_of(p), "installed_on": p.installed_on.isoformat() if p.installed_on else None} for p in s.parts
            ],
            # a copy's printer settings, until a 3MF sliced with it comes in (read from a 3MF: no logins in them)
            **({"settings_copy": {
                "copied_from": s.settings_copy.copied_from, "from_file": s.settings_copy.from_file,
                "copied_at": s.settings_copy.copied_at.isoformat() if s.settings_copy.copied_at else None,
                "settings": s.settings_copy.settings,
            }} if s.settings_copy else {}),
        }
        for s in printer.sub_printers
    ]


def _restored_part(rec) -> SubPrinterPart | None:
    if not isinstance(rec, dict) or not isinstance(rec.get("part"), str) or not rec["part"].strip():
        return None
    try:
        installed = dt.date.fromisoformat(rec["installed_on"]) if isinstance(rec.get("installed_on"), str) else None
    except ValueError:
        installed = None
    return SubPrinterPart(
        part=rec["part"].strip()[:MAX_NAME], make=_text(rec.get("make"), 120), model=_text(rec.get("model"), 200),
        installed_on=installed, note=_text(rec.get("note"), 2000), in_name=rec.get("in_name") is True,
    )


def restore(db: Session, printer: Printer, saved) -> bool:
    """
    Printer profiles from a saved printer record that this printer doesn't have yet, its default if it has none, and
    the parts of any that have nothing written down (no parts, or only the untouched defaults; never mixed into a list
    someone filled in). Each is {name, parts, ...}, or a bare name: a record from before parts were kept, which comes
    back with the default parts. True if anything was added.
    """
    by_name = {s.name: s for s in printer.sub_printers}
    added = False
    default = None
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
        if isinstance(rec, dict) and rec.get("default") is True:
            default = sub
        if isinstance(rec, dict) and isinstance(rec.get("aliases"), list):
            for alias in rec["aliases"][:200]:
                if isinstance(alias, str) and alias.strip():
                    before = len(sub.alias_rows)
                    _remember(db, sub, alias.strip()[:MAX_NAME])
                    added |= len(sub.alias_rows) != before
        copied = rec.get("settings_copy") if isinstance(rec, dict) else None
        if sub.settings_copy is None and isinstance(copied, dict) and isinstance(copied.get("settings"), dict):
            when = record_files.parse_iso(copied.get("copied_at"))
            sub.settings_copy = SubPrinterSettingsCopy(
                copied_from=_text(copied.get("copied_from"), MAX_NAME) or name, from_file=_text(copied.get("from_file"), 255),
                settings=copied["settings"], **({"copied_at": when} if when else {}),
            )
            added = True
        if saved_parts is not None and (not sub.parts or _only_defaults(sub)):
            restored = list(filter(None, map(_restored_part, saved_parts[:500])))
            if [_fields_of(p) for p in restored] != [_fields_of(p) for p in sub.parts]:
                sub.parts = restored
                added = True
    if default is not None and printer.default_sub_printer_row is None:  # never replaces one picked here
        db.flush()  # a printer profile just added needs its id
        printer.default_sub_printer_row = DefaultSubPrinter(printer_id=printer.id, sub_printer_id=default.id)
        added = True
    return added
