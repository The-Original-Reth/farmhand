"""
Parser for OrcaSlicer and Bambu Studio 3MF files (Orca is a fork of Bambu Studio and writes its format).

The settings are one JSON object in Metadata/project_settings.config. A value is a string, or a list of strings: one
per filament or per extruder (filament_type: ["PLA"], nozzle_diameter: ["0.4"]). Lists are kept as one string, the
way PrusaSlicer writes them, so every slicer's settings look alike to the rest of Farmhand: joined with "," (or ";"
when an item has a comma or semicolon in it). Every key is kept, as with PrusaSlicer, except any printer login.
"""
from __future__ import annotations

import json

from .prusaslicer import ParsedBundle
from .threemf import RawThreeMF

# A printer's login can be in a project's settings (Orca's "Physical printer" upload settings): never stored
_SECRET_HINTS = ("apikey", "api_key", "password", "printhost_user", "authorization_token")


def _flat(value) -> str:
    if isinstance(value, list):
        items = [_flat(v) for v in value]
        sep = ";" if any("," in i or ";" in i for i in items) else ","
        return sep.join(items)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _app(raw: RawThreeMF, family: str) -> str:
    """ "OrcaSlicer 2.4.2", "Bambu Studio 02.06.00.51" """
    meta = raw.model_metadata
    if family == "orcaslicer":
        version = meta.get("OrcaSlicer") or meta.get("Application", "").partition("-")[2]
        return f"OrcaSlicer {version or 'unknown version'}"
    version = meta.get("Application", "").partition("-")[2]
    return f"Bambu Studio {version or 'unknown version'}"


def parse(raw: RawThreeMF, family: str = "orcaslicer") -> ParsedBundle:
    try:
        data = json.loads(raw.config_text or "")
    except ValueError as e:
        raise ValueError(f"This 3MF's settings (project_settings.config) can't be read: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("This 3MF's settings (project_settings.config) aren't a list of settings")

    settings = {
        str(k): _flat(v) for k, v in data.items() if not any(h in str(k).lower() for h in _SECRET_HINTS)
    }
    printer = settings.get("printer_settings_id") or None
    return ParsedBundle(
        slicer_family=family,
        slicer_display_name=_app(raw, family),
        # Orca has no physical printer in a 3MF: the printer preset is what names the printer
        printer_profile_name=printer,
        print_settings_id=settings.get("print_settings_id") or None,
        filament_settings_id=settings.get("filament_settings_id") or None,
        settings=settings,
        thumbnail_bytes=raw.thumbnail_bytes,
        printer_preset_name=printer,
    )
