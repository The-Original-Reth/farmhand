"""
The plugins the operator installed and their tokens: registering one (its manifest checked, the permissions granted,
a token made), listing them, making a new token, removing one, and knowing a plugin by its token.

A token is random (secrets.token_urlsafe(32)), kept only as its sha256, and given back once, when it's made. A plugin
has one token at a time: a new one ends the old.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...errors import NotFound
from ...models import Plugin, PluginToken
from ...timeutil import as_utc, utc_iso, utc_now
from . import manifest as manifests

LAST_USED_EVERY = dt.timedelta(minutes=1)  # how often a token's last use is written down (not on every call)


class AlreadyInstalled(ValueError):
    """A plugin with that id is installed already (409)."""


@dataclass(frozen=True)
class Caller:
    """The plugin a plugin API call came from, and what it was granted."""

    plugin_id: str
    permissions: frozenset[str]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get(db: Session, plugin_id: str) -> Plugin:
    plugin = db.get(Plugin, plugin_id)
    if plugin is None:
        raise NotFound("Plugin not found")
    return plugin


def all_plugins(db: Session) -> list[Plugin]:
    return list(db.scalars(select(Plugin).order_by(Plugin.name, Plugin.id)))


def register(db: Session, raw_manifest, granted, image: str | None = None) -> tuple[Plugin, str]:
    """Install a plugin: its manifest checked, the permissions granted (each one it asked for). (plugin, token)."""
    checked = manifests.check(raw_manifest)
    permissions = manifests.check_granted(checked, granted)
    if image is not None and (not isinstance(image, str) or not image.strip() or len(image) > 300):
        raise ValueError("The plugin's image must be a Docker image name, like ghcr.io/someone/plugin:1.0.")
    if db.get(Plugin, checked["id"]) is not None:
        raise AlreadyInstalled(f"A plugin called \"{checked['id']}\" is already installed. Remove it first to install it again.")
    plugin = Plugin(
        id=checked["id"], name=checked["name"], version=checked["version"], image=image.strip() if image else None,
        farmhand_api=checked["farmhand_api"], enabled=True, manifest=checked,
    )
    db.add(plugin)
    token = _new_token(plugin, permissions)
    db.commit()
    return plugin, token


def new_token(db: Session, plugin_id: str) -> str:
    """A new token for the plugin, with the same permissions; the old one stops working at once."""
    plugin = get(db, plugin_id)
    permissions = granted(plugin)
    plugin.tokens.clear()
    db.flush()
    token = _new_token(plugin, permissions)
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
    return Caller(row.plugin_id, frozenset(row.permissions or []))


def granted(plugin: Plugin) -> list[str]:
    return list(plugin.tokens[0].permissions) if plugin.tokens else []


def out(plugin: Plugin) -> dict:
    """A plugin as the Plugins page shows it. Never its token (only its hash is kept anyway)."""
    token = plugin.tokens[0] if plugin.tokens else None
    permissions = granted(plugin)
    return {
        "id": plugin.id, "name": plugin.name, "version": plugin.version, "image": plugin.image,
        "farmhand_api": plugin.farmhand_api, "enabled": plugin.enabled,
        "permissions": permissions, "permissions_described": manifests.describe(permissions),
        "manifest": plugin.manifest, "created_at": utc_iso(plugin.created_at),
        "token_created_at": utc_iso(token.created_at) if token else None,
        "token_last_used_at": utc_iso(token.last_used_at) if token else None,
    }


def mirror_entries(db: Session) -> list[dict]:
    """What the settings copy keeps of each plugin: which are installed and what they were granted. Never a token."""
    return [
        {"id": p.id, "name": p.name, "version": p.version, "image": p.image, "enabled": p.enabled,
         "permissions": granted(p)}
        for p in all_plugins(db)
    ]


def _new_token(plugin: Plugin, permissions: list[str]) -> str:
    token = secrets.token_urlsafe(32)
    plugin.tokens.append(PluginToken(token_hash=hash_token(token), permissions=list(permissions), created_at=utc_now()))
    return token
