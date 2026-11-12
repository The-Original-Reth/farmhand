"""
The Stream plugin's settings, in its own store (secrets never answered), the saved layouts and the stream folder;
the one-off move of Farmhand's own Stream page set-up; and what Farmhand asks of every plugin.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from streamer import config, farm, layouts, migrate, store
from streamer.live_stream.constants import SETTINGS_KEY, STREAM_KEY_KEY

from .conftest import wait_until

from .conftest import KEY, grid

pytestmark = pytest.mark.usefixtures("stream_fresh")


# ------------------------------------------------------------------ settings, kept by the plugin


def test_settings_live_in_the_plugins_own_store_and_secrets_never_come_back(api, plugin):
    page = grid(api, [{"camera": "1:Bed"}, None])
    assert page["settings"]["key_set"] is True and KEY not in json.dumps(page)
    saved = json.loads(plugin.path.read_text(encoding="utf-8"))
    assert saved[STREAM_KEY_KEY] == KEY and json.loads(saved[SETTINGS_KEY])["cols"] == 2
    if sys.platform != "win32":
        assert oct(os.stat(plugin.path).st_mode & 0o777) == "0o600"  # only the plugin reads its key
    again = store.Store(plugin.path)  # (the plugin started again)
    assert again.get(STREAM_KEY_KEY) == KEY
    assert api.put("/api/stream", json={"clear_key": True}).json()["settings"]["key_set"] is False


def test_saved_layouts_are_kept_by_the_plugin(api):
    r = api.put("/api/layouts", json={"layouts": [{"name": "Morning", "cols": 1, "rows": 1, "cells": [{"camera": "1:Bed"}]}, "junk"]})
    assert r.status_code == 200 and [x["name"] for x in r.json()["layouts"]] == ["Morning"]
    assert api.get("/api/layouts").json()["layouts"][0]["cells"][0]["camera"] == "1:Bed"


def test_the_stream_folder_is_the_folder_the_container_is_given(api, plugin, tmp_path, monkeypatch):
    r = api.post("/api/stream/pictures", files={"files": ("logo.png", b"\x89PNG fake", "image/png")})
    assert r.status_code == 201 and r.json()["media"]["images"] == ["logo.png"]
    assert (tmp_path / "media" / "images" / "logo.png").is_file()
    monkeypatch.setattr(config.settings, "media_dir", tmp_path / "not-mounted")
    from streamer import stream_media
    stream_media.forget()
    r = api.post("/api/stream/pictures", files={"files": ("logo.png", b"x", "image/png")})
    assert r.status_code == 503 and "isn't there" in r.json()["detail"]


# ------------------------------------------------------------------ Farmhand's settings, brought over once


def test_farmhands_stream_settings_are_brought_over_once(api, plugin, farmhand):
    assert api.get("/api/migrate").json() == {"done": None, "own_settings": False}
    r = api.post("/api/migrate", json={})
    assert r.status_code == 200 and r.json()["done"]["stream_folder"] == "/data/nas/farmhand/stream"
    page = api.get("/api/stream").json()
    assert page["settings"]["title"] == "The farm" and page["settings"]["key_set"] is True
    assert page["youtube"]["signed_in"] is True and page["youtube"]["client_id"] == "123-abc.apps.googleusercontent.com"
    assert "GOCSPX-secret" not in json.dumps(page) and "1//refresh" not in json.dumps(page) and "abcd-efgh" not in json.dumps(page)
    assert [x["name"] for x in layouts.layouts(plugin)] == ["Morning"]
    # settings of its own now: not over them unless asked, and Farmhand hands over only once
    assert "settings of its own" in api.post("/api/migrate", json={}).json()["detail"]
    assert "only once" in api.post("/api/migrate", json={"replace": True}).json()["detail"]


def test_at_first_start_it_brings_them_over_only_with_the_permission(plugin, farmhand):
    farmhand.permissions.discard("stream:migrate")
    migrate.at_start(plugin)
    assert wait_until(lambda: "/plugin-api/v1/me" in farmhand.calls)
    assert not any(c.startswith("POST") for c in farmhand.calls)
    farmhand.permissions.add("stream:migrate")
    migrate.at_start(plugin)
    assert wait_until(lambda: plugin.get(migrate.MIGRATED_KEY) is not None)
    assert plugin.get(STREAM_KEY_KEY) == "abcd-efgh-ijkl"


# ------------------------------------------------------------------ what Farmhand asks of a plugin


def test_manifest_and_health(api, farmhand):
    m = api.get("/manifest").json()
    assert m["id"] == "stream" and set(m["permissions"]) == {"cameras:read", "prints:read", "stream:migrate"}
    assert api.get("/health").text == "ok"
    farm.cameras(store.store())
    config.settings.farmhand_token = "wrong"
    try:
        farm.cameras(store.store())
        r = api.get("/health")
        assert r.status_code == 503 and "refused this plugin's token" in r.text
    finally:
        from .fake_farmhand import TOKEN
        config.settings.farmhand_token = TOKEN
