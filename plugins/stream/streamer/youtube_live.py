"""
Farmhand signed in to a YouTube channel, to set the live broadcast's own title and description (the stream key alone
can only send the picture).

Signing in uses Google's sign-in for TVs and other devices: the farm's owner makes an OAuth client of the type "TVs and
Limited Input devices" in Google Cloud (with the YouTube Data API v3 turned on) and enters its client ID and secret on
the Stream page. Sign in then shows a code, which they enter at google.com/device in any browser, signed in to Google
there; Farmhand never sees their Google password. Farmhand asks Google whether the code has been entered each time the
Stream page asks for its state (account()), so nothing runs in the background.

Kept in app_settings, never answered by the API and never written to the settings copy: the client secret and the
refresh token. Signing out forgets the token and tells Google to forget it too.
"""
from __future__ import annotations

import json
import re
import threading
import time

import httpx
from .store import Session

from . import app_settings

SCOPE = "https://www.googleapis.com/auth/youtube"
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)

CLIENT_KEY = "youtube_client"  # {client_id, client_secret}
TOKEN_KEY = "youtube_refresh_token"
CHANNEL_KEY = "youtube_channel"  # the channel's name, as signed in

CLIENT_ID_SHAPE = re.compile(r"^[A-Za-z0-9\-_.]{3,200}\.apps\.googleusercontent\.com$")
SECRET_SHAPE = re.compile(r"^[A-Za-z0-9\-_]{10,200}$")
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

# Tests swap this for an httpx.MockTransport that plays a fake Google
transport: httpx.BaseTransport | None = None

_lock = threading.Lock()
_sign_in: dict = {"pending": None, "error": None}  # a sign-in under way: the code shown and when to ask Google next
_tokens: dict[str, tuple[str, float]] = {}  # refresh token -> (access token, when it runs out)


class YouTubeError(Exception):
    """Google or YouTube said no. retry: worth trying again shortly (the broadcast isn't there yet)."""

    def __init__(self, message: str, retry: bool = False):
        super().__init__(message)
        self.retry = retry


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=transport)


def _google_says(r: httpx.Response) -> str:
    """Google's own reason, from either of its error shapes."""
    try:
        body = r.json()
    except ValueError:
        return f"{r.status_code} {r.text[:200]}"
    err = body.get("error")
    if isinstance(err, dict):
        return err.get("message") or str(err.get("code") or r.status_code)
    return body.get("error_description") or str(err or r.status_code)


def _post(url: str, data: dict) -> httpx.Response:
    try:
        with _client() as c:
            return c.post(url, data=data)
    except httpx.HTTPError as e:
        raise YouTubeError(f"Google couldn't be reached ({type(e).__name__}). Is the internet connection up?", retry=True) from None


# ------------------------------------------------------------------ the OAuth client and signing in


def _client_info(db: Session) -> dict | None:
    try:
        raw = json.loads(app_settings.get(db, CLIENT_KEY) or "null")
    except ValueError:
        return None
    return raw if isinstance(raw, dict) and raw.get("client_id") and raw.get("client_secret") else None


def set_client(db: Session, client_id: str, client_secret: str | None) -> None:
    """Keep the OAuth client (a blank secret keeps the saved one). Changing the client signs out."""
    client_id = (client_id or "").strip()
    if not CLIENT_ID_SHAPE.match(client_id):
        raise ValueError("That doesn't look like a Google client ID: it ends in .apps.googleusercontent.com.")
    saved = _client_info(db) or {}
    secret = (client_secret or "").strip() or (saved.get("client_secret") if saved.get("client_id") == client_id else "")
    if not secret:
        raise ValueError("Paste the client secret too (from the same OAuth client in Google Cloud).")
    if not SECRET_SHAPE.match(secret):
        raise ValueError("That doesn't look like a Google client secret.")
    if saved.get("client_id") != client_id:
        _forget_sign_in(db)
    app_settings.put(db, CLIENT_KEY, json.dumps({"client_id": client_id, "client_secret": secret}))
    db.commit()


