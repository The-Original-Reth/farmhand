"""
go2rtc on a Klipper printer, found by itself: a printer moved from Crowsnest to go2rtc plays its camera from go2rtc in
Farmhand without its camera being changed in Mainsail.

When Mainsail still lists a camera Crowsnest serves (its MJPEG streamer, or camera-streamer) but Moonraker says
Crowsnest isn't running, Farmhand asks the printer's go2rtc (port 1984) which streams it has. Each such camera is then
played from go2rtc instead (WebRTC on the Monitor page, RTSP for plugins), keeping its name, rotation and flips as
Mainsail has them, so the Stream plugin's squares and the Monitor page find it under the same name. A go2rtc stream
with the camera's name is taken first; the rest go in the order both list them. A printer whose Mainsail lists no
camera at all gets one per go2rtc stream. While Crowsnest runs, or Moonraker doesn't say whether it does, Mainsail's
cameras are used as they are, go2rtc or not.

Not Farmhand's own go2rtc (services/go2rtc.py), which plays Buddy3D cameras: this one runs on the printer.
"""
from __future__ import annotations

from urllib.parse import quote, urlsplit

import httpx

PORT = 1984
TIMEOUT = httpx.Timeout(2.0, connect=1.0)  # asked each time the cameras are: one that isn't there isn't waited on long

# Tests swap this for an httpx.MockTransport that plays a printer's go2rtc
transport: httpx.BaseTransport | None = None

# The services Crowsnest provides, as Mainsail names them
CROWSNEST_SERVICES = {"mjpegstreamer", "mjpegstreamer-adaptive", "uv4l-mjpeg", "webrtc-camerastreamer"}


def crowsnest_stopped(info: dict | None) -> bool:
    """Whether Moonraker says Crowsnest isn't running: it watches it (it's in its service list) and it isn't active.
    False when Moonraker won't say (an older one, one not reached, or one not watching Crowsnest, which may well be
    running): nothing is guessed."""
    if not isinstance(info, dict):
        return False
    state = (info.get("service_state") or {}).get("crowsnest")
    return isinstance(state, dict) and state.get("active_state") != "active"


def streams(host: str) -> list[str]:
    """The streams the printer's go2rtc has, in the order its settings list them; [] when there's no go2rtc there."""
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
            r = client.get(f"http://{_netloc(host)}/api/streams")
        found = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return []
    return [name for name in found if isinstance(name, str) and name] if isinstance(found, dict) else []


def camera(host: str, name: str, like: dict | None = None) -> dict:
    """A go2rtc stream as one of Mainsail's cameras (mr.webcams' shape), keeping `like`'s name and how it's turned."""
    base, src = f"http://{_netloc(host)}", quote(name, safe="")
    like = like or {"name": name, "flip_horizontal": False, "flip_vertical": False, "rotation": 0, "aspect_ratio": "16:9",
                    "target_fps": 15}
    return {
        **like, "service": "webrtc-go2rtc", "mjpeg": False,
        "stream_url": f"{base}/stream.html?src={src}&mode=webrtc", "snapshot_url": f"{base}/api/frame.jpeg?src={src}",
        "found": "go2rtc",  # (not set in Mainsail: found on the printer)
    }


def apply(host: str | None, cams: list[dict], info: dict | None) -> list[dict]:
    """Mainsail's cameras (mr.webcams), with those Crowsnest no longer serves played from the printer's go2rtc, when it
    has streams (see the module's words). As they were otherwise."""
    if not host or not crowsnest_stopped(info):
        return cams
    served = [i for i, c in enumerate(cams) if c.get("service") in CROWSNEST_SERVICES]
    if cams and not served:
        return cams
    names = streams(host)
    if not names:
        return cams
    if not cams:
        return [camera(host, n) for n in names]
    out, left = list(cams), list(names)
    unmatched = []
    for i in served:  # a stream with the camera's own name first
        same = next((n for n in left if n.lower() == str(cams[i].get("name") or "").lower()), None)
        if same:
            out[i] = camera(host, same, cams[i])
            left.remove(same)
        else:
            unmatched.append(i)
    for i, n in zip(unmatched, left):  # then in the order both list them
        out[i] = camera(host, n, cams[i])
    return out


def _netloc(host: str) -> str:
    return f"[{host}]:{PORT}" if ":" in host else f"{host}:{PORT}"


def host_of(url: str | None) -> str | None:
    return urlsplit(url or "").hostname