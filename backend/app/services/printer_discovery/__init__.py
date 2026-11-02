"""
Finding printers on the network: every address in a range is asked, by each scanner in SCANNERS in turn, whether a
printer Farmhand can talk to is there. Addresses an active printer in Farmhand already has are skipped. One found at a
decommissioned printer's address is listed with that printer (decommissioned_id / _name), to be brought back rather
than added twice. Nothing is added: the answer is a list for the user to choose from, and choosing one is an ordinary
POST /printers (or, for a decommissioned one, a PATCH of it).

A machine on both a cable and Wi-Fi answers at two addresses. Where the scanner can tell (Moonraker lists its network
interfaces), those answers become one entry: the wired one, carrying both IPs.

A scanner is one kind of printer (Moonraker and PrusaLink; OctoPrint could follow): a module with a `probe(ip)` that
answers what it found there, or None. Adding a kind is a new module and a line in SCANNERS.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Printer
from . import moonraker, prusalink

log = logging.getLogger("farmhand.discovery")

MAX_ADDRESSES = 1024  # a /22; a bigger range would take minutes and is more likely a typo
WORKERS = 32

# Asked in this order; the first that recognises an address has it (a machine is listed once). Moonraker first: a
# Klipper machine serves its Mainsail page on port 80 too, so it's known for what it is before PrusaLink is asked.
SCANNERS = [moonraker, prusalink]


def scan(db: Session, cidr: str) -> list[dict]:
    """The printers in `cidr` (e.g. "192.168.1.0/24") that aren't active in Farmhand, in address order."""
    try:
        net = ipaddress.ip_network(cidr.strip(), strict=False)
    except ValueError:
        raise ValueError(f"'{cidr}' isn't a network range. Write it like 192.168.1.0/24.") from None
    if net.version != 4:
        raise ValueError("Only IPv4 ranges can be scanned, like 192.168.1.0/24.")
    if not net.is_private:
        # the farm's own network only: a public range would have Farmhand knocking on strangers' machines
        raise ValueError("Only your own network can be scanned: a range starting 10., 172.16 to 172.31, or 192.168.")
    if net.num_addresses > MAX_ADDRESSES:
        raise ValueError(f"That range has {net.num_addresses} addresses. Scan {MAX_ADDRESSES} or fewer at a time (a /22 or smaller).")

    known = _known_hosts(db)
    targets = [str(ip) for ip in (net.hosts() if net.num_addresses > 1 else [net.network_address]) if str(ip) not in known]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        found = [f for f in pool.map(_probe, targets) if f]
    merged = sorted(_one_per_machine(found), key=lambda f: ipaddress.ip_address(f["ip"]))
    retired = _decommissioned_hosts(db)
    out = []
    for f in merged:
        if known & _ips(f):
            continue
        was = next((retired[ip] for ip in sorted(_ips(f)) if ip in retired), None)
        out.append({**f, "decommissioned_id": was.id if was else None, "decommissioned_name": was.name if was else None})
    return out


def _probe(ip: str) -> dict | None:
    for scanner in SCANNERS:
        try:
            found = scanner.probe(ip)
        except Exception:  # noqa: BLE001 — one device answering oddly mustn't sink the whole scan: it's skipped
            log.warning("Skipped %s: it answered %s's questions in a way that couldn't be read", ip, scanner.__name__, exc_info=True)
            continue
        if found:
            return {"ip": ip, "hostname": None, "firmware": None, "version": None, "state": None, "web_url": None,
                    "needs_api_key": False, "link": None, "wired_ip": None, "wireless_ip": None, **found}
    return None


def _ips(found: dict) -> set[str]:
    return {h for h in (found["ip"], found["wired_ip"], found["wireless_ip"]) if h}


def _one_per_machine(found: list[dict]) -> list[dict]:
    """
    Answers from the same machine merged into one, kept where the wired answer was (else the first). Two answers are
    the same machine when one's address is among the IPs the other said it has.
    """
    kept: list[dict] = []
    for f in found:
        twin = next((k for k in kept if f["ip"] in _ips(k) or k["ip"] in _ips(f)), None)
        if twin is None:
            kept.append(f)
            continue
        merged = f if f["link"] == "wired" and twin["link"] != "wired" else twin
        other = twin if merged is f else f
        merged = {**merged, "wired_ip": merged["wired_ip"] or other["wired_ip"],
                  "wireless_ip": merged["wireless_ip"] or other["wireless_ip"]}
        kept[kept.index(twin)] = merged
    return kept


def default_range(db: Session) -> str | None:
    """
    The range a scan starts with: the /24 of the network Farmhand's server is on. Outside Docker that's its own
    address there; a container only sees Docker's network inside it, so then it's the /24 most printers already in
    Farmhand are on (the farm's network). None when neither is known.
    """
    own = None if os.path.exists("/.dockerenv") else _own_address()
    if own and _slash_24(own):
        return _slash_24(own)
    counts = Counter(_slash_24(ip) for p in db.scalars(select(Printer)) for ip in (p.wired_ip, p.wireless_ip) if ip)
    counts.pop(None, None)
    return counts.most_common(1)[0][0] if counts else None


def _own_address() -> str | None:
    """The server's address on its network: the one it would send from (a UDP socket that's never sent on)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def _slash_24(ip: str) -> str | None:
    """The /24 an address is in (192.168.10.125: 192.168.10.0/24); None unless it's a private IPv4 one a scan would take."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.version != 4 or not addr.is_private or addr.is_loopback or addr.is_link_local:
        return None
    return str(ipaddress.ip_network(f"{addr}/24", strict=False))


def _known_hosts(db: Session) -> set[str]:
    """Every address an active printer in Farmhand is reached at (a decommissioned one's are scanned again)."""
    return {h for p in db.scalars(select(Printer).where(Printer.decommissioned.is_(False))) for h in _hosts(p)}


def _decommissioned_hosts(db: Session) -> dict[str, Printer]:
    """Each address of a decommissioned printer, and that printer."""
    return {h: p for p in db.scalars(select(Printer).where(Printer.decommissioned.is_(True)).order_by(Printer.id))
            for h in _hosts(p)}


def _hosts(p: Printer) -> set[str]:
    """A printer's addresses: its IPs, and the host of any Moonraker or PrusaLink address set for it."""
    hosts = {h for h in (p.wired_ip, p.wireless_ip) if h}
    for url in (p.moonraker_url_override, p.prusalink_url_override):
        host = urlsplit(url).hostname if url else None
        if host:
            hosts.add(host)
    return hosts
