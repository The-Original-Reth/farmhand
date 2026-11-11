"""The docker-compose file Farmhand's Stream page shows (frontend/src/stream/plugin/) is this plugin's own."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parent.parent
SHOWN = PLUGIN.parent.parent / "frontend" / "src" / "stream" / "plugin" / "docker-compose.yml"


def test_compose_file_is_valid_and_builds_the_plugin():
    data = yaml.safe_load((PLUGIN / "docker-compose.yml").read_text(encoding="utf-8"))
    stream = data["services"]["stream"]
    assert stream["build"].endswith("#main:plugins/stream")
    assert stream["ports"] == ["8080:8080"]
    assert stream["env_file"] == [{"path": "stream.env", "required": False}]
    assert "stream-data:/data" in stream["volumes"]
    assert "stream-data" in data["volumes"]


@pytest.mark.skipif(not SHOWN.exists(), reason="Farmhand's frontend isn't beside the plugin")
def test_stream_page_shows_the_same_compose_file():
    ours = (PLUGIN / "docker-compose.yml").read_text(encoding="utf-8").replace("\r\n", "\n")
    shown = SHOWN.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert shown == ours, "copy plugins/stream/docker-compose.yml to frontend/src/stream/plugin/docker-compose.yml"
