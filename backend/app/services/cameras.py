"""
A printer's cameras for the Monitor page: as set up in Mainsail, plus one Farmhand plays itself through go2rtc (a
Buddy3D's). Never fails: says why there are none.
"""
from __future__ import annotations

from ..models import Printer
from . import go2rtc
from . import moonraker as mr


def printer_cameras(printer: Printer) -> dict:
    """
    {webcams, error, board}. board: the computer a Klipper printer runs on, shown in the corner of its cameras
    ({name: "Pi 4", model, memory_gb}, see moonraker.board), or null.
    """
    cams, errors, board = [], [], None
    if printer.connection_type == "moonraker":
        try:
            cams += mr.webcams(printer)
            board = mr.board(printer)  # only once it has answered: an unreachable one isn't waited for twice
        except mr.MoonrakerError as e:
            errors.append(str(e))
    if printer.camera_address:
        try:
            cams.append(relayed_camera(printer))
        except go2rtc.Go2rtcError as e:
            errors.append(str(e))
    elif printer.connection_type == "prusalink":
        errors.append("No camera address set. Add the Buddy3D camera's IP on the printer's Edit page")
    return {"webcams": cams, "error": "; ".join(errors) or None, "board": board}


def relayed_camera(printer: Printer) -> dict:
    """The printer's own camera (a Buddy3D's RTSP stream), handed to go2rtc, in the shape mr.webcams gives."""
    name = go2rtc.stream_name(printer.id)
    go2rtc.register(name, go2rtc.rtsp_url(printer.camera_address))
    return {
        "name": "Camera", "service": "farmhand-go2rtc", "mjpeg": False,
        "stream_url": f"/go2rtc/api/ws?src={name}",  # on the web server the page came from
        "snapshot_url": None, "flip_horizontal": False, "flip_vertical": False, "rotation": 0,
        "aspect_ratio": "16:9", "target_fps": 15,
    }
