from __future__ import annotations

import json

import pytest

from app import config_store as cs


def _doc(**over):
    base = cs.build_document(cs.normalize_config({}), None, None, [])
    base.update(over)
    return base


def test_defaults_and_clean_up():
    assert cs.normalize_config({}) == {"appearance": cs.DEFAULT_APPEARANCE, "preferences": cs.DEFAULT_PREFERENCES}
    a = cs.normalize_appearance({"scheme": "midnight", "contrast": "400", "font": "play", "size": "large"})
    assert a == {"scheme": "midnight", "contrast": 100, "font": "play", "size": "large", "file_name_color": "auto"}  # contrast clamped
    junk = cs.normalize_appearance({"scheme": "../../etc", "contrast": "x", "font": 3, "size": None})
    assert junk == cs.DEFAULT_APPEARANCE  # anything not shaped like an id, or not a number, falls back
    assert cs.normalize_appearance({"contrast": -5})["contrast"] == 0
    assert cs.normalize_preferences({"model_sort": {"key": "added", "dir": "sideways"}})["model_sort"] == {"key": "added", "dir": "asc"}
    assert cs.normalize_config(None) == cs.normalize_config("nonsense")


def test_the_file_never_carries_a_password_whatever_it_is_handed():
    shares = [{"name": "Lab", "protocol": "smb", "server": "10.0.0.5", "share": "farmhand", "username": "alice",
               "password": "hunter2", "domain": None, "version": None, "token": "also-secret"}]
    doc = cs.build_document(cs.normalize_config({}), "/data/nas/lab/stl", None, shares)
    text = json.dumps(doc)
    assert "hunter2" not in text and "also-secret" not in text and "password" not in text
    assert doc["shares"][0]["username"] == "alice"  # the login NAME is fine; the password is not


def test_write_is_atomic_and_read_gives_back_what_was_written(tmp_path):
    cs.write_document(tmp_path, _doc(storage={"stl_path": "/data/x", "threemf_path": None}))
    assert (tmp_path / cs.CONFIG_FILENAME).is_file() and not list(tmp_path.glob("*.part"))
    got = cs.read_document(tmp_path)
    assert got["storage"]["stl_path"] == "/data/x" and got["appearance"] == cs.DEFAULT_APPEARANCE
    info = cs.file_info(tmp_path)
    assert info["exists"] and info["size"] > 0 and info["modified_at"]


def test_a_failed_write_leaves_no_half_written_file_and_keeps_the_old_one(tmp_path, monkeypatch):
    cs.write_document(tmp_path, _doc())
    before = (tmp_path / cs.CONFIG_FILENAME).read_text()

    def boom(src, dst):
        raise OSError("share dropped mid-write")

    monkeypatch.setattr(cs.os, "replace", boom)
    with pytest.raises(OSError):
        cs.write_document(tmp_path, _doc(note="new"))
    assert (tmp_path / cs.CONFIG_FILENAME).read_text() == before  # the previous good file is untouched
    assert not list(tmp_path.glob("*.part"))


def test_no_file_is_not_an_error(tmp_path):
    assert cs.read_document(tmp_path) is None
    assert cs.file_info(tmp_path) == {"exists": False, "modified_at": None, "size": None}


def test_files_that_are_not_usable_say_why(tmp_path):
    f = tmp_path / cs.CONFIG_FILENAME
    cases = [
        ("not json {", "can't be read"),
        ("[1, 2]", "isn't a Farmhand settings file"),
        ('{"hello": 1}', "isn't a Farmhand settings file"),
        ('{"farmhand_config": 99}', "newer Farmhand"),
        ('{"farmhand_config": "one"}', "newer Farmhand"),
    ]
    for text, message in cases:
        f.write_text(text)
        with pytest.raises(cs.ConfigFileError, match=message):
            cs.read_document(tmp_path)
    f.write_text("x" * (cs.MAX_FILE_BYTES + 10))
    with pytest.raises(cs.ConfigFileError, match="far too large"):
        cs.read_document(tmp_path)


def test_a_hand_edited_or_hostile_file_is_cleaned_up_on_read(tmp_path):
    (tmp_path / cs.CONFIG_FILENAME).write_text(json.dumps({
        "farmhand_config": 1,
        "appearance": {"scheme": "<script>", "contrast": 9999, "font": "play", "size": 7},
        "storage": {"stl_path": 12, "threemf_path": "/data/x"},
        "shares": [{"name": "Lab", "protocol": "nfs", "server": "10.0.0.5", "share": "/vol", "password": "leak", "evil": "x"}, "junk", 5],
    }))
    got = cs.read_document(tmp_path)
    assert got["appearance"]["scheme"] == "farmhand" and got["appearance"]["contrast"] == 100 and got["appearance"]["font"] == "play"
    assert got["storage"] == {"stl_path": None, "threemf_path": "/data/x"}
    assert len(got["shares"]) == 1 and "password" not in got["shares"][0] and "evil" not in got["shares"][0]


def test_the_3mf_file_name_colour_is_auto_or_a_colour():
    assert cs.normalize_appearance({})["file_name_color"] == "auto"
    assert cs.normalize_appearance({"file_name_color": "#4a90e2"})["file_name_color"] == "#4A90E2"
    for bad in ("blue", "#12345", "#GGGGGG", 5, None):
        assert cs.normalize_appearance({"file_name_color": bad})["file_name_color"] == "auto"
