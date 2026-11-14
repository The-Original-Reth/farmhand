"""
A PrusaLink print's filament, estimated: the printer says only the file's name, so Farmhand finds the 3MF version it
was sliced from on the same printer and reads the slicer's "filament used" from that version's stored G-code. Then
it's costed from the 3MF as any print is, and everywhere says it's an estimate.

The Sloth case is a real print on Prusa_2: "...MMMini_Sloth -PLA_0.4n_0.16mm_PLA_COREONE_8h59m.bgcode", from
"...MMMini_Sloth -PLA ver 3.3mf", whose bgcode says 39324.56 mm / 117.29 g / 2.98 and whose 3MF says 25.4 per kg,
1.24 g/cm³, 1.75 mm.
"""
from __future__ import annotations

import datetime as dt
import io
import struct
import zlib

import pytest

from app.models import Bundle, BundleVersion, PrintJob
from app.parsers.gcode import slicer_filament
from app.services import farm_cost, filament_cost, print_history, printer_service
from app.services import prusalink as pl

SLOTH_3MF = "Prusa2 - Prusa Slicer - MMMini_Sloth -PLA ver 3.3mf"
SLOTH_PRINT = "Prusa2 - Prusa Slicer - MMMini_Sloth -PLA_0.4n_0.16mm_PLA_COREONE_8h59m.bgcode"
SLOTH_SETTINGS = {"filament_cost": "25.4", "filament_density": "1.24", "filament_diameter": "1.75"}
LONG_AGO = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def _block(kind: int, data: bytes, deflate: bool = False) -> bytes:
    params = struct.pack("<H", 0)
    if deflate:
        packed = zlib.compress(data)
        head = struct.pack("<HHII", kind, 1, len(data), len(packed))
    else:
        packed, head = data, struct.pack("<HHI", kind, 0, len(data))
    return head + params + packed + struct.pack("<I", zlib.crc32(head + params + packed))


def bgcode(mm="39324.56", g="117.29", cost="2.98") -> bytes:
    """A small .bgcode as PrusaSlicer writes it for the Core One: the filament figures in its printer and print
    metadata blocks, before the moves."""
    figures = f"filament used [mm]={mm}\nfilament used [g]={g}\nfilament cost={cost}\n".encode()
    return (
        b"GCDE" + struct.pack("<IH", 1, 1)
        + _block(0, b"Producer=PrusaSlicer 2.9.4\n")
        + _block(3, b"printer_model=COREONE\nfilament_type=PLA\n" + figures, deflate=True)
        + struct.pack("<HHI", 5, 0, 4) + struct.pack("<HHH", 0, 16, 16) + b"\x89PNG" + b"\0\0\0\0"
        + _block(4, figures + b"estimated printing time (normal mode)=8h 59m\n")
        + _block(2, b"filament_cost = 25.4\nfilament_density = 1.24\n", deflate=True)
        + _block(1, b"G28\n" * 200, deflate=True)
    )


# ------------------------------------------------------------------ reading the slicer's figures


def test_the_figures_are_read_from_a_bgcodes_metadata():
    assert slicer_filament(io.BytesIO(bgcode()), "a.bgcode") == {"filament_mm": 39324.56, "filament_g": 117.29, "filament_cost": 2.98}


def test_the_figures_are_read_from_a_plain_gcodes_comments():
    text = (b"G1 X1 E1\n" * 5000 + b"; filament used [mm] = 1200.5, 300.25\n; filament used [g] = 3.6, 0.9\n"
            b"; filament cost = 0.10, 0.02\n; prusaslicer_config = begin\n; filament_cost = 25.4, 30\n; prusaslicer_config = end\n")
    assert slicer_filament(io.BytesIO(text), "a.gcode") == {"filament_mm": 1500.75, "filament_g": 4.5, "filament_cost": 0.12}


