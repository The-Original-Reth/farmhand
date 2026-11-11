"""
What the stream reads of Farmhand, through the plugin API, and only that: the cameras' addresses (cameras:read) and each
printer's print, for the words under its camera (prints:read). Neither ever holds the picture up: calls wait a few
seconds at most, the cameras fall back to what was last heard (sources.py keeps it), and a printer whose print can't
be asked has just its name written under its camera.
"""
from __future__ import annotations

import time

from . import config
from .farmhand import Farmhand, FarmhandError


QUICK = 5  # seconds a call made while going live (or for the words) may take
_last_problem: dict = {"error": None, "at": None}


def client(timeout: float = QUICK) -> Farmhand:
    return Farmhand(config.settings.farmhand_url, config.settings.farmhand_token, timeout=timeout)


def _noted(e: FarmhandError | None) -> None:
    _last_problem.update(error=e, at=time.time() if e else None)


def problem() -> FarmhandError | None:
    """What went wrong the last time Farmhand was asked (None: it answered)."""
    return _last_problem["error"]


def cameras(db) -> tuple[dict, str | None]:
    """The farm's cameras by printer id (sources.remember), asked of Farmhand now; with Farmhand not answering, what
    was last heard, and why it wasn't asked (for the page)."""
    from .live_stream.sources import known, remember  # (not at the top: the engine imports this module)

    try:
        answer = client().cameras()
    except FarmhandError as e:
        _noted(e)
        return known(db), e.message
    _noted(None)
    return remember(db, answer), None


def print_of(printer_id: int) -> dict | None:
    """A printer's print {state, progress, file, error}, or None when Farmhand couldn't be asked."""
    try:
        got = client().print_of(printer_id)
    except FarmhandError as e:
        _noted(e)
        return None
    _noted(None)
    return got
