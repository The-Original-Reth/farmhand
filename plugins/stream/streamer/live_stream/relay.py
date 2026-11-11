"""
The one connection to YouTube, kept for as long as the stream is live, and what goes down it.

The picture ffmpeg makes the picture and compresses it (MPEG-TS on its stdout); the sender, an ffmpeg of its own,
passes it on unchanged to YouTube (-c copy), so it costs next to nothing. Between them, the relay: it reads the picture
ffmpeg and writes the sender. Changing the layout starts a new picture ffmpeg beside the old one: once it's going, the
relay switches over at its first whole frame (a keyframe comes every two seconds) and the old one is stopped. YouTube
never loses the connection; viewers see the new layout instead of a pause.

Each picture ffmpeg is given its times from the stream's start (-output_ts_offset), so the sender sees one picture whose
times carry on across a switch. Both make the same MPEG-TS programme (the same PIDs), so the sender reads on as if it
were one.
"""
from __future__ import annotations

import collections
import threading
import time

PACKET = 188
CHUNK = PACKET * 64
VIDEO_PID = 0x100  # ffmpeg's mpegts muxer gives the first stream (the picture) this PID
TRIM_OVER = 5  # seconds over the delay the buffer may hold before it's trimmed back (Buffer._trim)


def keyframe_at(data: bytes) -> int | None:
    """Where in `data` (whole TS packets) the first packet starting a keyframe of the picture is, or None. A keyframe's
    first packet has the random access indicator set in its adaptation field."""
    for i in range(0, len(data) - PACKET + 1, PACKET):
        p = data[i:i + PACKET]
        if p[0] != 0x47:
            continue
        pid = ((p[1] & 0x1F) << 8) | p[2]
        if pid != VIDEO_PID or not (p[1] & 0x40):  # (payload unit start: a new frame)
            continue
        if (p[3] >> 4) & 0x2 and p[4] > 0 and p[5] & 0x40:
            return i
    return None


def last_frame_start(data: bytes) -> int | None:
    """Where in `data` the last packet starting a frame of the picture is (or None): what follows it may be half a
    frame, held back until the next read, so a switch never cuts the old picture in the middle of one."""
    for i in range(len(data) - PACKET, -1, -PACKET):
        p = data[i:i + PACKET]
        if p[0] == 0x47 and p[1] & 0x40 and (((p[1] & 0x1F) << 8) | p[2]) == VIDEO_PID:
            return i
    return None


def last_time(data: bytes) -> float | None:
    """The time (seconds) of the last frame of the picture starting in `data`, from its PES header's PTS, or None."""
    for i in range(len(data) - PACKET, -1, -PACKET):
        p = data[i:i + PACKET]
        if p[0] != 0x47 or not p[1] & 0x40 or (((p[1] & 0x1F) << 8) | p[2]) != VIDEO_PID:
            continue
        at = 4 + (1 + p[4] if (p[3] >> 4) & 0x2 else 0)
        pes = p[at:]
        if len(pes) < 14 or pes[:3] != b"\x00\x00\x01" or not (pes[7] >> 6) & 0x2:
            continue
        b = pes[9:14]
        pts = ((b[0] >> 1) & 0x7) << 30 | b[1] << 22 | (b[2] >> 1) << 15 | b[3] << 7 | b[4] >> 1
        return pts / 90000
    return None


def _read_packets(stream, size: int = CHUNK) -> bytes:
    """Up to `size` bytes from `stream`, in whole TS packets (b"" once it has ended)."""
    data = stream.read(size)
    if not data:
        return b""
    while len(data) % PACKET:
        more = stream.read(PACKET - len(data) % PACKET)
        if not more:
            return data[: len(data) - len(data) % PACKET]
        data += more
    return data


