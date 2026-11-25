"""
Clips on Stream control: each stream plugin's own clips (its page's API, CLIPS_PATH, as the Clips panel on its own page
uses it), asked through Farmhand so Stream control's Clips panel can take them. A stream plugin keeps them itself:

    GET  /api/clips          {seconds, least, most, held, sources: [{key, label}], recording: [...], ended: [...],
                             folder: {path, shown_as, problem}, clips: [{name, size, made}]}
    PUT  /api/clips          {seconds}: how long a clip is
    POST /api/clips          {source, seconds, tz}: "stream" (the default) saves the last stretch of what went to its site,
                             201 {name, seconds, size}; a camera ("printer id:camera name") records the next stretch from
                             it, in the background, 202 {recording: {...}}
    GET  /api/clips/{name}   one of its clips, the MP4

Only a stream plugin brought into Stream control and switched on is asked (as for starting and stopping). Nothing here
is kept by Farmhand: the clips, their folder and the length are the plugin's.
"""
from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from ...errors import NotFound
from ..plugins import registry, remote
from . import streams

CLIPS_PATH = "/api/clips"
TIMEOUT = 8.0
SAVE_TIMEOUT = 60.0  # saving the last 5 minutes of the stream as an MP4 takes a moment
DOWNLOAD_TIMEOUT = httpx.Timeout(30.0, read=120.0)
CHUNK = 256 * 1024


def _target(db: Session, plugin_id: str) -> tuple[str, str]:
    """(address, site) of a stream plugin that can be asked from here; ValueError (in plain words) when it can't."""
    plugin = streams._one(db, plugin_id)
    site = streams.control_of(plugin).get("site") or plugin.name
    address = registry.connection_of(plugin).address
    db.commit()  # (let go of the database while the plugin is asked)
    return address, site


def _said(body: dict, code: int) -> str:
    return body["detail"] if isinstance(body.get("detail"), str) and body["detail"] else f"The plugin answered {code}."


