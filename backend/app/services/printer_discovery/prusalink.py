"""The PrusaLink scanner: Prusa printers (Core One, MK4, XL...) on their own network, by the web page they serve."""
from __future__ import annotations

from ..prusalink import client


def probe(ip: str) -> dict | None:
    base = f"http://{ip}"
    info = client.probe(base)
    if info is None:
        return None
    return {
        "connection_type": "prusalink",
        "address": base,
        "web_url": f"{base}/",
        "hostname": info.get("hostname"),
        "firmware": "Prusa",
        "version": info.get("version"),
        "state": None,
        "needs_api_key": info["needs_password"],  # its login: a password for PrusaLink (Settings > Network on the printer)
    }
