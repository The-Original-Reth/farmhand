"""
What plugins hear on GET /plugin-api/v1/events: a print starting, pausing, resuming or finishing, and a printer
becoming reachable or unreachable. Worked out from what Farmhand already sees of its printers (print_progress, asked
by the printer poller every minute and by the Monitor page), never by asking the printers more often.

The first look at a printer only notes how it is: events are changes after that.
"""
from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator

from ...timeutil import utc_iso, utc_now

KEEPALIVE_SECONDS = 15.0  # a comment line this often, so proxies and the plugin know the connection is alive

_lock = threading.Lock()
_last: dict[int, dict] = {}  # printer id -> {"reachable", "state", "file"} as last seen
_listeners: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
_sequence = 0


def listening() -> bool:
    """Whether any plugin is listening: the poller only asks Klipper printers for their print every minute then."""
    return bool(_listeners)


def observe(printer_id: int, printer_name: str, progress: dict) -> None:
    """A fresh look at a printer's print ({state, progress, file, error}, print_progress): tell listeners what changed."""
    now = {"reachable": progress.get("error") is None, "state": progress.get("state"), "file": progress.get("file")}
    with _lock:
        before = _last.get(printer_id)
        _last[printer_id] = now if now["reachable"] else {**(before or now), "reachable": False}
    if before is None:
        return
    base = {"printer_id": printer_id, "printer_name": printer_name}
    if before["reachable"] != now["reachable"]:
        publish("printer.reachable" if now["reachable"] else "printer.unreachable", {**base, "error": progress.get("error")})
    if not now["reachable"]:
        return  # what it's printing isn't known while it can't be asked: not taken as the print ending
    print_fields = {**base, "file": now["file"], "progress": progress.get("progress")}
    was, is_ = before["state"], now["state"]
    if is_ and (was is None or before["file"] != now["file"]):
        if was is not None:
            publish("print.finished", {**base, "file": before["file"], "progress": None})
        publish("print.started", print_fields)
        if is_ == "paused":
            publish("print.paused", print_fields)
    elif was == "printing" and is_ == "paused":
        publish("print.paused", print_fields)
    elif was == "paused" and is_ == "printing":
        publish("print.resumed", print_fields)
    elif was is not None and is_ is None:
        publish("print.finished", {**base, "file": before["file"], "progress": None})


def publish(kind: str, data: dict) -> None:
    global _sequence
    with _lock:
        _sequence += 1
        event = {"id": _sequence, "type": kind, "at": utc_iso(utc_now()), **data}
        listeners = list(_listeners)
    for loop, queue in listeners:
        try:
            loop.call_soon_threadsafe(_offer, queue, event)
        except RuntimeError:  # its loop has closed: it's gone
            with _lock:
                _listeners.discard((loop, queue))


def _offer(queue: asyncio.Queue, event: dict) -> None:
    """A listener that has stopped reading (1000 events behind) misses events rather than holding them all."""
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass


def frame(event: dict) -> str:
    """One server-sent event, as written on the wire."""
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


async def stream(keepalive: float = KEEPALIVE_SECONDS) -> AsyncIterator[str]:
    """Server-sent events for one listener, until it goes away."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    entry = (asyncio.get_running_loop(), queue)
    with _lock:
        _listeners.add(entry)
    try:
        yield ": connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=keepalive)
            except asyncio.TimeoutError:
                yield ": still here\n\n"
                continue
            yield frame(event)
    finally:
        with _lock:
            _listeners.discard(entry)


def reset() -> None:
    """Forget every printer and listener (tests)."""
    global _sequence
    with _lock:
        _last.clear()
        _listeners.clear()
        _sequence = 0
