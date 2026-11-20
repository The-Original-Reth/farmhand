"""The HTTP side: requests to a printer's PrusaLink (its local API, version 1), logged in with HTTP digest auth."""
from __future__ import annotations

from typing import BinaryIO, Iterator
from urllib.parse import quote

import httpx

from ... import printer_links
from ...models import Printer
from .. import printer_http
from ..printer_http import PROBE_TIMEOUT, TIMEOUT, UPLOAD_TIMEOUT


def job_file_name(job: dict) -> str | None:
    """The name of the file a PrusaLink job is printing, as the printer shows it."""
    file = job.get("file") or {}
    return file.get("display_name") or file.get("name")

# Tests swap this for an httpx.MockTransport that plays a fake PrusaLink
transport: httpx.BaseTransport | None = None


class PrusaLinkError(printer_http.PrinterLinkError):
    """kind: no_address | unreachable | unauthorized | not_found | busy | bad_response"""


def answered_at(printer: Printer) -> str | None:
    """The address the printer's PrusaLink answered at last, while that counts (see printer_links)."""
    return printer_links.answered("prusalink", printer.id, printer.prusalink_urls)


def _call(printer: Printer, method: str, path: str, *, content: bytes | FileChunks | None = None, headers: dict | None = None,
          timeout: httpx.Timeout = TIMEOUT) -> httpx.Response:
    bases = printer.prusalink_urls
    if not bases:
        raise PrusaLinkError("no_address", "This printer has no IP address or PrusaLink address set.")
    link = printer.prusalink_row
    auth = httpx.DigestAuth(link.username or "maker", link.password or "") if link and link.password else None
    r, _ = printer_http.request_first_answering(
        PrusaLinkError, "PrusaLink", "prusalink", printer.id, bases, method, path,
        transport=transport, timeout=timeout, auth=auth, content=content, headers=headers,
    )
    if r.status_code == 401:
        raise PrusaLinkError(
            "unauthorized",
            "PrusaLink refused the login. Check the username (usually maker) and the password shown on the printer "
            "under Settings > Network > PrusaLink.",
        )
    if r.status_code == 409:
        raise PrusaLinkError("busy", "The printer is busy (printing, or waiting for someone at it), so it can't do that now.")
    if r.status_code >= 400:
        raise PrusaLinkError("bad_response", f"PrusaLink answered {r.status_code}: {r.text[:200]}")
    return r


def _json(r: httpx.Response) -> dict:
    if r.status_code == 204:
        return {}
    try:
        data = r.json()
    except ValueError:
        raise PrusaLinkError("bad_response", "The printer answered, but not like PrusaLink does.") from None
    if not isinstance(data, dict):
        raise PrusaLinkError("bad_response", "The printer answered, but not like PrusaLink does.")
    return data


def _reported(printer: Printer):
    """printer_reports, when the printer takes its status from a plugin (the Prusa Connect plugin, say) instead of its
    own PrusaLink being asked; else None. Sending it a print always goes to its PrusaLink."""
    if not printer.status_from:
        return None
    from .. import printer_reports

    return printer_reports


def version(printer: Printer) -> dict:
    """{api, server, text, firmware, printer}: what the printer says it is (e.g. text "PrusaLink", printer "COREONE")."""
    if reports := _reported(printer):
        return reports.version(printer, PrusaLinkError)
    return _json(_call(printer, "GET", "/api/version"))


def probe(base: str) -> dict | None:
    """
    Is there a PrusaLink at `base` (e.g. http://192.168.10.129)? Asked without logging in, it turns the question down
    with its digest login, whose realm "Printer API" is Prusa's own, so it's known all the same: {needs_password: True}.
    One that needs no login says what it is: {needs_password: False, hostname, version}. None when nothing there
    answers like PrusaLink (most addresses, and other machines' web pages on port 80).
    """
    try:
        r = printer_http.request(PrusaLinkError, "PrusaLink", base, "GET", "/api/version",
                                 transport=transport, timeout=PROBE_TIMEOUT)
    except PrusaLinkError:
        return None
    if r.status_code == 401:
        said = r.headers.get("www-authenticate", "").lower()
        return {"needs_password": True} if said.startswith("digest") and 'realm="printer api"' in said else None
    if r.status_code != 200:
        return None
    try:
        info = r.json()
    except ValueError:
        return None
    if not isinstance(info, dict) or "prusalink" not in str(info.get("text") or "").lower():
        return None
    return {"needs_password": False, "hostname": info.get("hostname") or None, "version": info.get("server") or None}


def status(printer: Printer) -> dict:
    """
    {printer: {state, temp_nozzle, target_nozzle, temp_bed, target_bed, ...}, job: {id, progress, time_remaining,
    time_printing} | missing, storage, transfer}. state is one of IDLE, BUSY, PRINTING, PAUSED, FINISHED, STOPPED,
    ERROR, ATTENTION, READY.
    """
    if reports := _reported(printer):
        return reports.status(printer, PrusaLinkError)
    return _json(_call(printer, "GET", "/api/v1/status"))


def job(printer: Printer) -> dict | None:
    """The current job ({id, state, progress, time_printing, time_remaining, file: {name, display_name, ...}}), or None."""
    if reports := _reported(printer):
        return reports.job(printer, PrusaLinkError)
    return _json(_call(printer, "GET", "/api/v1/job")) or None