@pytest.mark.parametrize("name, body", [("a.bgcode", b"not a bgcode"), ("a.gcode", b"G28\n"), ("a.bgcode", b"")])
def test_a_file_without_them_answers_nothing(name, body):
    assert slicer_filament(io.BytesIO(body), name) == {"filament_mm": None, "filament_g": None, "filament_cost": None}


# ------------------------------------------------------------------ PrusaSlicer's Core One name matches its 3MF


def _names(*filenames):
    exact, by_base = filament_cost.name_index((i, n, 1) for i, n in enumerate(filenames))
    return exact[1], by_base[1]


@pytest.mark.parametrize("printed, expected", [
    (SLOTH_PRINT, [0]),
    ("Prusa2 - Prusa Slicer - MMMini_Sloth -PLA_0.6n_0.2mm_PETG_COREONE_3h1m.gcode", [0]),
    ("Prusa2 - Prusa Slicer - MMMini_Sloth -PLA_0.4n_0.16mm.bgcode", [0]),
    ("Frog-V2_BOG_Rapido_0.5-Inland_PLA.gcode", [1]),  # the "-printer-filament" template still works
    ("Frog_keychain_0.4n_0.2mm_PLA_COREONE_1h.bgcode", None),  # "Frog" is a different 3MF from "Frog keychain"
    ("Frog_big.bgcode", None),
    ("Prusa2 - Prusa Slicer - MMMini_Sloth -PLA_extra_0.4n_0.2mm.bgcode", None),
])
def test_prusaslicers_core_one_name_matches_its_3mf_without_over_matching(printed, expected):
    exact, by_base = _names(SLOTH_3MF, "Frog.3mf")
    assert filament_cost._match(filament_cost._stem(printed), exact, by_base) == expected


# ------------------------------------------------------------------ a PrusaLink print gets an estimated figure


def _core_one(db):
    p = printer_service.create_printer(db, name="Prusa_2", kind="Prusa Core One", wired_ip="10.0.6.40", wireless_ip=None)
    return printer_service.update_printer(db, p.id, {"connection_type": "prusalink", "prusalink_password": "secret123"})


def _version(db, printer, tmp_path, *, version=3, filename=SLOTH_3MF, gcode_name=SLOTH_PRINT, body=None, bundle=None,
             uploaded=LONG_AGO, settings=SLOTH_SETTINGS):
    """A 3MF version on the printer, its G-code stored as `gcode_name` (None: none stored)."""
    if bundle is None:
        bundle = Bundle(printer_id=printer.id)
        db.add(bundle)
        db.flush()
    path = None
    if gcode_name:
        folder = tmp_path / f"v{version}-{bundle.id}"
        folder.mkdir()
        path = folder / gcode_name
        path.write_bytes(body if body is not None else bgcode())
    v = BundleVersion(bundle_id=bundle.id, version=version, filename=filename, slicer_family="prusaslicer",
                      slicer_display_name="PrusaSlicer 2.9.4", uploaded_at=uploaded, gcode_path=str(path) if path else None,
                      settings=settings)
    db.add(v)
    db.commit()
    return v


def _jobs(db, printer_id):
    return list(db.query(PrintJob).filter_by(printer_id=printer_id).order_by(PrintJob.id))


