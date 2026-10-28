"""
go2rtc, the video relay beside Farmhand: it takes a camera's RTSP stream (a Buddy3D's) and plays it to the browser.
Farmhand tells it which streams there are; the browser then reaches a stream through the web server's /go2rtc/
address, which only lets Farmhand's own streams through (see frontend/nginx.conf).
"""
from __future__ import annotations

import httpx

from ..config import settings

TIMEOUT = httpx.Timeout(4.0, connect=2.0)

# Tests swap this for an httpx.MockTransport that plays a fake go2rtc
transport: httpx.BaseTransport | None = None


class Go2rtcError(Exception):
    pass


def stream_name(printer_id: int) -> str:
    """What a printer's camera is called in go2rtc. nginx lets only names of this shape through."""
    return f"farmhand_{printer_id}"


def rtsp_url(address: str) -> str:
    """A Buddy3D streams at rtsp://<its IP>/live; a whole rtsp:// URL is used as it is."""
    return address if address.lower().startswith(("rtsp://", "rtsps://")) else f"rtsp://{address}/live"


def register(name: str, source: str) -> None:
    """Add the stream to go2rtc, or point it at a new source. Done each time the Monitor page asks for cameras."""
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
            r = client.put(f"{settings.go2rtc_url}/api/streams", params={"name": name, "src": source})
    except httpx.HTTPError as e:
        raise Go2rtcError(f"Farmhand's video relay (go2rtc) isn't answering ({type(e).__name__}). Is its container running?") from None
    if r.status_code >= 400:
        raise Go2rtcError(f"Farmhand's video relay (go2rtc) refused the camera: {r.status_code} {r.text[:200]}")
