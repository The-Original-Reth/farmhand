"""
The stream itself, while it's meant to be live: the one connection to YouTube (the sender) and the delay's buffer
before it, kept for as long as it's live; each camera read by its own feeder (feeders.py), kept for as long as it's
live; the picture ffmpeg making the picture from the feeders' steady pipes, handed over to a new one when the layout
changes (relay.py) with no break in what YouTube gets; the words on the cameras kept current from Farmhand (just the
printer's name while Farmhand doesn't answer); and the YouTube title set once the broadcast is there.

Going live is remembered in the plugin's store (LIVE_KEY), and cleared only by Stop (or the switch turned off), so after
the plugin's own restart it goes live again by itself (resume()).
"""
from __future__ import annotations

import collections
import os
import shutil
import tempfile
import threading
import time

from datetime import datetime, timezone

from ..store import Session, store
from .. import app_settings, config, farm, stream_media, youtube_live
from . import feeders, holding, music, procs, staging
from .cameras import CamerasMixin
from .pictures import PicturesMixin
from .self_check import SelfCheckMixin
from .sending import SendingMixin
from .broadcast import Broadcast, own_stream, title_on_active
from .constants import DEFAULT_RESOLUTION, DESTINATIONS, KEPT_LINES, RESOLUTIONS, STREAM_KEY_KEY
from .fonts import font_file
from .choices import settings
from .encoders import encoder
from .buffer import Buffer
from .relay import Relay
from .sources import Source, sources
from .picture import Look, command, sender_command, timetable
from .staging import write_atomically

LIVE_KEY = "live_wanted"  # in the plugin's store while the stream is meant to be live: it goes live again after a restart
RESUME_EVERY = 30  # seconds between tries at going live again after a restart, while it can't yet

