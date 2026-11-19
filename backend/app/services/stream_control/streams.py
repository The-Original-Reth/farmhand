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
# The YouTube and Twitch plugins' own page API: {settings (its own), status, media (its own stream folder), ...}, with its
# files under it (PAGE_PATH/pictures/<name>, /slideshows/<show>/pictures/<name>, /music/<name>). Copy layout and the
# music folders read it too.
PAGE_PATH = "/api/stream"
CAMERA_STATES = ("live", "down", "starting")
NOTHING_SHOWN = {"links": [], "cameras": [], "viewers": None, "buffer": None, "hardware": None}
# What a stream plugin says it compresses its stream with ("encoder") and unpacks its cameras with ("camera_decoding"),
# as Stream control shows them: "gpu" (an NVIDIA card) or "cpu" (the processor)
ENCODERS = {"nvenc": "gpu", "cpu": "cpu"}
DECODERS = {"gpu": "gpu", "cpu": "cpu"}


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
        return {"path": PAGE_PATH, "site": BEFORE_STREAM_CONTROL[plugin.id], "legacy": True, "settings": settings}
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


def _request(address: str, path: str, method: str = "GET") -> tuple[int | None, dict, str | None]:
    """(status code, JSON body ({} when there's none), why it couldn't be asked) of one call to the plugin."""
    try:
        with httpx.Client(transport=remote.transport, timeout=START_TIMEOUT if method == "POST" else TIMEOUT,
                          follow_redirects=False) as client:
            r = client.request(method, f"{address}{path}", headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        return None, {}, remote.unreachable(address, e)
    try:
        body = r.json()
    except ValueError:
        body = {"detail": r.text.strip()[:300]} if not 200 <= r.status_code < 300 else {}
    return r.status_code, body if isinstance(body, dict) else {}, None


def _answer(code: int | None, body: dict, problem: str | None, legacy: bool) -> dict:
    """{live, following, error, watch_url, reachable} from what the plugin answered. `legacy`: one from before Stream
    control, answering its own page's {settings, status} (see BEFORE_STREAM_CONTROL)."""
    if code is None:
        return {"live": False, "following": None, "error": problem, "watch_url": None, "reachable": False}
    if not 200 <= code < 300:
        said = body.get("detail") if isinstance(body.get("detail"), str) else None
        return {"live": None, "following": None, "error": said or f"The plugin answered {code}.", "watch_url": None,
                "reachable": True, "refused": True}
    if legacy:
        status = _dict(body.get("status"))
        channel = _dict(body.get("settings")).get("channel")
        watch = _dict(status.get("youtube")).get("watch_url")
        return {
            "live": status.get("live") is True, "following": False, "error": _text(status.get("error")),
            "watch_url": _text(watch) or (f"https://www.twitch.tv/{channel}" if _text(channel) else None), "reachable": True,
        }
    return {
        "live": body.get("live") is True,
        "following": body.get("following") if isinstance(body.get("following"), bool) else None,
        "error": _text(body.get("error")), "watch_url": _text(body.get("watch_url")), "reachable": True,
    }


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _text(v) -> str | None:
    return v if isinstance(v, str) and v else None


def _links(status: dict, settings: dict) -> list[dict]:
    """The links each plugin's own page shows, as [{label, url, title}]: YouTube's broadcast (Watch, and YouTube Studio
    for its chat and analytics, while there's a broadcast), Twitch's channel (Watch, Chat, Stream Manager, Analytics)."""
    out = []
    youtube = _dict(status.get("youtube"))
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


def _buffer(status: dict) -> dict | None:
    """The stream's delay as its plugin holds it, while live: {seconds (how long it's set to), held (how much of it is
    held now), filling (it's being collected again: after going live or a stall), holding (the holding screen is on the
    site meanwhile)}; None when not live, or a plugin that doesn't say (no delay set: seconds 0)."""
    delay = _dict(status.get("delay"))
    seconds, held = delay.get("seconds"), delay.get("held")
    if status.get("live") is not True or not isinstance(seconds, (int, float)) or not isinstance(held, (int, float)):
        return None
    return {"seconds": round(float(seconds), 1), "held": round(max(0.0, min(float(held), float(seconds))), 1),
            "filling": delay.get("filling") is True, "holding": status.get("holding") is True}


def _hardware(status: dict) -> dict | None:
    """Where a live stream's work is done, as its plugin says: {encoder (compressing the stream), cameras (unpacking
    and fitting them): "gpu" | "cpu" | None (not said), note (why something the card did is on the processor now, or
    None)}; None when not live, or a plugin that says neither."""
    if status.get("live") is not True:
        return None
    encoder, cameras = ENCODERS.get(status.get("encoder")), DECODERS.get(status.get("camera_decoding"))
    if encoder is None and cameras is None:
        return None
    return {"encoder": encoder, "cameras": cameras,
            "note": _text(status.get("encoder_note")) or _text(status.get("camera_decoding_note"))}


def _shown(page: dict) -> dict:
    """From the plugin's own page answer: {links, cameras: [{key, label, state: live | down | starting, since}] (while
    live), viewers (YouTube's, while live), buffer (its delay, while live: _buffer), hardware (GPU or CPU, while live:
    _hardware)}."""
    status, settings = _dict(page.get("status")), _dict(page.get("settings"))
    cameras = [
        {"key": c.get("key"), "label": c.get("label") or c.get("key"), "state": c["state"], "since": c.get("since")}
        for c in status.get("camera_states") or [] if isinstance(c, dict) and c.get("state") in CAMERA_STATES
    ]
    viewers = _dict(status.get("youtube")).get("viewers")
    return {"links": _links(status, settings), "cameras": cameras, "viewers": viewers if type(viewers) is int else None,
            "buffer": _buffer(status), "hardware": _hardware(status)}


def _status(address: str, path: str, method: str = "GET", legacy: bool = False) -> dict:
    """Ask the plugin (its stream_control path, or a start or stop): its answer, with what its own page shows (its
    links and cameras), read from that answer when it is its page (a legacy plugin's GET), else asked for it."""
    code, body, problem = _request(address, path, method)
    answer = _answer(code, body, problem, legacy)
    if not answer["reachable"]:
        return {**answer, **NOTHING_SHOWN}
    if path == PAGE_PATH and method == "GET" and 200 <= code < 300:
        return {**answer, **_shown(body)}
    page_code, page, _ = _request(address, PAGE_PATH)
    return {**answer, **(_shown(page) if page_code == 200 else NOTHING_SHOWN)}


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
        **NOTHING_SHOWN,
        **(answer or {"live": False, "following": None, "error": None, "watch_url": None, "reachable": None}),
    }


