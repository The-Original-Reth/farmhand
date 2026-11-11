"""
Keeping an up-to-date picture of the farm (the "snapshot" the page shows), with two background threads:

- the refresher asks Farmhand for every printer and its print every REFRESH_SECONDS (progress creeps along between
  events), and straight away when the listener hears something. When Farmhand is down or refuses, it keeps the
  problem in the snapshot, for the page to show, and tries again every RETRY_SECONDS (or when Farmhand says).
- the listener stays connected to Farmhand's /events, so a print starting or finishing shows within moments of
  Farmhand seeing it, rather than at the next refresh. It reconnects by itself when the connection drops.

The page never talks to Farmhand: only this plugin holds the token. The page asks this plugin (server.py), which
answers from the snapshot, however many people have the page open.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .config import Settings
from .farmhand import Farmhand, FarmhandError

REFRESH_SECONDS = 20.0  # a print's progress, between events. Farmhand keeps a print's answer 3 s, so no faster than that
RETRY_SECONDS = 10.0  # while Farmhand is down or refusing
ASK_AT_ONCE = 4  # printers asked side by side: one that's off (slow to answer) doesn't hold up the others


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Watcher:
    def __init__(self, farmhand: Farmhand, settings: Settings,
                 refresh_seconds: float = REFRESH_SECONDS, retry_seconds: float = RETRY_SECONDS):
        self.farmhand, self.settings = farmhand, settings
        self.refresh_seconds, self.retry_seconds = refresh_seconds, retry_seconds
        self._changed = threading.Condition()  # held while the snapshot changes; waited on by the page's event stream
        self._version = 0
        self._printers: list[dict] = []
        self._farm: dict | None = None
        self._problem: FarmhandError | None = None
        self._checked_at: str | None = None
        self._live = False  # connected to Farmhand's /events
        self._last_event: dict | None = None
        self._wake = threading.Event()  # set by the listener (or a new setting) to refresh now
        self._stop = threading.Event()

    # ------------------------------------------------------------------ what the page is shown

    def snapshot(self) -> dict:
        with self._changed:
            hidden = self.settings.hidden_printers
            return {
                "version": self._version,
                "farmhand": {
                    "ok": self._problem is None and self._checked_at is not None,
                    "problem": self._problem.message if self._problem else None,
                    "problem_kind": self._problem.kind if self._problem else None,
                    "checked_at": self._checked_at,
                    "live": self._live,
                    "retry_seconds": self.retry_seconds,
                },
                "printers": [p for p in self._printers if p["id"] not in hidden],
                "all_printers": [{"id": p["id"], "name": p["name"]} for p in self._printers],
                "hidden_printers": hidden,
                "farm": self._farm,
                "last_event": self._last_event,
            }

    def wait_for_change(self, seen_version: int, timeout: float) -> int:
        """Block until the snapshot is newer than seen_version (or timeout); the version now."""
        with self._changed:
            self._changed.wait_for(lambda: self._version != seen_version or self._stop.is_set(), timeout)
            return self._version

    def problem(self) -> FarmhandError | None:
        with self._changed:
            return self._problem

    def _update(self, **fields) -> None:
        with self._changed:
            for name, value in fields.items():
                setattr(self, f"_{name}", value)
            self._version += 1
            self._changed.notify_all()

    def settings_changed(self) -> None:
        self._update()  # nothing to ask Farmhand: the page just shows a different set of printers

    # ------------------------------------------------------------------ asking Farmhand

    def refresh(self) -> None:
        """Ask Farmhand for every printer and its print now. FarmhandError when it can't be asked."""
        printers = self.farmhand.printers()
        with ThreadPoolExecutor(max_workers=ASK_AT_ONCE) as pool:
            prints = list(pool.map(lambda p: self.farmhand.print_of(p["id"]), printers))
        try:
            farm = self.farmhand.farm()
        except FarmhandError as e:
            if e.kind != "forbidden":
                raise
            farm = None  # the operator didn't grant farm:read: the page keeps its own colours
        rows = [
            {
                "id": p["id"], "name": p["name"], "kind": p.get("kind"), "connection_type": p.get("connection_type"),
                "state": pr.get("state"), "progress": pr.get("progress"), "file": pr.get("file"), "error": pr.get("error"),
            }
            for p, pr in zip(printers, prints)
        ]
        self._update(printers=rows, farm=farm, problem=None, checked_at=now_iso())

    def _refresher(self) -> None:
        while not self._stop.is_set():
            wait = self.refresh_seconds
            try:
                self.refresh()
            except FarmhandError as e:
                # Keep the printers last seen (the page greys them out) and say what's wrong
                if self._problem is None or self._problem.message != e.message:
                    print(f"hello: {e.message}", flush=True)
                self._update(problem=e, checked_at=now_iso())
                wait = e.retry_after or self.retry_seconds
            except Exception as e:  # a bug, or an answer this plugin doesn't understand: keep going
                print(f"hello: refreshing failed: {e!r}", flush=True)
                self._update(problem=FarmhandError(f"Something went wrong reading Farmhand's answer: {e}", "error"))
                wait = self.retry_seconds
            self._wake.wait(wait)
            self._wake.clear()

    def _listener(self) -> None:
        while not self._stop.is_set():
            try:
                for kind, data in self.farmhand.events():
                    if kind == "connected":
                        self._update(live=True)
                    elif kind.startswith(("print.", "printer.")):
                        self._update(last_event={**data, "type": kind})
                        self._wake.set()  # refresh now: a new print, a finished one, a printer back
                    if self._stop.is_set():
                        return
            except FarmhandError as e:
                if self._live:
                    print(f"hello: {e.message} Reconnecting.", flush=True)
                self._update(live=False)
                self._stop.wait(e.retry_after or self.retry_seconds)
            except Exception as e:
                print(f"hello: listening for events failed: {e!r}", flush=True)
                self._update(live=False)
                self._stop.wait(self.retry_seconds)
            else:
                # The connection opened, but Farmhand never sent anything (or ended it): it's no longer live
                self._update(live=False)

    def start(self) -> None:
        threading.Thread(target=self._refresher, name="hello-refresher", daemon=True).start()
        threading.Thread(target=self._listener, name="hello-listener", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        with self._changed:
            self._changed.notify_all()

