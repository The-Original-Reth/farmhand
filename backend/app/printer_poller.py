"""
Keeps each printer's copy in Farmhand current without anyone opening its page.

Every MOONRAKER_INTERVAL seconds a background thread syncs every active Moonraker printer that has an address: its
print history and totals, and a reading of its power meter if it has one. Those regular meter readings are what let
Farmhand work out the whole printer's energy use per month and year (Moonraker only knows the meter's current value).

PrusaLink printers are looked at every minute instead: PrusaLink keeps no history, so Farmhand records each print
by seeing it while it runs (see app/services/prusalink/tracking.py). While a plugin listens for events (GET
/plugin-api/v1/events), Moonraker printers are asked for their print every minute too, so it hears of a print starting
or ending. A printer that's off just records why on its connection; nothing here ever stops the thread.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import select

from .database import SessionLocal
from .models import Printer
from .periodic import PeriodicWorker
from .services import config_service, moonraker, print_progress, prusalink
from .services.plugins import events

log = logging.getLogger("farmhand.printers")

INTERVAL_SECONDS = 60  # how often the thread wakes: PrusaLink printers are looked at every time
MOONRAKER_INTERVAL_SECONDS = 15 * 60


class PrinterPoller(PeriodicWorker):
    name, failure, log = "printer-poller", "Syncing printers failed", log

    def __init__(self, interval: float = INTERVAL_SECONDS, moonraker_interval: float = MOONRAKER_INTERVAL_SECONDS):
        super().__init__(interval, first_wait=30)  # let the API finish starting first
        self.moonraker_interval = moonraker_interval
        self._moonraker_due = 0.0  # monotonic time of the next Moonraker sync

    def run_once(self) -> None:
        sync_moonraker = time.monotonic() >= self._moonraker_due
        if sync_moonraker:
            self._moonraker_due = time.monotonic() + self.moonraker_interval
        with SessionLocal() as db:
            ids = list(db.scalars(select(Printer.id).where(Printer.decommissioned.is_(False))))
        for printer_id in ids:
            if self.stopping:
                return
            with SessionLocal() as db:  # one session per printer: one failing can't spoil the others
                printer = db.get(Printer, printer_id)
                if printer is None:
                    continue
                try:
                    if printer.connection_type == "prusalink":
                        if printer.prusalink_url:
                            print_progress.progress(db, printer)  # polls it (recording its prints), telling plugins
                    elif printer.moonraker_url:
                        if events.listening():
                            print_progress.progress(db, printer)
                        if sync_moonraker:
                            moonraker.sync_history(db, printer)
                except (moonraker.MoonrakerError, prusalink.PrusaLinkError) as e:
                    log.debug("Couldn't sync printer %s: %s", printer.name, e)
        if sync_moonraker:
            config_service.request_mirror(config_service.MirrorScope(printers=True))  # each printer's file picks up what came in


poller = PrinterPoller()
