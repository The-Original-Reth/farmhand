"""
Stream control's schedule: times the stream plugins go live and stop on their own, in the farm's time zone (the one
its browser last told Farmhand, Settings). Kept as an app_settings row (SCHEDULE_KEY):

    {"on": true, "entries": [{"days": [0, 1, 2, 3, 4], "start": "08:00", "stop": "18:00", "streams": "all"}]}

days are Monday (0) to Sunday (6); `start` or `stop` may be left out (null) for an entry that only starts or only
stops; `streams` is "all" or a list of stream plugins' ids. A stop earlier than its start is the next morning's.

The worker looks every 30 seconds for the starts and stops that have come round since it last looked, so each one
happens once; one missed while Farmhand was down more than a few minutes is let go (it's not done late). It rests
while Stream control is switched off or the schedule is.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading

from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...periodic import PeriodicWorker
from ...timeutil import utc_iso, utc_now
from .. import app_settings, config_service
from ..energy import zone
from . import enabled, streams

log = logging.getLogger("farmhand.stream_control")

SCHEDULE_KEY = "stream_control_schedule"
MAX_ENTRIES = 50
TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
LATE_MOST = dt.timedelta(minutes=5)  # a start or stop missed by more than this (Farmhand was down) isn't done late
KEPT_HAPPENINGS = 20


def schedule(db: Session) -> dict:
    """{on, entries: [{days, start, stop, streams}]} as kept (anything unusable left out)."""
    try:
        raw = json.loads(app_settings.get(db, SCHEDULE_KEY) or "{}")
    except ValueError:
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    entries = []
    for e in raw.get("entries") or []:
        try:
            entries.append(_entry(e))
        except ValueError:
            continue
    return {"on": raw.get("on") is True, "entries": entries[:MAX_ENTRIES]}


def _entry(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("A schedule entry didn't come through.")
    days = raw.get("days")
    if not isinstance(days, list) or not days or not all(type(d) is int and 0 <= d <= 6 for d in days):
        raise ValueError("Choose at least one day for each time in the schedule.")
    times = {}
    for name, what in (("start", "going live"), ("stop", "stopping")):
        v = raw.get(name)
        if v in (None, ""):
            times[name] = None
        elif isinstance(v, str) and TIME.match(v):
            times[name] = v
        else:
            raise ValueError(f"The time for {what} has to be a time of day, like 08:00.")
    if times["start"] is None and times["stop"] is None:
        raise ValueError("Each time in the schedule needs a time to go live, a time to stop, or both.")
    if times["start"] == times["stop"]:
        raise ValueError("A time in the schedule can't go live and stop at the same moment.")
    which = raw.get("streams", "all")
    if which != "all":
        if not isinstance(which, list) or not which or not all(isinstance(s, str) and 0 < len(s) <= 40 for s in which):
            raise ValueError("Choose which streams each time in the schedule is for, or all of them.")
        which = list(dict.fromkeys(which))
    return {"days": sorted(set(days)), "start": times["start"], "stop": times["stop"], "streams": which}


def save(db: Session, raw) -> dict:
    """Keep this schedule ({on, entries}); ValueError says what's wrong with it."""
    if not isinstance(raw, dict) or not isinstance(raw.get("entries", []), list):
        raise ValueError("The schedule didn't come through.")
    if len(raw.get("entries") or []) > MAX_ENTRIES:
        raise ValueError(f"The schedule can have up to {MAX_ENTRIES} times.")
    kept = {"on": raw.get("on") is True, "entries": [_entry(e) for e in raw.get("entries") or []]}
    app_settings.put(db, SCHEDULE_KEY, json.dumps(kept))
    db.commit()
    return schedule(db)


def farm_zone(db: Session):
    return zone(config_service.get_config(db)["preferences"].get("time_zone"))


def due(entries: list[dict], since: dt.datetime, now: dt.datetime, tz) -> list[tuple[str, dict]]:
    """[(action "start" | "stop", entry)] for each start and stop that came round after `since`, up to `now` (aware
    datetimes), in the order they came round. A stop earlier than its entry's start is on the next day."""
    found: list[tuple[dt.datetime, str, dict]] = []
    first, last = since.astimezone(tz).date() - dt.timedelta(days=1), now.astimezone(tz).date()
    day = first
    while day <= last:
        for e in entries:
            if day.weekday() not in e["days"]:
                continue
            for action in ("start", "stop"):
                if not e[action]:
                    continue
                h, m = map(int, e[action].split(":"))
                when_day = day + dt.timedelta(days=1) if action == "stop" and e["start"] and e["stop"] < e["start"] else day
                when = dt.datetime.combine(when_day, dt.time(h, m), tzinfo=tz)
                if since < when <= now:
                    found.append((when, action, e))
        day += dt.timedelta(days=1)
    found.sort(key=lambda f: (f[0], f[1] == "start"))  # a stop and a start at the same minute: the stop first
    return [(action, e) for _, action, e in found]


# What the schedule did lately, newest first: [{at, action, streams, results: [{name, live, error}]}] (kept in memory)
_happened: list[dict] = []
_lock = threading.Lock()


def happened() -> list[dict]:
    with _lock:
        return list(_happened)


def _do(db: Session, action: str, entry: dict) -> None:
    results = []
    for s in streams.listed(db):
        if not s["chosen"] or (entry["streams"] != "all" and s["id"] not in entry["streams"]):
            continue  # (one left out of Stream control is never started or stopped from here)
        if not s["enabled"]:
            results.append({"name": s["name"], "live": False, "error": f"{s['name']} is switched off."})
            continue
        try:
            done = streams.start_or_stop(db, s["id"], action)
        except ValueError as e:
            done = {"name": s["name"], "live": None, "error": str(e)}
        results.append({"name": done["name"], "live": done.get("live"), "error": done.get("error")})
        if done.get("error"):
            log.info("Stream control's schedule: %s %s: %s", action, done["name"], done["error"])
    with _lock:
        _happened.insert(0, {"at": utc_iso(utc_now()), "action": action, "streams": entry["streams"], "results": results})
        del _happened[KEPT_HAPPENINGS:]


class ScheduleWorker(PeriodicWorker):
    name, failure, log = "stream-schedule", "Stream control's schedule failed", log

    def __init__(self):
        super().__init__(interval=30, first_wait=30)
        self.last: dt.datetime | None = None

    def run_once(self) -> None:
        now = utc_now()
        # (the first look covers the wait since starting; starting a stream that's live already does nothing)
        since = max(self.last or now - dt.timedelta(seconds=self.first_wait + 1), now - LATE_MOST)
        self.last = now
        with SessionLocal() as db:
            if not enabled(db):
                return
            kept = schedule(db)
            if not kept["on"] or not kept["entries"]:
                return
            for action, entry in due(kept["entries"], since, now, farm_zone(db)):
                _do(db, action, entry)


worker = ScheduleWorker()
