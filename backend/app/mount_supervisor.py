"""
Keeps saved network shares mounted.

Mounts live inside the container and vanish when it restarts, and a NAS is often switched on a
little after the computer that uses it (after a power cut, say). So rather than mounting once at
startup, a background thread checks every INTERVAL seconds and mounts anything that isn't. It runs
in a thread so a slow or unreachable NAS never delays the API coming up.
"""
from __future__ import annotations

import logging

from .database import SessionLocal
from .periodic import PeriodicWorker
from .services import network_shares_service

log = logging.getLogger("farmhand.mounts")

INTERVAL_SECONDS = 30


class MountSupervisor(PeriodicWorker):
    name, failure, log = "mount-supervisor", "Checking network shares failed", log

    def __init__(self, interval: float = INTERVAL_SECONDS):
        super().__init__(interval)

    def run_once(self) -> None:
        with SessionLocal() as db:
            network_shares_service.ensure_mounted(db)


supervisor = MountSupervisor()
