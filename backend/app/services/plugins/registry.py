"""
The plugins the operator installed and their tokens: registering one (by its address, where Farmhand fetches its
manifest, or from the manifest itself), listing them, switching one off or on, making a new token, removing one,
knowing a plugin by its token, and the settings copy's list of them (written, and brought back by Load all).

A token is random (secrets.token_urlsafe(32)), kept only as its sha256, and given back once, when it's made. A plugin
has one token at a time: a new one ends the old. A plugin brought back by Load all settings has its permissions but
no token anyone knows (needs_token) until the operator makes one.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...errors import NotFound
from ...models import Plugin, PluginConnection, PluginToken
from ...timeutil import as_utc, utc_iso, utc_now
from . import manifest as manifests
from . import remote

LAST_USED_EVERY = dt.timedelta(minutes=1)  # how often a token's last use is written down (not on every call)


class AlreadyInstalled(ValueError):
    """A plugin with that id is installed already (409)."""


@dataclass(frozen=True)
class Caller:
    """The plugin a plugin API call came from, and what it was granted."""

    plugin_id: str
    permissions: frozenset[str]
    token_hash: str = ""
    # Its address, when the plugin API takes its token only from there ("only accept calls from its address")
    only_from: str | None = None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get(db: Session, plugin_id: str) -> Plugin:
    plugin = db.get(Plugin, plugin_id)
    if plugin is None:
        raise NotFound("Plugin not found")
    return plugin


def all_plugins(db: Session) -> list[Plugin]:
    return list(db.scalars(select(Plugin).order_by(Plugin.name, Plugin.id)))


def preview(db: Session, address) -> dict:
    """What the plugin at this address is, before it's registered: its manifest checked, its permissions in plain words."""
    address = remote.check_address(address)
    checked = manifests.check(remote.fetch_manifest(address))
    return {
        "address": address, "manifest": checked, "permissions_described": manifests.describe(checked["permissions"]),
        "installed": db.get(Plugin, checked["id"]) is not None,
    }


def register_by_address(db: Session, address, granted, only_from_address: bool = True) -> tuple[Plugin, str]:
    """
    Register a plugin that runs at this address (maybe on another machine): its manifest fetched from there and
    checked, the permissions granted (each one it asked for). (plugin, token).
    """
    address = remote.check_address(address)
    raw = remote.fetch_manifest(address)
    plugin, token = register(db, raw, granted, address=address, only_from_address=only_from_address)
    link = plugin.connection
    link.health, link.last_error = "running", None  # it just answered
    link.last_seen_at = link.checked_at = utc_now()
    db.commit()
    return plugin, token


def register(
    db: Session, raw_manifest, granted, image: str | None = None, address: str | None = None,
    only_from_address: bool | None = None,
) -> tuple[Plugin, str]:
    """
    Install a plugin: its manifest checked, the permissions granted (each one it asked for). (plugin, token). With no
    address it's taken to run as a container beside Farmhand, named by its id (http://<id>:<port>). Its token is
    taken only from its address unless asked otherwise, except for one beside Farmhand: those are off by default.
    """
    checked = manifests.check(raw_manifest)
    if db.get(Plugin, checked["id"]) is not None:
        raise AlreadyInstalled(f"A plugin called \"{checked['id']}\" is already installed. Remove it first to install it again.")
    permissions = manifests.check_granted(checked, granted)
    if image is not None and (not isinstance(image, str) or not image.strip() or len(image) > 300):
        raise ValueError("The plugin's image must be a Docker image name, like ghcr.io/someone/plugin:1.0.")
    plugin = Plugin(
        id=checked["id"], name=checked["name"], version=checked["version"], image=image.strip() if image else None,
        farmhand_api=checked["farmhand_api"], enabled=True, manifest=checked,
    )
    plugin.connection = PluginConnection(
        address=remote.check_address(address) if address else f"http://{checked['id']}:{checked['port']}",
        only_from_address=bool(address) if only_from_address is None else bool(only_from_address),
    )
    db.add(plugin)
    token = _new_token(plugin, permissions)
    db.commit()
    return plugin, token


def update(db: Session, plugin_id: str, enabled=None, only_from_address=None, address=None) -> Plugin:
    """
    Switch a plugin off or on (off: its token is refused and its page leaves the menu), whether the plugin API takes
    its token only from its address, or its address (the plugin there must be the same one: its manifest is fetched).
    """
    plugin = get(db, plugin_id)
    link = connection_of(plugin)
    if address is not None:
        address = remote.check_address(address)
        found = manifests.check(remote.fetch_manifest(address))
        if found["id"] != plugin.id:
            raise ValueError(
                f"The plugin at {address} is \"{found['id']}\", not \"{plugin.id}\". To use that one, add it as a plugin "
                "of its own."
            )
        link.address, link.health, link.last_error = address, "running", None
        link.last_seen_at = link.checked_at = utc_now()
    if enabled is not None:
        plugin.enabled = bool(enabled)
    if only_from_address is not None:
        link.only_from_address = bool(only_from_address)
    db.commit()
    return plugin


def new_token(db: Session, plugin_id: str) -> str:
    """A new token for the plugin, with the same permissions; the old one stops working at once."""
    plugin = get(db, plugin_id)
    permissions = granted(plugin)
    plugin.tokens.clear()
    db.flush()
    token = _new_token(plugin, permissions)
    connection_of(plugin).needs_token = False
    db.commit()
    return token


