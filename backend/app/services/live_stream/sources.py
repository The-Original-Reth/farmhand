"""
The cameras, as ffmpeg reads them: a Mainsail MJPEG stream, go2rtc on the printer, or a Buddy3D's RTSP.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, urlsplit

from sqlalchemy.orm import Session

from ...models import Printer
from .. import cameras, go2rtc

# ------------------------------------------------------------------ the cameras, as ffmpeg reads them


@dataclass
class Source:
    """One camera in the stream: what's written under it, and how ffmpeg reads it."""

    printer_id: int
    label: str
    input_args: list[str]
    turn: list[str] = field(default_factory=list)  # ffmpeg filters that turn it the way Mainsail shows it


def _turn(cam: dict) -> list[str]:
    out = []
    rotation = int(cam.get("rotation") or 0) % 360
    if rotation == 90:
        out.append("transpose=1")
    elif rotation == 270:
        out.append("transpose=2")
    flip_h = bool(cam.get("flip_horizontal")) ^ (rotation == 180)
    flip_v = bool(cam.get("flip_vertical")) ^ (rotation == 180)
    if flip_h:
        out.append("hflip")
    if flip_v:
        out.append("vflip")
    return out


def input_args(printer: Printer, cam: dict) -> list[str]:
    """How ffmpeg reads this camera, or ValueError saying why it can't."""
    name = f"{printer.name}'s camera" if cam.get("name") in (None, "Camera") else f"{printer.name}'s {cam['name']} camera"
    if cam.get("service") == "farmhand-go2rtc":  # a Buddy3D: its RTSP stream, straight from the camera
        return ["-rtsp_transport", "tcp", "-i", go2rtc.rtsp_url(printer.camera_address)]
    stream = cam.get("stream_url")
    # an MJPEG stream; Mainsail's "adaptive" service shows snapshots in the browser, but its address is the same stream
    if stream and (cam.get("mjpeg") or cam.get("service") == "mjpegstreamer-adaptive" or "action=stream" in stream):
        return ["-f", "mpjpeg", "-i", stream]
    if stream and cam.get("service") == "webrtc-go2rtc":
        # go2rtc on the printer: the same camera over RTSP, on go2rtc's own RTSP port
        parts = urlsplit(stream)
        src = parse_qs(parts.query).get("src", [None])[0]
        if parts.hostname and src:
            return ["-rtsp_transport", "tcp", "-i", f"rtsp://{parts.hostname}:8554/{quote(src, safe='')}"]
    if stream and cam.get("service") == "webrtc-camerastreamer" and stream.rstrip("/").endswith("/webrtc"):
        # camera-streamer serves the same camera as MJPEG beside its WebRTC page
        return ["-f", "mpjpeg", "-i", stream.rstrip("/")[: -len("webrtc")] + "stream"]
    raise ValueError(
        f"{name} only plays in a browser (WebRTC), which Farmhand can't send to a stream. "
        "In Mainsail (Settings → Webcams) give it the MJPEG streamer service, or leave it out of the stream."
    )


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
        cam = next((c for c in listed if c.get("name") == cam_name), None)
        if cam is None:
            why = found.get("error") or "it isn't set up in Mainsail any more"
            raise ValueError(f"{printer.name}'s {cam_name} camera can't be reached: {why}")
        label = printer.name if len(listed) == 1 else f"{printer.name} · {cam_name}"
        out.append(Source(printer.id, label, input_args(printer, cam), _turn(cam)))
    return out
