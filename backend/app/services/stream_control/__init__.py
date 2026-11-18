"""
Stream control: a plugin built into Farmhand (not a container added by address), switched on or off on the Plugins
page. One stream is designed here (design.py: its grid of cameras and cards, words, colours, music and holding
screen, with its pictures and music in Farmhand's stream folder, media.py), and the stream plugins (YouTube, Twitch)
each send that one stream to their own site: they read it through the plugin API's stream:read permission. From here
the operator starts and stops each of them, or all at once (streams.py), and sets times they go live and stop on
their own (schedule.py).

Its on/off switch is an app_settings row (off until switched on). Switched off, its page leaves the menu, its API
answers 404 and the schedule rests; what it has saved is kept.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...errors import NotFound
from .. import app_settings

ID = "stream-control"  # its id on the Plugins page and in the menu (/plugin/stream-control); no added plugin may take it
NAME = "Stream control"
DESCRIPTION = (
    "Design one stream here (cameras, pictures, words and music) and have the YouTube and Twitch stream plugins each "
    "send it to their site. Start and stop them, one at a time or all at once, or at set times."
)
ENABLED_KEY = "stream_control_enabled"


class SwitchedOff(NotFound):
    """Stream control is switched off (404)."""


def enabled(db: Session) -> bool:
    return app_settings.get(db, ENABLED_KEY) == "1"


def set_enabled(db: Session, on: bool) -> None:
    app_settings.put(db, ENABLED_KEY, "1" if on else None)
    db.commit()


def require_on(db: Session) -> None:
    if not enabled(db):
        raise SwitchedOff("Stream control is switched off. Switch it on on the Plugins page to use it.")


def entry(db: Session) -> dict:
    """Stream control as the Plugins page and the menu list it, beside the plugins added by address."""
    return {
        "id": ID, "name": NAME, "builtin": True, "enabled": enabled(db), "description": DESCRIPTION,
        "page": {"menu": NAME, "icon": "video", "path": "/"},
    }
