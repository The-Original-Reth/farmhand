from __future__ import annotations

import os

import pytest

from app import config, config_store as cs, storage
from app.services import config_service as svc


@pytest.fixture()
def client(api, tmp_path, monkeypatch):
    area = tmp_path / "data"
    (area / "storage").mkdir(parents=True)
    nas = area / "nas" / "lab"
    nas.mkdir(parents=True)
    monkeypatch.setattr(config.settings, "storage_root", str(area / "storage"))
    monkeypatch.setattr(config.settings, "storage_browse_root", str(area))
    real = str(nas.resolve())
    monkeypatch.setattr(storage, "_is_mount", lambda p: os.path.realpath(p) == real)
    storage.reset()
    svc._last_mirror.update(ok=None, error=None, at=None)
    return api, nas


def test_settings_round_trip_over_the_api(client):
    c, _ = client
    first = c.get("/settings/config").json()
    assert first["config"]["appearance"]["scheme"] == "farmhand" and first["location"]["is_set"] is False
    r = c.put("/settings/config", json={"appearance": {"scheme": "violet", "contrast": 55, "font": "play", "size": "large"}})
    assert r.status_code == 200 and r.json()["mirror"]["skipped"] is True  # no network folder chosen yet
    assert c.get("/settings/config").json()["config"]["appearance"] == {"scheme": "violet", "contrast": 55, "font": "play", "size": "large", "file_name_color": "auto"}


def test_the_whole_network_folder_flow(client):
    c, nas = client
    folder = nas / "settings"
    folder.mkdir()

    r = c.put("/settings/config/location", json={"path": str(folder)})
    assert r.status_code == 200 and r.json()["saved"] and r.json()["location"]["file"]["exists"]

    c.put("/settings/config", json={"appearance": {"scheme": "midnight", "contrast": 0, "font": "archivo", "size": "default"}})
    assert cs.read_document(folder)["appearance"]["scheme"] == "midnight"  # refreshed after the change

    again = c.put("/settings/config/location", json={"path": str(folder)}).json()  # now it has a file in it
    assert again["needs_choice"] is True and again["saved"] is False  # it has a file in it now: asked, not overwritten

    assert c.post("/settings/config/save-now").json()["ok"] is True
    assert c.post("/settings/config/restore").json()["restored"][0] == "appearance"


def test_inspect_and_error_answers(client, tmp_path):
    c, nas = client
    assert c.get("/settings/config/location/inspect", params={"path": str(tmp_path)}).status_code == 422  # outside the share area
    assert c.post("/settings/config/save-now").status_code == 422  # no folder chosen
    assert c.post("/settings/config/restore").status_code == 422
    folder = nas / "s"
    folder.mkdir()
    seen = c.get("/settings/config/location/inspect", params={"path": str(folder)}).json()
    assert seen["file_exists"] is False and seen["path"] == str(folder.resolve())


def test_junk_values_inside_the_settings_are_cleaned_up_not_rejected(client):
    c, _ = client
    r = c.put("/settings/config", json={"appearance": {"scheme": "../x", "contrast": "NaN", "font": 5}, "preferences": {"model_sort": {"key": "!", "dir": "up"}}})
    assert r.status_code == 200
    got = r.json()["config"]
    assert got["appearance"] == cs.DEFAULT_APPEARANCE
    assert got["preferences"]["model_sort"] == {"key": "name", "dir": "asc"}


def test_a_request_of_the_wrong_shape_is_rejected(client):
    c, _ = client
    assert c.put("/settings/config", json={"preferences": 7}).status_code == 422  # a number where an object belongs
    assert c.put("/settings/config/location", json={"path": None, "if_exists": "maybe"}).status_code == 422


def test_the_3mf_file_name_colour_is_saved_and_returned(client):
    c, _ = client
    r = c.put("/settings/config", json={"appearance": {"scheme": "farmhand", "contrast": 0, "font": "archivo", "size": "default", "file_name_color": "#9B7BE0"}})
    assert r.status_code == 200 and r.json()["config"]["appearance"]["file_name_color"] == "#9B7BE0"
    assert c.get("/settings/config").json()["config"]["appearance"]["file_name_color"] == "#9B7BE0"
