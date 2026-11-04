"""
Saves each month's Farm cost record once the month is over, without anyone opening the page.

A background thread looks once an hour (and soon after start-up, so a month that ended while Farmhand was off is
caught up): if last month's record isn't in the "farm cost" folder yet, it's written (services/farm_cost.py). A
folder that can't be written right now (a network share that isn't mounted) is just tried again the next hour;
nothing here ever stops the thread.
"""
from __future__ import annotations

import logging
import threading

from . import storage
from .database import SessionLocal
from .services import farm_cost

log = logging.getLogger("farmhand.farm_cost")

INTERVAL_SECONDS = 60 * 60
FIRST_LOOK_SECONDS = 2 * 60  # after start-up: let the printers sync first


class FarmCostRecorder:
    def __init__(self, interval: float = INTERVAL_SECONDS, first_look: float = FIRST_LOOK_SECONDS):
        self.interval = interval
        self.first_look = first_look
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="farm-cost-recorder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> None:
        with SessionLocal() as db:
            try:
                written = farm_cost.record_last_month(db)
            except storage.StorageUnavailableError as e:
                log.info("Last month's farm cost record will be saved later: %s", e)
                return
        if written:
            log.info("Saved the farm cost record %s", written)

    def _run(self) -> None:
        wait = self.first_look
        while not self._stop.wait(wait):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - one bad look must never stop the thread
                log.exception("Couldn't save the farm cost record")
            wait = self.interval


recorder = FarmCostRecorder()