def _call(db: Session, plugin_id: str, method: str, path: str = "", payload: dict | None = None,
          timeout: float = TIMEOUT) -> tuple[int, dict, str]:
    """(status code, JSON body, site) of one call to the plugin's clips; ValueError with what went wrong."""
    address, site = _target(db, plugin_id)
    try:
        with httpx.Client(transport=remote.transport, timeout=timeout, follow_redirects=False) as client:
            r = client.request(method, f"{address}{CLIPS_PATH}{path}", json=payload, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise ValueError(f"{site}: {remote.unreachable(address, e)}") from None
    try:
        body = r.json()
    except ValueError:
        body = {"detail": r.text.strip()[:300]} if not 200 <= r.status_code < 300 else {}
    body = body if isinstance(body, dict) else {}
    if r.status_code in (404, 405) and not path and method in ("GET", "PUT"):
        raise ValueError(f"{site}'s stream plugin doesn't take clips. Update it to a version that does.")
    if not 200 <= r.status_code < 300:
        raise ValueError(_said(body, r.status_code))
    return r.status_code, body, site


def _num(v, default: float = 0.0) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def _text(v) -> str | None:
    return v if isinstance(v, str) and v else None


def _dicts(v) -> list[dict]:
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _job(j: dict) -> dict:
    """A camera being recorded, or one that ended: {source, label, until (when it ends, seconds since 1970), ok, text,
    name}, as the plugin says."""
    return {"source": _text(j.get("source")) or "", "label": _text(j.get("label")) or _text(j.get("source")) or "",
            "until": _num(j.get("until")), "ok": j.get("ok") is True, "text": _text(j.get("text")), "name": _text(j.get("name"))}


def _shown(body: dict, plugin_id: str, site: str) -> dict:
    """The plugin's clips, as Stream control's Clips panel shows them (anything it doesn't say given a plain default)."""
    folder = body.get("folder") if isinstance(body.get("folder"), dict) else {}
    least, most = int(_num(body.get("least"), 1)), int(_num(body.get("most"), 300))
    return {
        "plugin": plugin_id, "site": site,
        "seconds": int(_num(body.get("seconds"), least)), "least": least, "most": most,
        "held": round(_num(body.get("held")), 1),
        "sources": [{"key": s["key"], "label": _text(s.get("label")) or s["key"]}
                    for s in _dicts(body.get("sources")) if _text(s.get("key"))] or [{"key": "stream", "label": "Stream"}],
        "recording": [_job(j) for j in _dicts(body.get("recording"))],
        "ended": [_job(j) for j in _dicts(body.get("ended"))],
        "folder": {"path": _text(folder.get("path")), "shown_as": _text(folder.get("shown_as")), "problem": _text(folder.get("problem"))},
        "clips": [{"name": x["name"], "size": int(_num(x.get("size"))), "made": _text(x.get("made"))}
                  for x in _dicts(body.get("clips")) if _text(x.get("name"))],
    }


def state(db: Session, plugin_id: str) -> dict:
    """A stream plugin's clips: {plugin, site, seconds, least, most, held (seconds of its stream it holds to clip),
    sources [{key, label}] ("stream", then each camera), recording, ended, folder {path, shown_as, problem}, clips}."""
    _, body, site = _call(db, plugin_id, "GET")
    return _shown(body, plugin_id, site)


def set_length(db: Session, plugin_id: str, seconds: int) -> dict:
    """How long that plugin's clips are (it checks the range): its clips, as state()."""
    _, body, site = _call(db, plugin_id, "PUT", payload={"seconds": seconds})
    return _shown(body, plugin_id, site)


def take(db: Session, plugin_id: str, source: str, seconds: int | None, tz: str | None) -> dict:
    """Take a clip with that plugin: {saved: {name, seconds, size}} for the stream (saved at once), {recording: {...}} for
    a camera (being recorded), and its clips afterwards (`clips`, as state(); None when the plugin didn't answer that:
    the clip was taken all the same, so the page asks again rather than the clip being taken twice)."""
    payload = {"source": source, "tz": tz, **({"seconds": seconds} if seconds else {})}
    code, body, site = _call(db, plugin_id, "POST", payload=payload, timeout=SAVE_TIMEOUT)
    if isinstance(body.get("recording"), dict):
        done = {"recording": _job(body["recording"])}
    else:
        done = {"saved": {"name": _text(body.get("name")), "seconds": _num(body.get("seconds")), "size": int(_num(body.get("size")))}}
    try:
        after = state(db, plugin_id)
    except (ValueError, NotFound):
        after = None
    return {**done, "clips": after}


def download(db: Session, plugin_id: str, name: str) -> tuple[Iterator[bytes], dict]:
    """One of that plugin's clips, passed on as it comes: (its bytes, the headers to answer with). NotFound when
    the plugin hasn't got it; ValueError when it can't be asked."""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise NotFound("No such clip.")
    address, site = _target(db, plugin_id)
    client = httpx.Client(transport=remote.transport, timeout=DOWNLOAD_TIMEOUT, follow_redirects=False)
    try:
        r = client.send(client.build_request("GET", f"{address}{CLIPS_PATH}/{quote(name)}"), stream=True)
    except httpx.HTTPError as e:
        client.close()
        raise ValueError(f"{site}: {remote.unreachable(address, e)}") from None
    if r.status_code != 200:
        r.close()
        client.close()
        if r.status_code == 404:
            raise NotFound(f"{site} hasn't got a clip called \"{name}\" (any more).")
        raise ValueError(f"The plugin answered {r.status_code}.")

    def body() -> Iterator[bytes]:
        try:
            yield from r.iter_bytes(CHUNK)
        finally:
            r.close()
            client.close()

    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"}
    if r.headers.get("content-length"):
        headers["Content-Length"] = r.headers["content-length"]
    return body(), headers