def start_sign_in(db: Session) -> dict:
    """Ask Google for a code to show: the page then shows it with google.com/device. Answers account()."""
    client = _client_info(db)
    if not client:
        raise ValueError("Add the Google OAuth client ID and secret first.")
    r = _post(DEVICE_URL, {"client_id": client["client_id"], "scope": SCOPE})
    if r.status_code >= 400:
        raise ValueError(f"Google wouldn't start the sign-in: {_google_says(r)}. Check the client is of the type “TVs and Limited Input devices”.")
    body = r.json()
    now = time.monotonic()
    interval = int(body["interval"]) if isinstance(body.get("interval"), int) else 5  # how often Google lets it ask
    with _lock:
        _sign_in["pending"] = {
            "device_code": body["device_code"],
            "user_code": body["user_code"],
            "verification_url": body.get("verification_url") or body.get("verification_uri") or "https://www.google.com/device",
            "expires_at": now + int(body.get("expires_in") or 1800),
            "interval": interval,
            "next": now + interval,
        }
        _sign_in["error"] = None
    return account(db)


def _check_sign_in(db: Session) -> None:
    """A sign-in under way: ask Google once whether the code has been entered (no more often than it allows)."""
    with _lock:
        pending = _sign_in["pending"]
        if not pending or time.monotonic() < pending["next"]:
            return
        if time.monotonic() > pending["expires_at"]:
            _sign_in.update(pending=None, error="The sign-in code ran out before it was entered. Press Sign in again.")
            return
        pending["next"] = time.monotonic() + pending["interval"]
    client = _client_info(db)
    if not client:
        return
    try:
        r = _post(TOKEN_URL, {"client_id": client["client_id"], "client_secret": client["client_secret"],
                              "device_code": pending["device_code"], "grant_type": DEVICE_GRANT})
    except YouTubeError:
        return  # asked again next time
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code < 400 and body.get("refresh_token"):
        app_settings.put(db, TOKEN_KEY, body["refresh_token"])
        _tokens[body["refresh_token"]] = (body.get("access_token") or "", time.monotonic() + int(body.get("expires_in") or 0) - 60)
        channel = None
        try:
            channel = _channel_name(body["access_token"])
        except (YouTubeError, KeyError):
            pass
        app_settings.put(db, CHANNEL_KEY, channel)
        db.commit()
        with _lock:
            _sign_in.update(pending=None, error=None)
        return
    reason = body.get("error")
    with _lock:
        if reason == "authorization_pending":
            return
        if reason == "slow_down":
            pending["interval"] += 5
            return
        _sign_in["pending"] = None
        _sign_in["error"] = ("You turned it down on Google's page. Press Sign in to try again." if reason == "access_denied"
                             else f"Google didn't sign in: {_google_says(r)}")


def _forget_sign_in(db: Session) -> None:
    token = app_settings.get(db, TOKEN_KEY)
    if token:
        _tokens.pop(token, None)
        try:
            _post(REVOKE_URL, {"token": token})  # Google forgets it too; never minded if it can't be told
        except YouTubeError:
            pass
    app_settings.put(db, TOKEN_KEY, None)
    app_settings.put(db, CHANNEL_KEY, None)
    with _lock:
        _sign_in.update(pending=None, error=None)


def sign_out(db: Session, forget_client: bool = False) -> None:
    _forget_sign_in(db)
    if forget_client:
        app_settings.put(db, CLIENT_KEY, None)
    db.commit()


def account(db: Session) -> dict:
    """
    {client_set, client_id, signed_in, channel, signing_in: {user_code, verification_url} | null, error}. The secret
    and the token are never given. A sign-in under way is checked with Google first.
    """
    _check_sign_in(db)
    client = _client_info(db)
    with _lock:
        pending = _sign_in["pending"]
        error = _sign_in["error"]
    return {
        "client_set": bool(client),
        "client_id": client["client_id"] if client else None,
        "signed_in": bool(app_settings.get(db, TOKEN_KEY)),
        "channel": app_settings.get(db, CHANNEL_KEY),
        "signing_in": {"user_code": pending["user_code"], "verification_url": pending["verification_url"]} if pending else None,
        "error": error,
    }


def credentials(db: Session) -> dict | None:
    """What setting a title needs, read now so a thread can use it later: {client_id, client_secret, refresh_token}."""
    client = _client_info(db)
    token = app_settings.get(db, TOKEN_KEY)
    return {**client, "refresh_token": token} if client and token else None


# ------------------------------------------------------------------ the broadcast's title and description


