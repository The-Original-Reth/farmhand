"""
The stream's ffmpegs, started and ended: one place, so the tests swap in a stand-in for every one of them (popen).
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess


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


def nice(proc, level: int) -> None:
    """Run `proc` at this priority (0: as usual; higher: gives way to others). (Best tried: a stand-in has no pid.)"""
    try:
        os.setpriority(os.PRIO_PROCESS, proc.pid, level)
    except (AttributeError, OSError):
        pass


def end(proc) -> None:
    """Ended: asked to stop, and killed if it won't within 5 seconds."""
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 - one that won't end is killed
            proc.kill()
