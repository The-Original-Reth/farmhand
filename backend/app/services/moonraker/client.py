"""The HTTP side: one request to a printer's Moonraker, and the few plain questions asked of it."""
from __future__ import annotations

import re
from typing import BinaryIO
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx

from ...models import Printer
from ... import printer_links
from .. import printer_http
from ..printer_http import PROBE_TIMEOUT, TIMEOUT, UPLOAD_TIMEOUT

# Tests swap this for an httpx.MockTransport that plays a fake Moonraker
transport: httpx.BaseTransport | None = None


class MoonrakerError(printer_http.PrinterLinkError):
    """kind: no_address | unreachable | unauthorized | not_found | bad_response"""


def answered_at(printer: Printer) -> str | None:
    """The address the printer's Moonraker answered at last, while that counts (see printer_links)."""
    return printer_links.answered("moonraker", printer.id, printer.moonraker_urls)


def call(printer: Printer, method: str, path: str, *, params: dict | None = None, json: dict | None = None,
          files: dict | None = None, data: dict | None = None, timeout: httpx.Timeout = TIMEOUT, unwrapped: bool = False):
    """
    One Moonraker request; returns its "result" (or, unwrapped, the whole answer: an upload's isn't wrapped). Asked at
    the printer's wired IP, or its Wi-Fi IP when the wired one can't be reached (see printer_http.request_first_answering).
    """
    bases = printer.moonraker_urls
    if not bases:
        raise MoonrakerError("no_address", "This printer has no IP address or Moonraker address set.")
    r, base = printer_http.request_first_answering(
        MoonrakerError, "Moonraker", "moonraker", printer.id, bases, method, path,
        transport=transport, timeout=timeout, params=params, json=json, files=files, data=data, headers=_headers(printer),
    )
    _check_allowed(r)
    if r.status_code >= 400:
        raise MoonrakerError("bad_response", f"Moonraker answered {r.status_code}: {_error_text(r)}")
    try:
        return r.json() if unwrapped else r.json()["result"]
    except (ValueError, KeyError, TypeError):
        raise MoonrakerError("bad_response", f"{base} answered, but not like Moonraker does.") from None


def _headers(printer: Printer, **extra: str) -> dict:
    headers = dict(extra)
    if printer.connection_row and printer.connection_row.api_key:
        headers["X-Api-Key"] = printer.connection_row.api_key
    return headers


def _check_allowed(r: httpx.Response) -> None:
    if r.status_code in (401, 403):
        raise MoonrakerError(
            "unauthorized",
            "Moonraker refused the request. Add this printer's Moonraker API key, or add Farmhand's address to "
            "[authorization] trusted_clients in moonraker.conf.",
        )


GCODE_TAIL_MAX = 512 * 1024  # the most of a G-code's end read for its settings block (PrusaSlicer's is ~100 KB)


def gcode_tail(printer: Printer, filename: str, start: int | None = None, size: int | None = None) -> bytes:
    """
    The end of a G-code in the printer's gcodes folder, from byte `start` (where the G-code moves end, as Moonraker's
    metadata says) or else its last GCODE_TAIL_MAX bytes: only that part is sent, never the whole file. A file that
    isn't there any more raises MoonrakerError("not_found").
    """
    if start is not None and size is not None and 0 <= start < size and size - start <= GCODE_TAIL_MAX:
        wanted = f"bytes={start}-"
    else:
        wanted = f"bytes=-{GCODE_TAIL_MAX}"
    bases = printer.moonraker_urls
    if not bases:
        raise MoonrakerError("no_address", "This printer has no IP address or Moonraker address set.")
    r, _ = printer_http.request_first_answering(
        MoonrakerError, "Moonraker", "moonraker", printer.id, bases, "GET", f"/server/files/gcodes/{quote(filename)}",
        transport=transport, headers=_headers(printer, Range=wanted),
    )
    _check_allowed(r)
    if r.status_code >= 400:
        raise MoonrakerError("bad_response", f"Moonraker answered {r.status_code}: {_error_text(r)}")
    return r.content[-GCODE_TAIL_MAX:]


