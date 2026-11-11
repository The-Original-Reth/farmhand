"""What the Printers page shows about a Moonraker printer right now: can Farmhand reach it, what state Klipper is in,
and what it's printing. Never fails: an unreachable printer says why."""
from __future__ import annotations

from ...models import Printer
from .client import MoonrakerError, live_print, server_info


def connection_status(printer: Printer) -> dict:
    out = {
        "moonraker_url": printer.moonraker_url,
        "mainsail_url": printer.mainsail_url,
        "has_api_key": printer.has_moonraker_api_key,
        "reachable": False,
        "klippy_state": None,
        "moonraker_version": None,
        "error": None,
        "error_kind": None,
        "print": None,  # the print running or paused right now, if any (see client.live_print)
    }
    try:
        out.update(server_info(printer), reachable=True)
    except MoonrakerError as e:
        out.update(error=str(e), error_kind=e.kind)
        return out
    # the one of its IPs it answered at just now (its Wi-Fi one when its cable is out)
    out.update(moonraker_url=printer.moonraker_url, mainsail_url=printer.mainsail_url)
    if out["klippy_state"] == "ready":
        try:
            out["print"] = live_print(printer)
        except MoonrakerError:
            pass  # connected, but Klipper didn't say: shown as not printing
    return out
