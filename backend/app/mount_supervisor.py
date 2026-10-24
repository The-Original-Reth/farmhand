"""
Keeps saved network shares mounted.

Mounts live inside the container and vanish when it restarts, and a NAS is often switched on a
little after the computer that uses it (after a power cut, say). So rather than mounting once at
startup, a background thread checks every INTERVAL seconds and mounts anything that isn't. It runs
in a thread so a slow or unreachable NAS never delays the API coming up.
"""
from __future__ import annotations

import logging
import threading

from .database import SessionLocal
from .services import network_shares_service

log = logging.getLogger("farmhand.mounts")

INTERVAL_SECONDS = 30


class MountSupervisor:
    def __init__(self, interval: float = INTERVAL_SECONDS):
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mount-supervisor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> None:
        with SessionLocal() as db:
            network_shares_service.ensure_mounted(db)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 — a supervisor must never die
                log.exception("Checking network shares failed")
            self._stop.wait(self.interval)


supervisor = MountSupervisor()