def _error_text(r: httpx.Response) -> str:
    try:
        return str(r.json()["error"]["message"])
    except Exception:  # noqa: BLE001 - any shape at all: fall back to the raw text
        return r.text[:200]


def server_info(printer: Printer) -> dict:
    """Is it reachable, and what state is Klipper in (ready, startup, shutdown, error, disconnected)?"""
    info = call(printer, "GET", "/server/info")
    return {"klippy_state": info.get("klippy_state"), "moonraker_version": info.get("moonraker_version")}


def probe(base: str) -> dict | None:
    """
    Is there a Moonraker at `base` (e.g. http://10.0.6.21:7125)? Its version, Klipper's state, and what Klipper says
    of itself (hostname, app, software_version) and its network interfaces (network, from /machine/system_info) when
    there is; None when nothing there answers like Moonraker. One
    that wants an API key still counts: the printer is there, it just needs the key (needs_api_key).
    """
    try:
        r = printer_http.request(MoonrakerError, "Moonraker", base, "GET", "/server/info",
                                 transport=transport, timeout=PROBE_TIMEOUT)
    except MoonrakerError:
        return None
    if r.status_code in (401, 403):
        return {"needs_api_key": True}
    try:
        info = r.json()["result"]
        found = {"moonraker_version": info["moonraker_version"], "klippy_state": info.get("klippy_state")}
    except (ValueError, KeyError, TypeError):
        return None
    try:
        r = printer_http.request(MoonrakerError, "Moonraker", base, "GET", "/printer/info",
                                 transport=transport, timeout=PROBE_TIMEOUT)
        klipper = r.json()["result"]
        found.update({k: klipper.get(k) for k in ("hostname", "app", "software_version")})
    except (MoonrakerError, ValueError, KeyError, TypeError, AttributeError):
        pass  # Klipper isn't up yet: found all the same, just without a name to suggest
    try:
        r = printer_http.request(MoonrakerError, "Moonraker", base, "GET", "/machine/system_info",
                                 transport=transport, timeout=PROBE_TIMEOUT)
        network = r.json()["result"]["system_info"]["network"]
        found["network"] = network if isinstance(network, dict) else {}
    except (MoonrakerError, ValueError, KeyError, TypeError):
        pass  # an older Moonraker, or one that won't say: found, just without knowing wired from wireless
    return found


def history_totals(printer: Printer) -> tuple[dict, list]:
    """(job_totals, auxiliary_totals): the second holds e.g. a power meter's energy summed over all prints."""
    result = call(printer, "GET", "/server/history/totals")
    return result.get("job_totals") or {}, result.get("auxiliary_totals") or []


def job_totals(printer: Printer) -> dict:
    """The printer's lifetime totals: total_print_time, total_filament_used, total_jobs..."""
    return history_totals(printer)[0]


def meter_reading(printer: Printer) -> tuple[str, float] | None:
    """
    (sensor id, kWh) from the first Moonraker [sensor] that reports an "energy" value, e.g. a smart plug over MQTT.
    None if the printer has no such sensor (or no sensors at all).
    """
    try:
        sensors = call(printer, "GET", "/server/sensors/list").get("sensors") or {}
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
    status = call(printer, "GET", "/printer/objects/query", params={"print_stats": "state"}).get("status") or {}
    return (status.get("print_stats") or {}).get("state")