def _access_token(creds: dict) -> str:
    kept = _tokens.get(creds["refresh_token"])
    if kept and kept[0] and time.monotonic() < kept[1]:
        return kept[0]
    r = _post(TOKEN_URL, {"client_id": creds["client_id"], "client_secret": creds["client_secret"],
                          "refresh_token": creds["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code >= 400:
        raise YouTubeError(f"Google turned the sign-in down ({_google_says(r)}). Sign out and sign in to YouTube again.")
    body = r.json()
    _tokens[creds["refresh_token"]] = (body["access_token"], time.monotonic() + int(body.get("expires_in") or 3600) - 60)
    return body["access_token"]


def _api(method: str, path: str, token: str, params: dict, body: dict | None = None) -> dict:
    try:
        with _client() as c:
            r = c.request(method, f"{API}{path}", params=params, json=body, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        raise YouTubeError(f"YouTube couldn't be reached ({type(e).__name__}).", retry=True) from None
    if r.status_code >= 400:
        raise YouTubeError(f"YouTube said: {_google_says(r)}", retry=r.status_code >= 500)
    return r.json() if r.content else {}  # (a delete answers with nothing)


def _channel_name(token: str) -> str | None:
    items = _api("GET", "/channels", token, {"part": "snippet", "mine": "true"}).get("items") or []
    return (items[0].get("snippet") or {}).get("title") if items else None


def set_broadcast_text(creds: dict, title: str, description: str) -> dict:
    """
    Give the channel's live broadcast this title and description (a blank one keeps what it has): {video_id, title}.
    YouTubeError(retry=True) while there's no live broadcast yet.
    """
    token = _access_token(creds)
    found = _api("GET", "/liveBroadcasts", token, {"part": "id,snippet", "broadcastStatus": "active", "broadcastType": "all", "maxResults": 5})
    items = found.get("items") or []
    if not items:
        raise YouTubeError("YouTube has no live broadcast on the channel yet.", retry=True)
    video_id = items[0]["id"]
    videos = _api("GET", "/videos", token, {"part": "snippet", "id": video_id}).get("items") or []
    old = (videos[0].get("snippet") if videos else None) or {}
    snippet = {
        "title": title or old.get("title") or "Live",
        "description": description if description else old.get("description", ""),
        "categoryId": old.get("categoryId") or "28",  # Science & Technology, when it had none
    }
    if old.get("tags"):
        snippet["tags"] = old["tags"]
    _api("PUT", "/videos", token, {"part": "snippet"}, {"id": video_id, "snippet": snippet})
    return {"video_id": video_id, "title": snippet["title"]}


# ------------------------------------------------------------------ Farmhand's own stream and broadcasts on YouTube
# Signed in, Farmhand runs the YouTube side itself: a live stream of its own on the channel (its stream key from YouTube,
# any resolution), a new broadcast each time it goes live (the video's settings from the YouTube settings window; it
# starts by itself when the stream arrives, so YouTube Studio needn't be open), ended when it stops, and the
# broadcast's health and viewers read now and then for the Stream page.

STREAM_KEY = "youtube_stream_id"  # Farmhand's own live stream on the channel
STREAM_TITLE = "Farmhand"
LATENCY = {"normal": "normal", "low": "low", "ultraLow": "ultraLow"}


def own_stream(creds: dict, stream_id: str | None) -> dict:
    """Farmhand's own live stream on the channel, made when there's none (or the one kept has gone): {id, key, url}
    (url: the RTMPS address the key goes on the end of). It takes any resolution and frame rate, so changing them never
    needs another."""
    token = _access_token(creds)
    if stream_id:
        items = _api("GET", "/liveStreams", token, {"part": "id,cdn", "id": stream_id}).get("items") or []
        if items:
            return _stream_out(items[0])
    made = _api("POST", "/liveStreams", token, {"part": "snippet,cdn,contentDetails"}, {
        "snippet": {"title": STREAM_TITLE, "description": "Farmhand's own stream: its broadcasts are made and ended by Farmhand."},
        "cdn": {"ingestionType": "rtmp", "resolution": "variable", "frameRate": "variable"},
        "contentDetails": {"isReusable": True},
    })
    return _stream_out(made)


def _stream_out(item: dict) -> dict:
    info = (item.get("cdn") or {}).get("ingestionInfo") or {}
    url = info.get("rtmpsIngestionAddress") or "rtmps://a.rtmps.youtube.com/live2"
    return {"id": item["id"], "key": info.get("streamName") or "", "url": url.rstrip("/") + "/"}


def _video_snippet(yt: dict, title: str, description: str) -> dict:
    snippet = {"title": (title or "Live")[:100], "description": description or "", "categoryId": yt.get("category") or "28"}
    if yt.get("tags"):
        snippet["tags"] = list(yt["tags"])
    return snippet


def start_broadcast(creds: dict, stream_id: str, yt: dict, title: str, description: str) -> dict:
    """A new broadcast on the channel, bound to Farmhand's own stream, set from the YouTube settings (`yt`: privacy, tags,
    category, made_for_kids, latency, dvr, auto_start, auto_stop): {id, watch_url, studio_url}. It starts by itself
    when the stream reaches YouTube (unless auto_start is off: then it's started in YouTube Studio)."""
    token = _access_token(creds)
    made = _api("POST", "/liveBroadcasts", token, {"part": "snippet,status,contentDetails"}, {
        "snippet": {"title": (title or "Live")[:100], "description": description or "",
                    "scheduledStartTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "status": {"privacyStatus": yt.get("privacy") or "public", "selfDeclaredMadeForKids": bool(yt.get("made_for_kids"))},
        "contentDetails": {"enableAutoStart": yt.get("auto_start", True) is not False, "enableAutoStop": yt.get("auto_stop", True) is not False,
                           "enableDvr": yt.get("dvr", True) is not False, "latencyPreference": LATENCY.get(yt.get("latency"), "normal"),
                           "monitorStream": {"enableMonitorStream": False}},
    })
    bid = made["id"]
    _api("POST", "/liveBroadcasts/bind", token, {"id": bid, "part": "id,contentDetails", "streamId": stream_id})
    try:  # the tags and category live on the video (the broadcast's own id)
        _api("PUT", "/videos", token, {"part": "snippet"}, {"id": bid, "snippet": _video_snippet(yt, title, description)})
    except YouTubeError:
        pass  # (the broadcast still goes ahead; the page says the tags weren't set when it reads the health)
    return {"id": bid, "watch_url": f"https://www.youtube.com/watch?v={bid}", "studio_url": f"https://studio.youtube.com/video/{bid}/livestreaming"}


def update_broadcast(creds: dict, broadcast_id: str, yt: dict, title: str, description: str) -> None:
    """Change the live broadcast's title, description, tags, category, privacy and made for kids straight away."""
    token = _access_token(creds)
    _api("PUT", "/videos", token, {"part": "snippet,status"}, {
        "id": broadcast_id, "snippet": _video_snippet(yt, title, description),
        "status": {"privacyStatus": yt.get("privacy") or "public", "selfDeclaredMadeForKids": bool(yt.get("made_for_kids"))},
    })


def end_broadcast(creds: dict, broadcast_id: str) -> None:
    """End the broadcast (it becomes the channel's saved video). One that never went live is deleted instead, so no
    empty broadcast is left waiting. Never minded if YouTube has already ended it."""
    token = _access_token(creds)
    try:
        _api("POST", "/liveBroadcasts/transition", token, {"broadcastStatus": "complete", "id": broadcast_id, "part": "status"})
    except YouTubeError:
        try:
            items = _api("GET", "/liveBroadcasts", token, {"part": "status", "id": broadcast_id}).get("items") or []
            life = ((items[0].get("status") or {}).get("lifeCycleStatus") if items else None) or ""
            if life in ("created", "ready", "testStarting", "testing"):
                _api("DELETE", "/liveBroadcasts", token, {"id": broadcast_id})
        except YouTubeError:
            pass


def health(creds: dict, stream_id: str, broadcast_id: str | None) -> dict:
    """What YouTube says now: {state: the broadcast's (created, ready, testing, live, complete...), health: good | ok |
    bad | noData, issues: [YouTube's own warnings], viewers: watching now (None while not live)}."""
    token = _access_token(creds)
    out = {"state": None, "health": None, "issues": [], "viewers": None}
    streams = _api("GET", "/liveStreams", token, {"part": "status", "id": stream_id}).get("items") or []
    if streams:
        h = (streams[0].get("status") or {}).get("healthStatus") or {}
        out["health"] = h.get("status")
        out["issues"] = [i.get("description") or i.get("reason") or i.get("type") for i in h.get("configurationIssues") or []
                         if (i.get("severity") or "") in ("error", "warning")][:5]
    if broadcast_id:
        items = _api("GET", "/liveBroadcasts", token, {"part": "status", "id": broadcast_id}).get("items") or []
        out["state"] = ((items[0].get("status") or {}).get("lifeCycleStatus")) if items else "gone"
        videos = _api("GET", "/videos", token, {"part": "liveStreamingDetails", "id": broadcast_id}).get("items") or []
        viewers = ((videos[0].get("liveStreamingDetails") or {}).get("concurrentViewers")) if videos else None
        out["viewers"] = int(viewers) if viewers is not None and str(viewers).isdigit() else None
    return out


def reset() -> None:
    """Forget any sign-in under way and the access tokens kept (tests)."""
    with _lock:
        _sign_in.update(pending=None, error=None)
    _tokens.clear()
