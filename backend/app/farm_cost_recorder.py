"""
Saves each month's Farm cost record once the month is over, without anyone opening the page.

A background thread looks once an hour (and soon after start-up, so a month that ended while Farmhand was off is
caught up): if last month's record isn't in the "farm-cost" folder yet, it's written (services/farm_cost.py). A
folder that can't be written right now (a network share that isn't mounted) is just tried again the next hour;
nothing here ever stops the thread.

Each look also works out the page's figures in the farm's time zone, so they're ready (services/farm_cost.py keeps
them) and the page opens without costing every print first.
"""
from __future__ import annotations

import logging

from . import storage
from .database import SessionLocal
from .periodic import PeriodicWorker
from .services import config_service, farm_cost

log = logging.getLogger("farmhand.farm_cost")

INTERVAL_SECONDS = 60 * 60
FIRST_LOOK_SECONDS = 2 * 60  # after start-up: let the printers sync first


class FarmCostRecorder(PeriodicWorker):
    name, failure, log = "farm-cost-recorder", "Couldn't save the farm cost record", log

    def __init__(self, interval: float = INTERVAL_SECONDS, first_look: float = FIRST_LOOK_SECONDS):
        super().__init__(interval, first_wait=first_look)

    def run_once(self) -> None:
        with SessionLocal() as db:
            farm_cost.filament_by_month(db, config_service.get_config(db)["preferences"].get("time_zone"))
            try:
                written = farm_cost.record_last_month(db)
            except storage.StorageUnavailableError as e:
                log.info("Last month's farm cost record will be saved later: %s", e)
                return
        if written:
            log.info("Saved the farm cost record %s", written)


recorder = FarmCostRecorder()
