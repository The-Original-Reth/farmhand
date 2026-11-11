"""
The plugin's own settings: <STREAM_DATA>/settings.json, a file in its own volume, with no database. It holds what
Farmhand's app_settings table held for the Stream page, under the same keys (live_stream, live_stream_key,
youtube_client, youtube_refresh_token, youtube_channel, youtube_stream_id), plus the saved layouts, the cameras last
heard of and what was last live. The file is readable only by the plugin (mode 600): the stream key and the YouTube
sign-in are in it, and the plugin's API never answers them.

The engine code copied from Farmhand takes a `db` everywhere: here that is the Store (its type is still called
Session in those files, so they differ from Farmhand's as little as possible). put() changes it in memory; commit()
writes the file, whole or not at all.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._values: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return  # first start: nothing kept yet
        except (OSError, ValueError) as e:
            print(f"stream: {self.path} couldn't be read ({e}); starting with nothing set up", flush=True)
            return
        if isinstance(raw, dict):
            self._values = {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._values.get(key)

    def put(self, key: str, value: str | None) -> None:
        with self._lock:
            if value is None:
                self._values.pop(key, None)
            else:
                self._values[key] = value

    def commit(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".tmp")
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._values, f, indent=1, sort_keys=True)
            os.replace(temp, self.path)

    # (the engine's `with session_factory() as s:`: the same store, nothing to open or close)
    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def json(self, key: str, default=None):
        """A value kept as JSON (default when it isn't there or can't be read)."""
        try:
            value = json.loads(self.get(key) or "null")
        except ValueError:
            return default
        return default if value is None else value

    def put_json(self, key: str, value) -> None:
        self.put(key, None if value is None else json.dumps(value))


Session = Store  # what the copied engine code calls it

_store: Store | None = None


def store() -> Store:
    """The plugin's store (made on first use, in STREAM_DATA)."""
    global _store
    if _store is None:
        from . import config
        _store = Store(config.settings.data_dir / "settings.json")
    return _store


def use(s: Store | None) -> None:
    """Use this store (tests), or make a fresh one on next use (None)."""
    global _store
    _store = s


def session_factory() -> Store:
    """The engine's session_factory: the one store."""
    return store()
