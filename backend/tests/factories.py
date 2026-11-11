"""
Making what tests need: a printer, a model, a 3MF and its versions, with plain defaults, so each test only says
what matters to it. `from . import factories as make`, then make.printer(db), make.bundle(db, path)...
"""
from __future__ import annotations

import io
import struct
import time

import numpy as np
from pathlib import Path

from app.models import SourceFileType
from app.services import bundle_service, printer_service, source_model_service

GCODE = b"G28\n"


def printer(db, name="VT 1190", kind="Voron", wired_ip=None):
    """The printer called `name`, made if it isn't there yet."""
    return printer_service.find_by_name(db, name) or printer_service.create_printer(
        db, name=name, kind=kind, wired_ip=wired_ip, wireless_ip=None
    )


def klipper_printer(db, name="VT 1190", ip="10.0.6.21"):
    """A new Klipper printer on its cable at `ip` (its Moonraker at port 7125 there)."""
    return printer_service.create_printer(db, name=name, kind="Voron", wired_ip=ip, wireless_ip=None)


def model(db, name="Model.stl", data=None):
    """A model (STL). data: its file's bytes; None makes one with no file of its own."""
    return source_model_service.create_source_model(
        db, name=name, file_type=SourceFileType.stl, file_obj=io.BytesIO(data) if data is not None else None
    )


def bundle(db, threemf_path, models=None, filename="a.3mf", gcode=GCODE, printer_id=None):
    """
    A new 3MF from that file, sliced from `models` (a fresh one if none), with a G-code unless gcode=None. It goes on
    the printer the file was sliced for, unless printer_id names one (either has to be registered).
    """
    with open(threemf_path, "rb") as f:
        return bundle_service.create_bundle(
            db,
            source_model_ids=[m.id for m in (models or [model(db)])],
            threemf_file_obj=f,
            threemf_filename=filename,
            gcode_file_obj=io.BytesIO(gcode) if gcode is not None else None,
            gcode_filename=Path(filename).with_suffix(".gcode").name if gcode is not None else None,
            printer_id=printer_id,
        )


def add_version(db, bundle, threemf_path, filename="a.3mf", gcode=GCODE):
    """A new version of `bundle` from that file, with a G-code unless gcode=None."""
    with open(threemf_path, "rb") as f:
        return bundle_service.add_bundle_version(
            db,
            bundle_id=bundle.id,
            threemf_file_obj=f,
            threemf_filename=filename,
            gcode_file_obj=io.BytesIO(gcode) if gcode is not None else None,
            gcode_filename=Path(filename).with_suffix(".gcode").name if gcode is not None else None,
        )



# ------------------------------------------------------------------ STL files


def stl_bytes(size: float = 10.0) -> bytes:
    """A binary STL of one triangle."""
    tri = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, size, 0, 0, 0, size, 0, 0)
    return b"\0" * 80 + struct.pack("<I", 1) + tri


def cube_stl_bytes():
    v = np.array([(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)], dtype=np.float32)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = np.array([[v[q[0]], v[q[1]], v[q[2]]] for q in quads] + [[v[q[0]], v[q[2]], v[q[3]]] for q in quads])
    rec = np.zeros(len(tris), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["v"] = tris
    return b"cube".ljust(80, b" ") + np.uint32(len(tris)).tobytes() + rec.tobytes()


def write_tetrahedron(path):
    """A small but valid binary STL, so thumbnailing really runs."""
    v = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    out = bytearray(b"\0" * 80 + struct.pack("<I", 4))
    for a, b, c in [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]:
        out += struct.pack("<12fH", 0, 0, 1, *v[a], *v[b], *v[c], 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


# ------------------------------------------------------------------ the Stream page


def webcam(**kw):
    """A Moonraker webcam, as Mainsail sets one up (an MJPEG streamer called Bed), with `kw` changed."""
    cam = {"name": "Bed", "enabled": True, "service": "mjpegstreamer", "stream_url": "/webcam/?action=stream",
           "snapshot_url": "/webcam/?action=snapshot", "rotation": 0}
    return {**cam, **kw}


def wait_for(check, seconds=3.0):
    """True once `check()` is, within `seconds` (things a stream does in its own threads)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return False


def api_db(api):
    """The API's own database session (the test client's override), for calling a service directly."""
    from app.database import get_db
    from app.main import app

    return next(app.dependency_overrides[get_db]())
