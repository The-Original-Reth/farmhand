"""Hello's docker-compose file builds this plugin, and Farmhand's Plugins page shows the same file
(frontend/src/plugins/compose/hello.yml). Plain text checks: the plugin and its tests need nothing beyond Python."""
from __future__ import annotations

from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SHOWN = PLUGIN.parent.parent / "frontend" / "src" / "plugins" / "compose" / "hello.yml"


def _ours() -> str:
    return (PLUGIN / "docker-compose.yml").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_compose_file_builds_the_plugin():
    lines = [line.split(" #")[0].strip() for line in _ours().splitlines()]  # (comments cut off)
    assert "build: https://github.com/The-Original-Reth/farmhand.git#main:plugins/hello" in _ours()
    assert '- "8080:8080"' in lines
    assert "- path: hello.env" in lines and "required: false" in lines
    assert "- hello-data:/data" in lines and "hello-data:" in lines


@pytest.mark.skipif(not SHOWN.exists(), reason="Farmhand's frontend isn't beside the plugin")
def test_plugins_page_shows_the_same_compose_file():
    shown = SHOWN.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert shown == _ours(), "copy plugins/hello/docker-compose.yml to frontend/src/plugins/compose/hello.yml"
