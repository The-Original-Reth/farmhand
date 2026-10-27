"""The HTTP side: one request to a printer's Moonraker, and the few plain questions asked of it."""
from __future__ import annotations

import httpx

from ...models import Printer

TIMEOUT = httpx.Timeout(6.0, connect=3.0)
UPLOAD_TIMEOUT = httpx.Timeout(600.0, connect=5.0)  # a big G-code over the printer's network takes a while

# Tests swap this for an httpx.MockTransport that plays a fake Moonraker
transport: httpx.BaseTransport | None = None


class MoonrakerError(Exception):
    """kind: no_address | unreachable | unauthorized | not_found | bad_response"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _call(printer: Printer, method: str, path: str, *, params: dict | None = None, json: dict | None = None,
          files: dict | None = None, data: dict | None = None, timeout: httpx.Timeout = TIMEOUT, unwrapped: bool = False):
    """One Moonraker request; returns its "result" (or, unwrapped, the whole answer: an upload's isn't wrapped)."""
    base = printer.moonraker_url
    if not base:
        raise MoonrakerError("no_address", "This printer has no IP address or Moonraker address set.")
    headers = {}
    if printer.connection_row and printer.connection_row.api_key:
        headers["X-Api-Key"] = printer.connection_row.api_key
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            r = client.request(method, f"{base}{path}", params=params, json=json, files=files, data=data, headers=headers)
    except httpx.TimeoutException:
        raise MoonrakerError("unreachable", f"Moonraker at {base} didn't answer in time. Is the printer on?") from None
    except httpx.HTTPError as e:
        raise MoonrakerError("unreachable", f"Couldn't connect to Moonraker at {base} ({type(e).__name__}).") from None
    if r.status_code in (401, 403):
        raise MoonrakerError(
            "unauthorized",
            "Moonraker refused the request. Add this printer's Moonraker API key, or add Farmhand's address to "
            "[authorization] trusted_clients in moonraker.conf.",
        )
    if r.status_code == 404:
        raise MoonrakerError("not_found", "Not found on Moonraker.")
    if r.status_code >= 400:
        raise MoonrakerError("bad_response", f"Moonraker answered {r.status_code}: {_error_text(r)}")
    try:
        return r.json() if unwrapped else r.json()["result"]
    except (ValueError, KeyError, TypeError):
        raise MoonrakerError("bad_response", f"{base} answered, but not like Moonraker does.") from None


def _error_text(r: httpx.Response) -> str:
    try:
        return str(r.json()["error"]["message"])
    except Exception:  # noqa: BLE001 - any shape at all: fall back to the raw text
        return r.text[:200]


def server_info(printer: Printer) -> dict:
    """Is it reachable, and what state is Klipper in (ready, startup, shutdown, error, disconnected)?"""
    info = _call(printer, "GET", "/server/info")
    return {"klippy_state": info.get("klippy_state"), "moonraker_version": info.get("moonraker_version")}


def job_totals(printer: Printer) -> dict:
    return _call(printer, "GET", "/server/history/totals").get("job_totals") or {}


def history_totals(printer: Printer) -> tuple[dict, list]:
    """(job_totals, auxiliary_totals): the second holds e.g. a power meter's energy summed over all prints."""
    result = _call(printer, "GET", "/server/history/totals")
    return result.get("job_totals") or {}, result.get("auxiliary_totals") or []


def meter_reading(printer: Printer) -> tuple[str, float] | None:
    """
    (sensor id, kWh) from the first Moonraker [sensor] that reports an "energy" value, e.g. a smart plug over MQTT.
    None if the printer has no such sensor (or no sensors at all).
    """
    try:
        sensors = _call(printer, "GET", "/server/sensors/list").get("sensors") or {}
    except MoonrakerError as e:
        if e.kind == "not_found":
            return None  # Moonraker's sensor component isn't set up
        raise
    for sensor_id, sensor in sensors.items():
        value = (sensor.get("values") or {}).get("energy")
        if isinstance(value, (int, float)):
            return sensor_id, float(value)
    return None


def print_state(printer: Printer) -> str | None:
    """What Klipper is doing: "standby", "printing", "paused", "complete", "cancelled" or "error"."""
    status = _call(printer, "GET", "/printer/objects/query", params={"print_stats": "state"}).get("status") or {}
    return (status.get("print_stats") or {}).get("state")


def upload_and_print(printer: Printer, filename: str, data: bytes) -> str:
    """Put a G-code in the printer's gcodes folder (replacing one of the same name) and start it. Returns where it went."""
    answer = _call(
        printer, "POST", "/server/files/upload", files={"file": (filename, data)}, data={"root": "gcodes", "print": "true"},
        timeout=UPLOAD_TIMEOUT, unwrapped=True,
    )
    return f"gcodes/{(answer.get('item') or {}).get('path') or filename}"


LIVE_OBJECTS = {"print_stats": None, "virtual_sdcard": None, "extruder": "temperature,target", "heater_bed": "temperature,target"}


def live_print(printer: Printer) -> dict | None:
    """
    The print Klipper is running or has paused, as Mainsail shows it: its file, progress through the file (0-100),
    time spent printing (pauses not counted) and time left, estimated from that progress the way Mainsail's default
    does. Plus nozzle and bed temperatures. None when nothing is printing.
    """
    params = {name: fields or "" for name, fields in LIVE_OBJECTS.items()}
    status = _call(printer, "GET", "/printer/objects/query", params=params).get("status") or {}
    stats = status.get("print_stats") or {}
    if stats.get("state") not in ("printing", "paused"):
        return None
    progress = float((status.get("virtual_sdcard") or {}).get("progress") or 0)
    printed = float(stats.get("print_duration") or 0)
    left = printed / progress - printed if progress > 0 and printed > 0 else None
    temps = lambda name: {k: (status.get(name) or {}).get(k) for k in ("temperature", "target")}  # noqa: E731
    return {
        "state": stats["state"],
        "file": stats.get("filename") or None,
        "progress": round(progress * 100, 1),
        "print_duration": printed,
        "time_remaining": round(left) if left is not None else None,
        "extruder": temps("extruder"),
        "heater_bed": temps("heater_bed"),
    }
