"""
A G-code (or a 3MF) sliced for another printer than the one its 3MF belongs to is refused, with a message that says
so: which printer it was sliced for, which one the 3MF belongs to, and what to do. The printer is read from the
settings PrusaSlicer writes into a .gcode, or into a .bgcode's slicer block.
"""
from __future__ import annotations

import io
import struct
import zlib

import pytest

from app.parsers.gcode import printer_profile


def gcode(profile: str | None) -> bytes:
    moves = b"G28\nG1 X10 Y10 E0.5\n" * 2000
    tail = b"; prusaslicer_config = begin\n; layer_height = 0.2\n"
    if profile is not None:
        tail += f"; physical_printer_settings_id = {profile}\n".encode()
    return moves + tail + b"; prusaslicer_config = end\n"


def _block(kind: int, data: bytes, params: bytes, deflate: bool = False, raw: bool = False) -> bytes:
    if deflate:
        packed = zlib.compress(data)
        if raw:
            c = zlib.compressobj(wbits=-15)
            packed = c.compress(data) + c.flush()
        head = struct.pack("<HHII", kind, 1, len(data), len(packed))
    else:
        packed, head = data, struct.pack("<HHI", kind, 0, len(data))
    return head + params + packed + struct.pack("<I", zlib.crc32(head + params + packed))


def bgcode(profile: str | None, deflate: bool = True, raw: bool = False) -> bytes:
    ini = b"layer_height=0.2\nprinter_model=COREONE\n"
    if profile is not None:
        ini += f"physical_printer_settings_id={profile}\n".encode()
    return (
        b"GCDE" + struct.pack("<IH", 1, 1)  # version 1, CRC32 checksums
        + _block(0, b"Producer=PrusaSlicer 2.9.6\n", struct.pack("<H", 0))
        + _block(3, b"printer_model=COREONE\n", struct.pack("<H", 0))
        + _block(5, b"\x89PNG" + b"x" * 300, struct.pack("<HHH", 0, 16, 16))
        + _block(4, b"estimated printing time=1h\n", struct.pack("<H", 0))
        + _block(2, ini, struct.pack("<H", 0), deflate=deflate, raw=raw)
        + _block(1, b"G28\n" * 500, struct.pack("<H", 0), deflate=True)
    )


# ------------------------------------------------------------------ reading the printer


@pytest.mark.parametrize("name, body, expected", [
    ("a.gcode", gcode("Prusa_2"), "Prusa_2"),
    ("a.GCODE", gcode("VT 1190"), "VT 1190"),
    ("a.gcode", gcode(""), None),  # no physical printer picked in the slicer
    ("a.gcode", gcode(None), None),  # another slicer
    ("a.gcode", b"", None),
    ("a.bgcode", bgcode("Prusa_2"), "Prusa_2"),
    ("a.bgcode", bgcode("VT 1190", deflate=False), "VT 1190"),
    ("a.bgcode", bgcode("VT 1190", raw=True), "VT 1190"),
    ("a.bgcode", bgcode(None), None),
    ("a.bgcode", b"GCDE\x01", None),  # cut short
    ("a.bgcode", b"not a bgcode at all", None),
], ids=["gcode", "upper-case", "no-printer", "other-slicer", "empty", "bgcode", "bgcode-plain", "bgcode-raw-deflate", "bgcode-no-printer", "bgcode-cut-short", "not-bgcode"])
def test_the_printer_a_gcode_was_sliced_for(name, body, expected):
    f = io.BytesIO(body)
    f.seek(5 if body else 0)
    assert printer_profile(f, name) == expected
    assert f.tell() == 0  # left ready to be saved


# ------------------------------------------------------------------ over the API


