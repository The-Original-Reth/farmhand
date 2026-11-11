"""
The words written on the stream's cameras: each printer's name and print, kept in a file per camera that ffmpeg reads
again every frame.
"""
from __future__ import annotations

import os

from .constants import DEFAULT_TEXT_COLOR
from .fonts import font_file

# The words on a camera shown on its own, taking turns: written on the camera's own picture before it's enlarged, so
# sized to it (28 px on the 720-high stream, whatever the camera's size)
FULL_WORDS = {"size": "h/26", "foot": "h/30", "border": "h/120", "left": "w/128"}


def filter_path(path: str) -> str:
    """A file's path as an ffmpeg filter option: forward slashes, and its : and ' escaped."""
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def camera_words(path: str, size: int | str, foot: int | str, border: int | str = 6, left: int | str = 10, own: dict | None = None) -> str:
    """The drawtext of the words under a camera; `own`: its square's choices (_camera_cell: words_color, words_font)."""
    own = own or {}
    color = (own.get("words_color") or DEFAULT_TEXT_COLOR).lstrip("#")
    return (f"drawtext=fontfile={filter_path(font_file(own.get('words_font')))}:textfile={filter_path(path)}:reload=1:expansion=none"
            f":fontsize={size}:fontcolor=0x{color}:box=1:boxcolor=black@0.6:boxborderw={border}:x={left}:y=h-th-{foot}")


def full_words(own: dict) -> dict:
    """The sizes of a camera's words when it's shown on its own: its own size (a part of the camera's own picture's
    height) when chosen, else FULL_WORDS."""
    f = own.get("words_size")
    if not f:
        return FULL_WORDS
    return {"size": f"h*{f}", "foot": f"h*{f * 2 / 3:.4f}", "border": f"h*{f / 3:.4f}", "left": f"h*{f / 2:.4f}"}


def status_line(label: str, p: dict) -> str:
    """What's written under a camera: "VT 1190 · Printing 42% · benchy.gcode", "VT 1190 · Idle", or "VT 1190 · Status
    unknown" when the printer couldn't be asked (not answering, or refusing Farmhand's login)."""
    if p.get("state"):
        pct = p.get("progress")
        line = f"{label} · {'Paused' if p['state'] == 'paused' else 'Printing'}"
        if isinstance(pct, (int, float)):
            line += f" {round(pct)}%"
        if p.get("file"):
            line += f" · {os.path.basename(str(p['file']))[:60]}"
        return line
    if p.get("error"):
        return f"{label} · Status unknown"
    return f"{label} · Idle"
