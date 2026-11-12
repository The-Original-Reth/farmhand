"""
Where ffmpeg reads a printer's camera: a Mainsail MJPEG stream, go2rtc on the printer (over RTSP), camera-streamer's
MJPEG beside its WebRTC page, or a Buddy3D's RTSP. Farmhand runs no ffmpeg itself: these are handed to plugins (the
plugin API's /cameras), such as the Stream plugin, as the arguments to read each camera with.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlsplit

from ..models import Printer
from . import go2rtc

# An MJPEG stream sends no times of its own: ffmpeg would count its frames as if 25 came every second, and a camera
# sending two a second would have the whole grid wait for it, the stream falling far behind real time while the other
# cameras' frames piled up in memory. Each frame is given the time it arrived instead: a slow camera just changes less
# often in its square.
# And a camera that drops the connection (it hung up while ffmpeg fell behind, or it restarted) is connected to again,
# instead of its square freezing on its last frame; one that goes quiet for 10 s counts as dropped.
MJPEG = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "5",
         "-rw_timeout", "10000000", "-use_wallclock_as_timestamps", "1", "-f", "mpjpeg"]
# An RTSP camera that goes quiet for 10 s ends its input (RTSP can't reconnect by itself): the plugin running ffmpeg
# sees that in what ffmpeg says and starts again with new connections (the Stream plugin's runner.INPUT_ENDED).
RTSP = ["-rtsp_transport", "tcp", "-timeout", "10000000"]


@dataclass(frozen=True)
class StreamAddress:
    kind: str  # "mjpeg" | "rtsp"
    url: str

    @property
    def input_args(self) -> list[str]:
        """ffmpeg's options for reading it, ending with -i and the address."""
        return [*(MJPEG if self.kind == "mjpeg" else RTSP), "-i", self.url]


def camera_label(printer: Printer, cam: dict) -> str:
    return f"{printer.name}'s camera" if cam.get("name") in (None, "Camera") else f"{printer.name}'s {cam['name']} camera"


def stream_address(printer: Printer, cam: dict) -> StreamAddress:
    """Where ffmpeg reads this camera (one of cameras.printer_cameras' webcams), or ValueError saying why it can't."""
    if cam.get("service") == "farmhand-go2rtc":  # a Buddy3D: its RTSP stream, straight from the camera
        return StreamAddress("rtsp", go2rtc.rtsp_url(printer.camera_address))
    stream = cam.get("stream_url")
    # an MJPEG stream; Mainsail's "adaptive" service shows snapshots in the browser, but its address is the same stream
    if stream and (cam.get("mjpeg") or cam.get("service") == "mjpegstreamer-adaptive" or "action=stream" in stream):
        return StreamAddress("mjpeg", stream)
    if stream and cam.get("service") == "webrtc-go2rtc":
        # go2rtc on the printer: the same camera over RTSP, on go2rtc's own RTSP port
        parts = urlsplit(stream)
        src = parse_qs(parts.query).get("src", [None])[0]
        if parts.hostname and src:
            return StreamAddress("rtsp", f"rtsp://{parts.hostname}:8554/{quote(src, safe='')}")
    if stream and cam.get("service") == "webrtc-camerastreamer" and stream.rstrip("/").endswith("/webrtc"):
        # camera-streamer serves the same camera as MJPEG beside its WebRTC page
        return StreamAddress("mjpeg", stream.rstrip("/")[: -len("webrtc")] + "stream")
    raise ValueError(
        f"{camera_label(printer, cam)} only plays in a browser (WebRTC), which Farmhand can't send to a stream. "
        "In Mainsail (Settings → Webcams) give it the MJPEG streamer service, or leave it out of the stream."
    )


def turn_filters(cam: dict) -> list[str]:
    """ffmpeg filters that turn the camera's picture the way Mainsail shows it (its rotation and flips)."""
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
