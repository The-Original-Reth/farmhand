"""
The stream:migrate permission: a Stream plugin taking over from Farmhand's own Stream page is handed, once, a copy of
what that page has set up (its settings and saved layouts, the stream key, the YouTube sign-in), so the operator doesn't
set it all up again. Farmhand keeps its own copy (it's only read here); it records that it handed it over, and asking
again is refused (410) until the plugin is removed and added afresh. docs/plugins.md has the shape.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ...models import PluginHandover
from ...timeutil import utc_iso
from .. import app_settings, config_service, stream_media, youtube_live
from ..live_stream.constants import SETTINGS_KEY, STREAM_KEY_KEY

STREAM = "stream"


class AlreadyHandedOver(Exception):
    """It was handed over before (410)."""


def _json(db: Session, key: str):
    try:
        return json.loads(app_settings.get(db, key) or "null")
    except ValueError:
        return None


def _stream_folder(db: Session) -> str | None:
    try:
        return stream_media.location_info(db)["path"]
    except Exception:  # noqa: BLE001 - (no storage chosen yet: the plugin's own folder is chosen on its machine anyway)
        return None


def stream_state(db: Session, plugin_id: str) -> dict:
    """Whether the Stream page's set-up can still be handed over to this plugin (no secrets in it)."""
    done = db.get(PluginHandover, (plugin_id, STREAM))
    saved = _json(db, SETTINGS_KEY)
    return {
        "available": done is None,
        "handed_over_at": utc_iso(done.handed_at) if done else None,
        "has_settings": isinstance(saved, dict) and bool(saved),
    }


def stream_handover(db: Session, plugin_id: str) -> dict:
    """The Stream page's set-up, once: AlreadyHandedOver the second time."""
    done = db.get(PluginHandover, (plugin_id, STREAM))
    if done is not None:
        raise AlreadyHandedOver(
            f"Farmhand already handed its Stream page set-up to this plugin ({utc_iso(done.handed_at)}), and hands it "
            "over only once. To take it again, remove the plugin on Farmhand's Plugins page and add it afresh."
        )
    saved = _json(db, SETTINGS_KEY)
    client = _json(db, youtube_live.CLIENT_KEY)
    record = PluginHandover(plugin_id=plugin_id, what=STREAM)
    db.add(record)
    db.commit()
    return {
        "settings": saved if isinstance(saved, dict) else {},
        "layouts": config_service.get_config(db)["preferences"]["stream_layouts"],
        "stream_key": app_settings.get(db, STREAM_KEY_KEY),
        "youtube": {
            "client": ({"client_id": client.get("client_id"), "client_secret": client.get("client_secret")}
                       if isinstance(client, dict) and client.get("client_id") else None),
            "refresh_token": app_settings.get(db, youtube_live.TOKEN_KEY),
            "channel": app_settings.get(db, youtube_live.CHANNEL_KEY),
            "stream_id": app_settings.get(db, youtube_live.STREAM_KEY),
        },
        "stream_folder": _stream_folder(db),
        "handed_over_at": utc_iso(record.handed_at),
    }
