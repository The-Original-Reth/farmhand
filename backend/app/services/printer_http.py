"""
What talking to a printer over HTTP has in common, Moonraker or PrusaLink: how long to wait, the error with its kind,
and turning a printer that doesn't answer (or isn't there) into that error. Each client adds its own login, its own
answers to a refusal, and reads its own replies.
"""
from __future__ import annotations

import httpx

TIMEOUT = httpx.Timeout(6.0, connect=3.0)
UPLOAD_TIMEOUT = httpx.Timeout(600.0, connect=5.0)  # a big G-code over the printer's network takes a while


class PrinterLinkError(Exception):
    """
    A printer that couldn't be asked, or didn't answer as it should. `kind` says which (each client lists its own).
    `never_sent`: the request didn't reach the printer at all (no connection could be made), so it's safe to ask again
    somewhere else; a request that timed out waiting for an answer may have been carried out.
    """

    def __init__(self, kind: str, message: str, *, never_sent: bool = False):
        super().__init__(message)
        self.kind = kind
        self.never_sent = never_sent


def request_first_answering(
    error: type[PrinterLinkError], label: str, bases: list[str], answered: dict, key, method: str, path: str, **kwargs,
) -> tuple[httpx.Response, str]:
    """
    One request to a printer that may answer at more than one address (`bases`, in the order to try: its wired IP, then
    its Wi-Fi one). The address it answered at last (`answered[key]`) is tried first, so one that's down isn't waited
    on every time. The next address is only tried when this one couldn't be reached at all (`never_sent`): a request
    that got there and then went quiet may have been carried out (a print started), and mustn't happen twice. Returns
    the answer and the address it came from, and notes that address in `answered`.
    """
    last = answered.get(key)
    if last in bases:
        bases = [last, *(b for b in bases if b != last)]
    for i, base in enumerate(bases):
        try:
            r = request(error, label, base, method, path, **kwargs)
        except PrinterLinkError as e:
            if e.never_sent and i < len(bases) - 1:
                continue
            raise
        answered[key] = base
        return r, base
    raise AssertionError("unreachable: bases is never empty here")


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
    except httpx.TimeoutException as e:
        raise error("unreachable", f"{label} at {base} didn't answer in time. Is the printer on?",
                    never_sent=isinstance(e, httpx.ConnectTimeout)) from None
    except httpx.HTTPError as e:
        raise error("unreachable", f"Couldn't connect to {label} at {base} ({type(e).__name__}).",
                    never_sent=isinstance(e, httpx.ConnectError)) from None
    if r.status_code == 404:
        raise error("not_found", f"Not found on {label}.")
    return r
