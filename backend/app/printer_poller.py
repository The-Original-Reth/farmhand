"""
Keeps each printer's copy in Farmhand current without anyone opening its page.

Every INTERVAL seconds a background thread syncs every active printer that has an address: its print history and
totals, and a reading of its power meter if it has one. Those regular meter readings are what let Farmhand work out
the whole printer's energy use per month and year (Moonraker only knows the meter's current value). A printer that's
off just records why on its connection; nothing here ever stops the thread.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy import select

from .database import SessionLocal
from .models import Printer
from .services import moonraker_service

log = logging.getLogger("farmhand.printers")

INTERVAL_SECONDS = 15 * 60


class PrinterPoller:
    def __init__(self, interval: float = INTERVAL_SECONDS):
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="printer-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> None:
        with SessionLocal() as db:
            ids = list(db.scalars(select(Printer.id).where(Printer.decommissioned.is_(False))))
        for printer_id in ids:
            if self._stop.is_set():
                return
            with SessionLocal() as db:  # one session per printer: one failing can't spoil the others
                printer = db.get(Printer, printer_id)
                if printer is None or not printer.moonraker_url:
                    continue
                try:
                    moonraker_service.sync_history(db, printer)
                except moonraker_service.MoonrakerError as e:
                    log.debug("Couldn't sync printer %s: %s", printer.name, e)

    def _run(self) -> None:
        self._stop.wait(30)  # let the API finish starting first
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 — a poller must never die
                log.exception("Syncing printers failed")
            self._stop.wait(self.interval)


poller = PrinterPoller()
