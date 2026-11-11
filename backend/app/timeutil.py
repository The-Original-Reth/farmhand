"""Times as Farmhand keeps them: always UTC. SQLite hands them back without a timezone, Postgres with one."""
from __future__ import annotations

import datetime as dt


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def as_utc(value: dt.datetime) -> dt.datetime:
    """A stored time with its timezone said: one without is UTC (that's how it was stored)."""
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def utc_iso(value: dt.datetime | None) -> str | None:
    """A time as ISO text that browsers read right (it always carries its offset); None stays None."""
    return as_utc(value).isoformat() if value is not None else None
