"""
What the plugin is told when its container starts (environment variables), and the one setting it keeps itself.

Farmhand gives every plugin two environment variables, shown to the operator once when they add the plugin on
Farmhand's Plugins page:

    FARMHAND_URL    where the plugin API is, e.g. http://192.168.10.213:4545/plugin-api/v1
    FARMHAND_TOKEN  this plugin's token, sent with every call

The rest are this plugin's own (any name you like; prefix yours with your plugin's name):

    PORT            where it listens (8080, as farmhand-plugin.json says)
    HELLO_DATA      the folder it keeps its settings in: /data, a Docker volume, so they outlive the container
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    farmhand_url: str
    farmhand_token: str
    port: int
    data_dir: Path

    @classmethod
    def from_env(cls, env=os.environ) -> "Config":
        return cls(
            # (no trailing "/", so paths can be added as f"{url}/printers")
            farmhand_url=env.get("FARMHAND_URL", "").strip().rstrip("/"),
            farmhand_token=env.get("FARMHAND_TOKEN", "").strip(),
            port=int(env.get("PORT", "8080")),
            data_dir=Path(env.get("HELLO_DATA", "/data")),
        )


class Settings:
    """
    The plugin's own settings, in <data dir>/settings.json. Hello has one: which printers the page leaves out.

    It keeps the printers to *hide* rather than the ones to show, so a printer added to Farmhand later shows up by
    itself. A plugin never writes to Farmhand (the plugin API is read-only): anything it needs to remember lives here,
    in its own volume.
    """

    def __init__(self, data_dir: Path):
        self.path = data_dir / "settings.json"
        self._lock = threading.Lock()
        self._hidden: set[int] = set()
        self._load()

    def _load(self) -> None:
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self._hidden = {int(i) for i in saved.get("hidden_printers", [])}
        except FileNotFoundError:
            pass  # first start: nothing saved yet
        except (ValueError, TypeError, AttributeError) as e:
            print(f"hello: {self.path} couldn't be read ({e}); starting with every printer shown", flush=True)

    @property
    def hidden_printers(self) -> list[int]:
        with self._lock:
            return sorted(self._hidden)

    def set_hidden_printers(self, ids) -> list[int]:
        """Save which printers to leave out. ValueError (in plain words) for anything but a list of printer ids."""
        if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            raise ValueError("hidden_printers must be a list of printer ids, like [1, 4].")
        with self._lock:
            self._hidden = set(ids)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Written to a temporary name and then renamed over the old file, so a crash never leaves half a file
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps({"hidden_printers": sorted(self._hidden)}, indent=2), encoding="utf-8")
            os.replace(temp, self.path)
            return sorted(self._hidden)
