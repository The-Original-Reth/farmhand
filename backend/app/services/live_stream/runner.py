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
import re
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
from .broadcast import Broadcast, own_stream, title_on_active
from .constants import DESTINATIONS, KEPT_LINES, RETRY_SECONDS, STATUS_EVERY, STREAM_KEY_KEY
from .choices import settings
from .encoders import encoder
from .relay import Buffer, Relay
from .sources import Source, sources
from .picture import Look, TURNS_FOR, command, sender_command, timetable
from .staging import write_atomically
from .words import status_line

HANDOVER_WAIT = 30  # seconds a new layout's picture ffmpeg has to start going before the old one is kept on instead
SETTLE = 3  # seconds a new layout waits before its picture ffmpeg starts: a burst of saves becomes one hand-over
WARMING_NICE = 10  # a picture ffmpeg warming up runs at this lower priority, so the one going out keeps the processor
SENDER_STEADY = 30  # seconds a sender connected again has to keep sending before its drop's message is cleared
REFRESH_EVERY = 60  # a camera dropped: at most one hand-over to fresh connections a minute
# What ffmpeg says when one of its inputs has ended or failed: a camera it has lost (input number, from 0)
INPUT_ENDED = re.compile(r"\[in#(\d+)/[^\]]*\] (?:Terminating thread with return code|Task finished with error code|Error during demuxing)")

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


