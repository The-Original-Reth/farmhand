"""The Moonraker scanner: Klipper (or Kalico) printers, whatever web UI they run (Mainsail, Fluidd)."""
from __future__ import annotations

from ..moonraker import client

PORT = 7125

# Linux interface names: wlan0 / wlp2s0 / wlx<mac> are Wi-Fi; eth0 / end0 / enp1s0 / enx<mac> (USB) are cabled.
# A guess by name, which holds on MainsailOS, CB1 and Armbian images; a renamed interface counts as neither.
WIRELESS_PREFIXES = ("wl",)
WIRED_PREFIXES = ("eth", "en")


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
        **_links(ip, info.get("network") or {}),
    }


def _firmware(info: dict) -> str:
    """Klipper, or Kalico (once called Danger Klipper) when Klipper's own info says so."""
    said = f"{info.get('app') or ''} {info.get('software_version') or ''}".lower()
    return "Kalico" if "kalico" in said or "danger" in said else "Klipper"


def _links(ip: str, network: dict) -> dict:
    """
    How `ip` reached it (link: "wired" | "wireless" | None), and its wired and wireless IPv4 addresses, from the
    interfaces Moonraker lists. The address it answered on fills its own side when the interfaces don't say.
    """
    ips: dict[str, str] = {}
    link = None
    for name, iface in network.items():
        kind = _kind(name)
        addresses = [a.get("address") for a in (iface or {}).get("ip_addresses") or []
                     if isinstance(a, dict) and a.get("family") == "ipv4" and not a.get("is_link_local")]
        if ip in addresses:
            link = kind
        if kind and addresses and kind not in ips:
            ips[kind] = ip if ip in addresses else addresses[0]
    if link:
        ips[link] = ip
    return {"link": link, "wired_ip": ips.get("wired"), "wireless_ip": ips.get("wireless")}


def _kind(interface: str) -> str | None:
    if interface.startswith(WIRELESS_PREFIXES):
        return "wireless"
    if interface.startswith(WIRED_PREFIXES):
        return "wired"
    return None
