from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "import hello" works from plugins/hello

from .fake_farmhand import TOKEN, FakeFarmhand  # noqa: E402


@pytest.fixture()
def farmhand():
    fake = FakeFarmhand()
    yield fake
    fake.stop()


@pytest.fixture()
def env(farmhand, tmp_path):
    """The environment a container of this plugin would be started with."""
    return {"FARMHAND_URL": farmhand.url, "FARMHAND_TOKEN": TOKEN, "PORT": "0", "HELLO_DATA": str(tmp_path / "data")}


def wait_until(check, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return bool(check())