def _nice(proc, level: int) -> None:
    """Run `proc` at this priority (0: as usual; higher: gives way to others). (Best tried: a stand-in has no pid.)"""
    try:
        os.setpriority(os.PRIO_PROCESS, proc.pid, level)
    except (AttributeError, OSError):
        pass


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
        self._warming = None  # a new layout's picture ffmpeg, warming up beside the one going out
        self._changing = False  # a new layout is on its way (settling, or warming up)
        self._cache: str | None = None  # slideshow screens put together this time live, reused by later layouts
        self._broadcast: Broadcast | None = None  # signed in: this time live's broadcast on YouTube

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
                # a new layout is on its way: waiting for more changes, or its picture warming up beside the one going out
                "changing": self._changing and wanted,
                # signed in: this time live's broadcast on YouTube {watch_url, studio_url, state, health, issues, viewers}
                "youtube": self._broadcast.status() if wanted and self._broadcast else None,
            }

    def update_broadcast(self, chosen: dict) -> bool:
        """The video's settings changed while live (title, description, tags, category, privacy...): changed on the
        broadcast going out straight away. False when there's none of Farmhand's own (a pasted key)."""
        with self._lock:
            b = self._broadcast if self._wanted.is_set() else None
        if not b:
            return False
        self.title_set(b.update(chosen))
        return True

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
        where = DESTINATIONS[chosen["destination"]]
        creds = youtube_live.credentials(db) if chosen["destination"] == "youtube" else None
        key = app_settings.get(db, STREAM_KEY_KEY)
        if not key and not creds:
            raise ValueError(f"Sign in to YouTube, or add your {where['label']} stream key, first (YouTube settings).")
        if not chosen["cameras"]:
            raise ValueError("Put at least one camera in the grid.")
        ffmpeg = ffmpeg_path()
        if not ffmpeg:
            raise ValueError("ffmpeg isn't installed where Farmhand's API runs, so it can't stream. Rebuild with the latest update.sh.")
        srcs = sources(db, chosen["cameras"])
        own = own_stream(db, creds) if creds else None  # signed in: Farmhand's own stream on the channel
        if own:
            key = own["key"]
        url = (own["url"] if own else where["url"]) + key
        with self._lock:
            sender = self._sender
            handover = self._wanted.is_set() and self._url == url and sender is not None and sender.poll() is None
        if not handover:
            self._start_session(db, session_factory, chosen, ffmpeg, url, key, creds if own else None, own)
        elif self._player:
            self.music_settings(chosen)

        # the picture for this layout: its own folder, words and command (the old one's keeps going until it's handed
        # over); slideshow screens already put together this session are reused
        folder = tempfile.mkdtemp(prefix="farmhand-stream-")
        files = [os.path.join(folder, f"{i}.txt") for i in range(len(srcs))] if chosen["show_status"] else None
        for i, s in enumerate(srcs):
            if files:
                write_atomically(files[i], s.label)
        cycle = (chosen["seconds_all"], chosen["seconds_each"]) if chosen["layout"] == "cycle" and len(srcs) > 1 else None
        with self._lock:
            cache = self._cache
        cells = staging.squares(db, chosen, folder, cache=cache)
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
                rows=chosen["rows"], cells=cells, music=True, relay_offset=offset, lists_dir=folder,
            ))

        with self._lock:
            gen = self._generation
            self._picture += 1
            picture = self._picture
            self._encoder = enc
            self._labels = [s.label for s in srcs]
            self._error = None
            warming, self._warming = self._warming, None
            if handover:
                self._changing = True
        _end(warming)  # a newer layout came while one was still warming up: that one is dropped at once
        threading.Thread(target=self._keep_picture, args=(gen, picture, make, folder, handover, len(srcs)), name="stream", daemon=True).start()
        if files:
            threading.Thread(target=self._keep_words_current, args=(gen, picture, srcs, files, session_factory), name="stream-words", daemon=True).start()
        return self.status()

    def _start_session(self, db: Session, session_factory, chosen: dict, ffmpeg: str, url: str, key: str,
                       creds: dict | None = None, own: dict | None = None) -> None:
        """Going live afresh: signed in, a new broadcast on the channel first (bound to Farmhand's own stream `own`, set
        from the YouTube settings; it starts by itself when the stream arrives); then the sender (the connection to
        YouTube), the delay's buffer and the music. With a pasted key instead, YouTube makes the broadcast itself and
        Farmhand can't set its title."""
        self.stop()
        broadcast = Broadcast.start(creds, own, chosen) if own else None
        wants_title = not own and chosen["destination"] == "youtube" and (chosen["title"] or chosen["description"])

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
            self._cache = tempfile.mkdtemp(prefix="farmhand-stream-slides-")
            self._player = player
            self._title = None
            if broadcast:
                self._title = Broadcast.made_message(chosen)
            elif wants_title:
                self._title = {"state": "failed", "message": "Sign in to YouTube (YouTube settings) for Farmhand to set the title and description."}
            self._broadcast = broadcast
            self._wanted.set()
        threading.Thread(target=self._keep_sending, args=(gen, sender_command(ffmpeg, url), buffer), name="stream-sender", daemon=True).start()
        if broadcast:
            def read_settings() -> dict:
                with session_factory() as s:
                    return settings(s)

            threading.Thread(target=broadcast.watch, name="stream-youtube", daemon=True, args=(
                buffer.delay, lambda seconds: _sleep_unless(self, gen, seconds), read_settings, lambda said: self._said_by_youtube(gen, said))).start()

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
            broadcast, self._broadcast = self._broadcast, None
            warming, self._warming = self._warming, None
            cache, self._cache = self._cache, None
            self._changing = False
        if player:
            player.stop()
        _end(warming)
        if cache:
            shutil.rmtree(cache, ignore_errors=True)
        if broadcast:  # ended on YouTube (it becomes the channel's saved video)
            broadcast.end()
        if buffer:
            buffer.close()
        for p in (proc, sender):
            _end(p)
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        return self.status()

    def send_to_youtube(self, db: Session, chosen: dict, text_changed: bool = True, asked: bool = False) -> None:
        """The YouTube settings (`chosen`) saved while live: onto Farmhand's own broadcast, all of them; live on a pasted
        key, just the title and description, on the broadcast YouTube made (when they changed, or `asked`: the page's
        button). Asked, ValueError says why it can't be tried; otherwise that's left quietly. status.title says how
        it went."""
        if self.update_broadcast(chosen) or not text_changed:
            return
        if not asked and not (youtube_live.credentials(db) and (chosen["title"] or chosen["description"])):
            return
        self.title_set(title_on_active(db, chosen))

    def _said_by_youtube(self, gen: int, outcome: dict) -> None:
        with self._lock:
            if self._current(gen):
                self._title = outcome

    def title_set(self, outcome: dict) -> None:
        """What setting the YouTube title came to, when done from the page while live."""
        with self._lock:
            if self._wanted.is_set():
                self._title = outcome

    def _current(self, gen: int, picture: int | None = None) -> bool:
        return self._wanted.is_set() and self._generation == gen and (picture is None or self._picture == picture)

    def _hide_key(self, text: str) -> str:
        return text.replace(self._key, "<stream key>") if self._key else text

    def _listen(self, proc, cameras: int = 0, lost: threading.Event | None = None) -> None:
        """What ffmpeg says, kept (the stream key blanked out); with `lost`, set when it says one of its first `cameras`
        inputs (the cameras) has ended or failed."""
        for line in proc.stderr or []:
            line = self._hide_key(line.strip())
            if not line:
                continue
            self._said.append(line)
            m = INPUT_ENDED.search(line) if lost is not None else None
            if m and int(m.group(1)) < cameras:
                lost.set()

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
            threading.Thread(target=self._clear_when_steady, args=(gen, proc), name="stream-sender-ok", daemon=True).start()
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

    def _start_picture(self, gen: int, picture: int, make, handover: bool, folder: str | None = None, cut: bool = False):
        """A picture ffmpeg for this layout, started and going out: handed over to from the one going out when `handover`
        (warming up at a lower priority until it takes over; the old one is then stopped), or straight away; with `cut`,
        the one going out is stopped first (it may hold a camera that takes one viewer at a time: the delay's buffer
        covers the few seconds the new one takes to start). The new one, or None when it didn't take over (dropped for a
        newer layout, failed, or too slow: the old one stays on)."""
        if cut:
            with self._lock:
                old = self._proc if self._current(gen, picture) else None
            _end(old)
        with self._lock:
            relay, player, since = self._relay, self._player, self._live_since or time.monotonic()
        # its times carry on from the last frame passed on, a little behind: after a break, a jump ahead would have the
        # sender (playing to the times) wait it out; a step back is just closed up (mpegts starts ~1.4 s after its offset)
        last = relay.last_time() if relay else None
        offset = max(0.0, last - 2.0) if last is not None else time.monotonic() - since
        proc = popen(make(time.time(), offset), feed=True, out=True)
        if player:
            player.attach(proc.stdin)
        with self._lock:
            old = self._proc
        if handover and old is not None and old.poll() is None:
            _nice(proc, WARMING_NICE)
            with self._lock:
                if not self._current(gen, picture):
                    _end(proc)
                    return None
                self._warming = proc
            took = relay.switch_to(proc, HANDOVER_WAIT)
            with self._lock:
                if self._warming is proc:
                    self._warming = None
            if not took:
                _end(proc)
                return None
            _nice(proc, 0)
        else:
            relay.start(proc)
        with self._lock:
            if not self._current(gen, picture):
                _end(proc)
                return None
            old, self._proc = self._proc, proc
            if folder:
                self._dir = folder
            self._run_started = time.monotonic()
            self._error = None
            self._changing = False
        if old is not None and old is not proc:
            _end(old)  # the one it took over from
        return proc

    def _clear_when_steady(self, gen: int, proc) -> None:
        """A sender connected again and still sending after SENDER_STEADY seconds: the message that it dropped is
        cleared (it said it would connect again, and it has)."""
        if _sleep_unless(self, gen, SENDER_STEADY) and proc.poll() is None:
            with self._lock:
                if self._error and self._error.startswith("The connection to"):
                    self._error = None

    def _keep_picture(self, gen: int, picture: int, make, folder: str, handover: bool, cameras: int) -> None:
        """This layout's picture, for as long as it's the layout and the stream is live: after settling (a newer layout
        within SETTLE seconds takes its place), handed over to from the one going out, or started straight away. A
        camera it loses (ffmpeg says that input has ended) brings a hand-over to a fresh picture, new connections to every
        camera, on the same connection to YouTube; one that stops is started again. Its folder is deleted once it's done
        with."""
        try:
            if handover and not _sleep_unless(self, gen, SETTLE, picture):
                return
            proc, last_refresh, cut = None, 0.0, False
            while self._current(gen, picture):
                if proc is None:
                    try:
                        proc = self._start_picture(gen, picture, make, handover and not cut, folder, cut=cut)
                    except OSError as e:
                        with self._lock:
                            self._error = f"ffmpeg couldn't be started: {e.strerror or e}"
                        return
                    if proc is None:  # it couldn't start beside the one going out (unless a newer layout came)
                        if not self._current(gen, picture):
                            return
                        if not cut and handover:  # (a camera taking one viewer at a time?): switched over directly at once
                            cut = True
                            with self._lock:
                                self._error = ("The new layout couldn't start beside the one going out (a camera that takes one "
                                               "viewer at a time?), so it's being switched over directly: the delay covers the gap.")
                            continue
                        with self._lock:
                            self._error = f"The new layout's picture didn't start. Trying again in {RETRY_SECONDS} s."
                        if not _sleep_unless(self, gen, RETRY_SECONDS, picture):
                            return
                        continue
                    lost = threading.Event()
                    threading.Thread(target=self._listen, args=(proc, cameras, lost), name="stream-listen", daemon=True).start()
                    started = time.monotonic()
                # going out: until it stops, a camera is lost, or the layout is handed over from
                while self._current(gen, picture) and proc.poll() is None and not lost.is_set():
                    time.sleep(0.5)
                if not self._current(gen, picture):
                    return
                if proc.poll() is None:  # a camera lost: a fresh picture takes over (at most once a minute)
                    wait = REFRESH_EVERY - (time.monotonic() - last_refresh)
                    if wait > 0 and not _sleep_unless(self, gen, wait, picture):
                        return
                    last_refresh = time.monotonic()
                    fresh = self._start_picture(gen, picture, make, True, folder)
                    if fresh is not None:
                        proc = fresh
                        lost = threading.Event()
                        threading.Thread(target=self._listen, args=(proc, cameras, lost), name="stream-listen", daemon=True).start()
                        started = time.monotonic()
                    else:
                        lost.clear()
                    continue
                code = proc.wait()
                proc, handover = None, False  # (from here, one started again just takes over)
                if code == 0 and time.monotonic() - started >= TURNS_FOR - 60:
                    continue  # the day's timetable and lists are done: started again at once, from the top
                with self._lock:
                    last = next((l for l in reversed(self._said) if l), None)
                    self._error = f"The picture stopped (ffmpeg exit {code}): {last or 'no reason given'}. Trying again in {RETRY_SECONDS} s."
                if not _sleep_unless(self, gen, RETRY_SECONDS, picture):
                    return
        finally:
            with self._lock:
                mine = self._dir == folder
                if self._current(gen) and self._picture == picture:
                    self._changing = False
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


def _sleep_unless(stream: Stream, gen: int, seconds: float, picture: int | None = None) -> bool:
    """Wait `seconds`, in short steps; False as soon as the stream is stopped or started again (or, given `picture`, its
    layout is handed over from)."""
    end = time.monotonic() + seconds
    while stream._current(gen, picture) and (left := end - time.monotonic()) > 0:
        time.sleep(min(0.5, left))
    return stream._current(gen, picture)


stream = Stream()
