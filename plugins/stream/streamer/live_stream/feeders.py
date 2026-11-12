"""
Each camera read on its own, and the picture fed from steady pipes, so one camera that stops never holds up or restarts
the others: its square says "Camera down" until it's back.

A Feeder per camera: a small ffmpeg reading the camera (as Farmhand's /cameras says), turning it the way Mainsail
shows it, fitting it in the stream's size and putting out JPEG frames at most FPS a second on its stdout; a thread
keeps the latest. One that stops is started again after a growing wait (RETRY_FIRST, doubling up to RETRY_MOST),
back to the shortest once frames come again. Feeders belong to the time live, not to a layout: a new layout's picture
reads the same ones, so a camera never gets a second connection.

A Pump per picture ffmpeg: for each camera square, a named pipe the picture ffmpeg reads as an image2pipe input, written
at a steady FPS with the camera's latest frame, or the "Camera down" frame when it has sent nothing for DOWN_AFTER
seconds. The picture's inputs never end or stall, so it never has to be started again for a camera.

The "Camera down" frame: drawn with Pillow at the camera's own size, in the square's background colour, "Camera down"
in the chosen font and words colour, the printer's name under it.
"""
from __future__ import annotations

import collections
import io
import os
import threading
import time

from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont

from .constants import FPS
from .pacing import pace

DOWN_AFTER = 10  # seconds without a frame before a camera counts as down
RETRY_FIRST, RETRY_MOST = 5, 60  # seconds before a feeder that stopped is started again (doubling)
READ = 65536
MOST_HELD = 8 * 1024 * 1024  # bytes read without a whole frame in them: the feeder is started again
JPEG_QUALITY = 4  # ffmpeg's -q:v for the feeders' frames (2 best .. 31 worst)
KEPT_LINES = 10
# A camera's own frame rate: its feeder puts out FPS frames a second whatever the camera sends (ffmpeg's fps filter
# repeats a frame for a slow camera), and a repeated frame comes out the same, byte for byte. So the frames that differ
# from the one before, over the last RATE_WINDOW seconds, are what the camera really sent. Under SLOW_FPS (a camera set
# to 15 a second gives 14.5 to 15.5), its square changes less often than the stream does, and the page says so.
RATE_WINDOW = 20
SLOW_FPS = 14.0


