"""
Asking each plugin that's switched on whether it's well, every 30 seconds: GET <address><its manifest's health path>
(its /manifest when it names none). What's found is kept on its plugin_connection row: running or not_answering, the
last error, and when it last answered. The Plugins page and the plugin's menu page show it.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...periodic import PeriodicWorker
from ...timeutil import utc_now
from . import registry, remote

log = logging.getLogger("farmhand.plugins")

EVERY = 30.0


def check(db: Session, plugin) -> str | None:
    """Ask one plugin now and keep what's found; None when it's well, else why not."""
    link = registry.connection_of(plugin)
    error = remote.check_health(link.address, (plugin.manifest or {}).get("health"))
    now = utc_now()
    if error is None:
        link.health, link.last_error, link.last_seen_at = "running", None, now
    else:
        if link.health != "not_answering":
            log.info("The %s plugin isn't answering: %s", plugin.id, error)
        link.health, link.last_error = "not_answering", error
    link.checked_at = now
    db.commit()
    return error


def check_all(db: Session) -> None:
    for plugin in registry.all_plugins(db):
        if plugin.enabled:
            check(db, plugin)


class HealthWorker(PeriodicWorker):
    name, failure, log = "plugin-health", "Checking the plugins failed", log

    def __init__(self):
        super().__init__(interval=EVERY, first_wait=5)

    def run_once(self) -> None:
        with SessionLocal() as db:
            check_all(db)


worker = HealthWorker()
