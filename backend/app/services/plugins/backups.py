"""
A copy of a plugin's own settings, kept with Farmhand's (stream:backup, docs/plugins.md "Keeping a copy of your
settings"): the plugin sends it through the plugin API with its token whenever its settings change (PUT /backup), and
Farmhand keeps the latest (plugin_backup, by the plugin's id, so removing the plugin and adding it again keeps it) and
writes it to the settings folder beside farmhand-config.json (plugin-backups/<id>.json), which Load all settings reads
back on a new Farmhand. A stream plugin's has its stream key and sign-in in it, as the printers' files have their
API keys: the settings folder is the operator's own.

Restoring (the Plugins page's Restore settings): Farmhand POSTs {saved_at} to the manifest's backup restore path, which
carries nothing secret, and the plugin fetches its copy itself (GET /backup, with its token).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import storage
from ...errors import NotFound
from ...models import Plugin, PluginBackup
from ...timeutil import utc_iso, utc_now
from . import registry, remote

log = logging.getLogger("farmhand")

FORMAT = 1
MOST = 2 * 1024 * 1024  # bytes of settings a plugin may keep here
FOLDER = "plugin-backups"  # in the settings folder
RESTORE_TIMEOUT = 30.0


def checked(body) -> dict:
    """A backup as a plugin sends it, checked: {"format": 1, "saved_at": "...", "settings": {"<key>": "<value>"}}."""
    if not isinstance(body, dict) or body.get("format") != FORMAT:
        raise ValueError(f"A plugin's settings copy must be {{\"format\": {FORMAT}, \"saved_at\": ..., \"settings\": {{...}}}}.")
    settings = body.get("settings")
    if not isinstance(settings, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in settings.items()):
        raise ValueError("A plugin's settings copy's settings must be an object of text values.")
    saved_at = body.get("saved_at")
    if not isinstance(saved_at, str) or not 1 <= len(saved_at) <= 40:
        raise ValueError("A plugin's settings copy needs saved_at, the time it was made.")
    data = json.dumps(settings, ensure_ascii=False, sort_keys=True)
    if len(data.encode("utf-8")) > MOST:
        raise ValueError(f"A plugin's settings copy may be at most {MOST // (1024 * 1024)} MB.")
    return {"saved_at": saved_at, "data": data}


def save(db: Session, plugin_id: str, body) -> dict:
    """Keep the plugin's newest copy of its settings: {saved_at} as kept. ValueError for one that isn't one."""
    got = checked(body)
    row = db.get(PluginBackup, plugin_id)
    if row is None:
        row = PluginBackup(plugin_id=plugin_id, data=got["data"], saved_at=got["saved_at"])
        db.add(row)
    else:
        row.data, row.saved_at, row.received_at = got["data"], got["saved_at"], utc_now()
    db.commit()
    return {"saved_at": row.saved_at}


def get(db: Session, plugin_id: str) -> dict:
    """The plugin's copy, as it sent it. NotFound while there's none."""
    row = db.get(PluginBackup, plugin_id)
    if row is None:
        raise NotFound("Farmhand has no copy of this plugin's settings yet.")
    return {"format": FORMAT, "saved_at": row.saved_at, "settings": json.loads(row.data)}


def summary(db: Session, plugin_id: str) -> dict | None:
    """What the Plugins page shows of it: {saved_at, received_at, size (bytes)}; None while there's none."""
    row = db.get(PluginBackup, plugin_id)
    if row is None:
        return None
    return {"saved_at": row.saved_at, "received_at": utc_iso(row.received_at), "size": len(row.data.encode("utf-8"))}


# ------------------------------------------------------------------ in the settings folder


def _document(row: PluginBackup) -> str:
    return json.dumps({"plugin_id": row.plugin_id, "format": FORMAT, "saved_at": row.saved_at,
                       "settings": json.loads(row.data)}, ensure_ascii=False, indent=1, sort_keys=True)


def write_all(db: Session, folder: Path) -> None:
    """Each plugin's copy written to the settings folder (plugin-backups/<id>.json), only when it changed."""
    rows = list(db.scalars(select(PluginBackup)))
    if not rows:
        return
    d = Path(folder) / FOLDER
    d.mkdir(exist_ok=True)
    for row in rows:
        path, text = d / f"{row.plugin_id}.json", _document(row)
        try:
            if path.read_text(encoding="utf-8") == text:
                continue
        except OSError:
            pass
        storage.write_text_atomically(path, text)


def read_all(db: Session, folder: Path) -> list[str]:
    """The copies in the settings folder taken in (Load all settings), each one this Farmhand has none of, or an older
    one: the ids of those taken in."""
    d = Path(folder) / FOLDER
    taken = []
    try:
        files = sorted(d.glob("*.json"))
    except OSError:
        return taken
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            plugin_id = doc.get("plugin_id") if isinstance(doc, dict) else None
            if plugin_id != path.stem:
                continue
            got = checked(doc)
        except (OSError, ValueError) as e:
            log.info("The plugin settings copy %s wasn't read: %s", path, e)
            continue
        row = db.get(PluginBackup, plugin_id)
        if row is not None and row.saved_at >= got["saved_at"]:
            continue
        if row is None:
            db.add(PluginBackup(plugin_id=plugin_id, data=got["data"], saved_at=got["saved_at"]))
        else:
            row.data, row.saved_at, row.received_at = got["data"], got["saved_at"], utc_now()
        taken.append(plugin_id)
    db.commit()
    return taken


# ------------------------------------------------------------------ given back


def restore(db: Session, plugin_id: str) -> dict:
    """Give a plugin its copy back: Farmhand asks it to fetch it (the manifest's backup restore path). Its answer
    ({restored, saved_at, note}). NotFound with no copy; ValueError (in plain words) when it can't be done."""
    plugin: Plugin = registry.get(db, plugin_id)
    restore_path = ((plugin.manifest or {}).get("backup") or {}).get("restore")
    if not restore_path:
        raise ValueError(f"{plugin.name} doesn't say how to take its settings back (this version of it can't).")
    if not plugin.enabled:
        raise ValueError(f"{plugin.name} is switched off. Switch it on first.")
    if "stream:backup" not in registry.granted(plugin):
        raise ValueError(f"{plugin.name} hasn't been given the stream:backup permission, so it can't fetch its settings. Allow it first.")
    row = db.get(PluginBackup, plugin_id)
    if row is None:
        raise NotFound(f"Farmhand has no copy of {plugin.name}'s settings yet.")
    address, saved_at = registry.connection_of(plugin).address, row.saved_at
    db.commit()  # (its database connection let go while the plugin is asked)
    try:
        with httpx.Client(transport=remote.transport, timeout=RESTORE_TIMEOUT, follow_redirects=False) as client:
            r = client.post(f"{address}{restore_path}", json={"saved_at": saved_at}, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise ValueError(remote.unreachable(address, e)) from None
    try:
        body = r.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    if not 200 <= r.status_code < 300:
        said = body.get("detail") if isinstance(body.get("detail"), str) else None
        raise ValueError(said or f"{plugin.name} answered {r.status_code} when asked to take its settings back.")
    log.info("The %s plugin took back its settings from %s", plugin_id, saved_at)
    return {"restored": body.get("restored") is True, "saved_at": body.get("saved_at") or saved_at,
            "note": body.get("note") if isinstance(body.get("note"), str) else None}
