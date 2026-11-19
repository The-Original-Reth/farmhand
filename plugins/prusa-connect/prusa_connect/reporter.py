"""
The plugin's work: every REPORT_SECONDS, each Farmhand printer that takes its status from this plugin gets its state
from Prusa Connect, passed on to Farmhand (PUT /plugin-api/v1/printers/{id}/status). Farmhand records its prints from
these reports, as it would from the printer's PrusaLink.

Which printers: Farmhand says (status_from in GET /printers is this plugin's id); the operator switches each one in its
PrusaLink section in Farmhand. Which Prusa Connect printer each one is: this plugin's settings (its page), filled in by
itself when a Prusa Connect printer has the same name as a Farmhand one.

The page reads snapshot(): Prusa Connect's state, the printers on both sides and the last report of each.
"""
from __future__ import annotations

import tempfile
import threading
import time
from urllib.parse import quote

from .config import Settings
from .connect import ConnectError, PrusaConnect, device_out, report, shown_pairing
from .farmhand import Farmhand, FarmhandError

PLUGIN_ID = "prusa-connect"  # farmhand-plugin.json's id: how Farmhand names this plugin in status_from
REPORT_SECONDS = 10.0


class Reporter:
    def __init__(self, farmhand: Farmhand, connect: PrusaConnect, settings: Settings, interval: float = REPORT_SECONDS):
        self.farmhand, self.connect, self.settings, self.interval = farmhand, connect, settings, interval
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot = {"farmhand_error": None, "connect": {"reachable": False, "version": None, "error": None},
                          "printers": [], "devices": [], "checked_at": None}
        self._farmhand_problem: FarmhandError | None = None

    # ------------------------------------------------------------------ running

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="prusa-connect-reporter", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        """Look again now (a setting changed on the page)."""
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            wait = self.interval
            try:
                self.run_once()
            except FarmhandError as e:
                if e.retry_after:
                    wait = max(wait, e.retry_after)
            except Exception as e:  # noqa: BLE001 - never let the thread die; say what happened
                print(f"prusa-connect: {type(e).__name__}: {e}", flush=True)
            self._wake.wait(wait)
            self._wake.clear()

    def run_once(self) -> dict:
        """One look: Prusa Connect's printers, Farmhand's, and a report of each printer Farmhand takes from here."""
        connect = {"reachable": False, "version": None, "error": None, "open": False}
        devices: list[dict] | None = None
        connect_error = None
        if self.settings.address:
            try:
                connect.update(reachable=True, version=self.connect.health().get("version"))
                connect["open"] = self.connect.is_open()
                if connect["open"] and self.settings.pairing:
                    self.settings.set_pairing(None)  # nobody can approve it, and it isn't needed
                if self.settings.token or connect["open"]:
                    devices = self.connect.devices()
            except ConnectError as e:
                connect_error = e.message
                connect["error"] = e.message
        try:
            printers = [p for p in self.farmhand.printers() if p.get("connection_type") == "prusalink"]
        except FarmhandError as e:
            self._farmhand_problem = e
            self._publish(farmhand_error=e.message, connect=connect, devices=devices)
            raise
        self._farmhand_problem = None
        if devices is not None:
            self._link_by_name(printers, devices)
        by_id = {d.get("id"): d for d in devices or []}
        links = self.settings.links
        rows = []
        for p in printers:
            device_id = links.get(p["id"])
            row = {"id": p["id"], "name": p["name"], "status_from": p.get("status_from"), "device_id": device_id, "last": None}
            if p.get("status_from") == PLUGIN_ID:
                row["last"] = self._report_one(p, device_id, by_id, devices is not None, connect_error)
            rows.append(row)
        self._publish(farmhand_error=None, connect=connect, devices=devices, printers=rows)
        return self.snapshot()

    def _report_one(self, printer: dict, device_id, by_id: dict, asked: bool, connect_error) -> dict:
        address = self.settings.address
        # its page on Prusa Connect (the printer's own, once linked): Farmhand's "Open in Prusa Connect"
        link = (f"{address}/printers/{quote(device_id, safe='')}" if device_id else f"{address}/") if address else None
        if not device_id:
            sent = report(None, link, f"Not linked to a printer on Prusa Connect yet: choose which one it is on the Prusa Connect plugin's page.")
        elif not asked:
            sent = report(None, link, connect_error or "The Prusa Connect plugin isn't paired with Prusa Connect yet.")
        elif device_id not in by_id:
            sent = report(None, link, "Prusa Connect doesn't know the printer it was linked to any more (it may have been paired again). Choose it again on the Prusa Connect plugin's page.")
        else:
            sent = report(by_id[device_id], link)
        at = time.time()
        try:
            answer = self.farmhand.report(printer["id"], sent)
        except FarmhandError as e:
            if e.kind in ("refused", "setup"):
                raise
            return {"at": at, "sent": sent, "recorded": False, "error": e.message}
        return {"at": at, "sent": sent, "recorded": bool(answer.get("recorded")), "error": answer.get("error")}

    def _link_by_name(self, printers: list[dict], devices: list[dict]) -> None:
        """A Farmhand printer not linked yet, with the same name as a Prusa Connect printer nothing is linked to: linked."""
        links = self.settings.links
        taken = set(links.values())
        names = {}
        for d in devices:
            names.setdefault(str(d.get("name") or "").strip().casefold(), []).append(d)
        for p in printers:
            same = names.get(p["name"].strip().casefold(), [])
            if p["id"] not in links and len(same) == 1 and same[0].get("id") not in taken:
                self.settings.link(p["id"], same[0]["id"])
                taken.add(same[0]["id"])

    # ------------------------------------------------------------------ a print Farmhand sends

    def send_print(self, body: dict) -> dict:
        """
        Farmhand hands a print over (POST /farmhand/print): {ticket, printer_id, file, size}. The G-code is fetched
        from Farmhand with the ticket, put in Prusa Connect and sent on to the printer linked to that Farmhand printer,
        which starts it. Returns {"sent": where it went on the printer}. PrintRefused (with an HTTP status) otherwise.
        """
        ticket, name = body.get("ticket"), body.get("file")
        try:
            printer_id = int(body.get("printer_id"))
        except (TypeError, ValueError):
            raise PrintRefused(400, "Farmhand didn't say which printer.") from None
        if not isinstance(ticket, str) or not ticket or not isinstance(name, str) or not name.strip() or "/" in name:
            raise PrintRefused(400, "Farmhand's print came without its ticket or file name.")
        device_id = self.settings.links.get(printer_id)
        if not device_id:
            raise PrintRefused(409, "This printer isn't linked to a printer on Prusa Connect yet: choose which one it is "
                                    "on the Prusa Connect plugin's page.")
        try:
            device = self.connect.device(device_id)
            if not device.get("connected"):
                raise PrintRefused(409, f"Prusa Connect isn't hearing from {device.get('name') or 'the printer'} right now.")
            state = (device.get("state") or {}).get("/state")
            if state not in READY_STATES:
                raise PrintRefused(409, f"{device.get('name') or 'The printer'} isn't ready for a new print (Prusa Connect "
                                        f"says {state or 'nothing'}).")
            where = self.connect.printer_storage(device_id)
            with tempfile.TemporaryFile() as held:
                size = self.farmhand.fetch_print(ticket, held)
                held.seek(0)
                storage, source = self.connect.upload(name, held, size)
            sent = self.connect.print_file(device_id, storage, source, f"{where}/{name}")
        except ConnectError as e:
            raise PrintRefused(409 if e.kind in ("busy", "refused_print") else 502, e.message) from None
        except FarmhandError as e:
            raise PrintRefused(502, e.message) from None
        self.wake()  # report the new print straight away
        return {"sent": sent.lstrip("/")}

    # ------------------------------------------------------------------ what the page and /health read

    def _publish(self, farmhand_error, connect, devices, printers=None) -> None:
        with self._lock:
            self._snapshot = {
                "farmhand_error": farmhand_error, "connect": connect,
                "printers": printers if printers is not None else self._snapshot["printers"],
                "devices": [device_out(d) for d in devices or []], "checked_at": time.time(),
            }

    def snapshot(self) -> dict:
        with self._lock:
            snap = dict(self._snapshot)
        snap.update(
            plugin_id=PLUGIN_ID, address=self.settings.address, open=bool((snap.get("connect") or {}).get("open")),
            paired=bool(self.settings.token) or bool((snap.get("connect") or {}).get("open")),
            pairing=shown_pairing(self.settings.pairing), links={str(k): v for k, v in self.settings.links.items()},
        )
        return snap

    def problem(self) -> FarmhandError | None:
        """What's wrong between this plugin and Farmhand, if anything (for /health)."""
        return self._farmhand_problem


READY_STATES = ("IDLE", "READY", "FINISHED", "STOPPED")  # a Prusa printer takes a new print in these


class PrintRefused(Exception):
    """A print Farmhand handed over that wasn't started: the HTTP status for Farmhand, and why in plain words."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message
