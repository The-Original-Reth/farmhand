"""
ffmpeg as the Stream page starts it (the picture, and the sender that holds the connection to YouTube), for the stream
tests: `ffmpeg` (conftest) puts FakeFfmpeg in its place. Each command is remembered, says what it's given to say on
stderr, and runs until ended; a picture one puts out a keyframe, so a hand-over to it completes.
"""
from __future__ import annotations

import threading


class FakeFfmpeg:
    """ffmpeg as the stream starts it: remembers each command (the picture's in `commands`, the sender's in `senders`),
    says `lines` on stderr, runs until ended. A picture one puts out a keyframe, so a hand-over to it completes."""

    def __init__(self, lines=(), exits=False):
        self.commands: list[list[str]] = []
        self.procs: list = []
        self.senders: list[list[str]] = []
        self.sender_procs: list = []
        self.lines = list(lines)
        self.exits = exits

    def __call__(self, args, feed=False, out=False):
        picture = "-filter_complex" in args
        proc = _Proc(self.lines, self.exits, picture=picture)
        if picture:
            self.commands.append(args)
            self.procs.append(proc)
        else:
            self.senders.append(args)
            self.sender_procs.append(proc)
        return proc


def _keyframe_packet() -> bytes:
    """One MPEG-TS packet starting a keyframe of the picture (PID 0x100, random access indicator set)."""
    return bytes([0x47, 0x41, 0x00, 0x30, 0x07, 0x40]) + bytes(182)


class _Out:
    """A picture ffmpeg's stdout: a keyframe, then nothing more until it's ended."""

    def __init__(self, ended):
        self._ended = ended
        self._sent = False

    def read(self, n=-1):
        if not self._sent and not self._ended.is_set():  # (one ended before it began sends nothing)
            self._sent = True
            return _keyframe_packet()
        self._ended.wait()
        return b""


class _Sink:
    """ffmpeg's stdin, as the music player writes to it: keeps what's written."""

    def __init__(self):
        self.written = bytearray()

    def write(self, data):
        self.written += data

    def flush(self):
        pass


class _Proc:
    def __init__(self, lines, exits, picture=False):
        self._ended = threading.Event()
        if exits:
            self._ended.set()
        self.stderr = iter([line + "\n" for line in lines])
        self.stdin = _Sink()
        self.stdout = _Out(self._ended) if picture else None

    def poll(self):
        return 1 if self._ended.is_set() else None

    def wait(self, timeout=None):
        self._ended.wait(timeout)
        return 1

    def terminate(self):
        self._ended.set()

    kill = terminate
