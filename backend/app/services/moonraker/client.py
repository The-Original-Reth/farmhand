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


def config_files(printer: Printer) -> list[dict]:
    """
    Every file in the printer's config folder (subfolders too), as Moonraker lists them: [{path, size, modified,
    writable}]. writable is False for one Moonraker won't let be changed (permissions "r": e.g. a link to mainsail.cfg).
    """
    listed = call(printer, "GET", "/server/files/list", params={"root": "config"})
    out = []
    for f in listed if isinstance(listed, list) else []:
        path = f.get("path") or f.get("filename")
        if isinstance(path, str) and path:
            out.append({"path": path, "size": int(f.get("size") or 0), "modified": f.get("modified"),
                        "writable": "w" in str(f.get("permissions", "rw"))})
    return out


def config_file(printer: Printer, path: str) -> bytes:
    """One file from the printer's config folder, whole. One that isn't there any more raises MoonrakerError("not_found")."""
    bases = printer.moonraker_urls
    if not bases:
        raise MoonrakerError("no_address", "This printer has no IP address or Moonraker address set.")
    r, _ = printer_http.request_first_answering(
        MoonrakerError, "Moonraker", "moonraker", printer.id, bases, "GET", f"/server/files/config/{quote(path)}",
        transport=transport, headers=_headers(printer),
    )
    _check_allowed(r)
    if r.status_code >= 400:
        raise MoonrakerError("bad_response", f"Moonraker answered {r.status_code}: {_error_text(r)}")
    return r.content


HISTORY_PAGE = 200
HISTORY_MAX_JOBS = 100_000  # a guard against a Moonraker that never stops paging


def database_dump(printer: Printer) -> dict[str, dict]:
    """
    What the printer's Moonraker keeps in its database, for a backup: {"history": {count, jobs, totals,
    auxiliary_totals}} with every job it remembers (oldest first), plus one entry per namespace it lets be read
    (Mainsail's settings, maintenance, timelapse...). A namespace Moonraker won't hand out is left out.
    """
    jobs: list = []
    while len(jobs) < HISTORY_MAX_JOBS:
        page = call(printer, "GET", "/server/history/list", params={"limit": HISTORY_PAGE, "start": len(jobs), "order": "asc"})
        got = page.get("jobs") or []
        jobs.extend(got)
        if len(got) < HISTORY_PAGE:
            break
    totals, aux = history_totals(printer)
    out: dict[str, dict] = {"history": {"count": len(jobs), "jobs": jobs, "totals": totals, "auxiliary_totals": aux}}
    try:
        listed = call(printer, "GET", "/server/database/list")
    except MoonrakerError as e:
        if e.kind != "not_found":
            raise
        return out
    names = listed.get("namespaces") if isinstance(listed, dict) else listed
    for ns in names if isinstance(names, list) else []:
        if not isinstance(ns, str) or ns == "history":
            continue
        try:
            item = call(printer, "GET", "/server/database/item", params={"namespace": ns})
        except MoonrakerError as e:
            if e.kind in ("unreachable", "no_address"):
                raise
            continue  # a namespace kept to Moonraker itself (it answers 403, as it does to a missing API key)
        out[ns] = {"namespace": ns, "value": item.get("value") if isinstance(item, dict) else item}
    return out


def config_root(printer: Printer) -> str:
    """Where the printer's config folder is on its computer, as Moonraker says (/home/pi/printer_data/config)."""
    for root in call(printer, "GET", "/server/files/roots") or []:
        if isinstance(root, dict) and root.get("name") == "config" and root.get("path"):
            return str(root["path"])
    raise MoonrakerError("bad_response", "Moonraker didn't say where its config folder is.")


def backup_database(printer: Printer, filename: str) -> str:
    """Have Moonraker save a copy of its database (made safely while it runs) in its backup/database folder, as
    `filename`. Returns the copy's path on the printer. not_found: a Moonraker too old to do it."""
    answer = call(printer, "POST", "/server/database/backup", json={"filename": filename})
    path = answer.get("backup_path") if isinstance(answer, dict) else None
    if not path:
        raise MoonrakerError("bad_response", "Moonraker didn't say where it saved the database copy.")
    return str(path)


def restore_database(printer: Printer, filename: str) -> dict:
    """Have Moonraker replace its database with a copy in its backup/database folder. Moonraker restarts itself after."""
    answer = call(printer, "POST", "/server/database/restore", json={"filename": filename}, timeout=UPLOAD_TIMEOUT)
    return answer if isinstance(answer, dict) else {}


def database_namespace(printer: Printer, namespace: str) -> dict:
    """Everything a namespace of Moonraker's database holds now ({} when it has none yet)."""
    try:
        item = call(printer, "GET", "/server/database/item", params={"namespace": namespace})
    except MoonrakerError as e:
        if e.kind == "not_found":
            return {}
        raise
    value = item.get("value") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else {}


def put_database_item(printer: Printer, namespace: str, key: str, value) -> None:
    """Write one item of a namespace of Moonraker's database (Mainsail's settings, maintenance...), replacing it."""
    call(printer, "POST", "/server/database/item", json={"namespace": namespace, "key": key, "value": value})


def put_config_file(printer: Printer, path: str, data: bytes) -> None:
    """Write a file into the printer's config folder (replacing the one there), at `path` ("macros/start.cfg")."""
    folder, _, name = path.rpartition("/")
    fields = {"root": "config"}
    if folder:
        fields["path"] = folder
    call(printer, "POST", "/server/files/upload", files={"file": (name, data)}, data=fields, timeout=UPLOAD_TIMEOUT, unwrapped=True)


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


def system_info(printer: Printer) -> dict | None:
    """/machine/system_info's system_info (the board, the services Moonraker watches and their state), or None when it
    won't say (an older Moonraker, or one that can't be reached)."""
    try:
        info = call(printer, "GET", "/machine/system_info")["system_info"]
    except (MoonrakerError, KeyError, TypeError):
        return None
    return info if isinstance(info, dict) else None


def board(printer: Printer) -> dict | None:
    """
    The computer Klipper runs on, as /machine/system_info describes it: {name, model, memory_gb}. name is short, the
    way it's spoken of ("Pi 4", "CM4"); model is the board's own words ("Raspberry Pi Compute Module 4 Rev 1.1").
    None when it won't say (an older Moonraker, or one that can't be reached).
    """
    return board_of(system_info(printer))


def board_of(info: dict | None) -> dict | None:
    """board(), from a system_info already asked for."""
    try:
        cpu = info["cpu_info"]
        model = str(cpu.get("model") or "").strip()
    except (KeyError, TypeError, AttributeError):
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
    addresses made whole: a relative one ("/webcam/?action=stream") is on port 80 of the printer, where Mainsail is,
    and one on either of the printer's IPs is moved to the IP its cameras are reached at (Printer.camera_network).
    """
    listed = call(printer, "GET", "/server/webcams/list").get("webcams") or []
    base = printer.mainsail_url or ""  # at the IP Moonraker just answered at
    out = []
    for cam in listed:
        if cam.get("enabled") is False:
            continue
        stream = printer.on_camera_ip(urljoin(base, cam["stream_url"])) if cam.get("stream_url") else None
        snapshot = printer.on_camera_ip(urljoin(base, cam["snapshot_url"])) if cam.get("snapshot_url") else None
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
