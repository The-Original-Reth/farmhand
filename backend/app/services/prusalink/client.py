"""The HTTP side: requests to a printer's PrusaLink (its local API, version 1), logged in with HTTP digest auth."""
from __future__ import annotations

from typing import BinaryIO, Iterator
from urllib.parse import quote

import httpx

from ... import printer_links
from ...models import Printer
from .. import printer_http
from ..printer_http import TIMEOUT, UPLOAD_TIMEOUT

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


def version(printer: Printer) -> dict:
    """{api, server, text, firmware, printer}: what the printer says it is (e.g. text "PrusaLink", printer "COREONE")."""
    return _json(_call(printer, "GET", "/api/version"))


def status(printer: Printer) -> dict:
    """
    {printer: {state, temp_nozzle, target_nozzle, temp_bed, target_bed, ...}, job: {id, progress, time_remaining,
    time_printing} | missing, storage, transfer}. state is one of IDLE, BUSY, PRINTING, PAUSED, FINISHED, STOPPED,
    ERROR, ATTENTION, READY.
    """
    return _json(_call(printer, "GET", "/api/v1/status"))


def job(printer: Printer) -> dict | None:
    """The current job ({id, state, progress, time_printing, time_remaining, file: {name, display_name, ...}}), or None."""
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


def upload_and_print(printer: Printer, filename: str, data: bytes | BinaryIO, size: int | None = None) -> str:
    """
    Put the file on the printer (replacing one of the same name) and start printing it. Returns where it went.
    data: the bytes, or an open file read from where it is now (with its size): streamed a piece at a time, so a big
    G-code is never held in memory whole.
    """
    storage = _storage(printer)
    path = f"/api/v1/files/{quote(storage)}/{quote(filename)}"
    headers = {"Content-Type": "application/octet-stream", "Print-After-Upload": "?1", "Overwrite": "?1"}
    if not isinstance(data, bytes):
        headers["Content-Length"] = str(size)  # PrusaLink wants the length up front, not a chunked upload
        data = FileChunks(data)
    _call(printer, "PUT", path, content=data, timeout=UPLOAD_TIMEOUT, headers=headers)
    return f"{storage}/{filename}"
