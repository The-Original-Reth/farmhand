"""
The live stream's cameras: each read by its own feeder (feeders.py) for as long as the stream is live, shared by
every layout's picture, and the words under each kept current from Farmhand. Part of runner.Stream.
"""
from __future__ import annotations

from .. import farm
from . import feeders, procs
from .constants import STATUS_EVERY
from .sources import Source
from .staging import write_atomically
from .words import status_line

FEEDERS_KEPT = 60  # seconds a camera no layout shows any more keeps its feeder (the old picture may still be going out)


class CamerasMixin:
    """The cameras' feeders and words (state on runner.Stream)."""

    def _feed(self, ffmpeg: str, srcs: list[Source], size: tuple[int, int]) -> list[feeders.Feeder]:
        """Each camera's feeder, started if it hasn't one reading it the same way already."""
        out, old = [], []
        with self._lock:
            for s in srcs:
                f = self._feeders.get(s.key)
                if f is None or not f.same(s.input_args, s.turn, size):
                    if f is not None:
                        old.append(f)
                    f = self._feeders[s.key] = feeders.Feeder(ffmpeg, s.key, s.input_args, s.turn, size, procs.popen, aspect=s.aspect).start()
                out.append(f)
        for f in old:
            f.stop()
        return out

    def _drop_feeders(self, gen: int, picture: int, keep: set[str]) -> None:
        """A layout took over: after a while (its old picture may still be going out), cameras no layout shows are let go."""
        if not self._wait(gen, FEEDERS_KEPT, picture):
            return
        with self._lock:
            gone = [self._feeders.pop(k) for k in list(self._feeders) if k not in keep]
        for f in gone:
            f.stop()

    def latest_frame(self, key: str) -> bytes | None:
        """A camera's latest picture from its feeder (a JPEG), while live and fresh; None otherwise."""
        with self._lock:
            f = self._feeders.get(key)
        return f.latest()[0] if f else None

    def _camera_states(self) -> list[dict]:
        out = []
        for key, label in self._showing:
            f = self._feeders.get(key)
            state = f.state() if f else {"state": "down", "since": None}
            out.append({"key": key, "label": label, **state})
        return out

    def _keep_words_current(self, gen: int, picture: int, srcs: list[Source], files: list[str]) -> None:
        """Each camera's words: its printer's print, asked of Farmhand every STATUS_EVERY seconds. A printer Farmhand
        can't be asked about (Farmhand down, or refusing the plugin) has just its name: never old progress, and the
        picture never waits for it (drawtext reads the files as they are)."""
        while self._current(gen, picture):
            by_printer: dict[int, dict | None] = {}
            for s in srcs:
                if s.printer_id not in by_printer:
                    by_printer[s.printer_id] = farm.print_of(s.printer_id)
                    if not self._current(gen, picture):
                        return
            for s, f in zip(srcs, files):
                p = by_printer.get(s.printer_id)
                try:
                    write_atomically(f, s.label if p is None else status_line(s.label, p))
                except OSError:
                    pass  # (its folder gone: the layout was handed over from)
            if not self._wait(gen, STATUS_EVERY, picture):
                return
