from __future__ import annotations

import threading

from app.periodic import PeriodicWorker


class Counting(PeriodicWorker):
    name, failure = "test-worker", "the test run failed"

    def __init__(self, fail_first: bool):
        super().__init__(interval=0.01, first_wait=0.0)
        self.runs, self.fail_first, self.third = 0, fail_first, threading.Event()

    def run_once(self):
        self.runs += 1
        if self.runs == 3:
            self.third.set()
        if self.fail_first and self.runs == 1:
            raise RuntimeError("boom")


def test_a_worker_keeps_running_after_a_run_fails_and_stops_when_asked():
    w = Counting(fail_first=True)
    w.start()
    assert w.third.wait(2)  # the failure on the first run didn't stop it
    w.stop()
    w._thread.join(2)
    assert not w._thread.is_alive() and w.stopping


def test_a_worker_waits_before_its_first_run():
    w = Counting(fail_first=False)
    w.first_wait = 60
    w.start()
    assert not w.third.wait(0.1) and w.runs == 0
    w.stop()
