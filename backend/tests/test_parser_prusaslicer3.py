"""
PrusaSlicer 3.0 / BOSS 3.0 3MFs: their settings are in Metadata/PrusaSlicer3_project.json. The fixture is a real one,
saved by Prusaslicer - Web Boss's engine (BOSS 3.0.0-alpha14): a 25 mm cube on a Prusa MK4S 0.4 HF, infill 35%.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from app.parsers import parse_3mf
from app.parsers.prusaslicer3 import _text
from app.services import bundle_service

from . import factories as make

CUBE = Path(__file__).parent / "fixtures" / "BOSS_3.0_-_Prusa_MK4S_-_cube.3mf"


def test_a_boss_3_project_is_read():
    parsed = parse_3mf(str(CUBE))
    assert parsed.slicer_family == "prusaslicer"
    assert parsed.slicer_display_name == "PrusaSlicer 3.0.0-alpha14+BOSS"
    assert parsed.printer_preset_name == "Prusa MK4S 0.4 HF"  # the printer the slicer lists, not its "Original..." preset
    assert parsed.printer_profile_name is None  # no physical printer picked
    assert parsed.print_settings_id == "0.20mm SPEED @MK4S 0.4HF"
    assert parsed.filament_settings_id == "Prusament PLA @MK4S HF0.4@MK4S 0.4"
    s = parsed.settings
    assert s["fill_density"] == "35%" and s["layer_height"] == "0.2" and s["temperature"] == "230"
    assert s["bed_shape"] == "0,0,250,0,250,210,0,210"
    assert s["printer_settings_id"] == "Prusa MK4S 0.4 HF" and s["physical_printer_settings_id"] == ""


@pytest.mark.parametrize("value, text", [
    (True, "1"), (False, "0"), (None, ""), (0.2, "0.2"), (230.0, "230"), ([1, 2.5], "1,2.5"),
    ({"is_percent": True, "value": 35.0}, "35%"), ({"is_percent": False, "value": 0.45}, "0.45"),
])
def test_values_are_written_as_2x_writes_them(value, text):
    assert _text(value) == text


def test_a_broken_project_file_says_so(tmp_path):
    bad = tmp_path / "bad.3mf"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("Metadata/PrusaSlicer3_project.json", "{not json")
    with pytest.raises(ValueError, match="PrusaSlicer3_project.json can't be read"):
        parse_3mf(str(bad))


def test_a_boss_3_project_is_uploaded_like_any_3mf(db_session):
    printer = make.printer(db_session, "Core One")
    with open(CUBE, "rb") as f:
        bundle = bundle_service.create_bundle(
            db_session, source_model_ids=[make.model(db_session).id], threemf_file_obj=f, threemf_filename="Cube.3mf",
            gcode_file_obj=io.BytesIO(b"G28\n"), gcode_filename="Cube.gcode", printer_id=printer.id,
        )
    version = bundle.latest_version
    assert version.filename == "Cube ver 1.3mf" and version.slicer_display_name == "PrusaSlicer 3.0.0-alpha14+BOSS"
    assert version.sub_printer_name == "Prusa MK4S 0.4 HF"  # its printer profile, by its printer preset
    assert json.loads(json.dumps(version.settings))["fill_density"] == "35%"
