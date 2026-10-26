"""
Making what tests need: a printer, a model, a 3MF and its versions, with plain defaults, so each test only says
what matters to it. `from . import factories as make`, then make.printer(db), make.bundle(db, path)...
"""
from __future__ import annotations

import io
from pathlib import Path

from app.models import SourceFileType
from app.services import bundle_service, printer_service, source_model_service

GCODE = b"G28\n"


def printer(db, name="VT 1190", kind="Voron", wired_ip=None):
    """The printer called `name`, made if it isn't there yet."""
    return printer_service.find_by_name(db, name) or printer_service.create_printer(
        db, name=name, kind=kind, wired_ip=wired_ip, wireless_ip=None
    )


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
