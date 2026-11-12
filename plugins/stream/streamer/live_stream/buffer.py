"""
The stream's delay (Buffer): the finished video and sound held before any of it goes to the sender, counted by the
stream's own times, filled again behind the holding screen after the plugin's own restart. The relay (relay.py) writes
into it; the sender reads it.
"""
from __future__ import annotations

import collections
import threading
import time

from .relay import _read_packets, keyframe_at, last_frame_start, last_time

TRIM_OVER = 5  # seconds over the delay the buffer may hold before it's trimmed back (Buffer._trim)
FILL_MOST = 30  # seconds past the delay, by the clock, after which the sender is started though less is held
JUMP = 5  # seconds: a step in the stream's times over this (back or forward) is a hand-over, not stream (Buffer)
PTS_WRAP = (1 << 33) / 90000  # seconds after which an MPEG-TS time starts again from 0 (about 26.5 hours)


class Buffer:
    """The stream's delay: the finished video and sound held for `delay` seconds before any of it goes to the sender, which
    then plays it out at its own real-time pace (-re) from the front. A stall shorter than the delay (a camera's hiccup,
    a moment the processor fell behind, a layout's hand-over) never reaches YouTube. The relay writes into it; the sender
    is given to it with set_sink (again whenever it's started again).

    What's held is counted by the stream's own times: each piece keeps how much stream it adds (its last frame's time
    less the one before's), and the held total is the sum. A step back or a leap (over JUMP: a layout's hand-over, whose
    new picture's times start a little behind the old one's) adds nothing, as the sender plays straight on over it."""

    def __init__(self, delay: float):
        self.delay = max(0.0, float(delay))
        self._cond = threading.Condition()
        self._chunks: collections.deque[tuple[float, bytes, float]] = collections.deque()  # (when it came, data, stream it adds)
        self._total = 0.0  # the sum of the pieces' stream (held: less the first's, which came before it)
        self._newest: float | None = None  # the time (PTS, seconds) of the newest frame written
        self._sink = None
        self._started = False  # the delay has passed once: from then on, what comes is passed on as the sender takes it
        self._first: float | None = None
        self._ended = False
        self._filler = None  # while filling: what the sender is given meanwhile (the holding screen's ffmpeg), or None
        threading.Thread(target=self._feed, name="stream-buffer", daemon=True).start()

    def fill_from(self, proc) -> None:
        """While the delay fills, give the sender `proc`'s stream (the holding screen: MPEG-TS on its stdout) so YouTube
        has video meanwhile; once the delay is held it's switched to what's held, at a whole frame, and `proc` is
        ended (terminate())."""
        with self._cond:
            if self._started or self._ended:
                _stop(proc)
                return
            self._filler = proc
            self._cond.notify_all()

    def filled_from(self):
        """The holding screen's ffmpeg while it's going out, else None."""
        with self._cond:
            return self._filler

    def write(self, data: bytes) -> None:
        with self._cond:
            now = time.monotonic()
            if self._first is None:
                self._first = now
            step, t = 0.0, last_time(data)
            if t is not None:
                if self._newest is not None:
                    gone = (t - self._newest) % PTS_WRAP
                    step = gone if gone <= JUMP else 0.0
                self._newest = t
            self._push((now, bytes(data), step))
            if self._started and self._held() > self.delay + TRIM_OVER:
                self._trim(now)
            self._cond.notify_all()

    def _push(self, chunk, front: bool = False) -> None:
        (self._chunks.appendleft if front else self._chunks.append)(chunk)
        self._total += chunk[2]

    def _pop(self):
        chunk = self._chunks.popleft()
        self._total -= chunk[2]
        if not self._chunks:
            self._total = 0.0  # (no rounding left over)
        return chunk

    def _trim(self, now: float) -> None:
        """More than TRIM_OVER seconds over the delay is held (each hand-over adds a little; a sender that isn't taking
        anything adds a lot): what's older is dropped, back to a keyframe that leaves about the delay held, so the
        sender reads on from a whole picture. (Called holding the lock.)"""
        timed = self._newest is not None
        left = self._held()
        for i, (came, data, step) in enumerate(self._chunks):
            if i:
                left -= step
            if (left if timed else now - came) > self.delay:
                continue
            at = keyframe_at(data)
            if at is not None:
                for _ in range(i):
                    self._pop()
                self._chunks[0] = (came, data[at:], self._chunks[0][2])
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
            filler, self._filler = self._filler, None
            self._cond.notify_all()
        _stop(filler)

    def held(self) -> float:
        """
        How many seconds of stream are held now: how far behind the picture YouTube gets is (0 before the first). By the
        stream's own times, not by when it came: a picture that stopped for a moment and then made up the time it lost
        holds as much stream as before, though none of it came in that moment. (By when it came for a stream with no
        times in it.)
        """
        with self._cond:
            return round(self._held(), 1)

    def _held(self) -> float:
        """held(), called holding the lock."""
        if not self._chunks:
            return 0.0
        if self._newest is None:
            return time.monotonic() - self._chunks[0][0]
        return max(0.0, self._total - self._chunks[0][2])

    def _full(self) -> bool:
        """The delay is held, by the stream's own times (a picture just started makes a little less than real time while
        its cameras connect: by the clock alone the stream would start, and stay, a few seconds short of its delay); or
        FILL_MOST seconds more have passed by the clock. (Called holding the lock.)"""
        waited = time.monotonic() - self._first
        return waited >= self.delay + FILL_MOST or (waited >= self.delay and self._held() >= self.delay)

    def filling(self) -> bool:
        """Still collecting the delay, before anything has gone to YouTube."""
        with self._cond:
            return not self._started

    def _ready(self) -> bool:
        """What's held can go to the sender: started already, or the delay is held. (Called holding the lock.)"""
        return bool(self._chunks) and (self._started or self._full())

    def _feed(self) -> None:
        spare = b""  # the holding screen's frame being read, not yet whole
        while True:
            with self._cond:
                while not self._ended and (self._sink is None or not (self._ready() or self._filler is not None)):
                    self._cond.wait(0.2)
                if self._ended:
                    return
                sink, chunk, filler = self._sink, None, None
                if self._ready():
                    self._started = True
                    filler, self._filler = self._filler, None
                    chunk = self._pop()
                else:
                    filler = self._filler
            if chunk is None:  # filling: a piece of the holding screen meanwhile, in whole frames
                try:
                    data = _read_packets(filler.stdout)
                except (OSError, ValueError, AttributeError):
                    data = b""
                if not data:  # (it ended: nothing more meanwhile)
                    with self._cond:
                        if self._filler is filler:
                            self._filler = None
                    continue
                data = spare + data
                cut = last_frame_start(data)
                data, spare = (data[:cut], data[cut:]) if cut is not None else (data, b"")
                if data and not self._send(sink, data):
                    spare = b""
                continue
            if filler is not None:  # the delay is held: the holding screen ends, and what's held goes out from here
                _stop(filler)
                spare = b""
            if not self._send(sink, chunk[1]):  # that sender has ended: what it didn't take goes to the next one
                with self._cond:
                    self._push(chunk, front=True)

    def _send(self, sink, data: bytes) -> bool:
        """`data` to the sender (blocking while the sender, reading at real time, has its pipe full). False when it has
        ended (it's started again, with set_sink)."""
        try:
            sink.write(data)
            sink.flush()
            return True
        except (OSError, ValueError):
            with self._cond:
                if self._sink is sink:
                    self._sink = None
            return False


def _stop(proc) -> None:
    """End the holding screen's ffmpeg (a stand-in may have nothing to end)."""
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
    except (AttributeError, OSError):
        pass
