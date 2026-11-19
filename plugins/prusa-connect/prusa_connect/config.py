"""
What the plugin is told when its container starts, and what it keeps itself.

Environment (FARMHAND_URL and FARMHAND_TOKEN come from Farmhand's Plugins page, when the plugin is added):

    FARMHAND_URL         where Farmhand's plugin API is, e.g. http://192.168.10.90:4545/plugin-api/v1
    FARMHAND_TOKEN       this plugin's token
    PORT                 where it listens (8085, as farmhand-plugin.json says)
    PRUSA_CONNECT_DATA   the folder its settings are kept in: /data, a Docker volume
    PRUSA_CONNECT_URL    optional: Prusa Connect's address to start with (it can be changed on the plugin's page)

Its settings (<data>/settings.json): Prusa Connect's address, the token Prusa Connect gave it when the pairing was
approved (kept as-is: it's sent with every call, and never shown on the page), a pairing that's waiting, and which
Prusa Connect printer each Farmhand printer is.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Config:
    farmhand_url: str
    farmhand_token: str
    port: int
    data_dir: Path
    connect_url: str | None

    @classmethod
    def from_env(cls, env=os.environ) -> "Config":
        return cls(
            farmhand_url=env.get("FARMHAND_URL", "").strip().rstrip("/"),
            farmhand_token=env.get("FARMHAND_TOKEN", "").strip(),
            port=int(env.get("PORT", "8085")),
            data_dir=Path(env.get("PRUSA_CONNECT_DATA", "/data")),
            connect_url=env.get("PRUSA_CONNECT_URL", "").strip() or None,
        )


def tidy_address(value) -> str | None:
    """http://host:port from what was typed ("192.168.10.93:8080" works too); None for blank; ValueError if it isn't one."""
    text = (value or "").strip().rstrip("/") if isinstance(value, str) else ""
    if not text:
        return None
    if "://" not in text:
        text = f"http://{text}"
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
        raise ValueError("That isn't an address Prusa Connect can be reached at. Type it like http://192.168.10.93:8080")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


class Settings:
    """The plugin's own settings, saved to <data>/settings.json at each change (written whole, then renamed over)."""

    FIELDS = ("address", "token", "pairing", "links")

    def __init__(self, data_dir: Path, default_address: str | None = None):
        self.path = data_dir / "settings.json"
        self._lock = threading.Lock()
        self._data = {"address": None, "token": None, "pairing": None, "links": {}}
        self._load()
        if not self._data["address"] and default_address:
            try:
                self._data["address"] = tidy_address(default_address)
            except ValueError:
                print(f"prusa-connect: PRUSA_CONNECT_URL {default_address!r} isn't an address; choose it on the page", flush=True)

    def _load(self) -> None:
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except ValueError as e:
            print(f"prusa-connect: {self.path} couldn't be read ({e}); starting afresh", flush=True)
            return
        if isinstance(saved, dict):
            for key in self.FIELDS:
                if key in saved:
                    self._data[key] = saved[key]
            links = self._data.get("links")
            self._data["links"] = {str(k): str(v) for k, v in links.items()} if isinstance(links, dict) else {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    # ------------------------------------------------------------------ reading

    @property
    def address(self) -> str | None:
        with self._lock:
            return self._data["address"]

    @property
    def token(self) -> str | None:
        with self._lock:
            return self._data["token"]

    @property
    def pairing(self) -> dict | None:
        with self._lock:
            p = self._data["pairing"]
            return dict(p) if isinstance(p, dict) else None

    @property
    def links(self) -> dict[int, str]:
        """Farmhand printer id -> the Prusa Connect printer's id."""
        with self._lock:
            return {int(k): v for k, v in self._data["links"].items() if str(k).isdigit()}

    # ------------------------------------------------------------------ changing

    def set_address(self, value) -> str | None:
        """Prusa Connect's address. A different one forgets the token and any pairing (they were the old server's)."""
        url = tidy_address(value)
        with self._lock:
            if url != self._data["address"]:
                self._data.update(address=url, token=None, pairing=None)
            self._save()
        return url

    def set_pairing(self, pairing: dict | None) -> None:
        with self._lock:
            self._data["pairing"] = pairing
            self._save()

    def set_token(self, token: str | None) -> None:
        with self._lock:
            self._data.update(token=token, pairing=None)
            self._save()

    def link(self, printer_id, device_id) -> dict[int, str]:
        """Say which Prusa Connect printer a Farmhand printer is (None or "" unlinks it). ValueError for bad values."""
        if isinstance(printer_id, bool) or not isinstance(printer_id, int):
            raise ValueError("printer_id must be a Farmhand printer's id, like 3.")
        if device_id is not None and not isinstance(device_id, str):
            raise ValueError("device_id must be a Prusa Connect printer's id, or null.")
        with self._lock:
            links = self._data["links"]
            if device_id:
                for other, dev in list(links.items()):
                    if dev == device_id and other != str(printer_id):
                        del links[other]  # a Prusa Connect printer is one Farmhand printer
                links[str(printer_id)] = device_id.strip()[:64]
            else:
                links.pop(str(printer_id), None)
            self._save()
        return self.links