def _each(db: Session, ask, only_chosen: bool = False) -> list[dict]:
    """Each stream plugin's entry; the switched-on ones (only those brought in, with `only_chosen`) asked, all at once,
    so one slow plugin doesn't hold up the rest."""
    plugins, picked = _stream_plugins(db), chosen(db)
    on = [p for p in plugins if p.enabled and (not only_chosen or picked is None or p.id in picked)]
    asked = {}
    if on:
        targets = {p.id: (registry.connection_of(p).address, control_of(p)["path"], control_of(p)["legacy"]) for p in on}
        db.commit()  # let go of its database connection while the plugins are asked (a slow one can take seconds)
        with ThreadPoolExecutor(max_workers=min(8, len(on))) as pool:
            jobs = {pid: pool.submit(ask, address, path, legacy=legacy) for pid, (address, path, legacy) in targets.items()}
            asked = {pid: job.result() for pid, job in jobs.items()}
    return [_entry(p, asked.get(p.id), picked) for p in plugins]


def listed(db: Session) -> list[dict]:
    """Every stream plugin and how its stream is doing: [{id, name, site, enabled, chosen (brought in), live, links,
    cameras (each one's state while live), viewers, buffer (its delay while live: {seconds, held, filling, holding}),
    hardware (while live, where its work is done: {encoder, cameras: "gpu" | "cpu" | None, note}),
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
