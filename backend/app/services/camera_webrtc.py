"""
Setting up a camera-streamer WebRTC camera's video for the Monitor page, passed on through Farmhand's API.

The browser sets up camera-streamer's WebRTC by POSTing JSON to the camera's stream address (a request, then its
answer and its ICE candidates). Mainsail can, being on the printer itself; Farmhand's page is on another address, and
some printers' web servers (a Snapmaker U1's) refuse a page from elsewhere: no CORS headers, OPTIONS answered 501.
So the page POSTs here and Farmhand passes each message on to the camera and its answer back. Only the set-up goes
through Farmhand: the video itself goes straight from the printer to the browser.

Only to a camera the printer's Moonraker lists as camera-streamer WebRTC, at the address it gives: nothing else can
be reached through this.
"""
from __future__ import annotations

import json
import time

import httpx

from ..models import Printer
from . import moonraker as mr
from .moonraker import client as mr_client

SERVICE = "webrtc-camerastreamer"
TIMEOUT = httpx.Timeout(5.0, connect=2.0)
KEEP_SECONDS = 60.0  # how long a camera's address is kept: a set-up POSTs several times (each ICE candidate)
MAX_BODY = 64 * 1024  # a request, an answer or a few candidates: a few KB

# (printer id, camera name) -> (its stream address, when it was found)
_found: dict[tuple[int, str], tuple[str, float]] = {}


class WebrtcError(Exception):
    """What went wrong, said plainly. status: the HTTP status to answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def signal_path(printer_id: int, cam: dict) -> str | None:
    """Where the page POSTs a camera-streamer camera's set-up (on Farmhand's API), or None for any other camera."""
    if cam.get("service") != SERVICE or not cam.get("stream_url"):
        return None
    from urllib.parse import quote

    return f"/printers/{printer_id}/webcams/webrtc?name={quote(cam['name'], safe='')}"


def _stream_url(printer: Printer, name: str) -> str:
    key = (printer.id, name)
    kept = _found.get(key)
    if kept and time.monotonic() - kept[1] < KEEP_SECONDS:
        return kept[0]
    cam = next((c for c in mr.webcams(printer) if c["name"] == name), None)
    if cam is None or cam["service"] != SERVICE or not cam.get("stream_url"):
        raise WebrtcError(404, f"{printer.name} has no WebRTC (camera-streamer) camera called {name!r}.")
    _found[key] = (cam["stream_url"], time.monotonic())
    return cam["stream_url"]


def signal(printer: Printer, name: str, body: bytes) -> dict:
    """POST one set-up message to the camera; its JSON answer ({} when it sends none, as for a candidate)."""
    if len(body) > MAX_BODY:
        raise WebrtcError(413, "That's too much for a camera's WebRTC set-up.")
    try:
        message = json.loads(body or b"{}")
    except ValueError:
        raise WebrtcError(422, "The camera's WebRTC set-up must be JSON.") from None
    url = _stream_url(printer, name)
    try:
        with httpx.Client(timeout=TIMEOUT, transport=mr_client.transport) as http:
            r = http.post(url, json=message)
    except httpx.HTTPError:
        _found.pop((printer.id, name), None)  # it may have moved IP: ask Moonraker again next time
        raise WebrtcError(502, f"{printer.name}'s camera can't be reached at {url}.") from None
    if r.status_code >= 400:
        raise WebrtcError(502, f"{printer.name}'s camera answered {r.status_code} to its WebRTC set-up.")
    if not r.content.strip():
        return {}
    try:
        answer = r.json()
    except ValueError:
        raise WebrtcError(502, f"{printer.name}'s camera didn't answer its WebRTC set-up like camera-streamer does.") from None
    if isinstance(answer, dict) and answer.get("error"):  # camera-streamer says no with a 200 and {"error": ...}
        if "max clients" in str(answer["error"]):
            raise WebrtcError(503, f"{printer.name}'s camera already has as many viewers as it takes. Close another page "
                                   "showing it, or wait a minute for one that's gone to be let go.")
        raise WebrtcError(502, f"{printer.name}'s camera turned down its WebRTC set-up: {answer['error']}")
    return answer if isinstance(answer, dict) else {"answer": answer}
