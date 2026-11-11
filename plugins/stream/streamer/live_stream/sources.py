"""
The cameras, as ffmpeg reads them: the addresses Farmhand gives through the plugin API (GET /cameras, cameras:read: a
Mainsail MJPEG stream, go2rtc on the printer, or a Buddy3D's RTSP, each with the ffmpeg options to read it).

The last answer is kept in the plugin's store (CAMERAS_KEY), each camera as it was last heard of, so going live (or
going live again after the plugin's own restart) never waits on Farmhand: with Farmhand down, or a printer that's off,
a camera known from before is read at its last address, and one never heard of starts as a "Camera down" square.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..store import Session

CAMERAS_KEY = "cameras_last_heard"  # {printer id: {name, error, cameras: [camera, as Farmhand gave it]}}


@dataclass
class Source:
    """One camera in the stream: what's written under it, and how ffmpeg reads it (empty: no address known, so its
    square is "Camera down" until there is one)."""

    printer_id: int
    label: str
    input_args: list[str]
    turn: list[str] = field(default_factory=list)  # ffmpeg filters that turn it the way Mainsail shows it
    key: str = ""  # "printer id:camera name"
    name: str = ""  # the printer's name, for its "Camera down" square
    aspect: str | None = None  # "16:9", "4:3"..., as Mainsail has it (the feeder's picture is that shape)


def followed_camera(cam_name: str, listed: list[dict], error: str | None, taken: set[str] = frozenset()) -> dict | None:
    """The camera called cam_name among a printer's cameras, or None. A printer with just one camera, which answered in
    full, has that one followed when it was renamed in Mainsail (as changing its service there can do), so a square
    chosen before keeps showing it; not when another square shows it by its new name already (`taken`: those names)."""
    cam = next((c for c in listed if c.get("name") == cam_name), None)
    if cam is None and len(listed) == 1 and not error and listed[0].get("name") not in taken:
        cam = listed[0]
    return cam


def remember(db: Session, answer: dict) -> dict:
    """Farmhand's /cameras answer, kept over what was heard before: a printer that answered replaces its cameras; one
    that didn't (it's off) keeps the cameras it last had, with its error. The farm as now known, by printer id."""
    known = db.json(CAMERAS_KEY, {}) if hasattr(db, "json") else {}
    now = {}
    for p in answer.get("printers") or []:
        pid = str(p.get("printer_id"))
        before = known.get(pid) or {}
        cams = p.get("cameras") or []
        if p.get("error") and not cams:
            cams = before.get("cameras") or []
        now[pid] = {"name": p.get("printer_name") or before.get("name") or f"Printer {pid}", "error": p.get("error"), "cameras": cams}
    if now != known:
        db.put_json(CAMERAS_KEY, now)
        db.commit()
    return now


def known(db: Session) -> dict:
    return db.json(CAMERAS_KEY, {})


def sources(db: Session, chosen: list[str], farm: dict | None = None) -> list[Source]:
    """
    The chosen cameras, from `farm` (remember()'s answer; None: what was last heard, Farmhand not answering). ValueError
    says which one can't be streamed and why: its printer is gone, or it only plays in a browser (a setup mistake). A
    camera Farmhand can't tell the address of now (its printer is off) and never could is a "Camera down" square.
    """
    farm = known(db) if farm is None else farm
    out = []
    for key in chosen:
        pid_text, cam_name = key.split(":", 1)
        printer = farm.get(pid_text)
        if printer is None:
            if not farm:  # (nothing heard from Farmhand yet: shown as down until it is)
                out.append(Source(int(pid_text), f"Printer {pid_text} · {cam_name}", [], key=key, name=f"Printer {pid_text}"))
                continue
            raise ValueError("A chosen camera's printer is gone from Farmhand. Take it out of the grid and save.")
        listed = printer.get("cameras") or []
        taken = {k.split(":", 1)[1] for k in chosen if k.split(":", 1)[0] == pid_text}
        cam = followed_camera(cam_name, listed, printer.get("error"), taken)
        label = printer["name"] if len(listed) <= 1 else f"{printer['name']} · {cam_name}"
        if cam is None:
            if printer.get("error"):  # off now, and never heard of: down until it's back
                out.append(Source(int(pid_text), label, [], key=key, name=printer["name"]))
                continue
            raise ValueError(f"{printer['name']}'s {cam_name} camera isn't set up in Mainsail any more. Take it out of the grid and save.")
        if not cam.get("ffmpeg_input"):
            raise ValueError(cam.get("error") or f"{printer['name']}'s {cam_name} camera can't be sent to a stream.")
        out.append(Source(int(pid_text), label, list(cam["ffmpeg_input"]), list(cam.get("ffmpeg_filters") or []),
                          key=key, name=printer["name"], aspect=cam.get("aspect_ratio")))
    return out
