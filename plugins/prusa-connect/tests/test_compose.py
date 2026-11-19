"""The plugin's docker-compose file builds it, and Farmhand's Plugins page shows the same file
(frontend/src/plugins/compose/prusa-connect.yml)."""
from __future__ import annotations

from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SHOWN = PLUGIN.parent.parent / "frontend" / "src" / "plugins" / "compose" / "prusa-connect.yml"


def _ours() -> str:
    return (PLUGIN / "docker-compose.yml").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_compose_file_builds_the_plugin():
    lines = [line.split(" #")[0].strip() for line in _ours().splitlines()]
    assert "build: https://github.com/The-Original-Reth/farmhand.git#main:plugins/prusa-connect" in _ours()
    assert '- "8085:8085"' in lines
    assert "- path: prusa-connect.env" in lines and "required: false" in lines
    assert "- prusa-connect-data:/data" in lines and "prusa-connect-data:" in lines


@pytest.mark.skipif(not SHOWN.exists(), reason="Farmhand's frontend isn't beside the plugin")
def test_plugins_page_shows_the_same_compose_file():
    shown = SHOWN.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert shown == _ours(), "copy plugins/prusa-connect/docker-compose.yml to frontend/src/plugins/compose/prusa-connect.yml"
