"""
Which of a printer's addresses it answered at last. A printer on a cable and Wi-Fi answers at both its IPs: Farmhand
talks to it over the cable (its wired IP comes first), and over Wi-Fi only when the wired IP can't be reached. Every
way of reaching a printer reads this: its requests (printer_http.request_first_answering), the addresses the page is
given for it (its Mainsail / PrusaLink button, its cameras), so they all use the same IP.

A fall back to Wi-Fi isn't for good: after RECHECK_WIRED seconds the wired IP is tried first again, so a cable plugged
back in is used again. Kept in memory only: a restart starts again from the wired IP.
"""
from __future__ import annotations

import time

RECHECK_WIRED = 120.0  # seconds a fall back to the Wi-Fi IP lasts before the wired IP is tried first again

# (kind of link, printer id) -> (the address that answered, when)
_answered: dict[tuple[str, int], tuple[str, float]] = {}


def remember(kind: str, printer_id, base: str) -> None:
    """`base` (one of the printer's addresses, e.g. http://10.0.6.21:7125) answered just now."""
    if printer_id is not None:
        _answered[(kind, printer_id)] = (base, time.monotonic())


def answered(kind: str, printer_id, bases: list[str]) -> str | None:
    """The address it answered at last, while that still counts (one of `bases`, and a backup only for a while)."""
    base, when = _answered.get((kind, printer_id), (None, 0.0))
    if base not in bases:
        return None
    if base != bases[0] and time.monotonic() - when >= RECHECK_WIRED:
        return None  # it's been on the backup a while: the wired one gets asked first again
    return base


def in_order(kind: str, printer_id, bases: list[str]) -> list[str]:
    """`bases` (wired first) in the order to try now: the one it answered at last first, while that counts."""
    last = answered(kind, printer_id, bases)
    return [last, *(b for b in bases if b != last)] if last else list(bases)


def current(kind: str, printer_id, bases: list[str]) -> str | None:
    """The address to give out for it now: the one it answered at last, else the first (its wired IP)."""
    return answered(kind, printer_id, bases) or (bases[0] if bases else None)
