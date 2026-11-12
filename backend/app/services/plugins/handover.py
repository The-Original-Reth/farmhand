"""
The stream:migrate permission: a Stream plugin taking over from the Stream page an older Farmhand had built in is
handed, once, a copy of what that page had set up (its settings and saved layouts, the stream key, the YouTube
sign-in), so the operator doesn't set it all up again. Farmhand has no Stream page of its own any more, but what that
page saved is still in its database: it's only read here, never changed or deleted. Farmhand records that it handed it
over, and asking again is refused (410) until the plugin is removed and added afresh. docs/plugins.md has the shape.

The rows are read by their own key names, as the Stream page saved them, so nothing else in Farmhand needs to know them.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ...models import PluginHandover
from ...timeutil import utc_iso
from .. import app_settings

STREAM = "stream"

# What the old Stream page kept in the app_settings table, by key
SETTINGS_KEY = "live_stream"  # its settings, as JSON
STREAM_KEY_KEY = "live_stream_key"  # the stream key itself, on its own
YOUTUBE_CLIENT_KEY = "youtube_client"  # {client_id, client_secret}, as JSON
YOUTUBE_TOKEN_KEY = "youtube_refresh_token"
YOUTUBE_CHANNEL_KEY = "youtube_channel"  # the channel's name, as signed in
YOUTUBE_STREAM_KEY = "youtube_stream_id"  # the page's own live stream on the channel
MEDIA_DIR_KEY = "stream_media_dir"  # the stream folder chosen in Settings (none: the default, not handed over)
CONFIG_KEY = "config_json"  # the settings (config_service.KEY_CONFIG): its saved layouts were preferences.stream_layouts


class AlreadyHandedOver(Exception):
    """It was handed over before (410)."""


def _json(db: Session, key: str):
    try:
        return json.loads(app_settings.get(db, key) or "null")
    except ValueError:
        return None


def _layouts(db: Session) -> list:
    """The saved layouts as stored (config_service keeps preferences it no longer knows as they were)."""
    config = _json(db, CONFIG_KEY)
    prefs = config.get("preferences") if isinstance(config, dict) else None
    layouts = prefs.get("stream_layouts") if isinstance(prefs, dict) else None
    return layouts if isinstance(layouts, list) else []


def stream_state(db: Session, plugin_id: str) -> dict:
    """Whether the old Stream page's set-up can still be handed over to this plugin (no secrets in it)."""
    done = db.get(PluginHandover, (plugin_id, STREAM))
    saved = _json(db, SETTINGS_KEY)
    return {
        "available": done is None,
        "handed_over_at": utc_iso(done.handed_at) if done else None,
        "has_settings": isinstance(saved, dict) and bool(saved),
    }


def stream_handover(db: Session, plugin_id: str) -> dict:
    """The old Stream page's set-up, once: AlreadyHandedOver the second time."""
    done = db.get(PluginHandover, (plugin_id, STREAM))
    if done is not None:
        raise AlreadyHandedOver(
            f"Farmhand already handed its Stream page set-up to this plugin ({utc_iso(done.handed_at)}), and hands it "
            "over only once. To take it again, remove the plugin on Farmhand's Plugins page and add it afresh."
        )
    saved = _json(db, SETTINGS_KEY)
    client = _json(db, YOUTUBE_CLIENT_KEY)
    record = PluginHandover(plugin_id=plugin_id, what=STREAM)
    db.add(record)
    db.commit()
    return {
        "settings": saved if isinstance(saved, dict) else {},
        "layouts": _layouts(db),
        "stream_key": app_settings.get(db, STREAM_KEY_KEY),
        "youtube": {
            "client": ({"client_id": client.get("client_id"), "client_secret": client.get("client_secret")}
                       if isinstance(client, dict) and client.get("client_id") else None),
            "refresh_token": app_settings.get(db, YOUTUBE_TOKEN_KEY),
            "channel": app_settings.get(db, YOUTUBE_CHANNEL_KEY),
            "stream_id": app_settings.get(db, YOUTUBE_STREAM_KEY),
        },
        "stream_folder": app_settings.get(db, MEDIA_DIR_KEY),
        "handed_over_at": utc_iso(record.handed_at),
    }