def _storage(printer: Printer) -> str:
    """Where a print can be put: the printer's USB drive on a Core One (the first storage that can be written to)."""
    items = _json(_call(printer, "GET", "/api/v1/storage")).get("storage_list") or []
    usable = [s for s in items if isinstance(s, dict) and s.get("available") and not s.get("read_only") and s.get("path")]
    usable.sort(key=lambda s: s.get("type") != "USB")
    if not usable:
        raise PrusaLinkError("not_found", "The printer has nowhere to put a file. Is its USB drive plugged in?")
    return usable[0]["path"].strip("/")


CHUNK = 1024 * 1024


class FileChunks:
    """
    An open file sent a piece at a time. Each pass starts from the beginning, because the digest login means the
    upload is sent twice: once to be told how to log in, then for real.
    """

    def __init__(self, fileobj: BinaryIO):
        self.fileobj = fileobj

    def __iter__(self) -> Iterator[bytes]:
        self.fileobj.seek(0)
        while chunk := self.fileobj.read(CHUNK):
            yield chunk


FILE_START_MOST = 64 * 1024 * 1024  # never read more of a printed file than this (a .bgcode's settings are near its start)


def printed_file_settings(printer: Printer, path: str, filename: str | None = None) -> tuple[dict, float]:
    """
    The filament settings of a file on the printer, read from the file itself (parsers/gcode.filament_settings), and
    when it was written (PrusaLink's m_timestamp): (settings, modified). See printed_file_details.
    """
    found, _, modified = printed_file_details(printer, path, filename)
    return found, modified


def printed_file_details(printer: Printer, path: str, filename: str | None = None) -> tuple[dict, dict, float]:
    """
    What a file on the printer says of its filament, read from the file itself: (settings, slicer, modified). settings:
    its price, density and diameter (parsers/gcode.filament_settings); slicer: the slicer's estimate for the whole print
    ({filament_mm, filament_g, filament_cost}, parsers/gcode.slicer_filament); modified: when it was written
    (PrusaLink's m_timestamp). Read only: the file's details, then its download, stopped as soon as a .bgcode's
    settings block is in (its estimate comes before it; a .gcode's are at its end: read whole, up to FILE_START_MOST).
    Used for a printer connected through Prusa Connect too, which can't read files on the printer.
    """
    from ...parsers import gcode

    info = _json(_call(printer, "GET", f"/api/v1/files/{quote(path.lstrip('/'), safe='/')}"))
    download = (info.get("refs") or {}).get("download")
    if not download:
        raise PrusaLinkError("not_found", "PrusaLink offers no download of that file.")
    base = answered_at(printer) or (printer.prusalink_urls or [None])[0]
    if not base:
        raise PrusaLinkError("no_address", "This printer has no IP address or PrusaLink address set.")
    link = printer.prusalink_row
    auth = httpx.DigestAuth(link.username or "maker", link.password or "") if link and link.password else None
    name = filename or path  # its full name says what it is: the path may be a short 8.3 one ("FROGKE~1.BGC")
    binary = name.lower().endswith(".bgcode")
    start = bytearray()
    try:
        with httpx.Client(transport=transport, timeout=UPLOAD_TIMEOUT, auth=auth) as c, c.stream("GET", base.rstrip("/") + download) as r:
            if r.status_code == 404:
                raise PrusaLinkError("not_found", "That file isn't on the printer any more.")
            if r.status_code >= 400:
                raise PrusaLinkError("bad_response", f"PrusaLink answered {r.status_code} to reading the file.")
            for chunk in r.iter_bytes():
                start += chunk
                if (binary and gcode.bgcode_settings_in(bytes(start))) or len(start) >= FILE_START_MOST:
                    break
    except httpx.HTTPError as e:
        raise PrusaLinkError("unreachable", f"PrusaLink didn't finish sending the file ({e}).") from None
    import io

    data = io.BytesIO(bytes(start))
    found = gcode.filament_settings(data, name)
    slicer = gcode.slicer_filament(data, name)
    return found, slicer, float(info.get("m_timestamp") or 0)


def upload_and_print(printer: Printer, filename: str, data: bytes | BinaryIO, size: int | None = None) -> str:
    """
    Put the file on the printer (replacing one of the same name) and start printing it. Returns where it went.
    data: the bytes, or an open file read from where it is now (with its size): streamed a piece at a time, so a big
    G-code is never held in memory whole.
    """
    if printer.status_from:  # connected through a plugin (Prusa Connect): it starts the print, not PrusaLink
        from .. import printer_reports

        return printer_reports.hand_over(printer, filename, data, size, PrusaLinkError)
    storage = _storage(printer)
    path = f"/api/v1/files/{quote(storage)}/{quote(filename)}"
    headers = {"Content-Type": "application/octet-stream", "Print-After-Upload": "?1", "Overwrite": "?1"}
    if not isinstance(data, bytes):
        headers["Content-Length"] = str(size)  # PrusaLink wants the length up front, not a chunked upload
        data = FileChunks(data)
    _call(printer, "PUT", path, content=data, timeout=UPLOAD_TIMEOUT, headers=headers)
    return f"{storage}/{filename}"
