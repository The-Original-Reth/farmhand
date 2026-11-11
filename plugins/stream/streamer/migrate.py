"""
The one-off move from Farmhand's own Stream page: with the stream:migrate permission, Farmhand hands the plugin, once,
its stream settings, saved layouts, stream key and YouTube sign-in (POST /stream/migrate), and they're kept in the
plugin's store as Farmhand kept them. Farmhand keeps its own copy (removed with Farmhand's Stream page, later).

It happens by itself the first time the plugin starts with the permission and nothing set up of its own (at_start()),
and the page can ask for it (run()): over settings already made here only when told to (`replace`).
"""
from __future__ import annotations

import threading
import time

from . import layouts
from .farm import client
from .farmhand import FarmhandError
from .live_stream.constants import SETTINGS_KEY, STREAM_KEY_KEY
from .store import Store
from . import youtube_live

MIGRATED_KEY = "migrated_from_farmhand"  # {at, stream_folder}: when it was moved, and Farmhand's stream folder then
PERMISSION = "stream:migrate"
RETRY = 60  # seconds between tries at start while Farmhand isn't answering


def state(db: Store) -> dict:
    """{done: {at, stream_folder} | None, own_settings: whether this plugin has settings of its own}."""
    return {"done": db.json(MIGRATED_KEY), "own_settings": bool(db.get(SETTINGS_KEY))}


def apply(db: Store, got: dict) -> None:
    """Farmhand's hand-over kept in the store, as Farmhand kept it (the layouts checked again on the way in)."""
    import json

    settings = got.get("settings") if isinstance(got.get("settings"), dict) else {}
    db.put(SETTINGS_KEY, json.dumps(settings) if settings else None)
    db.put(STREAM_KEY_KEY, got.get("stream_key") or None)
    yt = got.get("youtube") if isinstance(got.get("youtube"), dict) else {}
    client_info = yt.get("client") if isinstance(yt.get("client"), dict) else None
    db.put(youtube_live.CLIENT_KEY, json.dumps(client_info) if client_info else None)
    db.put(youtube_live.TOKEN_KEY, yt.get("refresh_token") or None)
    db.put(youtube_live.CHANNEL_KEY, yt.get("channel") or None)
    db.put(youtube_live.STREAM_KEY, yt.get("stream_id") or None)
    db.put_json(MIGRATED_KEY, {"at": got.get("handed_over_at"), "stream_folder": got.get("stream_folder")})
    layouts.save(db, got.get("layouts") or [])  # (commits all of it)


def run(db: Store, replace: bool = False) -> dict:
    """Ask Farmhand for its Stream page set-up now and keep it. ValueError says why not (in words for the operator)."""
    if db.get(SETTINGS_KEY) and not replace:
        raise ValueError("This plugin has settings of its own already. Bringing Farmhand's over would replace them: "
                         "tick to replace them and try again.")
    try:
        got = client(timeout=15).stream_migration()
    except FarmhandError as e:
        if e.kind == "forbidden":
            raise ValueError("Farmhand hasn't given this plugin the stream:migrate permission. Remove the plugin on "
                             "Farmhand's Plugins page and add it again, leaving that permission ticked.") from None
        raise ValueError(e.message) from None
    apply(db, got)
    return state(db)


def at_start(db: Store) -> None:
    """The first start: move Farmhand's set-up over by itself when allowed and nothing is set up here yet (tried again
    while Farmhand isn't answering; never again once moved, or once settings are made here)."""
    def go():
        while not db.get(MIGRATED_KEY) and not db.get(SETTINGS_KEY):
            try:
                if PERMISSION not in (client().me().get("permissions") or []):
                    return
                run(db)
                print("stream: Farmhand's Stream page settings, layouts, key and YouTube sign-in brought over", flush=True)
                return
            except FarmhandError as e:
                if e.kind != "down" and e.kind != "busy":
                    print(f"stream: not bringing Farmhand's Stream settings over: {e.message}", flush=True)
                    return
            except ValueError as e:
                print(f"stream: not bringing Farmhand's Stream settings over: {e}", flush=True)
                return
            time.sleep(RETRY)

    threading.Thread(target=go, name="stream-migrate", daemon=True).start()
