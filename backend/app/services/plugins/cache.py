"""
Plugin API answers, kept for a few seconds: however often plugins ask, Farmhand asks its database and printers at most
once per answer per few seconds. Answers are the same for every plugin (each call's permission is checked first).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

_lock = threading.Lock()
_kept: dict[Any, tuple[float, Any]] = {}  # key -> (monotonic time it goes stale, answer)
_making: defaultdict[Any, threading.Lock] = defaultdict(threading.Lock)  # one maker per answer at a time


def kept(key, seconds: float, make: Callable[[], Any]) -> Any:
    """The answer kept under key while it's fresh, else make() (once, however many ask together), kept for seconds."""
    with _lock:
        hit = _kept.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        maker = _making[key]
    with maker:
        with _lock:
            hit = _kept.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]  # made by another caller while this one waited
        answer = make()
        with _lock:
            _kept[key] = (time.monotonic() + seconds, answer)
        return answer


def clear() -> None:
    with _lock:
        _kept.clear()
