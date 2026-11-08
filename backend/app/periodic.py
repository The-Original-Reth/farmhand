"""
A job Farmhand does on its own every so often, on a thread of its own (keeping shares mounted, syncing printers,
saving the Farm cost record, bringing in what another Farmhand shares...). Started when the app starts, stopped when
it stops; one run failing is logged and never stops the thread.
"""
from __future__ import annotations

import logging
import threading


class PeriodicWorker:
    """
    Subclasses set `name` (the thread's), `failure` (what the log says when a run fails) and `log`, and write run_once().
    It runs `first_wait` seconds after start() (0: straight away), then every `interval` seconds.
    """

    name = "periodic"
    failure = "A background job failed"
    log = logging.getLogger("farmhand")

    def __init__(self, interval: float, first_wait: float = 0.0):
        self.interval = interval
        self.first_wait = first_wait
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopping(self) -> bool:
        """Asked to stop: a long run_once can check this and leave early."""
        return self._stop.is_set()

    def run_once(self) -> None:
        raise NotImplementedError

    def _run(self) -> None:
        wait = self.first_wait
        while not self._stop.wait(wait):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - one bad run must never stop the thread
                self.log.exception(self.failure)
            wait = self.interval
