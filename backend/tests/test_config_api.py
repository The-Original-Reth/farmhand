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


def test_the_monitor_order_is_kept_on_its_own(client):
    c, _ = client
    c.put("/settings/config", json={"preferences": {"model_sort": {"key": "added", "dir": "desc"}}})
    r = c.put("/settings/config", json={"preferences": {"monitor_order": ["8:Chamber", "3:rear", "8:Chamber", 5, "", "x" * 201]}})
    prefs = r.json()["config"]["preferences"]
    assert prefs["monitor_order"] == ["8:Chamber", "3:rear"]  # each once; junk dropped
    assert prefs["model_sort"] == {"key": "added", "dir": "desc"}  # saving one preference leaves the other alone
    c.put("/settings/config", json={"preferences": {"model_sort": {"key": "name", "dir": "asc"}}})
    assert c.get("/settings/config").json()["config"]["preferences"]["monitor_order"] == ["8:Chamber", "3:rear"]


def test_the_farm_cost_order_is_printer_ids(client):
    c, _ = client
    assert c.get("/settings/config").json()["config"]["preferences"]["farm_cost_order"] == []
    r = c.put("/settings/config", json={"preferences": {"farm_cost_order": [4, 2, 4, "3", 0, -1, True, 1.5, 7]}})
    assert r.json()["config"]["preferences"]["farm_cost_order"] == [4, 2, 7]  # each once; junk dropped


def test_the_tools_page_links_are_kept_in_order_and_only_web_addresses(client):
    c, _ = client
    first = c.get("/settings/config").json()["config"]["preferences"]["tool_links"]
    assert [l["url"] for l in first][:2] == ["https://canbus.esoterical.online/", "https://usb.esoterical.online/"]
    assert len(first) == 13  # the Klipper defaults, until a list is saved
    sent = [
        {"name": " Klipper docs ", "url": " https://www.klipper3d.org/ "},
        {"name": "", "url": "http://192.168.10.50:7125"},
        {"name": "Bad", "url": "javascript:alert(1)"},
        {"name": "No scheme", "url": "example.com"},
        {"name": "x" * 101, "url": "https://example.com"},
        "https://loose.example.com",
        {"url": "https://nameless.example.com"},
    ]
    r = c.put("/settings/config", json={"preferences": {"tool_links": sent}})
    assert r.status_code == 200
    expected = [
        {"name": "Klipper docs", "url": "https://www.klipper3d.org/"},
        {"name": "", "url": "http://192.168.10.50:7125"},
        {"name": "", "url": "https://nameless.example.com"},
    ]
    assert r.json()["config"]["preferences"]["tool_links"] == expected
    c.put("/settings/config", json={"preferences": {"monitor_max_zoom": 6}})  # another preference leaves them alone
    assert c.get("/settings/config").json()["config"]["preferences"]["tool_links"] == expected
    c.put("/settings/config", json={"preferences": {"tool_links": []}})  # emptied on purpose: the defaults don't come back
    assert c.get("/settings/config").json()["config"]["preferences"]["tool_links"] == []


def test_the_monitor_max_zoom_is_one_of_the_choices(client):
    c, _ = client
    assert c.get("/settings/config").json()["config"]["preferences"]["monitor_max_zoom"] == 4
    r = c.put("/settings/config", json={"preferences": {"monitor_max_zoom": 6}})
    assert r.json()["config"]["preferences"]["monitor_max_zoom"] == 6
    for junk in (5, 100, "8", 8.0, True, None):
        r = c.put("/settings/config", json={"preferences": {"monitor_max_zoom": junk}})
        assert r.json()["config"]["preferences"]["monitor_max_zoom"] == 4, junk


def test_the_price_of_electricity_is_a_plain_number_or_not_set(client):
    c, _ = client
    assert c.get("/settings/config").json()["config"]["preferences"]["energy_price_per_kwh"] is None
    r = c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": 0.1534}})
    assert r.json()["config"]["preferences"]["energy_price_per_kwh"] == 0.1534
    c.put("/settings/config", json={"preferences": {"monitor_max_zoom": 6}})  # another preference leaves it alone
    assert c.get("/settings/config").json()["config"]["preferences"]["energy_price_per_kwh"] == 0.1534
    assert c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": 0}}).json()["config"]["preferences"]["energy_price_per_kwh"] == 0
    r = c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": 0.12345}})  # 5 decimal places are kept
    assert r.json()["config"]["preferences"]["energy_price_per_kwh"] == 0.12345
    r = c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": 0.1234567}})  # more are rounded to 5
    assert r.json()["config"]["preferences"]["energy_price_per_kwh"] == 0.12346
    for junk in (-1, 1000, "0.15", True, None):
        r = c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": junk}})
        assert r.json()["config"]["preferences"]["energy_price_per_kwh"] is None, junk


def _prefs(r):
    return r.json()["config"]["preferences"]


def test_a_new_average_cost_only_counts_from_its_month_on(client):
    from app.config_store import energy_price_for

    c, _ = client
    put = lambda price, month: c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": price, "energy_price_from": month}})
    put(0.15, "2026-09")
    put(0.151, "2026-09")  # typed on, the same month: replaces it
    p = _prefs(put(0.2, "2026-11"))
    assert p["energy_price_per_kwh"] == 0.2 and "energy_price_from" not in p
    assert p["energy_price_history"] == [{"from": "2026-09", "price": 0.151}, {"from": "2026-11", "price": 0.2}]
    # the first price counts for every month before it too; each later one from its month on
    assert [energy_price_for(p, m) for m in ("2020-01", "2026-10", "2026-11", "2027-05")] == [0.151, 0.151, 0.2, 0.2]

    p = _prefs(c.put("/settings/config", json={"preferences": {"energy_price_months": {"2026-10": 0.14, "nope": 1, "2026-13": 1}}}))
    assert p["energy_price_months"] == {"2026-10": 0.14}  # a month typed by hand wins
    assert energy_price_for(p, "2026-10") == 0.14 and energy_price_for(p, "2026-09") == 0.151


def test_a_price_set_before_there_was_a_history_keeps_counting_for_the_months_before(client):
    c, _ = client
    c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": 0.15, "energy_price_history": []}})
    p = _prefs(c.put("/settings/config", json={"preferences": {"energy_price_per_kwh": 0.2, "energy_price_from": "2026-11"}}))
    assert p["energy_price_history"] == [{"from": "0001-01", "price": 0.15}, {"from": "2026-11", "price": 0.2}]
