"""
A printer's cameras for the Monitor page: as set up in Mainsail (those Crowsnest no longer serves played from go2rtc on
the printer, when it has it: see printer_go2rtc), plus one Farmhand plays itself through go2rtc (a Buddy3D's). A Klipper
printer given a camera address has that camera played through Farmhand's go2rtc in place of Mainsail's first camera (a
Snapmaker U1's RTSP stream): the printer then sends its video once, to Farmhand, however many pages show it. Never fails:
says why there are none.
"""
from __future__ import annotations

from ..models import Printer
from . import camera_webrtc, go2rtc, printer_go2rtc
from . import moonraker as mr


def printer_cameras(printer: Printer) -> dict:
    """
    {webcams, error, board}. board: the computer a Klipper printer runs on, shown in the corner of its cameras
    ({name: "Pi 4", model, memory_gb}, see moonraker.board), or null.
    """
    cams, errors, board = [], [], None
    if printer.connection_type == "moonraker":
        try:
            listed = mr.webcams(printer)
            info = mr.system_info(printer)  # only once it has answered: an unreachable one isn't waited for twice
            board = mr.board_of(info)
            cams += printer_go2rtc.apply(printer.camera_ip or printer_go2rtc.host_of(printer.mainsail_url), listed, info)
            for cam in cams:  # a camera-streamer WebRTC one is set up through Farmhand's API (see camera_webrtc)
                if path := camera_webrtc.signal_path(printer.id, cam):
                    cam["signal_url"] = path
        except mr.MoonrakerError as e:
            errors.append(str(e))
    if printer.camera_address:
        try:
            relayed = relayed_camera(printer)
            if cams:  # a Klipper printer: its camera, as Mainsail names and turns it, played through Farmhand instead
                first = cams.pop(0)
                relayed.update({k: first[k] for k in TAKEN_FROM_MAINSAIL if first.get(k) is not None})
            cams.insert(0, relayed)
        except go2rtc.Go2rtcError as e:
            errors.append(str(e))
    elif printer.connection_type == "prusalink":
        errors.append("No camera address set. Add the Buddy3D camera's IP on the printer's Edit page")
    return {"webcams": cams, "error": "; ".join(errors) or None, "board": board}


# What the relayed camera keeps of the Mainsail camera it stands in for
TAKEN_FROM_MAINSAIL = ("name", "snapshot_url", "flip_horizontal", "flip_vertical", "rotation", "aspect_ratio", "target_fps")


def relayed_camera(printer: Printer) -> dict:
    """The printer's own camera (a Buddy3D's RTSP stream), handed to go2rtc, in the shape mr.webcams gives."""
    name = go2rtc.stream_name(printer.id)
    source = go2rtc.rtsp_url(printer.camera_source)  # on its camera IP (the Camera switch)
    if printer.connection_type == "moonraker":
        # A Klipper printer's RTSP camera is read through ffmpeg (copied, not re-encoded): go2rtc's own RTSP reader gets
        # only ~3.5 s from a Snapmaker U1's (LIVE555) before it stops sending, then starts again, every 10 s
        source = f"ffmpeg:{source}#video=copy"
    go2rtc.register(name, source)
    return {
        "name": "Camera", "service": "farmhand-go2rtc", "mjpeg": False,
        "stream_url": f"/go2rtc/api/ws?src={name}",  # on the web server the page came from
        "snapshot_url": None, "flip_horizontal": False, "flip_vertical": False, "rotation": 0,
        "aspect_ratio": "16:9", "target_fps": 15,
    }
