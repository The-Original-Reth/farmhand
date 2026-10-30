"""
Sub printers: a printer's printer presets in PrusaSlicer (BOSS edition), found from the 3MFs uploaded (their
printer_settings_id) or added by hand, renamed and removed, with each 3MF version linked to the one it was sliced with.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import BundleVersionSubPrinter, Printer
from app.services import printer_service, records_service, sub_printer_service

from . import factories as make

FROG_PRESET = "Trident_Allyson_DragonBurner_Rapido_0.5_WC"


def _upload(api, path, printer_id, status=201, **choice):
    """A new 3MF from that file; choice: sub_printer_id or new_sub_printer_name, picked on upload."""
    with open(path, "rb") as f:
        data = f.read()
    mid = api.post("/source-models", data={"name": "Frog.stl", "file_type": "STL"}, files={"file": ("Frog.stl", b"x" * 64)}).json()["id"]
    form = {"source_model_ids": f"[{mid}]", "printer_id": str(printer_id), **{k: str(v) for k, v in choice.items()}}
    r = api.post("/bundles", data=form, files={"threemf": ("Frog.3mf", data)})
    assert r.status_code == status, r.text
    return r.json()


def _subs(api, pid):
    return {s["name"]: s for s in api.get(f"/printers/{pid}").json()["sub_printers"]}


def test_inspecting_a_3mf_says_which_preset_it_was_sliced_with(api, sample_3mf_paths):
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        r = api.post("/bundles/inspect", files={"threemf": ("Frog.3mf", f.read())})
    assert r.status_code == 200 and r.json()["printer_preset_name"] == FROG_PRESET


def test_a_3mf_can_be_put_with_another_sub_printer_and_the_next_one_goes_there_too(api, sample_3mf_paths):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    brass = api.post(f"/printers/{pid}/sub-printers", json={"name": "Trident 0.4 brass"}).json()["sub_printers"][0]["id"]
    b = _upload(api, sample_3mf_paths["frog_vt1190"], pid, sub_printer_id=brass)
    assert b["versions"][0]["sub_printer_name"] == "Trident 0.4 brass"
    subs = _subs(api, pid)
    assert list(subs) == ["Trident 0.4 brass"]  # the file's preset wasn't added as a sub printer of its own
    assert subs["Trident 0.4 brass"]["aliases"] == [FROG_PRESET]  # remembered for next time

    b = _upload(api, sample_3mf_paths["shark_vt1190"], pid)  # same preset, nothing picked: goes where the last went
    assert b["versions"][0]["sub_printer_name"] == "Trident 0.4 brass"


def test_a_3mf_can_go_to_a_new_sub_printer_named_on_upload(api, sample_3mf_paths):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    b = _upload(api, sample_3mf_paths["frog_vt1190"], pid, new_sub_printer_name=" Trident Rapido 0.5 ")
    assert b["versions"][0]["sub_printer_name"] == "Trident Rapido 0.5"
    assert _subs(api, pid)["Trident Rapido 0.5"]["aliases"] == [FROG_PRESET]
    # a name the printer already has is that sub printer, not a second one
    b = _upload(api, sample_3mf_paths["shark_vt1190"], pid, new_sub_printer_name="Trident Rapido 0.5")
    assert b["versions"][0]["sub_printer_name"] == "Trident Rapido 0.5" and len(_subs(api, pid)) == 1


def test_another_printers_sub_printer_cant_be_picked(api, sample_3mf_paths):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    other = api.post("/printers", json={"name": "V2 BOG"}).json()["id"]
    theirs = api.post(f"/printers/{other}/sub-printers", json={"name": "V2 brass"}).json()["sub_printers"][0]["id"]
    r = _upload(api, sample_3mf_paths["frog_vt1190"], pid, status=422, sub_printer_id=theirs)
    assert "isn't one of VT 1190's" in r["detail"]
    assert api.get(f"/printers/{pid}/bundles").json() == []  # nothing was stored


def test_a_renamed_sub_printer_keeps_getting_its_old_presets_3mfs(api, sample_3mf_paths):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    _upload(api, sample_3mf_paths["frog_vt1190"], pid)
    sid = _subs(api, pid)[FROG_PRESET]["id"]
    r = api.patch(f"/printers/{pid}/sub-printers/{sid}", json={"name": "VT1190_Stealthburner_Rapido_UHF"})
    assert r.json()["sub_printers"][0]["aliases"] == [FROG_PRESET]
    b = _upload(api, sample_3mf_paths["shark_vt1190"], pid)  # still sliced with the old preset name
    assert b["versions"][0]["sub_printer_name"] == "VT1190_Stealthburner_Rapido_UHF" and len(_subs(api, pid)) == 1
    # renamed back: that's its name again, not a name it was known by
    r = api.patch(f"/printers/{pid}/sub-printers/{sid}", json={"name": FROG_PRESET})
    assert r.json()["sub_printers"][0]["aliases"] == ["VT1190_Stealthburner_Rapido_UHF"]


def test_an_uploaded_3mf_adds_its_preset_as_a_sub_printer_and_is_linked_to_it(api, sample_3mf_paths):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    bundle = _upload(api, sample_3mf_paths["frog_vt1190"], pid)
    printer = api.get(f"/printers/{pid}").json()
    assert [s["name"] for s in printer["sub_printers"]] == [FROG_PRESET]
    v = bundle["versions"][0]
    assert v["sub_printer_name"] == FROG_PRESET and v["sub_printer_id"] == printer["sub_printers"][0]["id"]

    # a second 3MF with the same preset uses the same sub printer, and lists show it too
    _upload(api, sample_3mf_paths["shark_vt1190"], pid)
    assert len(api.get(f"/printers/{pid}").json()["sub_printers"]) == 1
    listed = api.get(f"/printers/{pid}/bundles").json()
    assert {v["sub_printer_name"] for b in listed for v in b["versions"]} == {FROG_PRESET}


def test_sub_printers_can_be_added_renamed_and_removed_by_hand(api, sample_3mf_paths):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    bundle = _upload(api, sample_3mf_paths["frog_vt1190"], pid)

    r = api.post(f"/printers/{pid}/sub-printers", json={"name": "  Trident 0.4 brass  "})
    assert r.status_code == 201
    assert [s["name"] for s in r.json()["sub_printers"]] == ["Trident 0.4 brass", FROG_PRESET]  # A to Z
    assert api.post(f"/printers/{pid}/sub-printers", json={"name": "Trident 0.4 brass"}).status_code == 409
    assert api.post(f"/printers/{pid}/sub-printers", json={"name": "   "}).status_code == 422

    frog = next(s for s in r.json()["sub_printers"] if s["name"] == FROG_PRESET)
    assert api.patch(f"/printers/{pid}/sub-printers/{frog['id']}", json={"name": "Trident 0.4 brass"}).status_code == 409
    r = api.patch(f"/printers/{pid}/sub-printers/{frog['id']}", json={"name": "Trident 0.5 Rapido"})
    assert r.status_code == 200 and "Trident 0.5 Rapido" in [s["name"] for s in r.json()["sub_printers"]]
    # renaming keeps the 3MF linked
    assert api.get(f"/bundles/{bundle['id']}").json()["versions"][0]["sub_printer_name"] == "Trident 0.5 Rapido"

    other = api.post("/printers", json={"name": "V2 BOG"}).json()["id"]
    assert api.delete(f"/printers/{other}/sub-printers/{frog['id']}?confirm=true").status_code == 404  # not its own
    assert api.delete(f"/printers/{pid}/sub-printers/{frog['id']}").status_code == 409  # not confirmed
    r = api.delete(f"/printers/{pid}/sub-printers/{frog['id']}?confirm=true")
    assert r.status_code == 200 and [s["name"] for s in r.json()["sub_printers"]] == ["Trident 0.4 brass"]
    v = api.get(f"/bundles/{bundle['id']}").json()["versions"][0]  # the 3MF stays, with no sub printer
    assert v["sub_printer_id"] is None and v["sub_printer_name"] is None


def test_3mfs_from_before_sub_printers_are_linked_once(db_session, sample_3mf_paths):
    printer = printer_service.create_printer(db_session, name="VT 1190", kind=None, wired_ip=None, wireless_ip=None)
    model = make.model(db_session, "Frog.stl")
    bundle = make.bundle(db_session, sample_3mf_paths["frog_vt1190"], [model], "Frog.3mf", gcode=None, printer_id=printer.id)
    make.add_version(db_session, bundle, sample_3mf_paths["shark_vt1190"], "Shark.3mf", gcode=None)
    # as they were before: no links, no sub printers
    db_session.query(BundleVersionSubPrinter).delete()
    for s in list(printer.sub_printers):
        printer.sub_printers.remove(s)
    db_session.commit()

    assert sub_printer_service.link_missing(db_session) == 2
    db_session.expire_all()
    assert [s.name for s in db_session.get(Printer, printer.id).sub_printers] == [FROG_PRESET]
    assert {v.sub_printer_name for v in bundle.versions} == {FROG_PRESET}
    assert sub_printer_service.link_missing(db_session) == 0  # each version is only looked at once


DEFAULTS = ["Toolhead", "Hotend", "Nozzle", "Extruder", "Gantry", "XY motor"]


def test_a_new_sub_printer_starts_with_the_default_parts(api, sample_3mf_paths):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    by_hand = api.post(f"/printers/{pid}/sub-printers", json={"name": "Trident 0.4 brass"}).json()["sub_printers"][0]["id"]
    parts = api.get(f"/printers/{pid}/sub-printers/{by_hand}/parts").json()
    assert [p["part"] for p in parts] == DEFAULTS
    assert all(p["make"] is None and p["model"] is None and p["installed_on"] is None and p["note"] is None for p in parts)  # to fill in
    # ticked "Add to name" to start with: all but the XY motor
    assert [p["part"] for p in parts if p["in_name"]] == ["Toolhead", "Hotend", "Nozzle", "Extruder", "Gantry"]

    _upload(api, sample_3mf_paths["frog_vt1190"], pid)  # one found from a 3MF gets them too
    found = next(s["id"] for s in api.get(f"/printers/{pid}").json()["sub_printers"] if s["name"] == FROG_PRESET)
    assert [p["part"] for p in api.get(f"/printers/{pid}/sub-printers/{found}/parts").json()] == DEFAULTS


def test_a_default_parts_name_cant_be_changed_but_the_rest_of_it_can(api):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    sid = api.post(f"/printers/{pid}/sub-printers", json={"name": "Trident 0.4 brass"}).json()["sub_printers"][0]["id"]
    base = f"/printers/{pid}/sub-printers/{sid}/parts"
    hotend = next(p for p in api.get(base).json() if p["part"] == "Hotend")
    r = api.put(f"{base}/{hotend['id']}", json={**hotend, "part": "Hot end"})
    assert r.status_code == 422 and "default parts" in r.json()["detail"]
    r = api.put(f"{base}/{hotend['id']}", json={**hotend, "make": "Phaetus", "model": "Rapido UHF"})
    assert r.status_code == 200 and [p["model"] for p in r.json() if p["part"] == "Hotend"] == ["Rapido UHF"]
    assert api.delete(f"{base}/{hotend['id']}?confirm=true").status_code == 200  # it can still be removed

    own = api.post(base, json={"part": "Bed"}).json()[-1]  # a part added by hand can be renamed
    assert api.put(f"{base}/{own['id']}", json={**own, "part": "Build plate"}).status_code == 200


def test_a_sub_printers_parts_can_be_written_down_changed_and_removed(api):
    pid = api.post("/printers", json={"name": "V2 BOG"}).json()["id"]
    sid = api.post(f"/printers/{pid}/sub-printers", json={"name": "V2_BOG_Rapido_Ace_0.5_WC"}).json()["sub_printers"][0]["id"]
    base = f"/printers/{pid}/sub-printers/{sid}/parts"
    for p in api.get(base).json():  # start from an empty list
        api.delete(f"{base}/{p['id']}?confirm=true")
    assert api.get(base).json() == []

    r = api.post(base, json={"part": " Hotend ", "make": " Phaetus ", "model": "Rapido UHF", "installed_on": "2026-08-14", "note": "after the clog"})
    assert r.status_code == 201
    assert r.json() == [{"id": r.json()[0]["id"], "part": "Hotend", "make": "Phaetus", "model": "Rapido UHF", "installed_on": "2026-08-14", "note": "after the clog", "in_name": False}]
    api.post(base, json={"part": "Nozzle", "model": "0.5 WC"})
    assert [p["part"] for p in api.get(base).json()] == ["Hotend", "Nozzle"]  # in the order they were added
    assert api.post(base, json={"part": "  "}).status_code == 422

    hotend = api.get(base).json()[0]["id"]
    r = api.put(f"{base}/{hotend}", json={"part": "Hotend", "make": "", "model": "Dragon UHF", "installed_on": None, "note": "", "in_name": False})
    assert r.status_code == 200 and r.json()[0] == {"id": hotend, "part": "Hotend", "make": None, "model": "Dragon UHF", "installed_on": None, "note": None, "in_name": False}

    other = api.post(f"/printers/{pid}/sub-printers", json={"name": "Another"}).json()["sub_printers"]
    other_id = next(s["id"] for s in other if s["name"] == "Another")
    assert api.put(f"/printers/{pid}/sub-printers/{other_id}/parts/{hotend}", json={"part": "x"}).status_code == 404  # not its part
    assert api.delete(f"{base}/{hotend}").status_code == 409  # not confirmed
    assert [p["part"] for p in api.delete(f"{base}/{hotend}?confirm=true").json()] == ["Nozzle"]

    # removing the sub printer takes its parts with it
    assert api.delete(f"/printers/{pid}/sub-printers/{sid}?confirm=true").status_code == 200
    assert api.get(base).status_code == 404


def test_a_sub_printers_whole_parts_list_is_saved_at_once(api):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    sid = api.post(f"/printers/{pid}/sub-printers", json={"name": "Trident 0.4 brass"}).json()["sub_printers"][0]["id"]
    base = f"/printers/{pid}/sub-printers/{sid}/parts"
    parts = api.get(base).json()
    hotend, xy = parts[1], parts[5]
    edited = [
        {**p, "make": "Phaetus", "model": "Rapido UHF"} if p["id"] == hotend["id"] else {**p, "note": "swapped"} if p["part"] == "Nozzle" else p
        for p in parts if p["id"] != xy["id"]
    ] + [{"part": "Bed", "model": "300 x 300"}]

    r = api.put(base, json=edited)
    assert r.status_code == 409  # it removes the XY motor, so it has to say so
    assert api.get(base).json() == parts  # and nothing was saved

    r = api.put(f"{base}?confirm=true", json=edited)
    assert r.status_code == 200
    saved = r.json()
    assert [p["part"] for p in saved] == ["Toolhead", "Hotend", "Nozzle", "Extruder", "Gantry", "Bed"]  # new ones after the rest
    assert saved[1]["id"] == hotend["id"] and saved[1]["model"] == "Rapido UHF" and saved[2]["note"] == "swapped"
    assert api.put(base, json=saved).status_code == 200  # removing nothing needs no confirm

    # all or nothing: one bad row and none of it is saved
    renamed = [{**p, "part": "Hot end"} if p["id"] == hotend["id"] else {**p, "note": "x"} for p in saved]
    r = api.put(base, json=renamed)
    assert r.status_code == 422 and "default parts" in r.json()["detail"]
    assert api.put(base, json=[*saved, {**saved[0]}]).status_code == 422  # the same part twice
    assert api.put(f"{base}?confirm=true", json=[{**saved[0], "id": 99999}, *saved[1:]]).status_code == 404  # not its part
    assert api.get(base).json() == saved


def test_sub_printers_and_their_parts_are_kept_in_the_settings_copy_and_restored(db_session, tmp_path):
    printer = printer_service.create_printer(db_session, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)
    sub = sub_printer_service.add(db_session, printer.id, "V2_BOG_Rapido_Ace_0.5_WC").sub_printers[0]
    hotend = next(p for p in sub.parts if p.part == "Hotend")
    sub_printer_service.update_part(db_session, printer.id, sub.id, hotend.id, {"part": "Hotend", "make": "Phaetus", "model": "Rapido", "installed_on": dt.date(2026, 8, 14), "note": None, "in_name": False})
    gantry = next(p for p in sub.parts if p.part == "Gantry")
    sub_printer_service.delete_part(db_session, printer.id, sub.id, gantry.id)  # one removed: it stays removed
    sub_printer_service.rename(db_session, printer.id, sub.id, "V2BOG_Rapido")  # its old name is remembered
    records_service.write_all(db_session, tmp_path)

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    records_service.restore_all(db, tmp_path)
    restored = db.query(Printer).one().sub_printers
    assert [s.name for s in restored] == ["V2BOG_Rapido"]
    assert restored[0].aliases == ["V2_BOG_Rapido_Ace_0.5_WC"]
    assert [p.part for p in restored[0].parts] == ["Toolhead", "Hotend", "Nozzle", "Extruder", "XY motor"]
    assert [(p.make, p.model, p.installed_on, p.in_name) for p in restored[0].parts if p.part == "Hotend"] == [("Phaetus", "Rapido", dt.date(2026, 8, 14), False)]
    assert [p.in_name for p in restored[0].parts if p.part == "Toolhead"] == [True]  # the ticks come back too
    again = records_service.restore_all(db, tmp_path)  # nothing new the second time
    assert again["printers_filled"] == [] and len(db.query(Printer).one().sub_printers[0].parts) == 5


def test_restoring_fills_in_a_sub_printer_that_only_has_the_untouched_defaults(db_session):
    # e.g. found again from its 3MFs when Farmhand started, before the settings copy was restored
    printer = printer_service.create_printer(db_session, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)
    sub_printer_service.add(db_session, printer.id, "V2_BOG_Rapido_Ace_0.5_WC")
    saved = [{"name": "V2_BOG_Rapido_Ace_0.5_WC", "parts": [{"part": "Hotend", "model": "Rapido", "installed_on": None, "note": None}]}]
    assert sub_printer_service.restore(db_session, printer, saved)
    db_session.commit()
    assert [(p.part, p.model) for p in printer.sub_printers[0].parts] == [("Hotend", "Rapido")]
    assert not sub_printer_service.restore(db_session, printer, saved)  # a list someone filled in is left alone


def test_a_settings_copy_from_before_parts_still_restores_its_sub_printers(db_session):
    printer = printer_service.create_printer(db_session, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)
    assert sub_printer_service.restore(db_session, printer, ["V2_BOG_Rapido_Ace_0.5_WC", "", 7])
    db_session.commit()
    assert [s.name for s in printer.sub_printers] == ["V2_BOG_Rapido_Ace_0.5_WC"]
    assert [p.part for p in printer.sub_printers[0].parts] == DEFAULTS  # nothing saved for it: the defaults


def test_a_printer_can_have_one_default_sub_printer(api):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    api.post(f"/printers/{pid}/sub-printers", json={"name": "Trident 0.4 brass"})
    subs = api.post(f"/printers/{pid}/sub-printers", json={"name": "Trident 0.5 Rapido"}).json()["sub_printers"]
    brass, rapido = (s["id"] for s in subs)
    assert api.get(f"/printers/{pid}").json()["default_sub_printer_id"] is None

    r = api.put(f"/printers/{pid}/default-sub-printer", json={"sub_printer_id": brass})
    assert r.status_code == 200 and r.json()["default_sub_printer_id"] == brass
    r = api.put(f"/printers/{pid}/default-sub-printer", json={"sub_printer_id": rapido})  # only one: it moves
    assert r.json()["default_sub_printer_id"] == rapido
    assert [p["default_sub_printer_id"] for p in api.get("/printers").json()] == [rapido]

    other = api.post("/printers", json={"name": "V2 BOG"}).json()["id"]
    assert api.put(f"/printers/{other}/default-sub-printer", json={"sub_printer_id": rapido}).status_code == 404
    assert api.put(f"/printers/{pid}/default-sub-printer", json={"sub_printer_id": None}).json()["default_sub_printer_id"] is None

    api.put(f"/printers/{pid}/default-sub-printer", json={"sub_printer_id": brass})
    r = api.delete(f"/printers/{pid}/sub-printers/{brass}?confirm=true")  # removing it leaves no default
    assert r.status_code == 200 and r.json()["default_sub_printer_id"] is None


def test_the_default_sub_printer_is_kept_in_the_settings_copy(db_session, tmp_path):
    printer = printer_service.create_printer(db_session, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)
    sub_printer_service.add(db_session, printer.id, "V2_BOG_0.4_brass")
    rapido = sub_printer_service.add(db_session, printer.id, "V2_BOG_Rapido").sub_printers[1]
    sub_printer_service.set_default(db_session, printer.id, rapido.id)
    records_service.write_all(db_session, tmp_path)

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    records_service.restore_all(db, tmp_path)
    restored = db.query(Printer).one()
    assert next(s.name for s in restored.sub_printers if s.id == restored.default_sub_printer_id) == "V2_BOG_Rapido"
