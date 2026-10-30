from __future__ import annotations

from app.parsers import parse_3mf


def test_parses_frog_vt1190(sample_3mf_paths):
    result = parse_3mf(sample_3mf_paths["frog_vt1190"])
    assert result.slicer_family == "prusaslicer"
    assert result.printer_profile_name == "VT 1190"
    assert result.settings["layer_height"] == "0.2"
    assert len(result.settings) > 400
    assert result.thumbnail_bytes is not None


def test_parses_shark_vt1190(sample_3mf_paths):
    result = parse_3mf(sample_3mf_paths["shark_vt1190"])
    assert result.printer_profile_name == "VT 1190"
    assert result.settings["layer_height"] == "0.18"


def test_parses_shark_v2bog(sample_3mf_paths):
    result = parse_3mf(sample_3mf_paths["shark_v2bog"])
    assert result.printer_profile_name == "V2 BOG"
    assert result.settings["layer_height"] == "0.2"
    assert result.settings["support_material"] == "1"


def test_two_bundles_of_same_model_differ_meaningfully(sample_3mf_paths):
    """
    Sanity check for the compare feature: the same GreatWhiteShark model on
    two different printers should show real, substantial config
    differences — this is what the diff view is built to surface.
    """
    vt = parse_3mf(sample_3mf_paths["shark_vt1190"])
    bog = parse_3mf(sample_3mf_paths["shark_v2bog"])
    shared_keys = set(vt.settings) & set(bog.settings)
    differing = [k for k in shared_keys if vt.settings[k] != bog.settings[k]]
    assert len(differing) > 30


def _bambu_3mf(path, settings, metadata):
    """A 3MF in Bambu Studio's format (OrcaSlicer writes it too): JSON settings, the app named in the model."""
    import json
    import zipfile

    meta = "".join(f' <metadata name="{k}">{v}</metadata>\n' for k, v in metadata.items())
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", f'<?xml version="1.0"?>\n<model unit="millimeter">\n{meta}<resources/></model>')
        zf.writestr("Metadata/project_settings.config", json.dumps(settings))
        zf.writestr("Metadata/plate_1.png", b"\x89PNG fake")
    return str(path)


ORCA_SETTINGS = {
    "printer_settings_id": "V2 3812 - Blue",
    "print_settings_id": "0.20mm Standard 0.4 CHT nozzle @V2 3812",
    "filament_settings_id": ["Sparta_3D_ABS", "Generic PLA"],
    "layer_height": "0.2",
    "nozzle_diameter": ["0.4"],
    "adaptive_pressure_advance_model": ["0,0,0\n0,0,0"],
    "printhost_apikey": "secret-key",
}


def test_parses_an_orcaslicer_3mf(tmp_path):
    path = _bambu_3mf(tmp_path / "a.3mf", ORCA_SETTINGS, {"Application": "BambuStudio-02.06.00.51", "OrcaSlicer": "2.4.2"})
    result = parse_3mf(path)
    assert result.slicer_family == "orcaslicer" and result.slicer_display_name == "OrcaSlicer 2.4.2"
    assert result.printer_profile_name == result.printer_preset_name == "V2 3812 - Blue"
    assert result.print_settings_id == "0.20mm Standard 0.4 CHT nozzle @V2 3812"
    # lists are kept the way PrusaSlicer writes them
    assert result.filament_settings_id == "Sparta_3D_ABS,Generic PLA"
    assert result.settings["nozzle_diameter"] == "0.4"
    assert result.settings["adaptive_pressure_advance_model"] == "0,0,0\n0,0,0"
    assert "printhost_apikey" not in result.settings  # a printer's login is never kept
    assert result.thumbnail_bytes == b"\x89PNG fake"


def test_parses_a_bambu_studio_3mf(tmp_path):
    path = _bambu_3mf(tmp_path / "a.3mf", {"printer_settings_id": "Bambu Lab A1 mini 0.4 nozzle"}, {"Application": "BambuStudio-02.06.00.51"})
    result = parse_3mf(path)
    assert result.slicer_family == "bambustudio" and result.slicer_display_name == "Bambu Studio 02.06.00.51"


def test_an_orca_3mf_with_unreadable_settings_is_refused(tmp_path):
    import zipfile

    with zipfile.ZipFile(tmp_path / "a.3mf", "w") as zf:
        zf.writestr("Metadata/project_settings.config", "{not json")
    try:
        parse_3mf(str(tmp_path / "a.3mf"))
    except ValueError as e:
        assert "can't be read" in str(e)
    else:
        raise AssertionError("expected a ValueError")
