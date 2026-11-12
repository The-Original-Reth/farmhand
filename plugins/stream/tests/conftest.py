from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "import streamer" works from plugins/stream

from streamer import config, store  # noqa: E402

from .fake_farmhand import TOKEN, FakeFarmhand  # noqa: E402
from .fake_ffmpeg import FakeFfmpeg  # noqa: E402


def wait_until(check, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return bool(check())


@pytest.fixture()
def farmhand():
    fake = FakeFarmhand()
    yield fake
    fake.stop()


@pytest.fixture()
def plugin(farmhand, tmp_path, monkeypatch):
    """The plugin as its container starts it: Farmhand's address and token, its own volume and stream folder (both
    empty), and a fresh store."""
    (tmp_path / "media").mkdir()
    monkeypatch.setattr(config, "settings", config.Config(
        farmhand_url=farmhand.url, farmhand_token=TOKEN, port=0, data_dir=tmp_path / "data", media_dir=tmp_path / "media"))
    s = store.Store(tmp_path / "data" / "settings.json")
    store.use(s)
    yield s
    store.use(None)


@pytest.fixture()
def stream_fresh(plugin):
    """Each stream test starts with no sign-in under way and the stream folder unread, and ends with the stream stopped."""
    from streamer import farm, stream_media, youtube_live
    from streamer.live_stream import stream

    youtube_live.reset()
    stream_media.forget()
    farm._noted(None)
    yield
    stream.stop()
    youtube_live.reset()


@pytest.fixture()
def ffmpeg(monkeypatch, tmp_path):
    """ffmpeg in its place (fake_ffmpeg.py): what the stream starts is remembered, and nothing really runs. The picture's
    pipes are plain files (Windows has no named pipes)."""
    from streamer.live_stream import encoders, feeders, pictures, procs

    fake = FakeFfmpeg()
    monkeypatch.setattr(procs, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(procs, "popen", fake)
    monkeypatch.setenv(encoders.ENCODER_SETTING, "cpu")  # no trying a real ffmpeg for an NVIDIA card
    monkeypatch.setattr(pictures, "SETTLE", 0)  # (a new layout's wait for more changes: none in tests)
    monkeypatch.setattr(feeders, "make_fifo", lambda path: open(path, "wb").close())
    return fake


# ------------------------------------------------------------------ the Stream page's API, for the stream tests

KEY = "farmtest-key"


@pytest.fixture()
def api(plugin):
    from fastapi.testclient import TestClient

    from streamer.app import app

    return TestClient(app)


def grid(api, cells, cols=2, rows=1):
    """The grid saved (with the stream key): the page as the plugin answered."""
    r = api.put("/api/stream", json={"stream_key": KEY, "cols": cols, "rows": rows, "cells": cells})
    assert r.status_code == 200, r.text
    return r.json()
