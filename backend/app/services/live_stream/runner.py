"""
The stream itself, while it's meant to be live: the one connection to YouTube (the sender) and the delay's buffer
before it, kept for as long as it's live; the picture ffmpeg making the picture, handed over to a new one when the
layout changes (relay.py) with no break in what YouTube gets; the words on the cameras kept current; and the YouTube
title set once the broadcast is there.
"""
from __future__ import annotations

import collections
import io
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
from . import music, staging
from .constants import DESTINATIONS, KEPT_LINES, RETRY_SECONDS, STATUS_EVERY, STREAM_KEY_KEY, TITLE_EVERY, TITLE_TRIES
from .choices import settings
from .encoders import encoder
from .relay import Buffer, Relay
from .sources import Source, sources
from .picture import Look, TURNS_FOR, command, sender_command, timetable
from .staging import write_atomically
from .words import status_line

HANDOVER_WAIT = 30  # seconds a new layout's picture ffmpeg has to start going before the old one is kept on instead

# ------------------------------------------------------------------ the stream itself


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def popen(args: list[str], feed: bool = False, out: bool = False):
    """ffmpeg started (tests swap this for a stand-in). `feed`: its stdin open for writing to (raw bytes: the music, or
    the stream for the sender); `out`: its stdout open for reading (the picture, for the relay); what it says comes as
    text either way."""
    proc = subprocess.Popen(args, stdin=subprocess.PIPE if feed else subprocess.DEVNULL, stdout=subprocess.PIPE if out else subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    proc.stderr = io.TextIOWrapper(proc.stderr, encoding="utf-8", errors="replace")
    return proc


def _end(proc) -> None:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 - one that won't end is killed
            proc.kill()


class Stream:
    """The one live stream: started with go_live (which, while live, hands over to the new layout), ended with stop.
    Its threads keep the sender and the picture ffmpeg running, the words on the video current, and set the YouTube
    title once the broadcast is there, while it's meant to be live."""

    def __init__(self):
        self._lock = threading.Lock()
        self._encoder: str | None = None
        self._run_started: float | None = None  # when the picture ffmpeg going out started (monotonic)
        self._wanted = threading.Event()
        self._proc = None  # the picture ffmpeg going out
        self._sender = None  # the ffmpeg holding the connection to YouTube
        self._relay: Relay | None = None
        self._buffer: Buffer | None = None
        self._url: str | None = None
        self._live_since: float | None = None  # (monotonic) the pictures' times count from here
        self._said: collections.deque[str] = collections.deque(maxlen=KEPT_LINES)
        self._error: str | None = None
        self._started_at: str | None = None
        self._destination: str | None = None
        self._labels: list[str] = []
        self._key = ""
        self._dir: str | None = None  # the folder of the picture going out (or coming in)
        self._generation = 0  # one per time live (a stop, or going live afresh, moves it on)
        self._picture = 0  # one per layout while live (a hand-over moves it on)
        self._title: dict | None = None  # setting the YouTube title: {state: "waiting" | "done" | "failed", message}
        self._player: music.Player | None = None  # the music, while live

    # what the page shows
    def status(self) -> dict:
        with self._lock:
            proc, sender, buffer = self._proc, self._sender, self._buffer
            wanted = self._wanted.is_set()
            on_air = bool(proc is not None and proc.poll() is None and sender is not None and sender.poll() is None)
            return {
                "live": wanted,
                "on_air": on_air and wanted,
                "started_at": self._started_at,
                "destination": self._destination,
                "cameras": list(self._labels),
                "error": self._error,
                "title": dict(self._title) if self._title else None,
                "encoder": self._encoder,  # "nvenc" (an NVIDIA card) or "cpu", while live; None otherwise
                # how long the picture going out has run, in seconds (None while it isn't going out)
                "running_for": round(time.monotonic() - self._run_started, 2) if on_air and self._run_started else None,
                # the server's time of day: slideshows and taking turns count from it, on the stream and on the page
                "server_time": round(time.time(), 3),
                # the music while live: {on, playing, track (its file name, None before the first), at (seconds into it)}
                "music": self._player.status() if self._player and wanted else None,
                # the delay before YouTube, while live: {seconds (as chosen), held (seconds of stream held now), filling
                # (still collecting it: nothing has gone to YouTube yet)}
                "delay": {"seconds": buffer.delay, "held": buffer.held(), "filling": buffer.filling()} if buffer and wanted else None,
            }

    def music_settings(self, chosen: dict) -> None:
        """The music's choices changed while live: the music follows straight away, no new ffmpeg."""
        with self._lock:
            player = self._player
        if player:
            player.settings(on=chosen["music"], shuffle=chosen["music_shuffle"], volume=chosen["music_volume"])

    def music_control(self, action: str) -> None:
        """"play", "pause", "next" or "back" on the music going out. ValueError when there's none to control."""
        with self._lock:
            player = self._player if self._wanted.is_set() else None
        if player is None:
            raise ValueError("The stream isn't live: the music plays on the stream once it is.")
        if not player.on:
            raise ValueError("The music is off: tick Play music on the stream, and Save.")
        getattr(player, action)()

    def go_live(self, db: Session, session_factory) -> dict:
        """Go live with what's chosen now; while live already (to the same place), hand over to it with no break in what
        YouTube gets. ValueError says why it can't."""
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
        url = where["url"] + key
        with self._lock:
            sender = self._sender
            handover = self._wanted.is_set() and self._url == url and sender is not None and sender.poll() is None
        if not handover:
            self._start_session(db, session_factory, chosen, ffmpeg, url, key)
        elif self._player:
            self.music_settings(chosen)

        # the picture for this layout: its own folder, words and command (the old one's keeps going until it's handed over)
        folder = tempfile.mkdtemp(prefix="farmhand-stream-")
        files = [os.path.join(folder, f"{i}.txt") for i in range(len(srcs))] if chosen["show_status"] else None
        for i, s in enumerate(srcs):
            if files:
                write_atomically(files[i], s.label)
        cycle = (chosen["seconds_all"], chosen["seconds_each"]) if chosen["layout"] == "cycle" and len(srcs) > 1 else None
        cells = staging.squares(db, chosen, folder)
        turns_file = os.path.join(folder, "turns.txt") if cycle else None
        enc = encoder(ffmpeg)

        def make(clock: float, offset: float) -> list[str]:
            """The command for a picture ffmpeg starting now (`clock`: the time of day, so its slideshows and turns keep
            the page's; `offset`: the stream's age, its times' start)."""
            if turns_file:
                write_atomically(turns_file, timetable(len(srcs), *cycle, clock=clock))
            return command(ffmpeg, srcs, url, Look(encoder=enc, clock=clock,
                status_files=files, cycle=cycle, turns_file=turns_file,
                resolution=chosen["resolution"], border_color=chosen["border_color"], background=chosen["background"], font=chosen["font"], color=chosen["color"], cols=chosen["cols"],
                rows=chosen["rows"], cells=cells, music=True, relay_offset=offset,
            ))

        with self._lock:
            gen = self._generation
            self._picture += 1
            picture = self._picture
            self._encoder = enc
            self._labels = [s.label for s in srcs]
            self._error = None
        threading.Thread(target=self._keep_picture, args=(gen, picture, make, folder, handover), name="stream", daemon=True).start()
        if files:
            threading.Thread(target=self._keep_words_current, args=(gen, picture, srcs, files, session_factory), name="stream-words", daemon=True).start()
        return self.status()

    def _start_session(self, db: Session, session_factory, chosen: dict, ffmpeg: str, url: str, key: str) -> None:
        """Going live afresh: the sender (the connection to YouTube), the delay's buffer, the music and the title."""
        wants_title = chosen["destination"] == "youtube" and (chosen["title"] or chosen["description"])
        creds = youtube_live.credentials(db) if wants_title else None
        self.stop()

        def tracks() -> list[str]:  # read again each round of the music, so tracks added while live join in
            with session_factory() as s:
                return [str(p) for p in stream_media.track_paths(s)]

        # the music starts with the stream (when it's on and there are tracks; silence otherwise)
        player = music.Player(ffmpeg, tracks, on=chosen["music"], shuffle=chosen["music_shuffle"], volume=chosen["music_volume"])
        buffer = Buffer(chosen["delay"])
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._key = key
            self._url = url
            self._destination = chosen["destination"]
            self._error = None
            self._said.clear()
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._live_since = time.monotonic()
            self._buffer = buffer
            self._relay = Relay(buffer)
            self._player = player
            self._title = None
            if wants_title:
                self._title = ({"state": "waiting", "message": "Setting the YouTube title once the broadcast starts…"} if creds
                               else {"state": "failed", "message": "Sign in to YouTube (below) for Farmhand to set the title and description."})
            self._wanted.set()
        threading.Thread(target=self._keep_sending, args=(gen, sender_command(ffmpeg, url), buffer), name="stream-sender", daemon=True).start()
        if wants_title and creds:
            threading.Thread(target=self._set_title, args=(gen, creds, chosen["title"], chosen["description"]), name="stream-title", daemon=True).start()

    def stop(self) -> dict:
        with self._lock:
            self._wanted.clear()
            self._generation += 1
            self._picture += 1
            proc, self._proc = self._proc, None
            sender, self._sender = self._sender, None
            buffer, self._buffer = self._buffer, None
            self._relay = None
            self._url = None
            folder, self._dir = self._dir, None
            self._started_at = None
            self._encoder = None
            self._run_started = None
            self._title = None
            player, self._player = self._player, None
        if player:
            player.stop()
        if buffer:
            buffer.close()
        for p in (proc, sender):
            _end(p)
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        return self.status()

    def title_set(self, outcome: dict) -> None:
        """What setting the YouTube title came to, when done from the page while live."""
        with self._lock:
            if self._wanted.is_set():
                self._title = outcome

    def _current(self, gen: int, picture: int | None = None) -> bool:
        return self._wanted.is_set() and self._generation == gen and (picture is None or self._picture == picture)

    def _hide_key(self, text: str) -> str:
        return text.replace(self._key, "<stream key>") if self._key else text

    def _listen(self, proc) -> None:
        for line in proc.stderr or []:
            line = self._hide_key(line.strip())
            if line:
                self._said.append(line)

    def _keep_sending(self, gen: int, args: list[str], buffer: Buffer) -> None:
        """The sender, started again whenever it stops (the connection to YouTube dropped), for as long as it's live."""
        while self._current(gen):
            try:
                proc = popen(args, feed=True)
            except OSError as e:
                with self._lock:
                    self._error = f"ffmpeg couldn't be started: {e.strerror or e}"
                    self._wanted.clear()
                return
            with self._lock:
                if not self._current(gen):
                    _end(proc)
                    return
                self._sender = proc
            buffer.set_sink(proc.stdin)
            started = time.monotonic()
            self._listen(proc)
            code = proc.wait()
            if not self._current(gen):
                return
            with self._lock:
                last = next((l for l in reversed(self._said) if l), None)
                self._error = (f"The connection to {self._destination and DESTINATIONS[self._destination]['label'] or 'YouTube'} dropped "
                               f"(ffmpeg exit {code}): {last or 'no reason given'}. Connecting again in {RETRY_SECONDS} s.")
                if time.monotonic() - started > 60:
                    self._said.clear()
            if not _sleep_unless(self, gen, RETRY_SECONDS):
                return

    def _keep_picture(self, gen: int, picture: int, make, folder: str, handover: bool) -> None:
        """This layout's picture ffmpeg, going out through the relay: handed over to from the one going out when
        `handover` (the old one stays on until this one's first keyframe, then is stopped), and started again whenever
        it stops, for as long as it's the layout and the stream is live. Its folder is deleted once it's done with."""
        try:
            while self._current(gen, picture):
                with self._lock:
                    relay, player, since = self._relay, self._player, self._live_since or time.monotonic()
                try:
                    proc = popen(make(time.time(), time.monotonic() - since), feed=True, out=True)
                except OSError as e:
                    with self._lock:
                        self._error = f"ffmpeg couldn't be started: {e.strerror or e}"
                    return
                if player:
                    player.attach(proc.stdin)
                with self._lock:
                    old = self._proc
                if handover and old is not None and old.poll() is None:
                    if not relay.switch_to(proc, HANDOVER_WAIT):
                        _end(proc)
                        with self._lock:
                            if self._current(gen, picture):
                                self._error = (f"The new layout's picture didn't start within {HANDOVER_WAIT} s, so the one going "
                                               f"out stayed on. Trying again in {RETRY_SECONDS} s.")
                        if not _sleep_unless(self, gen, RETRY_SECONDS, picture):
                            return
                        continue
                else:
                    relay.start(proc)
                handover = False  # (from here, one started again after this one stops just takes over)
                with self._lock:
                    if not self._current(gen, picture):
                        _end(proc)
                        return
                    old, self._proc = self._proc, proc
                    self._dir = folder
                    self._run_started = time.monotonic()
                    self._error = None
                if old is not None and old is not proc:
                    _end(old)  # the old layout's (its own thread then deletes its folder)
                started = time.monotonic()
                self._listen(proc)
                code = proc.wait()
                if not self._current(gen, picture):
                    return
                if code == 0 and time.monotonic() - started >= TURNS_FOR - 60:
                    continue  # the day's timetable and lists are done: started again at once, from the top
                with self._lock:
                    last = next((l for l in reversed(self._said) if l), None)
                    self._error = f"The picture stopped (ffmpeg exit {code}): {last or 'no reason given'}. Trying again in {RETRY_SECONDS} s."
                    if time.monotonic() - started > 60:
                        self._said.clear()
                if not _sleep_unless(self, gen, RETRY_SECONDS, picture):
                    return
        finally:
            with self._lock:
                mine = self._dir == folder
            if not mine:
                shutil.rmtree(folder, ignore_errors=True)

    def _keep_words_current(self, gen: int, picture: int, srcs: list[Source], files: list[str], session_factory) -> None:
        while self._current(gen, picture):
            try:
                with session_factory() as db:
                    by_printer: dict[int, dict] = {}
                    for s in srcs:
                        if s.printer_id not in by_printer:
                            printer = db.get(Printer, s.printer_id)
                            by_printer[s.printer_id] = print_progress.progress(db, printer) if printer else {}
                    for s, f in zip(srcs, files):
                        if not self._current(gen, picture):
                            return
                        write_atomically(f, status_line(s.label, by_printer.get(s.printer_id) or {}))
            except Exception:  # noqa: BLE001 - the words stay as they were until the next time round
                pass
            if not _sleep_unless(self, gen, STATUS_EVERY, picture):
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


def _sleep_unless(stream: Stream, gen: int, seconds: float, picture: int | None = None) -> bool:
    """Wait `seconds`, in short steps; False as soon as the stream is stopped or started again (or, given `picture`, its
    layout is handed over from)."""
    end = time.monotonic() + seconds
    while stream._current(gen, picture) and (left := end - time.monotonic()) > 0:
        time.sleep(min(0.5, left))
    return stream._current(gen, picture)


stream = Stream()
