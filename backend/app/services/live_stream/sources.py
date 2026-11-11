"""
The cameras, as ffmpeg reads them: a Mainsail MJPEG stream, go2rtc on the printer, or a Buddy3D's RTSP.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ...models import Printer
from .. import cameras
from ..camera_streams import MJPEG, RTSP, stream_address, turn_filters  # noqa: F401 (MJPEG, RTSP: what ffmpeg is given)

# ------------------------------------------------------------------ the cameras, as ffmpeg reads them


@dataclass
class Source:
    """One camera in the stream: what's written under it, and how ffmpeg reads it."""

    printer_id: int
    label: str
    input_args: list[str]
    turn: list[str] = field(default_factory=list)  # ffmpeg filters that turn it the way Mainsail shows it


def input_args(printer: Printer, cam: dict) -> list[str]:
    """How ffmpeg reads this camera, or ValueError saying why it can't (the rules are in services/camera_streams.py)."""
    return stream_address(printer, cam).input_args


def followed_camera(cam_name: str, listed: list[dict], error: str | None, taken: set[str] = frozenset()) -> dict | None:
    """The camera called cam_name among a printer's cameras, or None. A printer with just one camera, which answered in
    full, has that one followed when it was renamed in Mainsail (as changing its service there can do), so a square
    chosen before keeps showing it; not when another square shows it by its new name already (`taken`: those names)."""
    cam = next((c for c in listed if c.get("name") == cam_name), None)
    if cam is None and len(listed) == 1 and not error and listed[0].get("name") not in taken:
        cam = listed[0]
    return cam


def sources(db: Session, chosen: list[str]) -> list[Source]:
    """The chosen cameras, each asked of its printer now. ValueError says which one can't be streamed and why."""
    out = []
    asked: dict[int, dict] = {}
    for key in chosen:
        pid_text, cam_name = key.split(":", 1)
        printer = db.get(Printer, int(pid_text))
        if printer is None:
            raise ValueError("A chosen camera's printer is gone. Untick it and save.")
        if printer.id not in asked:
            asked[printer.id] = cameras.printer_cameras(printer)
        found = asked[printer.id]
        listed = found["webcams"]
        taken = {k.split(":", 1)[1] for k in chosen if k.split(":", 1)[0] == pid_text}
        cam = followed_camera(cam_name, listed, found.get("error"), taken)
        if cam is None:
            why = found.get("error") or "it isn't set up in Mainsail any more"
            raise ValueError(f"{printer.name}'s {cam_name} camera can't be reached: {why}")
        label = printer.name if len(listed) == 1 else f"{printer.name} · {cam_name}"
        out.append(Source(printer.id, label, input_args(printer, cam), turn_filters(cam)))
    return out