class Relay:
    """Passes one picture ffmpeg's output on to the sender at a time. `out`: the sender's stdin (swapped with set_out when
    the sender is started again)."""

    def __init__(self, out=None):
        self._lock = threading.Lock()
        self._out = out
        self._current = None  # the picture ffmpeg going out
        self._next = None  # the one to switch to at its first keyframe
        self._switched = threading.Event()
        self._last: float | None = None  # the time of the last frame passed on (its PTS, seconds)

    def set_out(self, out) -> None:
        with self._lock:
            self._out = out

    def start(self, picture) -> None:
        """Pass this picture ffmpeg on from now (the first, or one started after the last one stopped)."""
        with self._lock:
            self._current, self._next = picture, None
        self._read(picture)

    def switch_to(self, picture, timeout: float = 20.0) -> bool:
        """Pass this one on instead, from its first keyframe; the one going out keeps going out until then. True once
        it has taken over (the caller then stops the old one); False when it didn't within `timeout` seconds, or ended
        first (stopped for a newer layout, or failed)."""
        self._switched.clear()
        with self._lock:
            self._next = picture
        self._read(picture)
        self._switched.wait(timeout)
        with self._lock:
            if self._next is picture:
                self._next = None
            return self._current is picture

    def current(self):
        with self._lock:
            return self._current

    def last_time(self) -> float | None:
        """The time of the last frame passed on (seconds), or None before the first: a new picture's times carry on
        from about here, so the sender, playing to the times, never waits out a jump ahead."""
        with self._lock:
            return self._last

    def _read(self, picture) -> None:
        threading.Thread(target=self._pump, args=(picture,), name="stream-relay", daemon=True).start()

    def _pump(self, picture) -> None:
        """Read one picture ffmpeg's output to its end: written on while it's the one going out; until then (a new one
        warming up) looked through for its first keyframe; after (an old one being stopped) read and dropped, so it never
        stalls on a full pipe."""
        stdout = picture.stdout
        held = b""  # the frame being read, not yet whole: written once the next one starts
        while True:
            try:
                data = _read_packets(stdout)
            except (OSError, ValueError):
                data = b""
            if not data:
                with self._lock:
                    if self._next is picture:  # ended before it took over: the one waiting on it hears at once
                        self._next = None
                        self._switched.set()
                return
            with self._lock:
                if self._next is picture:
                    at = keyframe_at(data)
                    if at is None:
                        continue
                    self._current, self._next = picture, None
                    data, held = data[at:], b""
                    self._switched.set()
                if self._current is not picture or self._out is None:
                    held = b""  # (switched away from: its half frame is never sent)
                    continue
                data = held + data
                cut = last_frame_start(data)
                if cut is None:  # (before the picture's first frame: nothing to hold back)
                    held = b""
                else:  # everything before the last frame's start is whole: sent; the rest held back
                    data, held = data[:cut], data[cut:]
                if not data:
                    continue
                out = self._out
                t = last_time(data)
                if t is not None:
                    self._last = t
                try:
                    out.write(data)
                    out.flush()
                except (OSError, ValueError):  # the sender has ended: it's started again, with set_out
                    pass


class Buffer:
    """The stream's delay: the finished video and sound held for `delay` seconds before any of it goes to the sender, which
    then plays it out at its own real-time pace (-re) from the front. A stall shorter than the delay (a camera's hiccup,
    a moment the processor fell behind, a layout's hand-over) never reaches YouTube. The relay writes into it; the sender
    is given to it with set_sink (again whenever it's started again)."""

    def __init__(self, delay: float):
        self.delay = max(0.0, float(delay))
        self._cond = threading.Condition()
        self._chunks: collections.deque[tuple[float, bytes]] = collections.deque()  # (when it came, data)
        self._sink = None
        self._started = False  # the delay has passed once: from then on, what comes is passed on as the sender takes it
        self._first: float | None = None
        self._ended = False
        threading.Thread(target=self._feed, name="stream-buffer", daemon=True).start()

    def write(self, data: bytes) -> None:
        with self._cond:
            now = time.monotonic()
            if self._first is None:
                self._first = now
            self._chunks.append((now, bytes(data)))
            if self._started and self._chunks and now - self._chunks[0][0] > self.delay + TRIM_OVER:
                self._trim(now)
            self._cond.notify_all()

    def _trim(self, now: float) -> None:
        """More than TRIM_OVER seconds over the delay is held (each hand-over adds a little; a sender that isn't taking
        anything adds a lot): what's older is dropped, back to a keyframe that leaves about the delay held, so the
        sender reads on from a whole picture. (Called holding the lock.)"""
        for i, (came, data) in enumerate(self._chunks):
            if now - came > self.delay:
                continue
            at = keyframe_at(data)
            if at is not None:
                for _ in range(i):
                    self._chunks.popleft()
                self._chunks[0] = (came, data[at:])
                return

    def flush(self) -> None:
        pass

    def set_sink(self, sink) -> None:
        with self._cond:
            self._sink = sink
            self._cond.notify_all()

    def close(self) -> None:
        with self._cond:
            self._ended = True
            self._cond.notify_all()

    def held(self) -> float:
        """How many seconds of stream are held now: how far behind the picture YouTube gets is (0 before the first)."""
        with self._cond:
            return round(time.monotonic() - self._chunks[0][0], 1) if self._chunks else 0.0

    def filling(self) -> bool:
        """Still collecting the delay, before anything has gone to YouTube."""
        with self._cond:
            return not self._started

    def _feed(self) -> None:
        while True:
            with self._cond:
                while not self._ended and (self._sink is None or not self._chunks
                                           or (not self._started and time.monotonic() - self._first < self.delay)):
                    self._cond.wait(0.2)
                if self._ended:
                    return
                self._started = True
                came, data = self._chunks.popleft()
                sink = self._sink
            try:
                sink.write(data)  # (blocks while the sender, reading at real time, has its pipe full)
                sink.flush()
            except (OSError, ValueError):  # that sender has ended: what it didn't take goes to the next one
                with self._cond:
                    self._chunks.appendleft((came, data))
                    if self._sink is sink:
                        self._sink = None