def test_the_sloth_print_gets_117g_and_its_cost_marked_estimated(db_session, prusalink, tmp_path):
    p = _core_one(db_session)
    v = _version(db_session, p, tmp_path)
    prusalink.start_job(475, SLOTH_PRINT, progress=50, time_printing=16000, meta=False)
    pl.poll(db_session, p)
    [job] = _jobs(db_session, p.id)
    assert job.filament_used == pytest.approx(39324.56 / 2, abs=0.01)  # half of it so far
    assert job.job_metadata["filament_estimated"] is True and job.job_metadata["filament_estimate"]["version_id"] == v.id

    prusalink.advance(progress=100, time_printing=32340, state="FINISHED")
    pl.poll(db_session, p)
    assert job.filament_used == pytest.approx(39324.56)

    [row] = print_history.jobs_page(db_session, p.id, limit=10, offset=0)["jobs"]
    assert row["filament_grams"] == 117.3 and row["filament_cost"] == 2.98 and row["filament_estimated"] is True
    detail = row["filament_cost_detail"]
    assert detail["source"] == "3mf" and detail["version_id"] == v.id and detail["estimated"] is True
    assert detail["cost_per_kg"] == 25.4 and detail["density"] == 1.24

    [printer] = [x for x in farm_cost.filament_by_month(db_session, "UTC")["printers"] if x["printer_id"] == p.id]
    [month] = printer["months"]
    assert month["grams"] == 117.3 and month["filament_cost"] == 2.98 and month["estimated"] == 1


def test_a_print_cancelled_part_way_is_estimated_by_how_far_it_got(db_session, prusalink, tmp_path):
    p = _core_one(db_session)
    _version(db_session, p, tmp_path)
    prusalink.start_job(5, SLOTH_PRINT, progress=40, time_printing=100, meta=False)
    pl.poll(db_session, p)
    prusalink.advance(progress=40, time_printing=100, state="STOPPED")
    pl.poll(db_session, p)
    [job] = _jobs(db_session, p.id)
    assert job.status == "cancelled" and job.filament_used == pytest.approx(39324.56 * 0.4, abs=0.01)


def test_the_stored_gcodes_name_is_matched_first(db_session, prusalink, tmp_path):
    p = _core_one(db_session)
    # a 3MF named nothing like the print, but its stored G-code is the printed file
    v = _version(db_session, p, tmp_path, filename="Plate 7.3mf", gcode_name="Sloth_for_the_shelf.bgcode")
    prusalink.start_job(6, "SLOTH FOR THE SHELF.bgcode", progress=100, time_printing=10, state="FINISHED", meta=False)
    pl.poll(db_session, p)
    [job] = _jobs(db_session, p.id)
    assert job.job_metadata["filament_estimate"]["version_id"] == v.id and job.filament_used == pytest.approx(39324.56)


