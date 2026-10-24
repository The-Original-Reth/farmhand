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
