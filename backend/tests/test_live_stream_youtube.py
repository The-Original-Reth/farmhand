"""The Stream page and YouTube: signing in, the broadcast Farmhand makes, changes, watches and ends, and its settings."""
from __future__ import annotations

import time

import pytest

from app.services import live_stream, youtube_live

from .factories import api_db as _db, wait_for as _wait_for, webcam as _cam
from .fake_google import CLIENT_ID, SECRET, signed_in as _signed_in

pytestmark = pytest.mark.usefixtures("stream_fresh")

KEY = "abcd-efgh-ijkl-mnop-qrst"


def test_signing_in_to_youtube_with_a_code(klipper, google):
    api, _ = klipper
    assert "client ID" in api.post("/stream/youtube/sign-in").json()["detail"]
    assert "client ID" in api.put("/stream/youtube", json={"client_id": "nope", "client_secret": SECRET}).json()["detail"]
    assert "secret too" in api.put("/stream/youtube", json={"client_id": CLIENT_ID}).json()["detail"]
    r = api.put("/stream/youtube", json={"client_id": CLIENT_ID, "client_secret": SECRET})
    assert r.json()["youtube"]["client_set"] is True and SECRET not in r.text

    yt = api.post("/stream/youtube/sign-in").json()["youtube"]
    assert yt["signing_in"] == {"user_code": "ABCD-EFGH", "verification_url": "https://www.google.com/device"}
    assert api.get("/stream").json()["youtube"]["signed_in"] is False  # not entered yet: still waiting
    google.entered = True
    yt = api.get("/stream").json()["youtube"]
    assert yt["signed_in"] is True and yt["channel"] == "3D Printing Elves" and yt["signing_in"] is None
    assert "rt-1" not in api.get("/stream").text

    # the same client again, secret left blank: kept, still signed in
    assert api.put("/stream/youtube", json={"client_id": CLIENT_ID}).json()["youtube"]["signed_in"] is True
    yt = api.post("/stream/youtube/sign-out", json={}).json()["youtube"]
    assert yt["signed_in"] is False and yt["client_set"] is True and google.revoked == ["rt-1"]
    assert api.post("/stream/youtube/sign-out", json={"forget_client": True}).json()["youtube"]["client_set"] is False


def test_turning_the_sign_in_down_says_so(klipper, google):
    api, _ = klipper
    api.put("/stream/youtube", json={"client_id": CLIENT_ID, "client_secret": SECRET})
    api.post("/stream/youtube/sign-in")
    google.denied = True
    yt = api.get("/stream").json()["youtube"]
    assert yt["signed_in"] is False and yt["signing_in"] is None and "turned it down" in yt["error"]


def test_the_title_and_description_are_set_on_the_live_broadcast(klipper, google):
    api, _ = klipper
    assert "Sign in to YouTube" in api.post("/stream/youtube/apply").json()["detail"]
    _signed_in(api, google)
    assert "title or description" in api.post("/stream/youtube/apply").json()["detail"]
    api.put("/stream", json={"title": "Farm live", "description": ""})
    assert api.post("/stream/youtube/apply").status_code == 200  # tried; not live, so nothing to show for it
    creds = youtube_live.credentials(_db(api))
    with pytest.raises(youtube_live.YouTubeError) as e:
        youtube_live.set_broadcast_text(creds, "Farm live", "")
    assert e.value.retry is True

    google.broadcasts = [{"id": "vid-9", "snippet": {"title": "Old"}}]
    google.videos["vid-9"] = {"title": "Old", "description": "Kept description", "categoryId": "20", "tags": ["voron"]}
    done = youtube_live.set_broadcast_text(creds, "Farm live", "")
    assert done == {"video_id": "vid-9", "title": "Farm live"}
    assert google.videos["vid-9"] == {"title": "Farm live", "description": "Kept description", "categoryId": "20", "tags": ["voron"]}