def upload_and_print(printer: Printer, filename: str, data: bytes | BinaryIO) -> str:
    """
    Put a G-code in the printer's gcodes folder (replacing one of the same name) and start it. Returns where it went.
    data: the bytes, or an open file, which is streamed from where it is rather than read into memory first.
    """
    answer = call(
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
    status = call(printer, "GET", "/printer/objects/query", params=params).get("status") or {}
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


# Camera services whose stream is a plain MJPEG feed a browser shows in an <img>. The page plays the others as Mainsail
# does (WebRTC through go2rtc or camera-streamer, the adaptive MJPEG one as snapshots at its frame rate).
MJPEG_SERVICES = {"mjpegstreamer", "uv4l-mjpeg", "ipstream"}


def _on_answering_ip(printer: Printer, url: str) -> str:
    """
    A camera address written out whole in Mainsail with one of the printer's own IPs in it, moved to the IP the printer
    answers at now (its Wi-Fi one when its cable is out). One at any other address (a camera of its own) is left alone.
    """
    parts = urlsplit(url)
    now = urlsplit(printer.moonraker_url or "").hostname
    own = {ip for ip in (printer.wired_ip, printer.wireless_ip) if ip}
    if not now or parts.hostname not in own or parts.hostname == now:
        return url
    host = f"[{now}]" if ":" in now else now
    return urlunsplit(parts._replace(netloc=host + (f":{parts.port}" if parts.port else "")))


def board(printer: Printer) -> dict | None:
    """
    The computer Klipper runs on, as /machine/system_info describes it: {name, model, memory_gb}. name is short, the
    way it's spoken of ("Pi 4", "CM4"); model is the board's own words ("Raspberry Pi Compute Module 4 Rev 1.1").
    None when it won't say (an older Moonraker, or one that can't be reached).
    """
    try:
        cpu = call(printer, "GET", "/machine/system_info")["system_info"]["cpu_info"]
        model = str(cpu.get("model") or "").strip()
    except (MoonrakerError, KeyError, TypeError, AttributeError):
        return None
    name = board_name(model) or cpu.get("hardware_desc") or cpu.get("cpu_desc") or cpu.get("processor") or None
    if not name:
        return None
    kb = cpu.get("total_memory")
    units = str(cpu.get("memory_units") or "kB").lower()
    memory_gb = None
    if isinstance(kb, (int, float)) and kb > 0 and units == "kb":
        memory_gb = max(1, round(kb / 1024 / 1024))  # 927824 kB is a 1 GB board
    return {"name": str(name)[:40], "model": model[:120] or None, "memory_gb": memory_gb}


def board_name(model: str) -> str | None:
    """A Raspberry Pi's short name: "Raspberry Pi 4 Model B Rev 1.5" is "Pi 4", a Compute Module 4 is "CM4"; any
    other board goes by its model without the revision. None for no model."""
    if m := re.search(r"Compute Module (\d+)", model):
        return f"CM{m[1]}"
    if m := re.search(r"Raspberry Pi (Zero(?: \d)?(?: W)?|\d+)", model):
        return f"Pi {m[1]}"
    return re.sub(r"\s+Rev\s+\S+$", "", model).strip() or None


def webcams(printer: Printer) -> list[dict]:
    """
    The cameras set up in the printer's Mainsail / Moonraker (enabled ones only), with their stream and snapshot
    addresses made whole: a relative one ("/webcam/?action=stream") is on port 80 of the printer, where Mainsail is
    (on whichever of its IPs it answered at).
    """
    listed = call(printer, "GET", "/server/webcams/list").get("webcams") or []
    base = printer.mainsail_url or ""  # at the IP Moonraker just answered at
    out = []
    for cam in listed:
        if cam.get("enabled") is False:
            continue
        stream = _on_answering_ip(printer, urljoin(base, cam["stream_url"])) if cam.get("stream_url") else None
        snapshot = _on_answering_ip(printer, urljoin(base, cam["snapshot_url"])) if cam.get("snapshot_url") else None
        if not stream and not snapshot:
            continue
        service = cam.get("service") or "mjpegstreamer"
        out.append({
            "name": cam.get("name") or "Camera",
            "service": service,
            "mjpeg": service in MJPEG_SERVICES and bool(stream),
            "stream_url": stream,
            "snapshot_url": snapshot,
            "flip_horizontal": bool(cam.get("flip_horizontal")),
            "flip_vertical": bool(cam.get("flip_vertical")),
            "rotation": int(cam.get("rotation") or 0),
            "aspect_ratio": cam.get("aspect_ratio") or "16:9",
            "target_fps": int(cam.get("target_fps") or 15),
        })
    return out
