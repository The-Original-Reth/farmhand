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

from ...errors import NotFound
from ... import storage
from ...models import Printer
from .. import app_settings, print_progress, stream_media, youtube_live
from .constants import DESTINATIONS, FPS, KEPT_LINES, RETRY_SECONDS, STATUS_EVERY, STREAM_KEY_KEY, TITLE_EVERY, TITLE_TRIES
from .choices import settings
from .sources import Source, sources
from .picture import Look, TURNS_FOR, command, encoder_args, status_line, timetable

# ------------------------------------------------------------------ the stream itself


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


# FARMHAND_STREAM_ENCODER: "auto" (the default: an NVIDIA card's encoder when one works here, else the processor),
# "nvenc" or "cpu" to say which. What "auto" finds is remembered until Farmhand starts again.
ENCODER_SETTING = "FARMHAND_STREAM_ENCODER"
_found_encoder: dict[str, str] = {}


def _nvenc_works(ffmpeg: str) -> bool:
    """Whether ffmpeg can compress with an NVIDIA card here: a moment's black picture through it (no card, no driver
    in reach, or an ffmpeg without it: no)."""
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s=256x144:r={FPS}",
             "-frames:v", "5", *encoder_args("nvenc"), "-f", "null", "-"],
            capture_output=True, timeout=20,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def encoder(ffmpeg: str) -> str:
    """"nvenc" or "cpu": how the stream is compressed (see FARMHAND_STREAM_ENCODER)."""
    wanted = (os.environ.get(ENCODER_SETTING) or "auto").strip().lower()
    if wanted in ("cpu", "nvenc"):
        return wanted
    if ffmpeg not in _found_encoder:
        _found_encoder[ffmpeg] = "nvenc" if _nvenc_works(ffmpeg) else "cpu"
    return _found_encoder[ffmpeg]


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
        cards = {c: cell for c, cell in enumerate(chosen["cells"]) if cell and "camera" not in cell}
        pictures = _card_pictures(db, cards)
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
                    _write_atomically(files[i], s.label)
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
        # ffmpeg reads each picture again every second: it reads copies made here once, never the stream folder (on
        # the NAS, that's a hundred files opened a second, and pictures being copied in clash with it)
        pictures = _local_copies(pictures, folder)
        # each card's words, as a file ffmpeg reads
        text_paths = {}
        captions = {}  # square -> {its picture's place in the slideshow: {"words": file, "text_box"}}
        for c, cell in cards.items():
            if cell.get("text"):
                text_paths[c] = os.path.join(folder, f"text-{c}.txt")
                _write_atomically(text_paths[c], cell["text"])
            for j, path in enumerate(pictures.get(c, [])):
                cap = (cell.get("captions") or {}).get(os.path.basename(path))
                if cap and cap.get("text"):
                    words = os.path.join(folder, f"text-{c}-{j}.txt")
                    _write_atomically(words, cap["text"])
                    captions.setdefault(c, {})[j] = {"words": words, "text_box": cap.get("text_box")}
        timed = timetable(len(srcs), *cycle) if cycle else ""
        turns_file = None
        if timed:
            turns_file = os.path.join(folder, "turns.txt")
            with open(turns_file, "w", encoding="utf-8") as f:
                f.write(timed)
        place = {k: i for i, k in enumerate(chosen["cameras"])}
        def square(c: int, cell: dict | None):
            if not cell:
                return None
            if "camera" in cell:
                return ("camera", place[cell["camera"]], cell)
            return ("card", {**cell, "pictures": pictures.get(c, []), "words": text_paths.get(c), "picture_words": captions.get(c, {})})

        cells = [square(c, cell) for c, cell in enumerate(chosen["cells"])]
        enc = encoder(ffmpeg)
        with self._lock:
            self._encoder = enc
        args = command(ffmpeg, srcs, where["url"] + key, Look(encoder=enc,
            status_files=files, cycle=cycle, turns_file=turns_file,
            resolution=chosen["resolution"], border_color=chosen["border_color"], background=chosen["background"], font=chosen["font"], color=chosen["color"], cols=chosen["cols"],
            rows=chosen["rows"], cells=cells,
        ))
        threading.Thread(target=self._keep_running, args=(gen, args), name="stream", daemon=True).start()
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

    def _keep_running(self, gen: int, args: list[str]) -> None:
        while self._current(gen):
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
                continue  # the day's timetable of turns is done: started again at once, from the top
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
                        _write_atomically(f, status_line(s.label, by_printer.get(s.printer_id) or {}))
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


def _card_pictures(db: Session, cards) -> dict:
    """Each card's pictures, as files in the stream folder: {square: [paths]} (its picture, or its slideshow's). One not
    there (or a stream folder that isn't available) shows just the card's colour and words."""
    out = {}
    for c, cell in (cards.items() if isinstance(cards, dict) else []):
        try:
            if cell.get("slideshow"):
                out[c] = [str(p) for p in stream_media.slideshow_paths(db, cell["slideshow"])]
            elif cell.get("image"):
                out[c] = [str(stream_media.picture_path(db, None, cell["image"]))]
        except (NotFound, ValueError, storage.StorageUnavailableError, OSError):
            out[c] = []
    return out


def _local_copies(pictures: dict, folder: str) -> dict:
    """The cards' pictures copied once into the stream's own folder, each under its own name (a slideshow picture's
    words go by it): {square: [copies]}. One picture in several squares is copied once; one that can't be read now
    (being copied in, say) is left out, as one not there is."""
    copied: dict[str, str | None] = {}
    out = {}
    for c, paths in pictures.items():
        out[c] = []
        for path in paths:
            if stream_media.is_blank(path):  # a blank screen: no picture, just its time
                out[c].append(path)
                continue
            if path not in copied:
                to = os.path.join(folder, "pictures", str(len(copied)), os.path.basename(path))
                try:
                    os.makedirs(os.path.dirname(to), exist_ok=True)
                    shutil.copyfile(path, to)
                    copied[path] = to
                except OSError:
                    copied[path] = None
            if copied[path]:
                out[c].append(copied[path])
    return out


def _sleep_unless(stream: Stream, gen: int, seconds: float) -> bool:
    """Wait `seconds`, in short steps; False as soon as the stream is stopped or started again."""
    end = time.monotonic() + seconds
    while stream._current(gen) and (left := end - time.monotonic()) > 0:
        time.sleep(min(0.5, left))
    return stream._current(gen)


def _write_atomically(path: str, text: str) -> None:
    """drawtext reads the file again every frame: it's swapped in whole, never seen half written."""
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


stream = Stream()
