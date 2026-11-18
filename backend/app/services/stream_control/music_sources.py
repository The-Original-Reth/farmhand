"""
The stream's music, from the folders chosen in the design's `music_from`: Stream control's own music folder
(design.OWN_MUSIC) and/or stream plugins' own music folders (YouTube's, Twitch's), played together. A plugin's tracks
are never copied into Farmhand: they're listed from its own page API (GET <address>/api/stream: media.music) and each
one is passed on from there when it's asked for (GET <address>/api/stream/music/<name>), to a stream plugin following
Stream control or to the page playing it in the browser.

A track is known by its file name; two folders with a track of the same name play it once, from the first folder.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from ...errors import NotFound
from ..plugins import registry, remote
from . import design, media, streams

PAGE_PATH = "/api/stream"
LIST_FOR = 10.0  # seconds a plugin's list of tracks is kept (the page and the stream plugins ask every few seconds)
LIST_TIMEOUT = 6.0
TRACK_TIMEOUT = 60.0
_listed: dict[str, tuple[float, list[str], str | None]] = {}  # plugin id -> (when, tracks, why none)


def _plugin(db: Session, plugin_id: str):
    try:
        plugin = registry.get(db, plugin_id)
    except NotFound:
        return None
    return plugin if plugin.enabled and streams.control_of(plugin) else None


def plugin_tracks(db: Session, plugin_id: str) -> tuple[list[str], str | None]:
    """(the MP3s in this stream plugin's own music folder, why there are none when it couldn't be asked)."""
    now = time.monotonic()
    kept = _listed.get(plugin_id)
    if kept and now - kept[0] < LIST_FOR:
        return kept[1], kept[2]
    plugin = _plugin(db, plugin_id)
    if plugin is None:
        tracks, problem = [], f"“{plugin_id}” isn't a stream plugin that's switched on."
    else:
        address = registry.connection_of(plugin).address
        try:
            with httpx.Client(transport=remote.transport, timeout=LIST_TIMEOUT, follow_redirects=False) as client:
                r = client.get(f"{address}{PAGE_PATH}", headers={"Accept": "application/json"})
            body = r.json() if r.status_code == 200 else {}
            found = ((body or {}).get("media") or {}).get("music") or []
            tracks = [n for n in found if isinstance(n, str) and Path(n).suffix.lower() in media.TRACK_TYPES]
            problem = None if r.status_code == 200 else f"{plugin.name} answered {r.status_code}."
        except (httpx.HTTPError, ValueError, AttributeError) as e:
            tracks, problem = [], remote.unreachable(address, e) if isinstance(e, httpx.HTTPError) else f"{plugin.name} didn't answer with its music."
    _listed[plugin_id] = (now, tracks, problem)
    return tracks, problem


def forget() -> None:
    _listed.clear()


def tracks(db: Session) -> list[dict]:
    """The stream's music, folder by folder as chosen: [{name, source (design.OWN_MUSIC or a plugin id)}], each name once."""
    out: list[dict] = []
    seen: set[str] = set()
    for source in design.settings(db)["music_from"]:
        names = media.media(db)["music"] if source == design.OWN_MUSIC else plugin_tracks(db, source)[0]
        for n in names:
            if n not in seen:
                seen.add(n)
                out.append({"name": n, "source": source})
    return out


def sources(db: Session) -> list[dict]:
    """The music folders there are to choose from: [{id, label, chosen, tracks (how many), problem}] (Stream control's
    own, then each switched-on stream plugin's)."""
    chosen = design.settings(db)["music_from"]
    own = media.media(db)["music"]
    out = [{"id": design.OWN_MUSIC, "label": "Stream control's music folder", "chosen": design.OWN_MUSIC in chosen,
            "tracks": len(own), "problem": None}]
    for p in registry.all_plugins(db):
        sc = streams.control_of(p)
        if not sc or not p.enabled:
            continue
        names, problem = plugin_tracks(db, p.id)
        out.append({"id": p.id, "label": f"{sc.get('site') or p.name}'s music folder", "chosen": p.id in chosen,
                    "tracks": len(names), "problem": problem})
    return out


def stamps(db: Session) -> dict[str, str]:
    """music/<name> -> a stamp for each track from a plugin's folder (its source and name: it's fetched once)."""
    return {f"{media.MUSIC}/{t['name']}": f"{t['source']}:{t['name']}" for t in tracks(db) if t["source"] != design.OWN_MUSIC}


def find(db: Session, name: str) -> Path | tuple[str, str]:
    """Where a track of the stream's music is: a file in Stream control's own folder (its Path), or a plugin's
    (address, path) to pass on from. NotFound when none of the chosen folders has it."""
    for t in tracks(db):
        if t["name"] != name:
            continue
        if t["source"] == design.OWN_MUSIC:
            return media.track_path(db, name)
        plugin = _plugin(db, t["source"])
        if plugin is not None:
            return registry.connection_of(plugin).address, f"{PAGE_PATH}/music/{quote(name, safe='')}"
    raise NotFound("That track isn't in the music folders chosen.")


def passed_on(address: str, path: str) -> Iterator[bytes]:
    """A plugin's track, passed on as it comes (NotFound when the plugin hasn't got it)."""
    client = httpx.Client(transport=remote.transport, timeout=TRACK_TIMEOUT, follow_redirects=False)
    try:
        req = client.build_request("GET", f"{address}{path}")
        r = client.send(req, stream=True)
    except httpx.HTTPError as e:
        client.close()
        raise NotFound(remote.unreachable(address, e)) from None
    if r.status_code != 200:
        r.close()
        client.close()
        raise NotFound("The stream plugin hasn't got that track any more.")

    def body() -> Iterator[bytes]:
        try:
            yield from r.iter_bytes()
        finally:
            r.close()
            client.close()

    return body()