class Stream(CamerasMixin, PicturesMixin, SendingMixin, SelfCheckMixin):
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
        self._healed: dict | None = None  # what the self-check last did this time live (_watch_flow)
        # the resolution chosen when going live: kept until Stop (YouTube takes a change of size mid-stream badly, so a
        # new one saved while live waits for the next Go live)
        self._resolution: str | None = None
        self._feeders: dict[str, feeders.Feeder] = {}  # each camera's feeder this time live, by its key
        self._showing: list[tuple[str, str]] = []  # the layout's cameras (key, label), in square order
        self._farmhand_note: str | None = None  # why Farmhand couldn't be asked for the cameras at the last Go live

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
                # each camera while live, in square order: {key, label, state: "live" | "down" | "starting", since}
                "camera_states": self._camera_states() if wanted else [],
                # Farmhand didn't answer at the last Go live: its cameras were read at the addresses last heard of. Only
                # while it still doesn't: once it answers the plugin again (a camera list, a print), the note goes
                "farmhand": self._farmhand_note if wanted and farm.problem() else None,
                "error": self._error,
                "title": dict(self._title) if self._title else None,
                "encoder": self._encoder,  # "nvenc" (an NVIDIA card) or "cpu", while live; None otherwise
                "resolution": self._resolution if wanted else None,  # the size going out (set when it went live)
                # how long the picture going out has run, in seconds (None while it isn't going out)
                "running_for": round(time.monotonic() - self._run_started, 2) if on_air and self._run_started else None,
                # the server's time of day: slideshows and taking turns count from it, on the stream and on the page
                "server_time": round(time.time(), 3),
                # the music while live: {on, playing, track (its file name, None before the first), at (seconds into it)}
                "music": self._player.status() if self._player and wanted else None,
                # the delay before YouTube, while live: {seconds (as chosen), held (seconds of stream held now), filling
                # (still collecting it: nothing has gone to YouTube yet)}
                "delay": {"seconds": buffer.delay, "held": buffer.held(), "filling": buffer.filling()} if buffer and wanted else None,
                # the holding screen is going out (after the plugin's own restart, while the delay fills again)
                "holding": bool(buffer and wanted and buffer.filled_from() is not None),
                # a new layout is on its way: waiting for more changes, or its picture warming up beside the one going out
                "changing": self._changing and wanted,
                # what the self-check last did this time live, {at (ISO time), message}, or None
                "self_check": dict(self._healed) if wanted and self._healed else None,
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

    def go_live(self, db: Session, session_factory, resumed: bool = False) -> dict:
        """Go live with what's chosen now; while live already (to the same place), hand over to it with no break in what
        YouTube gets. `resumed`: going live again after the plugin's own restart (the holding screen goes out while the
        delay fills, so the broadcast never goes without video). ValueError says why it can't."""
        chosen = settings(db)
        if not chosen["enabled"]:
            raise ValueError("The stream is turned off: turn it on at the top of the Stream page first.")
        where = DESTINATIONS[chosen["destination"]]
        test = config.settings.test_destination  # trying the plugin out: there instead of YouTube, which is never asked
        creds = youtube_live.credentials(db) if chosen["destination"] == "youtube" and not test else None
        key = app_settings.get(db, STREAM_KEY_KEY)
        if not key and not creds:
            raise ValueError(f"Sign in to YouTube, or add your {where['label']} stream key, first (YouTube settings).")
        if not chosen["cameras"]:
            raise ValueError("Put at least one camera in the grid.")
        ffmpeg = procs.ffmpeg_path()
        if not ffmpeg:
            raise ValueError("ffmpeg isn't installed in the Stream plugin's container, so it can't stream. Rebuild its image.")
        known, note = farm.cameras(db)  # (Farmhand not answering: the addresses last heard of)
        srcs = sources(db, chosen["cameras"], known)
        own = own_stream(db, creds) if creds else None  # signed in: Farmhand's own stream on the channel
        if own:
            key = own["key"]
        url = f"{test}/{key}" if test else (own["url"] if own else where["url"]) + key
        with self._lock:
            sender = self._sender
            handover = self._wanted.is_set() and self._url == url and sender is not None and sender.poll() is None
        if not handover:
            self._start_session(db, session_factory, chosen, ffmpeg, url, key, creds if own else None, own, resumed=resumed)
        elif self._player:
            self.music_settings(chosen)

        db.put(LIVE_KEY, "1")  # (gone live: again by itself after a restart, until Stop)
        db.commit()

        # each camera's feeder: the ones already reading it carry on (a new layout never connects to a camera again)
        with self._lock:
            resolution = self._resolution or DEFAULT_RESOLUTION
        size = RESOLUTIONS.get(resolution, RESOLUTIONS[DEFAULT_RESOLUTION])[:2]
        fed = self._feed(ffmpeg, srcs, size)
        own_cells = {c["camera"]: c for c in chosen["cells"] if c and "camera" in c}

        def looks(s) -> feeders.DownFrames:  # its "Camera down" square: its own colour and words' font and colour
            mine = own_cells.get(s.key) or {}
            return feeders.DownFrames(mine.get("background") or chosen["background"], font_file(mine.get("words_font") or chosen["font"]),
                                      mine.get("words_color") or chosen["color"], s.name or s.label)

        downs = [looks(s) for s in srcs]

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
            resolution = self._resolution  # (this time live's, whatever is saved now)
        cells = staging.squares(db, chosen, folder, cache=cache)
        turns_file = os.path.join(folder, "turns.txt") if cycle else None
        enc = encoder(ffmpeg)

        starts = [0]

        def make(clock: float, offset: float) -> tuple[list[str], feeders.Pump]:
            """The command for a picture ffmpeg starting now (`clock`: the time of day, so its slideshows and turns keep
            the page's; `offset`: the stream's age, its times' start), and the pump feeding it its cameras: its own pipes,
            so one starting beside the one going out never takes its frames."""
            if turns_file:
                write_atomically(turns_file, timetable(len(srcs), *cycle, clock=clock))
            starts[0] += 1
            paths = [os.path.join(folder, f"camera-{i}-{starts[0]}.mjpeg") for i in range(len(srcs))]
            pump = feeders.Pump(list(zip(fed, downs)), paths)
            piped = [Source(s.printer_id, s.label, feeders.pipe_input(p), [], key=s.key, name=s.name) for s, p in zip(srcs, paths)]
            return command(ffmpeg, piped, url, Look(encoder=enc, clock=clock,
                status_files=files, cycle=cycle, turns_file=turns_file,
                resolution=resolution, border_color=chosen["border_color"], background=chosen["background"], font=chosen["font"], color=chosen["color"], cols=chosen["cols"],
                rows=chosen["rows"], cells=cells, music=True, relay_offset=offset, lists_dir=folder,
            )), pump

        with self._lock:
            gen = self._generation
            self._picture += 1
            picture = self._picture
            self._encoder = enc
            self._labels = [s.label for s in srcs]
            self._showing = [(s.key, s.label) for s in srcs]
            self._farmhand_note = note
            self._error = None
            warming, self._warming = self._warming, None
            if handover:
                self._changing = True
        procs.end(warming)  # a newer layout came while one was still warming up: that one is dropped at once
        threading.Thread(target=self._keep_picture, args=(gen, picture, make, folder, handover, {s.key for s in srcs}), name="stream", daemon=True).start()
        if files:
            threading.Thread(target=self._keep_words_current, args=(gen, picture, srcs, files), name="stream-words", daemon=True).start()
        return self.status()

    def resume(self, db: Session, session_factory) -> None:
        """After the plugin's own restart: live again by itself when it was live (LIVE_KEY), trying every RESUME_EVERY
        seconds while it can't yet, until it is, or Stop is pressed."""
        def run():
            while db.get(LIVE_KEY) and not self._wanted.is_set():
                try:
                    self.go_live(db, session_factory, resumed=True)
                    print("stream: live again after a restart, as it was before", flush=True)
                    return
                except Exception as e:  # noqa: BLE001 - said on the page, and tried again
                    with self._lock:
                        self._error = f"Going live again after a restart didn't work yet ({e}). Trying again in {RESUME_EVERY} s."
                    print(f"stream: {self._error}", flush=True)
                time.sleep(RESUME_EVERY)

        if db.get(LIVE_KEY):
            threading.Thread(target=run, name="stream-resume", daemon=True).start()

    def _start_session(self, db: Session, session_factory, chosen: dict, ffmpeg: str, url: str, key: str,
                       creds: dict | None = None, own: dict | None = None, resumed: bool = False) -> None:
        """Going live afresh: signed in, a new broadcast on the channel first (bound to Farmhand's own stream `own`, set
        from the YouTube settings; it starts by itself when the stream arrives); then the sender (the connection to
        YouTube), the delay's buffer and the music. With a pasted key instead, YouTube makes the broadcast itself and
        Farmhand can't set its title."""
        self.stop(forget=False)
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
            self._resolution = chosen["resolution"]
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
            self._healed = None
            self._wanted.set()
        if resumed and buffer.delay > 0:
            self._hold(db, chosen, ffmpeg, buffer, player)
        threading.Thread(target=self._keep_sending, args=(gen, sender_command(ffmpeg, url), buffer), name="stream-sender", daemon=True).start()
        threading.Thread(target=self._watch_flow, args=(gen, self._relay), name="stream-self-check", daemon=True).start()
        if broadcast:
            def read_settings() -> dict:
                with session_factory() as s:
                    return settings(s)

            threading.Thread(target=broadcast.watch, name="stream-youtube", daemon=True, args=(
                buffer.delay, lambda seconds: self._wait(gen, seconds), read_settings, lambda said: self._said_by_youtube(gen, said))).start()

    def _hold(self, db: Session, chosen: dict, ffmpeg: str, buffer: Buffer, player) -> None:
        """After the plugin's own restart: the holding screen to YouTube straight away, while the delay fills again
        behind it (holding.py). Best tried: without it the stream still goes live, as from Go live."""
        width, height, kbps = RESOLUTIONS.get(chosen["resolution"], RESOLUTIONS[DEFAULT_RESOLUTION])
        mine = chosen["holding"]
        colours = holding.look(mine, chosen)
        picture = None
        if mine.get("image"):
            try:
                picture = str(stream_media.picture_path(db, None, mine["image"]))
            except (ValueError, OSError, LookupError):
                picture = None  # (gone from the stream folder: the words alone)
        with self._lock:
            folder = self._cache
        try:
            png = os.path.join(folder, "holding.png")
            holding.draw(png, width, height, mine["text"], colours["background"], colours["color"], font_file(colours["font"]), picture)
            proc = procs.popen(holding.command(ffmpeg, png, encoder(ffmpeg), kbps), feed=True, out=True)
        except (OSError, ValueError, TypeError) as e:
            print(f"stream: the holding screen couldn't be shown ({e}); going live without it", flush=True)
            return
        threading.Thread(target=self._listen, args=(proc,), name="stream-holding-listen", daemon=True).start()
        if player:
            player.attach(proc.stdin)
        buffer.fill_from(proc)

    def stop(self, forget: bool = True, end_broadcast: bool = True) -> dict:
        """Stop the stream. `forget`: Stop pressed (it won't go live again after a restart); False when the plugin is
        only shutting down, or going live afresh. `end_broadcast`: end the broadcast on YouTube too; False when the
        plugin is only shutting down (a new image, a reboot): it carries on with that broadcast when it's back."""
        if forget:
            s = store()
            s.put(LIVE_KEY, None)
            s.commit()
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
            self._resolution = None
            self._run_started = None
            self._title = None
            player, self._player = self._player, None
            broadcast, self._broadcast = self._broadcast, None
            warming, self._warming = self._warming, None
            cache, self._cache = self._cache, None
            fed, self._feeders = self._feeders, {}
            self._showing = []
            self._changing = False
        for f in fed.values():
            f.stop()
        if player:
            player.stop()
        procs.end(warming)
        if cache:
            shutil.rmtree(cache, ignore_errors=True)
        if broadcast and end_broadcast:  # ended on YouTube (it becomes the channel's saved video)
            broadcast.end()
        elif broadcast:
            broadcast.ended = True  # (left live on YouTube; nothing more is asked of it here)
        if buffer:
            buffer.close()
        for p in (proc, sender):
            procs.end(p)
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        return self.status()

    def send_to_youtube(self, db: Session, chosen: dict, text_changed: bool = True, asked: bool = False) -> None:
        """The YouTube settings (`chosen`) saved while live: onto Farmhand's own broadcast, all of them; live on a pasted
        key, just the title and description, on the broadcast YouTube made (when they changed, or `asked`: the page's
        button). Asked, ValueError says why it can't be tried; otherwise that's left quietly. status.title says how
        it went."""
        if config.settings.test_destination:  # (being tried out: YouTube is never sent anything)
            return
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

    def _wait(self, gen: int, seconds: float, picture: int | None = None) -> bool:
        """Wait `seconds`, in short steps; False as soon as the stream is stopped or started again (or, given `picture`,
        its layout is handed over from)."""
        end = time.monotonic() + seconds
        while self._current(gen, picture) and (left := end - time.monotonic()) > 0:
            time.sleep(min(0.5, left))
        return self._current(gen, picture)


stream = Stream()