def test_the_version_there_was_when_it_printed_is_used(db_session, prusalink, tmp_path):
    p = _core_one(db_session)
    v1 = _version(db_session, p, tmp_path, version=1, filename="Sloth ver 1.3mf", gcode_name="Sloth ver 1.bgcode",
                  body=bgcode(mm="1000"))
    _version(db_session, p, tmp_path, version=2, filename="Sloth ver 2.3mf", gcode_name="Sloth ver 2.bgcode",
             body=bgcode(mm="2000"), bundle=v1.bundle, uploaded=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
    prusalink.start_job(7, "Sloth_0.4n_0.2mm_PLA_COREONE_1h.bgcode", progress=100, time_printing=10, state="FINISHED", meta=False)
    pl.poll(db_session, p)
    [job] = _jobs(db_session, p.id)
    assert job.filament_used == 1000


def test_no_matching_3mf_leaves_it_without_a_figure_until_one_is_added(db_session, prusalink, tmp_path):
    p = _core_one(db_session)
    prusalink.start_job(8, SLOTH_PRINT, progress=100, time_printing=10, state="FINISHED", meta=False)
    pl.poll(db_session, p)
    [job] = _jobs(db_session, p.id)
    assert job.filament_used == 0 and not job.job_metadata.get("filament_estimated")
    [row] = print_history.jobs_page(db_session, p.id, limit=10, offset=0)["jobs"]
    assert row["filament_cost"] is None and row["filament_estimated"] is False

    _version(db_session, p, tmp_path)  # the 3MF is added afterwards: the print is estimated at the next look
    prusalink.clear_job()
    pl.poll(db_session, p)
    assert job.filament_used == pytest.approx(39324.56) and job.job_metadata["filament_estimated"] is True


def test_a_matched_version_without_a_stored_gcode_gives_no_figure(db_session, prusalink, tmp_path):
    p = _core_one(db_session)
    _version(db_session, p, tmp_path, gcode_name=None)
    prusalink.start_job(9, SLOTH_PRINT, progress=100, time_printing=10, state="FINISHED", meta=False)
    pl.poll(db_session, p)
    [job] = _jobs(db_session, p.id)
    assert job.filament_used == 0 and not job.job_metadata.get("filament_estimated")


def test_prints_recorded_before_are_estimated_too(db_session, prusalink, tmp_path):
    p = _core_one(db_session)
    _version(db_session, p, tmp_path)
    old = PrintJob(printer_id=p.id, job_id="470@20261101T080000", filename=SLOTH_PRINT, status="completed",
                   start_time=dt.datetime(2026, 11, 1, 8, tzinfo=dt.timezone.utc), end_time=dt.datetime(2026, 11, 1, 17, tzinfo=dt.timezone.utc),
                   job_metadata={"path": "/usb"})
    unknown = PrintJob(printer_id=p.id, job_id="471@20261102T080000", filename=SLOTH_PRINT, status="unknown",
                       start_time=dt.datetime(2026, 11, 2, 8, tzinfo=dt.timezone.utc), end_time=dt.datetime(2026, 11, 2, 9, tzinfo=dt.timezone.utc),
                       job_metadata={"path": "/usb"})  # how far it got wasn't kept: no figure can be given
    db_session.add_all([old, unknown])
    db_session.commit()
    pl.poll(db_session, p)  # the printer is idle
    assert old.filament_used == pytest.approx(39324.56) and old.job_metadata["filament_estimated"] is True
    assert unknown.filament_used == 0 and not unknown.job_metadata.get("filament_estimated")


def test_an_older_print_whose_end_was_missed_is_estimated_by_its_print_time(db_session, prusalink, tmp_path):
    p = _core_one(db_session)
    _version(db_session, p, tmp_path)
    # as production has them: closed as "unknown", no progress kept, but the printer's expected time is
    whole = PrintJob(printer_id=p.id, job_id="487@20261113T060234", filename=SLOTH_PRINT, status="unknown",
                     start_time=LONG_AGO, end_time=LONG_AGO, print_duration=32736, job_metadata={"estimated_time": 32340.0})
    half = PrintJob(printer_id=p.id, job_id="488@20261114T011024", filename=SLOTH_PRINT, status="unknown",
                    start_time=LONG_AGO, end_time=LONG_AGO, print_duration=16170, job_metadata={"estimated_time": 32340.0})
    db_session.add_all([whole, half])
    db_session.commit()
    pl.poll(db_session, p)
    assert whole.filament_used == pytest.approx(39324.56) and half.filament_used == pytest.approx(39324.56 / 2, abs=0.01)


def test_a_different_slicing_of_the_same_3mf_gets_no_figure(db_session, prusalink, tmp_path):
    p = _core_one(db_session)
    _version(db_session, p, tmp_path)  # its stored G-code is the 8h59m one
    prusalink.start_job(451, SLOTH_PRINT.replace("8h59m", "3h0m"), progress=100, time_printing=10, state="FINISHED", meta=False)
    pl.poll(db_session, p)
    [job] = _jobs(db_session, p.id)
    assert job.filament_used == 0 and not job.job_metadata.get("filament_estimated")


def test_a_klipper_print_is_not_marked_estimated(db_session, tmp_path):
    from . import factories as make
    p = make.printer(db_session)
    db_session.add(PrintJob(printer_id=p.id, job_id="0001", filename="Frog.gcode", status="completed",
                            start_time=LONG_AGO, filament_used=1000.0, job_metadata={"filament_total": 1000, "filament_weight_total": 3}))
    db_session.commit()
    [row] = print_history.jobs_page(db_session, p.id, limit=10, offset=0)["jobs"]
    assert row["filament_grams"] == 3.0 and row["filament_estimated"] is False
