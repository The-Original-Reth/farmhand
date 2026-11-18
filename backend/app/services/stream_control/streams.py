"""
The stream plugins Stream control starts and stops: each plugin added to Farmhand whose manifest has a
`stream_control` entry ({"path": "/api/stream-control", "site": "YouTube"}, see docs/plugins.md). Farmhand asks it
where it runs: GET <address><path> for how its stream is doing, POST <path>/start and <path>/stop. Each answers
{live, following, error, watch_url}: `following` says it sends the stream designed here (rather than its own
layout), `error` why it isn't live when it should be. A plugin that's switched off is listed, but never asked.

The operator chooses which of them Stream control brings in (an app_settings row, CHOSEN_KEY: their ids; none saved
yet = all of them). One left out keeps its own layout (the plugin API tells it Stream control is off for it), and
isn't started or stopped from here: not by Go live everywhere, Stop all or the schedule, nor by its own buttons.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy.orm import Session

from .. import app_settings
from ..plugins import registry, remote

TIMEOUT = 6.0  # a plugin going live may take a moment to say so
START_TIMEOUT = 20.0
CHOSEN_KEY = "stream_control_streams"


# The YouTube (id "stream") and Twitch (id "twitch") plugins from before Stream control: no `stream_control` in their
# manifests, but their own page's API goes live and stops (POST /api/stream/start, /stop) and says how it's doing
# (GET /api/stream: {settings, status: {live, error, youtube: {watch_url}}, ...}). Stream control starts and stops them
# that way; they send their own layout until they're updated to read Stream control's design.
BEFORE_STREAM_CONTROL = {"stream": "YouTube", "twitch": "Twitch"}
# Their site's settings window (the stream key, sign-in, privacy or category), when their manifest doesn't name one
SETTINGS_PAGES = {"stream": "/?view=youtube-settings", "twitch": "/?view=twitch-settings"}


def control_of(plugin) -> dict | None:
    """How Stream control reaches a stream plugin: {path, site, legacy}, or None for a plugin that isn't one."""
    sc = (plugin.manifest or {}).get("stream_control")
    settings = (sc or {}).get("settings") or SETTINGS_PAGES.get(plugin.id)
    if sc:
        return {"path": sc["path"], "site": sc.get("site"), "legacy": False, "settings": settings}
    if plugin.id in BEFORE_STREAM_CONTROL:
        return {"path": "/api/stream", "site": BEFORE_STREAM_CONTROL[plugin.id], "legacy": True, "settings": settings}
    return None


def _stream_plugins(db: Session) -> list:
    return [p for p in registry.all_plugins(db) if control_of(p)]


def chosen(db: Session) -> list[str] | None:
    """The ids of the stream plugins brought in, as saved; None when none were ever chosen (all of them are)."""
    try:
        raw = json.loads(app_settings.get(db, CHOSEN_KEY) or "null")
    except ValueError:
        return None
    return [x for x in raw if isinstance(x, str)] if isinstance(raw, list) else None


def is_chosen(db: Session, plugin_id: str) -> bool:
    picked = chosen(db)
    return picked is None or plugin_id in picked


def choose(db: Session, ids) -> list[dict]:
    """Bring in these stream plugins (and leave the others out): each one's entry, as listed."""
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise ValueError("Say which streams to bring in, as a list of the plugins' ids.")
    known = {p.id for p in _stream_plugins(db)}
    unknown = [x for x in ids if x not in known]
    if unknown:
        raise ValueError(f"\"{unknown[0]}\" isn't a stream plugin added to Farmhand.")
    app_settings.put(db, CHOSEN_KEY, json.dumps(list(dict.fromkeys(ids))))
    db.commit()
    return listed(db)


