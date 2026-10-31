"""The Moonraker scanner: Klipper (or Kalico) printers, whatever web UI they run (Mainsail, Fluidd)."""
from __future__ import annotations

from ..moonraker import client

PORT = 7125


def probe(ip: str) -> dict | None:
    base = f"http://{ip}:{PORT}"
    info = client.probe(base)
    if info is None:
        return None
    return {
        "connection_type": "moonraker",
        "address": base,
        "web_url": f"http://{ip}/",
        "hostname": info.get("hostname"),
        "firmware": _firmware(info) if "moonraker_version" in info else None,  # one that wants a key won't say
        "version": info.get("moonraker_version"),
        "state": info.get("klippy_state"),
        "needs_api_key": bool(info.get("needs_api_key")),
    }


def _firmware(info: dict) -> str:
    """Klipper, or Kalico (once called Danger Klipper) when Klipper's own info says so."""
    said = f"{info.get('app') or ''} {info.get('software_version') or ''}".lower()
    return "Kalico" if "kalico" in said or "danger" in said else "Klipper"