def fit(aspect: str | None, width: int, height: int, turned: bool = False) -> tuple[int, int]:
    """The size (even) a camera of this shape ("16:9", "4:3"; turned: on its side) has fitted in width x height."""
    try:
        a, b = (float(x) for x in str(aspect or "16:9").split(":"))
        ratio = a / b if a > 0 and b > 0 else 16 / 9
    except ValueError:
        ratio = 16 / 9
    if turned:
        ratio = 1 / ratio
    w, h = width, round(width / ratio)
    if h > height:
        w, h = round(height * ratio), height
    return max(2, w // 2 * 2), max(2, h // 2 * 2)


def jpeg_size(frame: bytes) -> tuple[int, int] | None:
    """A JPEG's (width, height), from its frame header, or None."""
    i = 2
    while i + 9 < len(frame):
        if frame[i] != 0xFF:
            return None
        marker = frame[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            return (frame[i + 7] << 8 | frame[i + 8], frame[i + 5] << 8 | frame[i + 6])
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + (frame[i + 2] << 8 | frame[i + 3])
    return None


def frames_in(buffer: bytearray) -> list[bytes]:
    """The whole JPEGs at the front of `buffer`, taken out of it (what follows the last is left for the next read)."""
    out = []
    while True:
        start = buffer.find(b"\xff\xd8")
        if start < 0:
            del buffer[:max(0, len(buffer) - 1)]
            return out
        end = buffer.find(b"\xff\xd9", start + 2)
        if end < 0:
            del buffer[:start]
            return out
        out.append(bytes(buffer[start:end + 2]))
        del buffer[:end + 2]


def feeder_command(ffmpeg: str, input_args: list[str], turn: list[str], size: tuple[int, int]) -> list[str]:
    """The camera read, turned, fitted in `size` (its own shape kept) and put out as JPEGs on stdout."""
    w, h = size
    chain = [*turn, f"fps={FPS}", f"scale={w}:{h}:force_original_aspect_ratio=decrease", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "setsar=1"]
    return [ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin", *input_args, "-an", "-vf", ",".join(chain),
            "-c:v", "mjpeg", "-q:v", str(JPEG_QUALITY), "-f", "image2pipe", "pipe:1"]


class Feeder:
    """One camera, read by its own ffmpeg for as long as the stream is live (`popen(args)` starts one with its stdout
    to read: the runner's, which tests swap). With no address (`input_args` empty) it's down until it has one."""

    def __init__(self, ffmpeg: str, key: str, input_args: list[str], turn: list[str], size: tuple[int, int], popen,
                 aspect: str | None = None):
        self.key, self.input_args, self.turn, self.size = key, list(input_args), list(turn), size
        # the size its frames are taken to be until the first comes (its shape as Mainsail has it, fitted in `size`)
        self.guess = fit(aspect, *size, turned=any(t.startswith("transpose") for t in turn))
        self._args = feeder_command(ffmpeg, input_args, turn, size) if input_args else None
        self._popen = popen
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._frame: bytes | None = None
        self._frame_size: tuple[int, int] | None = None
        self._at = 0.0  # (monotonic) when the latest frame came
        self._proc = None
        self._started = time.monotonic()
        self._down_since: float | None = time.time()  # (time of day) since when it has been down; None while live
        self.said: collections.deque[str] = collections.deque(maxlen=KEPT_LINES)
        self.restarts = 0
        self._new: collections.deque[float] = collections.deque()  # (monotonic) when each new picture came, RATE_WINDOW's worth
        self._reading_since: float | None = None  # (monotonic) when the frames of this connection began

    def same(self, input_args: list[str], turn: list[str], size: tuple[int, int]) -> bool:
        return self.input_args == list(input_args) and self.turn == list(turn) and self.size == size

    def start(self) -> "Feeder":
        if self._args:
            threading.Thread(target=self._run, name=f"stream-feeder {self.key}", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stopped.set()
        with self._lock:
            proc = self._proc
        _end(proc)

    def latest(self) -> tuple[bytes | None, tuple[int, int] | None]:
        """The latest frame and its size, while it's fresh (DOWN_AFTER); (None, the last size known) when it's down."""
        with self._lock:
            fresh = self._frame is not None and time.monotonic() - self._at < DOWN_AFTER
            return (self._frame if fresh else None), self._frame_size

    def fps(self) -> float | None:
        """The camera's own frame rate (see RATE_WINDOW), once it has sent frames for a whole RATE_WINDOW; else None."""
        now = time.monotonic()
        with self._lock:
            while self._new and now - self._new[0] > RATE_WINDOW:
                self._new.popleft()
            if self._reading_since is None or now - self._reading_since < RATE_WINDOW:
                return None
            return len(self._new) / RATE_WINDOW

    def state(self) -> dict:
        """{state: "live" | "down" | "starting", since (ISO time it went down, or None)}; while live also fps (the
        camera's own frame rate, one decimal, or None until it's known) and slow (under SLOW_FPS)."""
        frame, _ = self.latest()
        fps = self.fps() if frame is not None else None
        with self._lock:
            if frame is not None:
                if self._down_since is not None:
                    self._down_since = None
                return {"state": "live", "since": None, "fps": None if fps is None else round(fps, 1),
                        "slow": fps is not None and fps < SLOW_FPS}
            if self._frame is None and time.monotonic() - self._started < DOWN_AFTER and self._args:
                return {"state": "starting", "since": None}
            if self._down_since is None:
                self._down_since = time.time()
            since = datetime.fromtimestamp(self._down_since, timezone.utc).isoformat()
            last = next((l for l in reversed(self.said) if l), None)
            return {"state": "down", "since": since, "said": last}

    def _run(self) -> None:
        wait = RETRY_FIRST
        while not self._stopped.is_set():
            got = False
            try:
                proc = self._popen(self._args, out=True)
            except OSError as e:
                self.said.append(f"ffmpeg couldn't be started: {e.strerror or e}")
                proc = None
            if proc is not None:
                with self._lock:
                    self._proc = proc
                if self._stopped.is_set():
                    _end(proc)
                    return
                threading.Thread(target=self._listen, args=(proc,), name=f"stream-feeder-said {self.key}", daemon=True).start()
                got = self._read(proc)
                _end(proc)
            if self._stopped.is_set():
                return
            self.restarts += 1
            wait = RETRY_FIRST if got else min(RETRY_MOST, wait * 2 if self.restarts > 1 else wait)
            self._stopped.wait(wait)

    def _read(self, proc) -> bool:
        """Frames kept as they come, until the camera's ffmpeg ends. Whether any came."""
        buffer, got = bytearray(), False
        while not self._stopped.is_set():
            try:
                chunk = proc.stdout.read1(READ) if hasattr(proc.stdout, "read1") else proc.stdout.read(READ)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            buffer += chunk
            for frame in frames_in(buffer):
                size = jpeg_size(frame)
                now = time.monotonic()
                with self._lock:
                    if not got:  # (this connection's first: its frame rate is counted from here)
                        self._new.clear()
                        self._reading_since = now
                    if frame != self._frame:  # (one the fps filter repeated is the same, byte for byte)
                        self._new.append(now)
                    self._frame, self._at = frame, now
                    if size:
                        self._frame_size = size
                got = True
            if len(buffer) > MOST_HELD:
                self.said.append("The camera sent something that isn't a picture: reading it again.")
                break
        return got

    def _listen(self, proc) -> None:
        for line in proc.stderr or []:
            line = line.strip() if isinstance(line, str) else line.decode("utf-8", "replace").strip()
            if line:
                self.said.append(line)


def _end(proc) -> None:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 - one that won't end is killed
            proc.kill()


# ------------------------------------------------------------------ the "Camera down" square


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def down_frame(size: tuple[int, int], background: str, font_file: str, color: str, name: str) -> bytes:
    """A JPEG of `size`: the background colour, "Camera down" in the middle, the printer's name under it."""
    w, h = size
    picture = Image.new("RGB", (w, h), "#" + background.lstrip("#"))
    draw = ImageDraw.Draw(picture)
    ink = "#" + color.lstrip("#")
    big, small = _font(font_file, max(10, h // 9)), _font(font_file, max(8, h // 16))
    for text, font, y in (("Camera down", big, h * 0.42), (name, small, h * 0.58)):
        box = draw.textbbox((0, 0), text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        draw.text(((w - tw) / 2 - box[0], y - th / 2 - box[1]), text, font=font, fill=ink)
    out = io.BytesIO()
    picture.save(out, "JPEG", quality=85)
    return out.getvalue()


class DownFrames:
    """One camera's "Camera down" frame for a layout, drawn again only when the camera's size changes."""

    def __init__(self, background: str, font_file: str, color: str, name: str):
        self._look = (background, font_file, color, name)
        self._made: dict[tuple[int, int], bytes] = {}

    def at(self, size: tuple[int, int]) -> bytes:
        if size not in self._made:
            self._made = {size: down_frame(size, *self._look)}
        return self._made[size]


# ------------------------------------------------------------------ the picture's steady inputs


def make_fifo(path: str) -> None:
    """A named pipe the picture ffmpeg reads (tests swap this: Windows has none)."""
    os.mkfifo(path)


PROBE = 500000  # µs of a pipe the picture ffmpeg looks at before it starts (its default, 5 s, is 5 s a camera, one after another)


def pipe_input(path: str) -> list[str]:
    """How the picture ffmpeg reads one of a pump's pipes: JPEGs at FPS, looked at only briefly before it starts (the
    frame rate is given, so there's nothing more to find out)."""
    return ["-f", "image2pipe", "-framerate", str(FPS), "-analyzeduration", str(PROBE), "-c:v", "mjpeg", "-i", path]


class Pump:
    """
    One picture ffmpeg's camera inputs: a pipe per camera square, each written at a steady FPS by its own thread with the
    camera's latest frame or its "Camera down" frame. Started before the picture ffmpeg (each writer waits for it to
    open its pipe) and ended when it ends (watch()).
    """

    def __init__(self, cameras: list[tuple[Feeder, DownFrames]], paths: list[str]):
        self._cameras = cameras
        self.paths = paths
        self._stopped = threading.Event()
        self._files: list = []
        self._lock = threading.Lock()

    def start(self) -> "Pump":
        for path in self.paths:
            make_fifo(path)
        for (feeder, downs), path in zip(self._cameras, self.paths):
            threading.Thread(target=self._write, args=(feeder, downs, path), name="stream-pump", daemon=True).start()
        return self

    def watch(self, proc) -> None:
        """End the pump once `proc` (the picture ffmpeg reading it) has ended."""
        def wait():
            while proc.poll() is None and not self._stopped.is_set():
                time.sleep(0.5)
            self.stop()

        threading.Thread(target=wait, name="stream-pump-watch", daemon=True).start()

    def stop(self) -> None:
        if self._stopped.is_set():
            return
        self._stopped.set()
        for path in self.paths:  # a writer still waiting for its reader is let go: it opens, sees it's stopped, ends
            try:
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
                os.close(fd)
            except OSError:
                pass
        with self._lock:
            files, self._files = self._files, []
        for f in files:
            try:
                f.close()
            except OSError:
                pass

    def frame_for(self, feeder: Feeder, downs: DownFrames) -> bytes:
        frame, size = feeder.latest()
        return frame if frame is not None else downs.at(size or feeder.guess)

    def _write(self, feeder: Feeder, downs: DownFrames, path: str) -> None:
        try:
            f = open(path, "wb", buffering=0)
        except OSError:
            return
        with self._lock:
            if self._stopped.is_set():
                f.close()
                return
            self._files.append(f)
        step = 1 / FPS
        due, written = time.monotonic(), 0
        try:
            while not self._stopped.is_set():
                f.write(self.frame_for(feeder, downs))
                due, written = due + step, written + 1
                due = pace(due, written, step, time.monotonic())
        except (OSError, ValueError):
            pass  # the picture ffmpeg ended, or the pump was stopped
        finally:
            try:
                f.close()
            except OSError:
                pass
