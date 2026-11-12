"""
The live stream's picture: an ffmpeg per layout, reading the cameras from its own pipes, kept going for as long as
its layout is the one going out, and handed over to from the one before with no break in what YouTube gets
(relay.py). Part of runner.Stream.
"""
from __future__ import annotations

import shutil
import threading
import time

from . import procs
from .constants import RETRY_SECONDS
from .picture import TURNS_FOR

HANDOVER_WAIT = 30  # seconds a new layout's picture ffmpeg has to start going before the old one is kept on instead
SETTLE = 3  # seconds a new layout waits before its picture ffmpeg starts: a burst of saves becomes one hand-over
WARMING_NICE = 10  # a picture ffmpeg warming up runs at this lower priority, so the one going out keeps the processor


class PicturesMixin:
    """Each layout's picture ffmpeg, and the hand-over between them (state on runner.Stream)."""

    def _start_picture(self, gen: int, picture: int, make, handover: bool, folder: str | None = None):
        """A picture ffmpeg for this layout, started and going out: handed over to from the one going out when `handover`
        (warming up at a lower priority until it takes over; the old one is then stopped), or straight away. It reads
        the cameras from its own pump's pipes, so it never connects to a camera itself. The new one, or None when it
        didn't take over (dropped for a newer layout, failed, or too slow: the old one stays on)."""
        with self._lock:
            relay, player, since = self._relay, self._player, self._live_since or time.monotonic()
        # its times carry on from the last frame passed on, a little behind: after a break, a jump ahead would have the
        # sender (playing to the times) wait it out; a step back is just closed up (mpegts starts ~1.4 s after its offset)
        last = relay.last_time() if relay else None
        offset = max(0.0, last - 2.0) if last is not None else time.monotonic() - since
        args, pump = make(time.time(), offset)
        pump.start()
        try:
            proc = procs.popen(args, feed=True, out=True)
        except OSError:
            pump.stop()
            raise
        pump.watch(proc)
        threading.Thread(target=self._listen, args=(proc,), name="stream-listen", daemon=True).start()
        if player:
            player.attach(proc.stdin)
        with self._lock:
            old = self._proc
        if handover and old is not None and old.poll() is None:
            procs.nice(proc, WARMING_NICE)
            with self._lock:
                if not self._current(gen, picture):
                    procs.end(proc)
                    return None
                self._warming = proc
            took = relay.switch_to(proc, HANDOVER_WAIT)
            with self._lock:
                if self._warming is proc:
                    self._warming = None
            if not took:
                procs.end(proc)
                return None
            procs.nice(proc, 0)
        else:
            relay.start(proc)
        with self._lock:
            if not self._current(gen, picture):
                procs.end(proc)
                return None
            old, self._proc = self._proc, proc
            if folder:
                self._dir = folder
            self._run_started = time.monotonic()
            self._error = None
            self._changing = False
        if old is not None and old is not proc:
            procs.end(old)  # the one it took over from
        return proc

    def _keep_picture(self, gen: int, picture: int, make, folder: str, handover: bool, keys: set[str]) -> None:
        """This layout's picture, for as long as it's the layout and the stream is live: after settling (a newer layout
        within SETTLE seconds takes its place), handed over to from the one going out, or started straight away. Its
        camera inputs never end (a camera that stops is a "Camera down" square), so it only needs starting again when
        it stops itself. Once it's going out, cameras no layout shows are let go (`keys`: this layout's). Its folder is
        deleted once it's done with."""
        try:
            if handover and not self._wait(gen, SETTLE, picture):
                return
            proc, dropping = None, False
            while self._current(gen, picture):
                if proc is None:
                    try:
                        proc = self._start_picture(gen, picture, make, handover, folder)
                    except OSError as e:
                        with self._lock:
                            self._error = f"ffmpeg couldn't be started: {e.strerror or e}"
                        return
                    if proc is None:  # it couldn't start beside the one going out (unless a newer layout came)
                        if not self._current(gen, picture):
                            return
                        with self._lock:
                            self._error = f"The new layout's picture didn't start. Trying again in {RETRY_SECONDS} s."
                        if not self._wait(gen, RETRY_SECONDS, picture):
                            return
                        continue
                    started = time.monotonic()
                    if not dropping:
                        dropping = True
                        threading.Thread(target=self._drop_feeders, args=(gen, picture, keys), name="stream-feeders", daemon=True).start()
                # going out: until it stops, or the layout is handed over from
                while self._current(gen, picture) and proc.poll() is None:
                    time.sleep(0.5)
                if not self._current(gen, picture):
                    return
                code = proc.wait()
                proc, handover = None, False  # (from here, one started again just takes over)
                if code == 0 and time.monotonic() - started >= TURNS_FOR - 60:
                    continue  # the day's timetable and lists are done: started again at once, from the top
                with self._lock:
                    last = next((l for l in reversed(self._said) if l), None)
                    self._error = f"The picture stopped (ffmpeg exit {code}): {last or 'no reason given'}. Trying again in {RETRY_SECONDS} s."
                if not self._wait(gen, RETRY_SECONDS, picture):
                    return
        finally:
            with self._lock:
                mine = self._dir == folder
                if self._current(gen) and self._picture == picture:
                    self._changing = False
            if not mine:
                shutil.rmtree(folder, ignore_errors=True)
