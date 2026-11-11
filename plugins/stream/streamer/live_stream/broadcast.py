"""
The YouTube side of a time live, when Farmhand is signed in to the channel: Farmhand's own stream there (where the
video goes, its key from YouTube) and the broadcast on it (made on Go live from the YouTube settings, changed when they
change, watched while live, made again if YouTube ends it, ended on Stop). The runner (runner.py) holds one Broadcast
per time live; with a pasted key there is none, and YouTube makes the broadcast itself.
"""
from __future__ import annotations

import threading
from typing import Callable

from ..store import Session

from .. import app_settings, youtube_live

YOUTUBE_EVERY = 120  # seconds between asking YouTube about the broadcast (its health, viewers): ~2,200 of the 10,000 units a day
YOUTUBE_FIRST = 20  # seconds after the delay has passed (the video reaching YouTube) before asking it the first time
ENDED = ("complete", "revoked", "gone")  # a broadcast YouTube has ended (auto-stop after a long drop, or ended in Studio)
NOTHING_YET = {"state": None, "health": None, "issues": [], "viewers": None}


def own_stream(db: Session, creds: dict) -> dict:
    """Farmhand's own stream on the signed-in channel, {id, key, url}, made the first time (its id kept, so the same one
    is used every time). ValueError when YouTube won't give it."""
    kept = app_settings.get(db, youtube_live.STREAM_KEY)
    try:
        own = youtube_live.own_stream(creds, kept)
    except youtube_live.YouTubeError as e:
        raise ValueError(f"YouTube wouldn't give Farmhand its stream: {e}") from None
    if kept != own["id"]:
        app_settings.put(db, youtube_live.STREAM_KEY, own["id"])
        db.commit()
    return own


def title_on_active(db: Session, chosen: dict) -> dict:
    """Live on a pasted key (YouTube made the broadcast): the chosen title and description set on the channel's active
    broadcast, {state, message}. ValueError when it can't be tried (not signed in, or nothing to set)."""
    creds = youtube_live.credentials(db)
    if not creds:
        raise ValueError("Sign in to YouTube first.")
    if not (chosen["title"] or chosen["description"]):
        raise ValueError("Write a title or description first, and save it.")
    try:
        done = youtube_live.set_broadcast_text(creds, chosen["title"], chosen["description"])
        return {"state": "done", "message": f"Title and description set on “{done['title']}”."}
    except youtube_live.YouTubeError as e:
        return {"state": "failed", "message": f"The YouTube title wasn't set: {e}"}


def _title_of(chosen: dict) -> str:
    return (chosen["title"] or "Live")[:100]


class Broadcast:
    """This time live's broadcast on YouTube: its links, and what YouTube last said of it. Its own lock guards both, as
    the broadcast may be made again (a new id and links) while the page reads it."""

    def __init__(self, creds: dict, stream_id: str, made: dict):
        self._lock = threading.Lock()
        self.creds, self.stream_id = creds, stream_id
        self._made = made  # {id, watch_url, studio_url}
        self._health: dict | None = None
        self.ended = False  # Stop: nothing more is asked of YouTube, and none is made again

    @classmethod
    def start(cls, creds: dict, own: dict, chosen: dict) -> "Broadcast":
        """A new broadcast bound to Farmhand's own stream `own`, set from the chosen settings. ValueError says why not."""
        try:
            made = youtube_live.start_broadcast(creds, own["id"], chosen["youtube"], chosen["title"], chosen["description"])
        except youtube_live.YouTubeError as e:
            raise ValueError(f"YouTube wouldn't make the broadcast: {e}") from None
        return cls(creds, own["id"], made)

    @staticmethod
    def made_message(chosen: dict) -> dict:
        return {"state": "done", "message": f"Broadcast made on YouTube ({chosen['youtube']['privacy']}): “{_title_of(chosen)}”."}

    @property
    def id(self) -> str:
        with self._lock:
            return self._made["id"]

    def status(self) -> dict:
        """Its links and what YouTube last said of it: {watch_url, studio_url, state, health, issues, viewers}."""
        with self._lock:
            return {"watch_url": self._made["watch_url"], "studio_url": self._made["studio_url"], **(self._health or NOTHING_YET)}

    def update(self, chosen: dict) -> dict:
        """The video's settings changed while live: changed on the broadcast going out straight away. {state, message}."""
        try:
            youtube_live.update_broadcast(self.creds, self.id, chosen["youtube"], chosen["title"], chosen["description"])
            return {"state": "done", "message": "The broadcast on YouTube has the new title, description, tags and privacy."}
        except youtube_live.YouTubeError as e:
            return {"state": "failed", "message": f"The broadcast on YouTube wasn't changed: {e}"}

    def watch(self, delay: float, wait: Callable[[float], bool], read_settings: Callable[[], dict],
              said: Callable[[dict], None]) -> None:
        """For as long as `wait(seconds)` says this time live goes on, page open or not: once the delay has passed and
        YouTube has had the video a few seconds (before that it has nothing to say), ask YouTube about the broadcast
        every YOUTUBE_EVERY seconds. One YouTube has ended while Farmhand is still sending (its auto-stop after a long
        drop, or ended in Studio) is replaced by a new one on the same stream, from the saved settings (`read_settings`),
        so a stream left running day and night never ends up with nowhere to show; `said` gets what came of it."""
        if not wait(delay + YOUTUBE_FIRST):
            return
        while not self.ended:
            try:
                got = youtube_live.health(self.creds, self.stream_id, self.id)
            except youtube_live.YouTubeError as e:
                got = {**NOTHING_YET, "issues": [f"Couldn't ask YouTube: {e}"]}
            with self._lock:
                self._health = got
            if got["state"] in ENDED and not self.ended:
                said(self._make_again(read_settings))
            if not wait(YOUTUBE_EVERY):
                return

    def _make_again(self, read_settings: Callable[[], dict]) -> dict:
        try:
            chosen = read_settings()
            made = youtube_live.start_broadcast(self.creds, self.stream_id, chosen["youtube"], chosen["title"], chosen["description"])
        except youtube_live.YouTubeError as e:
            return {"state": "failed", "message": f"YouTube ended the broadcast and wouldn't make a new one ({e}); trying again in {YOUTUBE_EVERY // 60} minutes."}
        with self._lock:
            self._made, self._health = made, None
            stopped = self.ended
        if stopped:  # (stopped meanwhile: the new one isn't needed)
            self.end()
        return {"state": "done", "message": f"YouTube had ended the broadcast, so Farmhand made a new one: “{_title_of(chosen)}”."}

    def end(self) -> None:
        """Stop: ended on YouTube in a thread of its own (stopping never waits on YouTube); it becomes the channel's saved
        video, or is deleted if it never went live."""
        self.ended = True
        threading.Thread(target=self._end_quietly, args=(self.id,), name="stream-youtube-end", daemon=True).start()

    def _end_quietly(self, broadcast_id: str) -> None:
        try:
            youtube_live.end_broadcast(self.creds, broadcast_id)
        except youtube_live.YouTubeError:
            pass  # (it ends by itself when the stream stops, auto-stop being on)