def _ask(address: str, path: str, method: str = "GET", legacy: bool = False) -> dict:
    """What the plugin answered, as {live, following, error, watch_url, reachable}. `legacy`: one from before Stream
    control, answering its own page's {settings, status} (see BEFORE_STREAM_CONTROL)."""
    try:
        with httpx.Client(transport=remote.transport, timeout=START_TIMEOUT if method == "POST" else TIMEOUT,
                          follow_redirects=False) as client:
            r = client.request(method, f"{address}{path}", headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        return {"live": False, "following": None, "error": remote.unreachable(address, e), "watch_url": None, "reachable": False}
    try:
        body = r.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    if not 200 <= r.status_code < 300:
        said = body.get("detail") if isinstance(body.get("detail"), str) else r.text.strip()[:300]
        return {"live": None, "following": None, "error": said or f"The plugin answered {r.status_code}.", "watch_url": None,
                "reachable": True, "refused": True}
    if legacy:
        status = body.get("status") if isinstance(body.get("status"), dict) else {}
        settings = body.get("settings") if isinstance(body.get("settings"), dict) else {}
        youtube = status.get("youtube") if isinstance(status.get("youtube"), dict) else {}
        channel = settings.get("channel") if isinstance(settings.get("channel"), str) and settings.get("channel") else None
        watch = youtube.get("watch_url") if isinstance(youtube.get("watch_url"), str) else None
        return {
            "live": status.get("live") is True, "following": False,
            "error": status.get("error") if isinstance(status.get("error"), str) and status.get("error") else None,
            "watch_url": watch or (f"https://www.twitch.tv/{channel}" if channel else None), "reachable": True,
        }
    return {
        "live": body.get("live") is True,
        "following": body.get("following") if isinstance(body.get("following"), bool) else None,
        "error": body.get("error") if isinstance(body.get("error"), str) and body.get("error") else None,
        "watch_url": body.get("watch_url") if isinstance(body.get("watch_url"), str) else None,
        "reachable": True,
    }


PAGE_PATH = "/api/stream"  # the YouTube and Twitch plugins' own page API: {settings, status, ...}
CAMERA_STATES = ("live", "down", "starting")


def _links(status: dict, settings: dict) -> list[dict]:
    """The links each plugin's own page shows, as [{label, url, title}]: YouTube's broadcast (Watch, and YouTube Studio
    for its chat and analytics, while there's a broadcast), Twitch's channel (Watch, Chat, Stream Manager, Analytics)."""
    out = []
    youtube = status.get("youtube") if isinstance(status.get("youtube"), dict) else {}
    if isinstance(youtube.get("watch_url"), str) and youtube["watch_url"].startswith("https://"):
        out.append({"label": "Watch", "url": youtube["watch_url"], "title": "The broadcast as viewers see it"})
    if isinstance(youtube.get("studio_url"), str) and youtube["studio_url"].startswith("https://"):
        out.append({"label": "Chat and analytics", "url": youtube["studio_url"], "title": "The broadcast in YouTube Studio"})
    channel = settings.get("channel")
    if isinstance(channel, str) and channel and all(ch.isalnum() or ch == "_" for ch in channel):
        out += [
            {"label": "Watch", "url": f"https://www.twitch.tv/{channel}", "title": "The channel as viewers see it"},
            {"label": "Chat", "url": f"https://www.twitch.tv/popout/{channel}/chat?popout=", "title": "The channel's chat in a window of its own"},
            {"label": "Stream Manager", "url": f"https://dashboard.twitch.tv/u/{channel}/stream-manager", "title": "Twitch's dashboard: chat, activity, title and category"},
            {"label": "Analytics", "url": f"https://dashboard.twitch.tv/u/{channel}/analytics/channel-analytics", "title": "Viewers, followers and watch time"},
        ]
    return out


def _page_extras(address: str) -> dict:
    """From the plugin's own page API: {links, cameras: [{key, label, state: live | down | starting, since}] (while
    live), viewers (YouTube's, while live)}. Empty when it doesn't answer one (a plugin of someone else's making)."""
    try:
        with httpx.Client(transport=remote.transport, timeout=TIMEOUT, follow_redirects=False) as client:
            r = client.get(f"{address}{PAGE_PATH}", headers={"Accept": "application/json"})
        body = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        body = {}
    body = body if isinstance(body, dict) else {}
    status = body.get("status") if isinstance(body.get("status"), dict) else {}
    settings = body.get("settings") if isinstance(body.get("settings"), dict) else {}
    cameras = []
    for c in status.get("camera_states") or []:
        if isinstance(c, dict) and c.get("state") in CAMERA_STATES:
            cameras.append({"key": c.get("key"), "label": c.get("label") or c.get("key"), "state": c["state"], "since": c.get("since")})
    youtube = status.get("youtube") if isinstance(status.get("youtube"), dict) else {}
    viewers = youtube.get("viewers") if type(youtube.get("viewers")) is int else None
    return {"links": _links(status, settings), "cameras": cameras, "viewers": viewers}


def _status(address: str, path: str, method: str = "GET", legacy: bool = False) -> dict:
    """_ask, with what the plugin's own page shows: its links and its cameras' states."""
    answer = _ask(address, path, method, legacy)
    return {**answer, **(_page_extras(address) if answer.get("reachable") else {"links": [], "cameras": [], "viewers": None})}


def _entry(plugin, answer: dict | None, picked: list[str] | None) -> dict:
    sc = control_of(plugin)
    return {
        "id": plugin.id, "name": plugin.name, "site": sc.get("site") or plugin.name, "enabled": plugin.enabled,
        "chosen": picked is None or plugin.id in picked,
        # from before Stream control: it starts and stops from here, but sends its own layout until it's updated
        "needs_update": sc["legacy"],
        "has_page": bool((plugin.manifest or {}).get("page")),
        # its site's settings window, a page of its own (shown inside Farmhand at /plugins/<id><settings_page>)
        "settings_page": sc.get("settings"),
        "can_read_design": "stream:read" in registry.granted(plugin),
        "links": [], "cameras": [], "viewers": None,
        **(answer or {"live": False, "following": None, "error": None, "watch_url": None, "reachable": None}),
    }


def _each(db: Session, ask, only_chosen: bool = False) -> list[dict]:
    """Each stream plugin's entry; the switched-on ones (only those brought in, with `only_chosen`) asked, all at once,
    so one slow plugin doesn't hold up the rest."""
    plugins, picked = _stream_plugins(db), chosen(db)
    on = [p for p in plugins if p.enabled and (not only_chosen or picked is None or p.id in picked)]
    asked = {}
    if on:
        with ThreadPoolExecutor(max_workers=min(8, len(on))) as pool:
            jobs = {p.id: pool.submit(ask, registry.connection_of(p).address, control_of(p)["path"], legacy=control_of(p)["legacy"])
                    for p in on}
            asked = {pid: job.result() for pid, job in jobs.items()}
    return [_entry(p, asked.get(p.id), picked) for p in plugins]


def listed(db: Session) -> list[dict]:
    """Every stream plugin and how its stream is doing: [{id, name, site, enabled, chosen (brought in), live, links,
    cameras (each one's state while live), viewers,
    following, error, watch_url, reachable (None: switched off, not asked), can_read_design (granted stream:read)}]."""
    return _each(db, _status)


def _one(db: Session, plugin_id: str):
    plugin = registry.get(db, plugin_id)
    if not control_of(plugin):
        raise ValueError(f"{plugin.name} isn't a stream plugin Stream control can start and stop.")
    if not plugin.enabled:
        raise ValueError(f"{plugin.name} is switched off. Switch it on on the Plugins page first.")
    if not is_chosen(db, plugin.id):
        raise ValueError(f"{plugin.name} isn't brought into Stream control. Tick it under Streams first.")
    return plugin


def _act(db: Session, plugin, action: str) -> dict:
    sc = control_of(plugin)
    answer = _status(registry.connection_of(plugin).address, f"{sc['path']}/{action}", "POST", sc["legacy"])
    return _entry(plugin, answer, chosen(db))


def start(db: Session, plugin_id: str) -> dict:
    """Tell one stream plugin to go live. Its entry as it answered; ValueError when it can't be asked."""
    return _act(db, _one(db, plugin_id), "start")


def stop(db: Session, plugin_id: str) -> dict:
    return _act(db, _one(db, plugin_id), "stop")


def all_of(db: Session, action: str) -> list[dict]:
    """Start or stop every switched-on stream plugin brought in, at once: those ones' entries, as they answered."""
    told = _each(db, lambda address, base, legacy=False: _status(address, f"{base}/{action}", "POST", legacy), only_chosen=True)
    return [e for e in told if e["enabled"] and e["chosen"]]
