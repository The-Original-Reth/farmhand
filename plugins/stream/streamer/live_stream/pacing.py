"""
Writing at the pace something plays (the camera pipes, the music): one step at a time, waiting while early, making up
time a reader held the writer up (see constants.CATCH_UP_MOST and STEADY_AFTER).
"""
from __future__ import annotations

import time

from .constants import CATCH_UP_MOST, STEADY_AFTER


def pace(due: float, written: int, step: float, now: float, sleep=time.sleep) -> float:
    """
    After writing a step (a frame, a piece of sound) due at `due`, the `written`th: wait for the next if it's early, or
    go straight on while behind, so time the reader held the writer up is made up (the reader counts its time in what
    it's given). Behind before the reader has taken STEADY_AFTER seconds of it (a new picture ffmpeg still opening its
    inputs), or by over CATCH_UP_MOST, the time is let go instead. The next step's due time.
    """
    left = due - now
    if left > 0:
        sleep(left)
        return due
    if left < -CATCH_UP_MOST or (written * step < STEADY_AFTER and left < -1):
        return now
    return due
