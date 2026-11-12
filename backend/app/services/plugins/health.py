"""
Asking each plugin that's switched on whether it's well, every 30 seconds: GET <address><its manifest's health path>
(its /manifest when it names none). What's found is kept on its plugin_connection row: running, unwell (it answered,
but not 2xx: it's running and says what's wrong) or not_answering, the last error, and when it last answered. The Plugins page and the plugin's menu page show it.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...periodic import PeriodicWorker
from ...timeutil import utc_now
from . import manifest as manifests
from . import registry, remote

log = logging.getLogger("farmhand.plugins")

EVERY = 30.0


def check(db: Session, plugin) -> str | None:
    """Ask one plugin now and keep what's found; None when it's well, else why not."""
    link = registry.connection_of(plugin)
    state, error = remote.check_health(link.address, (plugin.manifest or {}).get("health"))
    now = utc_now()
    if state != "not_answering":
        link.last_seen_at = now  # it answered, well or not
    if error and (state, error) != (link.health, link.last_error):
        log.info("The %s plugin is %s: %s", plugin.id, state.replace("_", " "), error)
    link.health, link.last_error, link.checked_at = state, error, now
    if state == "running":
        refresh_manifest(plugin, link.address)
    db.commit()
    return error


def refresh_manifest(plugin, address: str) -> bool:
    """
    The plugin's manifest read again, so a new name, menu entry or version (a plugin updated where it runs) shows in
    Farmhand without adding it again. Kept only when it is still the same plugin, on the same plugin API, asking for no
    permission it didn't ask for before (a new one needs the operator's yes: add it again). True when something changed.
    """
    try:
        found = manifests.check(remote.fetch_manifest(address))
    except ValueError:
        return False  # (the health check says what's wrong, if anything)
    asked = set((plugin.manifest or {}).get("permissions") or [])
    same = found["id"] == plugin.id and found["farmhand_api"] == plugin.farmhand_api
    if not same or not set(found["permissions"]) <= asked or found == plugin.manifest:
        return False
    if (found["name"], found["version"]) != (plugin.name, plugin.version):
        log.info("The %s plugin is now %s %s", plugin.id, found["name"], found["version"])
    plugin.name, plugin.version, plugin.manifest = found["name"], found["version"], found
    return True


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
