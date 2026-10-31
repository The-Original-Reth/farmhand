"""
Finding printers on the network: every address in a range is asked, by each scanner in SCANNERS in turn, whether a
printer Farmhand can talk to is there. Addresses a printer in Farmhand already has are skipped, retired ones
included. Nothing is added: the answer is a list for the user to choose from, and choosing one is an ordinary
POST /printers.

A machine on both a cable and Wi-Fi answers at two addresses. Where the scanner can tell (Moonraker lists its network
interfaces), those answers become one entry: the wired one, carrying both IPs.

A scanner is one kind of printer (Moonraker and PrusaLink; OctoPrint could follow): a module with a `probe(ip)` that
answers what it found there, or None. Adding a kind is a new module and a line in SCANNERS.
"""
from __future__ import annotations

import ipaddress
import logging
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
    """The printers in `cidr` (e.g. "192.168.1.0/24") that aren't in Farmhand yet, in address order."""
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
    return [f for f in merged if not known & _ips(f)]


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
