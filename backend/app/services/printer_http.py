"""
What talking to a printer over HTTP has in common, Moonraker or PrusaLink: how long to wait, the error with its kind,
and turning a printer that doesn't answer (or isn't there) into that error. Each client adds its own login, its own
answers to a refusal, and reads its own replies.
"""
from __future__ import annotations

import httpx

TIMEOUT = httpx.Timeout(6.0, connect=3.0)
UPLOAD_TIMEOUT = httpx.Timeout(600.0, connect=5.0)  # a big G-code over the printer's network takes a while
PROBE_TIMEOUT = httpx.Timeout(1.5, connect=0.5)  # a network scan asks hundreds of addresses; most aren't there


class PrinterLinkError(Exception):
    """A printer that couldn't be asked, or didn't answer as it should. `kind` says which (each client lists its own)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def request(
    error: type[PrinterLinkError], label: str, base: str, method: str, path: str, *,
    transport: httpx.BaseTransport | None, timeout: httpx.Timeout = TIMEOUT, auth: httpx.Auth | None = None, **kwargs,
) -> httpx.Response:
    """
    One request to `label` ("Moonraker", "PrusaLink") at `base`. A printer that doesn't answer in time, can't be
    reached, or says the thing isn't there raises `error`; every other answer comes back for the client to read.
    `transport` is passed in on each call, so the tests' stand-in printer is used whenever it's set.
    """
    try:
        with httpx.Client(timeout=timeout, transport=transport, auth=auth) as client:
            r = client.request(method, f"{base}{path}", **kwargs)
    except httpx.TimeoutException:
        raise error("unreachable", f"{label} at {base} didn't answer in time. Is the printer on?") from None
    except httpx.HTTPError as e:
        raise error("unreachable", f"Couldn't connect to {label} at {base} ({type(e).__name__}).") from None
    if r.status_code == 404:
        raise error("not_found", f"Not found on {label}.")
    return r
