"""
How often a plugin may call the plugin API: a bucket of calls per token, which fills again at RATE a second up to
BURST. A plugin asking faster than that gets 429 for a moment; answers are kept a few seconds anyway (cache.py), so a
well-made plugin never comes near it.
"""
from __future__ import annotations

import threading
import time

RATE = 10.0  # calls a second, kept up for as long as it likes
BURST = 60  # calls at once, after a quiet spell

_lock = threading.Lock()
_buckets: dict[str, tuple[float, float]] = {}  # token hash -> (calls left, when counted)


def allow(key: str) -> float:
    """0 when this call may go ahead (and it's counted); else the seconds until one may."""
    now = time.monotonic()
    with _lock:
        left, then = _buckets.get(key, (float(BURST), now))
        left = min(float(BURST), left + (now - then) * RATE)
        if left >= 1:
            _buckets[key] = (left - 1, now)
            return 0.0
        _buckets[key] = (left, now)
        return (1 - left) / RATE


def reset() -> None:
    with _lock:
        _buckets.clear()
