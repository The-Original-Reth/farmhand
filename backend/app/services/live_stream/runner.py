"""
The stream itself: ffmpeg kept running for as long as the stream is meant to be live, the words on the cameras kept current, and the YouTube title set once the broadcast is there.
"""
from __future__ import annotations

import collections
import os
import shutil
import subprocess
import tempfile
import threading
import time

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ...models import Printer
from .. import app_settings, print_progress, stream_media, youtube_live
from . import staging
from .constants import DESTINATIONS, KEPT_LINES, RETRY_SECONDS, STATUS_EVERY, STREAM_KEY_KEY, TITLE_EVERY, TITLE_TRIES
from .choices import settings
from .encoders import encoder
from .sources import Source, sources
from .picture import Look, TURNS_FOR, command, timetable
from .staging import write_atomically
from .words import status_line

# ------------------------------------------------------------------ the stream itself


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def popen(args: list[str]):
    """ffmpeg started (tests swap this for a stand-in)."""
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")


class Stream:
    """The one live stream: started with go_live, ended with stop. Its threads keep ffmpeg running, the words on the
    video current, and set the YouTube title once the broadcast is there, while it's meant to be live."""

    def __init__(self):
        self._lock = threading.Lock()
        self._encoder: str | None = None
        self._run_started: float | None = None  # when the ffmpeg now running started (monotonic)
        self._wanted = threading.Event()
        self._proc = None
        self._said: collections.deque[str] = collections.deque(maxlen=KEPT_LINES)
        self._error: str | None = None
        self._started_at: str | None = None
        self._destination: str | None = None
        self._labels: list[str] = []
        self._key = ""
        self._dir: str | None = None
        self._generation = 0
        self._title: dict | None = None  # setting the YouTube title: {state: "waiting" | "done" | "failed", message}

    # what the page shows
    def status(self) -> dict:
        with self._lock:
            proc = self._proc
            on_air = bool(proc is not None and proc.poll() is None)
            return {
                "live": self._wanted.is_set(),
                "on_air": on_air and self._wanted.is_set(),
                "started_at": self._started_at,
                "destination": self._destination,
                "cameras": list(self._labels),
                "error": self._error,
                "title": dict(self._title) if self._title else None,
                "encoder": self._encoder,  # "nvenc" (an NVIDIA card) or "cpu", while live; None otherwise
                # how long the picture going out has run, in seconds: its slideshows and taking turns count from its
                # start, so the page can show the same picture at the same moment (None while it isn't going out)
                "running_for": round(time.monotonic() - self._run_started, 2) if on_air and self._run_started else None,
                # the server's time of day: slideshows and taking turns count from it, on the stream and on the page
                "server_time": round(time.time(), 3),
            }

    def go_live(self, db: Session, session_factory) -> dict:
        """Start (or start again, with what's chosen now). ValueError says why it can't."""
        chosen = settings(db)
        if not chosen["enabled"]:
            raise ValueError("The stream is turned off: turn it on at the top of the Stream page first.")
        key = app_settings.get(db, STREAM_KEY_KEY)
        where = DESTINATIONS[chosen["destination"]]
        if not key:
            raise ValueError(f"Add your {where['label']} stream key first.")
        if not chosen["cameras"]:
            raise ValueError("Put at least one camera in the grid.")
        ffmpeg = ffmpeg_path()
        if not ffmpeg:
            raise ValueError("ffmpeg isn't installed where Farmhand's API runs, so it can't stream. Rebuild with the latest update.sh.")
        srcs = sources(db, chosen["cameras"])
        wants_title = chosen["destination"] == "youtube" and (chosen["title"] or chosen["description"])
        creds = youtube_live.credentials(db) if wants_title else None
        self.stop()
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._dir = folder = tempfile.mkdtemp(prefix="farmhand-stream-")
            files = [os.path.join(self._dir, f"{i}.txt") for i in range(len(srcs))] if chosen["show_status"] else None
            for i, s in enumerate(srcs):
                if files:
                    write_atomically(files[i], s.label)
            self._key = key
            self._destination = chosen["destination"]
            self._labels = [s.label for s in srcs]
            self._error = None
            self._said.clear()
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._title = None
            if wants_title:
                self._title = ({"state": "waiting", "message": "Setting the YouTube title once the broadcast starts…"} if creds
                               else {"state": "failed", "message": "Sign in to YouTube (below) for Farmhand to set the title and description."})
            self._wanted.set()
        cycle = (chosen["seconds_all"], chosen["seconds_each"]) if chosen["layout"] == "cycle" and len(srcs) > 1 else None
        cells = staging.squares(db, chosen, folder)
        turns_file = os.path.join(folder, "turns.txt") if cycle else None
        tracks = stream_media.track_paths(db) if chosen["music"] else []  # none: a silent sound track
        enc = encoder(ffmpeg)
        with self._lock:
            self._encoder = enc
        url = where["url"] + key

        def make(clock: float) -> list[str]:
            """The command for an ffmpeg starting now (`clock`: the time of day): its slideshows and turns counted from
            midnight 1970, as the page counts them, so the stream shows what the page shows."""
            if turns_file:
                write_atomically(turns_file, timetable(len(srcs), *cycle, clock=clock))
            music = staging.playlist(tracks, os.path.join(folder, "music.txt"), chosen["music_shuffle"]) if tracks else None
            return command(ffmpeg, srcs, url, Look(encoder=enc, clock=clock,
                status_files=files, cycle=cycle, turns_file=turns_file,
                resolution=chosen["resolution"], border_color=chosen["border_color"], background=chosen["background"], font=chosen["font"], color=chosen["color"], cols=chosen["cols"],
                rows=chosen["rows"], cells=cells, music=music, music_volume=chosen["music_volume"],
            ))

        threading.Thread(target=self._keep_running, args=(gen, make), name="stream", daemon=True).start()
        if files:
            threading.Thread(target=self._keep_words_current, args=(gen, srcs, files, session_factory), name="stream-words", daemon=True).start()
        if wants_title and creds:
            threading.Thread(target=self._set_title, args=(gen, creds, chosen["title"], chosen["description"]), name="stream-title", daemon=True).start()
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._wanted.clear()
            self._generation += 1
            proc, self._proc = self._proc, None
            folder, self._dir = self._dir, None
            self._started_at = None
            self._encoder = None
            self._run_started = None
            self._title = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001 - one that won't end is killed
                proc.kill()
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        return self.status()

    def title_set(self, outcome: dict) -> None:
        """What setting the YouTube title came to, when done from the page while live."""
        with self._lock:
            if self._wanted.is_set():
                self._title = outcome

    def _current(self, gen: int) -> bool:
        return self._wanted.is_set() and self._generation == gen

    def _hide_key(self, text: str) -> str:
        return text.replace(self._key, "<stream key>") if self._key else text

    def _keep_running(self, gen: int, make) -> None:
        """ffmpeg, started again (with `make(time of day)`'s command, so it keeps the page's time) whenever it stops."""
        while self._current(gen):
            args = make(time.time())
            try:
                proc = popen(args)
            except OSError as e:
                with self._lock:
                    self._error = f"ffmpeg couldn't be started: {e.strerror or e}"
                    self._wanted.clear()
                return
            with self._lock:
                if not self._current(gen):
                    proc.terminate()
                    return
                self._proc = proc
                self._run_started = time.monotonic()  # its slideshows and turns count from here
            started = time.monotonic()
            for line in proc.stderr or []:
                line = self._hide_key(line.strip())
                if line:
                    self._said.append(line)
            code = proc.wait()
            if not self._current(gen):
                return
            if code == 0 and "-t" in args and time.monotonic() - started >= TURNS_FOR - 60:
                continue  # the day's timetable of turns or playlist is done: started again at once, from the top
            with self._lock:
                last = next((l for l in reversed(self._said) if l), None)
                self._error = f"The stream stopped (ffmpeg exit {code}): {last or 'no reason given'}. Trying again in {RETRY_SECONDS} s."
                if time.monotonic() - started > 60:
                    self._said.clear()
            if not _sleep_unless(self, gen, RETRY_SECONDS):
                return

    def _keep_words_current(self, gen: int, srcs: list[Source], files: list[str], session_factory) -> None:
        while self._current(gen):
            try:
                with session_factory() as db:
                    by_printer: dict[int, dict] = {}
                    for s in srcs:
                        if s.printer_id not in by_printer:
                            printer = db.get(Printer, s.printer_id)
                            by_printer[s.printer_id] = print_progress.progress(db, printer) if printer else {}
                    for s, f in zip(srcs, files):
                        if not self._current(gen):
                            return
                        write_atomically(f, status_line(s.label, by_printer.get(s.printer_id) or {}))
            except Exception:  # noqa: BLE001 - the words stay as they were until the next time round
                pass
            if not _sleep_unless(self, gen, STATUS_EVERY):
                return

    def _set_title(self, gen: int, creds: dict, title: str, description: str) -> None:
        """YouTube makes the broadcast a little after the stream reaches it: tried every TITLE_EVERY seconds until then."""
        last = None
        for _ in range(TITLE_TRIES):
            if not _sleep_unless(self, gen, TITLE_EVERY):
                return
            try:
                done = youtube_live.set_broadcast_text(creds, title, description)
            except youtube_live.YouTubeError as e:
                last = str(e)
                if not e.retry:
                    break
                continue
            with self._lock:
                if self._current(gen):
                    self._title = {"state": "done", "message": f"Title and description set on “{done['title']}”."}
            return
        with self._lock:
            if self._current(gen):
                self._title = {"state": "failed", "message": f"The YouTube title wasn't set: {last or 'no broadcast found'}"}


def _sleep_unless(stream: Stream, gen: int, seconds: float) -> bool:
    """Wait `seconds`, in short steps; False as soon as the stream is stopped or started again."""
    end = time.monotonic() + seconds
    while stream._current(gen) and (left := end - time.monotonic()) > 0:
        time.sleep(min(0.5, left))
    return stream._current(gen)


stream = Stream()
