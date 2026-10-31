"""
Finding Klipper printers on the network: every address in a range is asked whether it runs Moonraker (the API
behind Mainsail and Fluidd, on port 7125). Addresses a printer in Farmhand already has are skipped, retired ones
included. Nothing is added: the answer is a list for the user to choose from, and choosing one is an ordinary
POST /printers.
"""
from __future__ import annotations

import ipaddress
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Printer
from .moonraker import client

MAX_ADDRESSES = 1024  # a /22; a bigger range would take minutes and is more likely a typo
MOONRAKER_PORT = 7125
WORKERS = 32


def scan(db: Session, cidr: str) -> list[dict]:
    """The Moonraker printers in `cidr` (e.g. "192.168.1.0/24") that aren't in Farmhand yet, in address order."""
    try:
        net = ipaddress.ip_network(cidr.strip(), strict=False)
    except ValueError:
        raise ValueError(f"'{cidr}' isn't a network range. Write it like 192.168.1.0/24.") from None
    if net.version != 4:
        raise ValueError("Only IPv4 ranges can be scanned, like 192.168.1.0/24.")
    if net.num_addresses > MAX_ADDRESSES:
        raise ValueError(f"That range has {net.num_addresses} addresses. Scan {MAX_ADDRESSES} or fewer at a time (a /22 or smaller).")

    known = _known_hosts(db)
    targets = [str(ip) for ip in (net.hosts() if net.num_addresses > 1 else [net.network_address]) if str(ip) not in known]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        answers = pool.map(lambda ip: client.probe(f"http://{ip}:{MOONRAKER_PORT}"), targets)
        found = [(ip, info) for ip, info in zip(targets, answers) if info]
    return [
        {"ip": ip, "moonraker_url": f"http://{ip}:{MOONRAKER_PORT}", "mainsail_url": f"http://{ip}/",
         "moonraker_version": None, "klippy_state": None, "hostname": None, "needs_api_key": False, **info}
        for ip, info in found
    ]


def _known_hosts(db: Session) -> set[str]:
    """Every address a printer in Farmhand is reached at: its IPs, and the host of any Moonraker or PrusaLink address set for it."""
    hosts: set[str] = set()
    for p in db.scalars(select(Printer)):
        hosts.update(h for h in (p.wired_ip, p.wireless_ip) if h)
        for url in (p.moonraker_url_override, p.prusalink_url_override):
            host = urlsplit(url).hostname if url else None
            if host:
                hosts.add(host)
    return hosts
