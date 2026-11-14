"""
Parser for PrusaSlicer 3.0 projects, as PrusaSlicer BOSS 3.0 (and Prusaslicer - Web Boss) write them.

3.0 keeps a project's settings in Metadata/PrusaSlicer3_project.json, not 2.x's Slic3r_PE.config:

  {"project": {...}, "objects": [...],
   "config_containers": [            one per printer group; the first is the project's printer
     {"preset": {"hw_config": {"config_name": ...}, "printer": {"name": ...}, "print": {"name": ...},
                 "materials": [{"name": ...}], ...},
      "physical_printer": {"uuid": ..., "name": ...}          (only when one is picked)
      "configuration": {"printer_settings": {"<key>": <value>, ...}, "print_settings": {...},
                        "filament_settings": {...}, "project_settings": {...}, ...},  (a list per tool or slot)
      "beds": [...]}]}

The settings are flattened into the same `key -> text` shape 2.x's are kept in (lists comma-separated, true/false as
1/0), so the compare view and the rest of Farmhand read them alike. The preset names go in as 2.x's
printer_settings_id / print_settings_id / filament_settings_id.
"""
from __future__ import annotations

import json

from .prusaslicer import ParsedBundle
from .threemf import RawThreeMF

PROJECT_MEMBER = "Metadata/PrusaSlicer3_project.json"


def _text(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(_text(v) for v in value)
    if isinstance(value, dict):
        if "value" in value and "is_percent" in value:  # a float or a percent: "35%", as 2.x writes it
            number = _text(value["value"])
            return f"{number}%" if value["is_percent"] else number
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _name(preset) -> str | None:
    return (preset.get("name") or None) if isinstance(preset, dict) else None


def _flatten(configuration) -> dict[str, str]:
    """Every setting of every location, key -> text. A location kept per tool or slot (a list of them) gives each key
    its values in order, comma-separated, as 2.x writes a per-extruder setting."""
    out: dict[str, str] = {}
    if not isinstance(configuration, dict):
        return out
    for boxes in configuration.values():
        if isinstance(boxes, dict):
            values = boxes.get("items") if isinstance(boxes.get("items"), dict) else boxes
            for key, value in values.items():
                out.setdefault(key, _text(value))
        elif isinstance(boxes, list):
            per_key: dict[str, list] = {}
            for box in boxes:
                if isinstance(box, dict):
                    values = box.get("items") if isinstance(box.get("items"), dict) else box
                    for key, value in values.items():
                        per_key.setdefault(key, []).append(value)
            for key, values in per_key.items():
                out.setdefault(key, _text(values))
    return out


def parse(raw: RawThreeMF) -> ParsedBundle:
    try:
        project = json.loads(raw.config_text or "")
    except ValueError as e:
        raise ValueError(f"This 3MF's {PROJECT_MEMBER} can't be read: {e}") from None
    containers = project.get("config_containers") if isinstance(project, dict) else None
    first = containers[0] if isinstance(containers, list) and containers and isinstance(containers[0], dict) else {}
    preset = first.get("preset") if isinstance(first.get("preset"), dict) else {}
    settings = _flatten(first.get("configuration"))

    # The printer is its hardware config's name ("Prusa MK4S 0.4 HF", what the slicer lists); the "printer" preset under
    # it ("Original Prusa MK4S") only when there's none
    hw = preset.get("hw_config") if isinstance(preset.get("hw_config"), dict) else {}
    printer_preset = hw.get("config_name") or _name(preset.get("printer"))
    print_preset = _name(preset.get("print"))
    materials = [n for n in (_name(m) for m in preset.get("materials") or []) if n]
    if printer_preset:
        settings["printer_settings_id"] = printer_preset
    if print_preset:
        settings["print_settings_id"] = print_preset
    if materials:
        settings["filament_settings_id"] = ";".join(materials)
    physical = first.get("physical_printer")
    physical_name = _name(physical)
    settings["physical_printer_settings_id"] = physical_name or ""

    app = raw.model_metadata.get("Application", "")  # "PrusaSlicer-3.0.0-alpha2+..." in 3D/3dmodel.model
    version = app.split("-", 1)[1] if app.lower().startswith("prusaslicer-") else "3"
    return ParsedBundle(
        slicer_family="prusaslicer",
        slicer_display_name=f"PrusaSlicer {version}",
        printer_profile_name=physical_name,
        print_settings_id=print_preset,
        filament_settings_id=";".join(materials) or None,
        settings=settings,
        thumbnail_bytes=raw.thumbnail_bytes,
        printer_preset_name=printer_preset,
    )