def remove(db: Session, plugin_id: str) -> None:
    """The plugin and its token. (Its container and storage are the plugin manager's, a later step.)"""
    db.delete(get(db, plugin_id))
    db.commit()


def caller(db: Session, token: str | None) -> Caller | None:
    """The plugin this token belongs to, or None for no token, an unknown one, or a plugin that's turned off."""
    if not token:
        return None
    row = db.scalars(select(PluginToken).where(PluginToken.token_hash == hash_token(token))).first()
    if row is None or not row.plugin.enabled:
        return None
    now = utc_now()
    if row.last_used_at is None or now - as_utc(row.last_used_at) >= LAST_USED_EVERY:
        row.last_used_at = now
        db.commit()
    link = row.plugin.connection
    only_from = link.address if link is not None and link.only_from_address else None
    return Caller(row.plugin_id, frozenset(row.permissions or []), row.token_hash, only_from)


def granted(plugin: Plugin) -> list[str]:
    return list(plugin.tokens[0].permissions) if plugin.tokens else []


def health_of(plugin: Plugin) -> dict:
    """How the plugin is doing: state running | not_answering | unknown (not asked yet) | off (switched off)."""
    link = connection_of(plugin)
    return {
        "state": "off" if not plugin.enabled else link.health,
        "last_error": link.last_error, "last_seen_at": utc_iso(link.last_seen_at), "checked_at": utc_iso(link.checked_at),
    }


def out(plugin: Plugin) -> dict:
    """A plugin as the Plugins page shows it. Never its token (only its hash is kept anyway)."""
    token = plugin.tokens[0] if plugin.tokens else None
    permissions = granted(plugin)
    link = connection_of(plugin)
    return {
        "id": plugin.id, "name": plugin.name, "version": plugin.version, "image": plugin.image,
        "farmhand_api": plugin.farmhand_api, "enabled": plugin.enabled,
        "permissions": permissions, "permissions_described": manifests.describe(permissions),
        "manifest": plugin.manifest, "created_at": utc_iso(plugin.created_at),
        "address": link.address, "only_from_address": link.only_from_address, "needs_token": link.needs_token,
        "page": (plugin.manifest or {}).get("page"), "health": health_of(plugin),
        "token_created_at": utc_iso(token.created_at) if token and not link.needs_token else None,
        "token_last_used_at": utc_iso(token.last_used_at) if token else None,
    }


def mirror_entries(db: Session) -> list[dict]:
    """
    What the settings copy keeps of each plugin: where it runs, its manifest, whether it's on and what it was granted.
    Never a token.
    """
    return [
        {"id": p.id, "name": p.name, "version": p.version, "image": p.image, "enabled": p.enabled,
         "permissions": granted(p), "address": connection_of(p).address,
         "only_from_address": connection_of(p).only_from_address, "manifest": p.manifest}
        for p in all_plugins(db)
    ]


def restore_entries(db: Session, entries: list[dict]) -> dict:
    """
    Load all settings: each plugin in the settings copy that isn't here yet registered again, as it was (address,
    permissions, on or off), but with no token: the copy never holds one, so each needs a new token made on the Plugins
    page and given to the plugin. Only ever adds. {added: [names], kept: [names], warnings: [...]}.
    """
    result = {"added": [], "kept": [], "warnings": []}
    for entry in entries:
        label = entry.get("name") or entry.get("id") or "(unnamed)"
        if isinstance(entry.get("id"), str) and db.get(Plugin, entry["id"]) is not None:
            result["kept"].append(label)
            continue
        try:
            checked = manifests.check(entry.get("manifest"))
            if checked["id"] != entry.get("id"):
                raise ValueError("its manifest is for another plugin.")
            permissions = manifests.check_granted(checked, entry.get("permissions") or [])
            plugin = Plugin(
                id=checked["id"], name=checked["name"], version=checked["version"], image=entry.get("image") or None,
                farmhand_api=checked["farmhand_api"], enabled=entry.get("enabled") is not False, manifest=checked,
            )
            plugin.connection = PluginConnection(
                address=remote.check_address(entry.get("address") or f"http://{checked['id']}:{checked['port']}"),
                only_from_address=entry.get("only_from_address") is not False, needs_token=True,
            )
            _new_token(plugin, permissions)  # one nobody is given: it holds the permissions until a new one is made
            db.add(plugin)
            db.commit()
        except ValueError as e:
            db.rollback()
            result["warnings"].append(f"The plugin “{label}” wasn't put back: {e}")
            continue
        result["added"].append(plugin.name)
    if result["added"]:
        result["warnings"].append(
            f"{', '.join(result['added'])} {'was' if len(result['added']) == 1 else 'were'} put back on the Plugins page, but "
            "the settings copy never keeps a plugin's token: on the Plugins page, make a new token for each and give it to "
            "the plugin (as FARMHAND_TOKEN)."
        )
    return result


def connection_of(plugin: Plugin) -> PluginConnection:
    """Where the plugin runs. One installed before addresses were kept is taken as a container beside Farmhand."""
    if plugin.connection is None:
        port = (plugin.manifest or {}).get("port") or 80
        plugin.connection = PluginConnection(address=f"http://{plugin.id}:{port}", only_from_address=True)
    return plugin.connection


def _new_token(plugin: Plugin, permissions: list[str]) -> str:
    token = secrets.token_urlsafe(32)
    plugin.tokens.append(PluginToken(token_hash=hash_token(token), permissions=list(permissions), created_at=utc_now()))
    return token