def test_going_live_signed_in_makes_the_broadcast_on_farmhands_own_stream(klipper, moonraker, ffmpeg, google, monkeypatch):
    api, pid = klipper
    monkeypatch.setattr(live_stream.broadcast, "YOUTUBE_FIRST", 0)
    moonraker.webcams = [_cam()]
    _signed_in(api, google)
    yt = {"privacy": "unlisted", "tags": ["3D print farm", "Voron"], "category": "27", "made_for_kids": False, "latency": "low",
          "dvr": False, "auto_start": True, "auto_stop": True}
    page = api.put("/stream", json={"cameras": [f"{pid}:Bed"], "show_status": False, "title": "Farm live", "description": "Printing all day", "delay": 0,
                                    "youtube": yt}).json()
    assert page["settings"]["youtube"] == yt and page["settings"]["key_set"] is False  # no key pasted: YouTube gives one
    status = api.post("/stream/start").json()["status"]
    assert status["live"] is True and status["title"]["state"] == "done" and "unlisted" in status["title"]["message"]

    # Farmhand's own stream (any resolution), its key from YouTube; one broadcast bound to it, set from the settings
    (sid, stream), = google.streams.items()
    assert stream["cdn"]["resolution"] == "variable" and stream["contentDetails"]["isReusable"] is True
    sender = ffmpeg.senders[0]
    assert sender[-1] == f"rtmps://a.rtmps.youtube.com/live2/key-{sid}"
    (bid, b), = google.made.items()
    assert b["bound"] == sid and b["status"] == {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False}
    assert b["contentDetails"]["enableAutoStart"] is True and b["contentDetails"]["latencyPreference"] == "low" and b["contentDetails"]["enableDvr"] is False
    assert google.videos[bid] == {"title": "Farm live", "description": "Printing all day", "categoryId": "27", "tags": ["3D print farm", "Voron"]}
    assert api.get("/stream").json()["settings"]["key_from_youtube"] is True

    # the page shows the broadcast's links and YouTube's word on it
    assert _wait_for(lambda: (live_stream.stream.status()["youtube"] or {}).get("health") == "good")
    seen = live_stream.stream.status()["youtube"]
    assert seen["watch_url"] == f"https://www.youtube.com/watch?v={bid}" and bid in seen["studio_url"]
    assert seen["issues"] == ["Use a higher bitrate."] and seen["viewers"] == 7 and seen["state"] == "ready"

    # changed while live: straight onto the broadcast going out, the stream not started again
    n = len(ffmpeg.commands)
    api.put("/stream", json={"title": "Night shift", "youtube": {"privacy": "public", "tags": ["night"]}})
    assert google.videos[bid]["title"] == "Night shift" and google.videos[bid]["tags"] == ["night"]
    assert google.made[bid]["status"]["privacyStatus"] == "public" and len(ffmpeg.commands) == n
    assert "new title" in live_stream.stream.status()["title"]["message"]

    # stopped before it ever went live on YouTube: the empty broadcast is deleted, not left waiting
    api.post("/stream/stop")
    assert _wait_for(lambda: google.deleted == [bid])

    # the next time: the same stream (its id kept), a new broadcast; one that went live is ended instead
    api.post("/stream/start")
    assert len(google.streams) == 1 and len(google.made) == 1
    (bid2, _), = google.made.items()
    google.made[bid2]["life"] = "live"
    api.post("/stream/stop")
    assert _wait_for(lambda: google.ended == [bid2])


def test_a_broadcast_youtube_ends_while_live_is_replaced(klipper, moonraker, ffmpeg, google, monkeypatch):
    # left running day and night: YouTube ends the broadcast (its auto-stop after a long drop, or ended in Studio),
    # and Farmhand, still sending, makes a new one on the same stream
    api, pid = klipper
    monkeypatch.setattr(live_stream.broadcast, "YOUTUBE_EVERY", 0.05)
    monkeypatch.setattr(live_stream.broadcast, "YOUTUBE_FIRST", 0)
    from sqlalchemy.orm import sessionmaker

    from app import database

    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=_db(api).get_bind(), future=True))  # (the saved settings are read again)
    moonraker.webcams = [_cam()]
    _signed_in(api, google)
    api.put("/stream", json={"cameras": [f"{pid}:Bed"], "show_status": False, "title": "Farm live", "delay": 0})
    api.post("/stream/start")
    (first, _), = google.made.items()
    assert _wait_for(lambda: (live_stream.stream.status()["youtube"] or {}).get("health") == "good")
    google.made[first]["life"] = "complete"
    assert _wait_for(lambda: len(google.made) == 2)
    new = [k for k in google.made if k != first][0]
    assert google.made[new]["bound"] == google.made[first]["bound"] and len(ffmpeg.senders) == 1  # the stream went on
    assert _wait_for(lambda: new in (live_stream.stream.status()["youtube"] or {}).get("watch_url", ""))
    assert "made a new one" in live_stream.stream.status()["title"]["message"]
    time.sleep(0.2)
    assert len(google.made) == 2  # the new one isn't ended: no more are made


def test_youtube_refusing_the_broadcast_says_why_and_nothing_goes_out(klipper, moonraker, ffmpeg, google):
    api, pid = klipper
    moonraker.webcams = [_cam()]
    _signed_in(api, google)
    google.refuse_broadcast = True
    api.put("/stream", json={"cameras": [f"{pid}:Bed"], "show_status": False})
    r = api.post("/stream/start")
    assert r.status_code == 422 and "wouldn't make the broadcast" in r.json()["detail"] and "not enabled for live streaming" in r.json()["detail"]
    assert live_stream.stream.status()["live"] is False and not ffmpeg.senders


def test_no_key_and_not_signed_in_says_both_ways(klipper, moonraker, ffmpeg):
    api, pid = klipper
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"cameras": [f"{pid}:Bed"], "show_status": False})
    detail = api.post("/stream/start").json()["detail"]
    assert "Sign in to YouTube" in detail and "stream key" in detail


def test_youtube_settings_are_checked(klipper):
    api, _ = klipper
    assert "public, unlisted or private" in api.put("/stream", json={"youtube": {"privacy": "secret"}}).json()["detail"]
    assert "categories" in api.put("/stream", json={"youtube": {"category": "99"}}).json()["detail"]
    assert "< or >" in api.put("/stream", json={"youtube": {"tags": ["<b>"]}}).json()["detail"]
    assert "500 characters" in api.put("/stream", json={"youtube": {"tags": ["x" * 300, "y" * 300]}}).json()["detail"]
    yt = api.put("/stream", json={"youtube": {"tags": [" farm ", "farm", "", "toys"], "made_for_kids": True}}).json()["settings"]["youtube"]
    assert yt["tags"] == ["farm", "toys"] and yt["made_for_kids"] is True and yt["privacy"] == "public"  # the rest kept


def test_going_live_without_signing_in_says_the_title_wont_be_set(klipper, moonraker, ffmpeg):
    api, pid = klipper
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False, "title": "Farm live"})
    status = api.post("/stream/start").json()["status"]
    assert status["title"]["state"] == "failed" and "Sign in to YouTube" in status["title"]["message"]
