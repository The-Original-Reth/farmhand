"""
The stream's music, played by Farmhand itself and fed to ffmpeg as it plays (raw sound on ffmpeg's stdin), so it can be
skipped, gone back, paused, turned up or down and turned off while live without starting ffmpeg again.

Two threads: one decodes the tracks (an ffmpeg of their own, a track at a time, `decoder`) into a couple of seconds
held ready; the other writes the sound out at exactly the pace it plays, 20 ms at a time: the music while it's on and
playing, silence otherwise (ffmpeg always gets sound, so the stream never waits for it). The tracks go round and
round: a round is every track there is when it starts (read again each round, so ones added while live join the next),
shuffled when chosen, in name order otherwise.
"""
from __future__ import annotations

import collections
import os
import random
import subprocess
import threading
import time

from array import array
from typing import Callable

SAMPLE_RATE, CHANNELS = 44100, 2
PER_SECOND = SAMPLE_RATE * CHANNELS * 2  # bytes of sound a second (16-bit)
CHUNK = PER_SECOND // 50  # 20 ms, a whole number of samples
HELD = PER_SECOND * 2  # how much is decoded ahead
BACK_RESTARTS = 3  # seconds into a track after which Back starts it again, rather than going to the one before
INPUT = ["-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS)]  # how the stream's ffmpeg reads it


def decoder(ffmpeg: str, path: str):
    """A track decoded to raw sound on stdout (tests swap this for a stand-in)."""
    return subprocess.Popen([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", path, "-vn", *INPUT, "pipe:1"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def gain(volume: int) -> float:
    """The volume (0 to 100) as a gain: squared, so the slider's middle sounds about half as loud (-12 dB)."""
    return (max(0, min(100, volume)) / 100) ** 2


class Player:
    """The music while live. `tracks()`: the tracks there are now (paths). attach() gives it where to write (the
    stream's ffmpeg's stdin, each time ffmpeg starts); stop() ends it."""

    def __init__(self, ffmpeg: str, tracks: Callable[[], list[str]], *, on: bool, shuffle: bool, volume: int):
        self._ffmpeg = ffmpeg
        self._tracks = tracks
        self._cond = threading.Condition()
        self._ended = False
        self.on, self.shuffle, self.volume = on, shuffle, volume
        self.playing = True
        self._upcoming: collections.deque[str] = collections.deque()  # what's to play, in order (a round, or Back's)
        self._held: collections.deque[list] = collections.deque()  # decoded sound to play: [track, bytes]
        self._held_bytes = 0
        self._decoding: str | None = None  # the track being decoded
        self._gen = 0  # moved on (skipped, gone back, turned off): the track being decoded is dropped
        self._heard: list[str] = []  # the tracks heard, latest last (the last is the one playing)
        self._at = 0  # bytes of the one playing heard so far
        self._outs: list[_Out] = []  # the picture ffmpegs being fed (two while a layout's hand-over is under way)
        threading.Thread(target=self._decode, name="stream-music-decode", daemon=True).start()
        threading.Thread(target=self._write, name="stream-music-write", daemon=True).start()

    # ---------------------------------------------------------------- what the page sees and does

    def status(self) -> dict:
        with self._cond:
            track = self._heard[-1] if self._heard else None
            return {"on": self.on, "playing": self.playing, "track": os.path.basename(track) if track else None,
                    "at": round(self._at / PER_SECOND, 1)}

    def attach(self, out) -> None:
        """Feed `out` too (a newly started picture ffmpeg's stdin), beside any already fed; ones that have ended are
        dropped."""
        with self._cond:
            self._outs = [o for o in self._outs if o.alive]
            self._outs.append(_Out(out))

    def stop(self) -> None:
        with self._cond:
            self._ended = True
            self._gen += 1
            self._cond.notify_all()

    def settings(self, *, on: bool, shuffle: bool, volume: int) -> None:
        """New choices, straight away: turned off, it's silent (and starts with a new track when on again); shuffling
        changes from the next round."""
        with self._cond:
            if self.on and not on:
                self._drop()
            self.on, self.shuffle, self.volume = on, shuffle, volume
            self._cond.notify_all()

    def play(self) -> None:
        with self._cond:
            self.playing = True
            self._cond.notify_all()

    def pause(self) -> None:
        """Silence, holding its place in the track."""
        with self._cond:
            self.playing = False

    def next(self) -> None:
        with self._cond:
            self._drop()
            self.playing = True
            self._cond.notify_all()

    def back(self) -> None:
        """The track playing from its start again, or (in its first seconds) the one before it."""
        with self._cond:
            current = self._heard[-1] if self._heard else None
            early = self._at < BACK_RESTARTS * PER_SECOND
            self._drop()
            if current:
                self._heard.pop()
                self._upcoming.appendleft(current)
                if early and self._heard:
                    self._upcoming.appendleft(self._heard.pop())
            self.playing = True
            self._cond.notify_all()

    # ---------------------------------------------------------------- inside

    def _drop(self) -> None:
        """Forget what's decoded ahead (the track being heard is left off; tracks decoded ahead go back to be played
        next) and drop the one being decoded. (Called holding the lock.)"""
        heard = self._heard[-1] if self._heard else None
        ahead = [t for t in dict.fromkeys([*(t for t, _ in self._held), *([self._decoding] if self._decoding else [])]) if t != heard]
        self._upcoming.extendleft(reversed(ahead))
        self._held.clear()
        self._held_bytes = 0
        self._decoding = None
        self._gen += 1

    def _new_round(self) -> list[str]:
        """Every track there is now, in this round's order. (Not holding the lock: it reads the stream folder.)"""
        try:
            round_ = list(self._tracks())
        except Exception:  # noqa: BLE001 - the stream folder can't be read now: tried again shortly
            round_ = []
        if self.shuffle:
            random.shuffle(round_)
        return round_

    def _next_track(self) -> str | None:
        """The next track to decode (a new round when this one is done), or None when there are none."""
        with self._cond:
            if self._upcoming:
                return self._upcoming.popleft()
        round_ = self._new_round()
        with self._cond:
            if not self._upcoming:
                self._upcoming.extend(round_)
            return self._upcoming.popleft() if self._upcoming else None

    def _decode(self) -> None:
        while True:
            with self._cond:
                while not self._ended and (not self.on or self._held_bytes >= HELD):
                    self._cond.wait(0.5)
                if self._ended:
                    return
                gen = self._gen
            track = self._next_track()
            with self._cond:
                if self._gen != gen:  # skipped or gone back meanwhile: this one is still to come
                    if track:
                        self._upcoming.appendleft(track)
                    continue
                self._decoding = track
            if track is None:
                time.sleep(1)
                continue
            got = False
            try:
                proc = decoder(self._ffmpeg, track)
            except OSError:
                proc = None
            try:
                while proc is not None:
                    data = proc.stdout.read(CHUNK)
                    if not data:
                        break
                    with self._cond:
                        while not self._ended and self._gen == gen and self._held_bytes >= HELD:
                            self._cond.wait(0.5)
                        if self._ended or self._gen != gen:
                            break
                        self._held.append([track, data])
                        self._held_bytes += len(data)
                        got = True
            finally:
                if proc is not None:
                    proc.kill()
                    proc.wait()
                with self._cond:
                    if self._gen == gen:
                        self._decoding = None
            if not got and self._gen == gen:
                time.sleep(0.5)  # a track that can't be played (gone, or not sound): the next, after a moment

    def _take(self) -> bytes:
        """The next 20 ms to write: the music while it's on and playing, silence otherwise."""
        with self._cond:
            out = bytearray()
            if self.on and self.playing:
                while self._held and len(out) < CHUNK:
                    piece = self._held[0]
                    if not self._heard or self._heard[-1] != piece[0]:
                        self._heard.append(piece[0])
                        del self._heard[:-50]
                        self._at = 0
                    take = piece[1][: CHUNK - len(out)]
                    out += take
                    self._at += len(take)
                    self._held_bytes -= len(take)
                    if len(take) == len(piece[1]):
                        self._held.popleft()
                    else:
                        piece[1] = piece[1][len(take):]
                self._cond.notify_all()
            volume = self.volume
        out += bytes(CHUNK - len(out))
        if volume < 100 and any(out):
            g = gain(volume)
            samples = array("h", bytes(out))
            out = array("h", [int(s * g) for s in samples]).tobytes()
        return bytes(out)

    def _write(self) -> None:
        """The sound, at the pace it plays, to every picture ffmpeg being fed: each through a queue of its own, so one
        not reading yet (a new one still connecting to its cameras) never holds up the one going out."""
        due = time.monotonic()
        while True:
            with self._cond:
                if self._ended:
                    for o in self._outs:
                        o.close()
                    return
                self._outs = [o for o in self._outs if o.alive]
                outs = list(self._outs)
            if not outs:
                time.sleep(0.05)
                due = time.monotonic()
                continue
            wait = due - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            elif wait < -1:  # well behind: from now, not catching up in a rush
                due = time.monotonic()
            chunk = self._take()
            for o in outs:
                o.put(chunk)
            due += CHUNK / PER_SECOND


class _Out:
    """One picture ffmpeg's stdin, written by a thread of its own from a short queue (two seconds: older sound is dropped
    while it isn't reading). `alive` turns False once it has ended."""

    MOST = 100  # chunks of 20 ms

    def __init__(self, out):
        self._out = out
        self._cond = threading.Condition()
        self._queue: collections.deque[bytes] = collections.deque()
        self.alive = True
        threading.Thread(target=self._run, name="stream-music-out", daemon=True).start()

    def put(self, chunk: bytes) -> None:
        with self._cond:
            self._queue.append(chunk)
            while len(self._queue) > self.MOST:
                self._queue.popleft()
            self._cond.notify()

    def close(self) -> None:
        with self._cond:
            self.alive = False
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                while self.alive and not self._queue:
                    self._cond.wait(0.5)
                if not self.alive:
                    return
                chunk = self._queue.popleft()
            try:
                self._out.write(chunk)
                self._out.flush()
            except (OSError, ValueError):  # that ffmpeg has ended
                with self._cond:
                    self.alive = False
                return