@pytest.fixture()
def farm(api, sample_3mf_paths):
    """A 3MF for VT 1190 (sliced under that profile), with a V2 BOG printer alongside."""
    api.post("/printers", json={"name": "V2 BOG"})
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    mid = api.post("/source-models", data={"name": "Shark.stl", "file_type": "STL"}, files={"file": ("Shark.stl", b"x" * 64)}).json()["id"]
    with open(sample_3mf_paths["shark_vt1190"], "rb") as f:
        vt = f.read()
    with open(sample_3mf_paths["shark_v2bog"], "rb") as f:
        bog = f.read()
    bundle = api.post("/bundles", data={"source_model_ids": f"[{mid}]", "printer_id": str(pid)}, files={"threemf": ("Shark.3mf", vt)}).json()
    return {"api": api, "bundle": bundle, "model": mid, "printer": pid, "vt": vt, "bog": bog}


def _count(farm):
    return len(farm["api"].get(f"/bundles/{farm['bundle']['id']}").json()["versions"])


def test_a_new_version_for_another_printer_says_so(farm):
    c, bid = farm["api"], farm["bundle"]["id"]
    r = c.post(f"/bundles/{bid}/versions", files={"threemf": ("Shark.3mf", farm["bog"])})
    assert r.status_code == 422
    assert r.json()["detail"] == (
        'Wrong printer: this 3MF was sliced for "V2 BOG", but this 3MF belongs to "VT 1190". Slice it again with '
        'the "VT 1190" printer profile, or upload it as a new 3MF for "V2 BOG".'
    )
    assert _count(farm) == 1


@pytest.mark.parametrize("name, body", [("Shark.gcode", gcode("V2 BOG")), ("Shark.bgcode", bgcode("V2 BOG"))], ids=["gcode", "bgcode"])
def test_a_gcode_for_another_printer_is_refused_with_its_3mf(farm, name, body):
    c, bid = farm["api"], farm["bundle"]["id"]
    r = c.post(f"/bundles/{bid}/versions", files={"threemf": ("Shark.3mf", farm["vt"]), "gcode": (name, body)})
    assert r.status_code == 422
    assert r.json()["detail"].startswith('Wrong printer: this G-code was sliced for "V2 BOG", but this 3MF belongs to "VT 1190".')
    assert _count(farm) == 1  # nothing kept


@pytest.mark.parametrize("body", [gcode("VT 1190"), gcode(None), gcode("")], ids=["same-printer", "other-slicer", "no-printer"])
def test_a_gcode_for_the_same_printer_or_none_named_is_taken(farm, body):
    c, bid = farm["api"], farm["bundle"]["id"]
    r = c.post(f"/bundles/{bid}/versions", files={"threemf": ("Shark.3mf", farm["vt"]), "gcode": ("Shark.gcode", body)})
    assert r.status_code == 201, r.text
    v = {v["version"]: v for v in r.json()["versions"]}[2]
    assert v["gcode_name"] == "Shark ver 2.gcode"
    assert c.get(f"/bundles/versions/{v['id']}/download/gcode").content == body  # saved whole, from its start


def test_a_gcode_added_later_for_another_printer_is_refused(farm):
    c = farm["api"]
    vid = farm["bundle"]["versions"][0]["id"]
    r = c.put(f"/bundles/versions/{vid}/gcode", files={"gcode": ("Shark.bgcode", bgcode("V2 BOG"))})
    assert r.status_code == 422 and r.json()["detail"].startswith('Wrong printer: this G-code was sliced for "V2 BOG"')
    assert c.put(f"/bundles/versions/{vid}/gcode", files={"gcode": ("Shark.bgcode", bgcode("VT 1190"))}).status_code == 200


def test_a_new_3mfs_gcode_must_match_it_or_its_printer(farm):
    c = farm["api"]
    form = {"source_model_ids": f"[{farm['model']}]", "printer_id": str(farm["printer"])}
    r = c.post("/bundles", data=form, files={"threemf": ("Shark.3mf", farm["vt"]), "gcode": ("Shark.gcode", gcode("V2 BOG"))})
    assert r.status_code == 422 and 'this G-code was sliced for "V2 BOG"' in r.json()["detail"]
    assert len(c.get("/bundles").json()) == 1  # nothing kept
    r = c.post("/bundles", data=form, files={"threemf": ("Shark.3mf", farm["vt"]), "gcode": ("Shark.gcode", gcode("VT 1190"))})
    assert r.status_code == 201, r.text
