from __future__ import annotations

import json
import os

import pytest

from app import config_store as cs, storage
from app.models import NetworkShare
from app.services import app_settings
from app.services import config_service as svc
from app.services import network_shares_service as shares


@pytest.fixture()
def share(share):
    """The shared fake NAS share, with no settings copy written yet."""
    svc.nas_copy._last_mirror.update(ok=None, error=None, at=None)
    return share


def _folder(share, name="settings"):
    d = share / name
    d.mkdir(exist_ok=True)
    return d


def _file(folder):
    return json.loads((folder / cs.CONFIG_FILENAME).read_text())


# ------------------------------------------------------------------ the settings themselves


def test_settings_default_save_merge_and_clean(db_session):
    assert svc.get_config(db_session) == cs.normalize_config({})
    out = svc.save_config(db_session, {"appearance": {"scheme": "violet", "contrast": 300, "font": "play", "size": "large"}})
    assert out["appearance"] == {"scheme": "violet", "contrast": 100, "font": "play", "size": "large", "file_name_color": "auto"}
    svc.save_config(db_session, {"preferences": {"model_sort": {"key": "added", "dir": "desc"}}})
    again = svc.get_config(db_session)
    assert again["appearance"]["scheme"] == "violet"  # the earlier part is kept when only the other is given
    assert again["preferences"]["model_sort"] == {"key": "added", "dir": "desc"}


# ------------------------------------------------------------------ choosing the network folder


def test_choosing_a_folder_writes_the_copy_there_and_marks_the_folder(db_session, share):
    svc.save_config(db_session, {"appearance": {"scheme": "midnight", "contrast": 20, "font": "play", "size": "default"}})
    folder = _folder(share)

    out = svc.set_location(db_session, str(folder))

    assert out["saved"] and not out["needs_choice"]
    assert (folder / storage.MARKER_NAME).is_file()
    assert _file(folder)["appearance"]["scheme"] == "midnight"
    assert out["location"]["is_set"] and out["location"]["status"]["ready"] and out["location"]["file"]["exists"]


def test_every_later_change_refreshes_the_copy(db_session, share):
    folder = _folder(share)
    svc.set_location(db_session, str(folder))
    svc.save_config(db_session, {"appearance": {"scheme": "violet", "contrast": 0, "font": "archivo", "size": "default"}})
    result = svc.mirror(db_session)
    assert result["ok"] and _file(folder)["appearance"]["scheme"] == "violet"


def test_saved_stream_layouts_have_a_file_each_in_streams(db_session, share, other_farmhand):
    from app.services import printer_service

    vt = printer_service.create_printer(db_session, name="VT 1190", kind=None, wired_ip=None, wireless_ip=None)
    v2 = printer_service.create_printer(db_session, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)
    folder = _folder(share)
    svc.set_location(db_session, str(folder))
    layouts = [
        {"name": "Whole farm", "cols": 2, "rows": 2, "layout": "cycle", "seconds_all": 0, "seconds_each": 40, "border_color": "#FF0000",
         "cells": [{"image": "Elves.png"}, {"camera": f"{vt.id}:Bed"}, None, {"camera": f"{v2.id}:Camera"}]},
        {"name": "Night/shift", "cols": 1, "rows": 1, "cells": [{"camera": f"{v2.id}:Camera"}]},
    ]
    svc.save_config(db_session, {"preferences": {"stream_layouts": layouts}})
    svc.mirror(db_session)
    whole = json.loads((folder / "streams" / "Whole farm.json").read_text(encoding="utf-8"))
    assert whole["farmhand_record"] == "streams" and whole["name"] == "Whole farm" and (whole["cols"], whole["rows"]) == (2, 2)
    assert whole["cells"][0]["image"] == "Elves.png"  # a card as it is: pictures are named by file already
    assert whole["cells"][1:] == [{"camera": {"printer": "VT 1190", "camera": "Bed"}}, None, {"camera": {"printer": "V2 BOG", "camera": "Camera"}}]
    assert (whole["layout"], whole["seconds_all"], whole["seconds_each"], whole["show_status"], whole["border_color"]) == ("cycle", 0, 40, True, "#FF0000")
    assert (folder / "streams" / "Night_shift.json").is_file()  # a name made safe for a file
    assert "stream_layouts" not in _file(folder)["preferences"]  # only in streams/, not twice

    # deleted on the page: its file goes too
    svc.save_config(db_session, {"preferences": {"stream_layouts": layouts[:1]}})
    svc.mirror(db_session)
    assert sorted(p.name for p in (folder / "streams").iterdir()) == ["Whole farm.json"]

    # Load all on another Farmhand, whose printers have other numbers: they're followed by name
    db2 = other_farmhand
    printer_service.create_printer(db2, name="Shelf", kind=None, wired_ip=None, wireless_ip=None)
    v2_here = printer_service.create_printer(db2, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)
    svc.save_config(db2, {"preferences": {"stream_layouts": [{"name": "WHOLE FARM", "cameras": []}, {"name": "Mine", "cameras": []}]}})
    app_settings.put(db2, svc.KEY_LOCATION, str(folder))
    db2.commit()
    out = svc.restore(db2)
    got = svc.get_config(db2)["preferences"]["stream_layouts"]
    # one by the same name here is kept as it is (Load all only adds), so nothing new came in yet
    assert [lay["name"] for lay in got] == ["WHOLE FARM", "Mine"] and "stream layouts" not in out["restored"]
    svc.save_config(db2, {"preferences": {"stream_layouts": []}})
    out = svc.restore(db2)
    got = svc.get_config(db2)["preferences"]["stream_layouts"]
    assert "stream layouts" in out["restored"]
    # VT 1190 came back from its printers/ file, so its camera is here too, in this Farmhand's numbers
    vt_here = next(p.id for p in printer_service.list_printers(db2) if p.name == "VT 1190")
    assert got[0]["cells"][0]["image"] == "Elves.png"
    assert {k: v for k, v in got[0].items() if k != "cells"} == {"name": "Whole farm", "cols": 2, "rows": 2, "layout": "cycle", "seconds_all": 0,
                                                                  "seconds_each": 40, "show_status": True, "border_color": "#FF0000", "background": "#000000", "font": "play", "color": "#FFFFFF"}
    assert got[0]["cells"][1:] == [{"camera": f"{vt_here}:Bed"}, None, {"camera": f"{v2_here.id}:Camera"}]


def test_a_folder_that_isnt_on_a_share_is_refused(db_session, share, tmp_path):
    plain = tmp_path / "data" / "elsewhere"
    plain.mkdir(parents=True)
    with pytest.raises(ValueError, match="lost when the container restarts|isn't under"):
        svc.set_location(db_session, str(plain))
    assert svc.location_path(db_session) is None


def test_clearing_the_location_keeps_the_file_that_was_written(db_session, share):
    folder = _folder(share)
    svc.set_location(db_session, str(folder))
    svc.set_location(db_session, None)
    assert svc.location_path(db_session) is None
    assert (folder / cs.CONFIG_FILENAME).is_file()  # nothing on the network is ever deleted
    assert svc.mirror(db_session)["skipped"] is True


# ------------------------------------------------------------------ an existing settings file is never overwritten unasked


def _existing_file(folder, scheme="violet"):
    cs.write_document(folder, cs.build_document(cs.normalize_config({"appearance": {"scheme": scheme}}), None, None,
                                                 [{"name": "Backup NAS", "protocol": "nfs", "server": "10.0.0.6", "share": "/vol1"}]))
    return (folder / cs.CONFIG_FILENAME).read_text()


def test_pointing_at_a_folder_with_settings_in_it_asks_first_and_changes_nothing(db_session, share):
    folder = _folder(share)
    original = _existing_file(folder)

    out = svc.set_location(db_session, str(folder))  # if_exists defaults to "ask"

    assert out["needs_choice"] and not out["saved"]
    assert out["found"]["file_valid"] and out["found"]["summary"]["scheme"] == "violet" and out["found"]["summary"]["shares"] == 1
    assert (folder / cs.CONFIG_FILENAME).read_text() == original  # untouched
    assert svc.location_path(db_session) is None  # and not saved either


def test_choosing_overwrite_replaces_it_with_the_current_settings(db_session, share):
    folder = _folder(share)
    _existing_file(folder, "violet")
    svc.save_config(db_session, {"appearance": {"scheme": "light", "contrast": 0, "font": "archivo", "size": "default"}})
    svc.set_location(db_session, str(folder), "overwrite")
    assert _file(folder)["appearance"]["scheme"] == "light"


def test_choosing_restore_loads_the_file_and_keeps_it(db_session, share):
    folder = _folder(share)
    _existing_file(folder, "violet")
    out = svc.set_location(db_session, str(folder), "restore")
    assert out["saved"] and "appearance" in out["restored"]["restored"]
    assert svc.get_config(db_session)["appearance"]["scheme"] == "violet"
    assert out["restored"]["shares_added"] == ["Backup NAS"]
    assert _file(folder)["appearance"]["scheme"] == "violet"  # the file now simply reflects what's in force


def test_a_damaged_settings_file_can_be_replaced_but_not_restored(db_session, share):
    folder = _folder(share)
    (folder / cs.CONFIG_FILENAME).write_text("not json {")
    ask = svc.set_location(db_session, str(folder))
    assert ask["needs_choice"] and ask["found"]["file_valid"] is False and "can't be read" in ask["found"]["error"]
    with pytest.raises(ValueError, match="can't be read"):
        svc.set_location(db_session, str(folder), "restore")
    assert svc.location_path(db_session) is None
    svc.set_location(db_session, str(folder), "overwrite")
    assert _file(folder)["farmhand_config"] == 1


# ------------------------------------------------------------------ restoring a fresh install from the file


def test_restore_brings_back_everything_but_never_a_password(db_session, share):
    folder = _folder(share)
    stl = _folder(share, "stl")
    cs.write_document(folder, cs.build_document(
        cs.normalize_config({"appearance": {"scheme": "midnight", "contrast": 30, "font": "play", "size": "large", "file_name_color": "#5CB85C"},
                             "preferences": {"model_sort": {"key": "added", "dir": "desc"}}}),
        str(stl), None,
        [{"name": "Lab NAS", "protocol": "smb", "server": "10.0.0.5", "share": "farmhand", "username": "alice"},
         {"name": "Backup", "protocol": "nfs", "server": "10.0.0.6", "share": "/vol1"},
         {"name": "../bad", "protocol": "smb", "server": "x", "share": "y"}]))
    app_settings.put(db_session, svc.KEY_LOCATION, str(folder))
    db_session.commit()

    out = svc.restore(db_session)

    cfg = svc.get_config(db_session)
    assert cfg["appearance"] == {"scheme": "midnight", "contrast": 30, "font": "play", "size": "large", "file_name_color": "#5CB85C"}
    assert cfg["preferences"]["model_sort"] == {"key": "added", "dir": "desc"}
    assert storage.custom_path("stl") == str(stl.resolve()) and "STL folder" in out["restored"]
    assert sorted(out["shares_added"]) == ["Backup", "Lab NAS"]
    assert out["needs_password"] == ["Lab NAS"]  # an SMB share with a login needs its password typed in
    assert any("bad" in w for w in out["warnings"])  # the unusable entry is reported, not fatal
    lab = db_session.query(NetworkShare).filter_by(name="Lab NAS").one()
    assert lab.password is None
    listed = {s["name"]: s for s in shares.list_shares(db_session)["shares"]}
    assert not listed["Lab NAS"]["mounted"] and "password" in listed["Lab NAS"]["error"]


def test_restore_keeps_a_share_that_is_already_there(db_session, share):
    folder = _folder(share)
    cs.write_document(folder, cs.build_document(cs.normalize_config({}), None, None,
                                                 [{"name": "Backup", "protocol": "nfs", "server": "10.0.0.6", "share": "/vol1"}]))
    app_settings.put(db_session, svc.KEY_LOCATION, str(folder))
    db_session.commit()
    first = svc.restore(db_session)
    second = svc.restore(db_session)  # running it again is harmless
    assert first["shares_added"] == ["Backup"] and second["shares_added"] == [] and second["shares_kept"] == ["Backup"]
    assert db_session.query(NetworkShare).count() == 1


def test_restore_takes_a_share_reaching_the_same_nas_folder_as_the_one_here(db_session, share):
    """A new Farmhand whose Save location was typed in (its share "Lab"), loading the old one's settings, which reached
    the same NAS folder through a share it called "TrueNas": its folders are taken as on Lab, no second share."""
    db_session.add(NetworkShare(name="Lab", protocol="smb", server="10.0.0.5", share="Elves/Farmhand", username="alice"))
    folder = _folder(share)
    nas = share.parent
    cs.write_document(folder, cs.build_document(
        cs.normalize_config({}), str(nas / "truenas" / "STL"), str(nas / "truenas" / "3MF"),
        [{"name": "TrueNas", "protocol": "smb", "server": "10.0.0.5", "share": "elves/farmhand/", "username": "alice"}],
        project_path=str(nas / "truenas" / "Projects"), farm_cost_path=str(nas / "truenas" / "farm-cost"),
    ))
    app_settings.put(db_session, svc.KEY_LOCATION, str(folder))
    db_session.commit()

    out = svc.restore(db_session)

    assert out["shares_added"] == [] and out["needs_password"] == [] and out["shares_kept"] == ["TrueNas (the same NAS folder as Lab)"]
    assert [s.name for s in db_session.query(NetworkShare)] == ["Lab"]
    for kind, name in (("stl", "STL"), ("threemf", "3MF"), ("project", "Projects")):
        assert storage.custom_path(kind) == str((share / name).resolve())


def test_restore_puts_folders_back_even_when_their_share_is_not_connected_yet(db_session, share):
    folder = _folder(share)
    gone = share / "stl-not-here-yet"  # does not exist right now
    cs.write_document(folder, cs.build_document(cs.normalize_config({}), str(gone), None, []))
    app_settings.put(db_session, svc.KEY_LOCATION, str(folder))
    db_session.commit()
    out = svc.restore(db_session)
    assert "STL folder" in out["restored"] and storage.custom_path("stl") == str(gone.resolve())
    with pytest.raises(storage.StorageUnavailableError):  # ...and uploads are still refused until it's really there
        storage.source_model_version_dir(1, 1)


def test_restore_refuses_overlapping_folders_in_the_file(db_session, share):
    folder = _folder(share)
    same = _folder(share, "same")
    cs.write_document(folder, cs.build_document(cs.normalize_config({}), str(same), str(same), []))
    app_settings.put(db_session, svc.KEY_LOCATION, str(folder))
    db_session.commit()
    out = svc.restore(db_session)
    assert "STL folder" not in out["restored"] and any("overlap" in w for w in out["warnings"])
    assert storage.custom_path("stl") is None


def test_restore_needs_a_folder_and_a_file(db_session, share):
    with pytest.raises(ValueError, match="Choose a settings folder first"):
        svc.restore(db_session)
    folder = _folder(share)
    svc.set_location(db_session, str(folder), "overwrite")
    (folder / cs.CONFIG_FILENAME).unlink()
    with pytest.raises(ValueError, match="no settings file"):
        svc.restore(db_session)


# ------------------------------------------------------------------ when the network is not there


def test_an_unmounted_share_does_not_lose_settings_or_get_written_to(db_session, share):
    folder = _folder(share)
    svc.set_location(db_session, str(folder))
    (folder / storage.MARKER_NAME).unlink()  # the share dropped: only the bare folder underneath is left
    (folder / cs.CONFIG_FILENAME).unlink()

    svc.save_config(db_session, {"appearance": {"scheme": "violet", "contrast": 0, "font": "archivo", "size": "default"}})
    result = svc.mirror(db_session)

    assert not result["ok"] and "marker" in result["error"]
    assert not (folder / cs.CONFIG_FILENAME).exists()  # nothing was written into the empty folder
    assert svc.get_config(db_session)["appearance"]["scheme"] == "violet"  # the server still has them
    assert svc.describe(db_session)["last_write"]["ok"] is False


def test_a_share_with_a_stored_password_never_leaks_it_into_the_file(db_session, share):
    db_session.add(NetworkShare(name="Lab", protocol="smb", server="10.0.0.5", share="farmhand", username="alice", password="hunter2-secret"))
    db_session.commit()
    folder = _folder(share)
    svc.set_location(db_session, str(folder))
    text = (folder / cs.CONFIG_FILENAME).read_text()
    assert "hunter2-secret" not in text and '"username": "alice"' in text


def test_changing_storage_folders_or_shares_refreshes_the_copy(db_session, share):
    from app.services import storage_settings_service as sss

    folder = _folder(share)
    svc.set_location(db_session, str(folder))
    stl = _folder(share, "stl")
    sss.save(db_session, {"stl_path": str(stl)})
    svc.mirror(db_session)
    assert _file(folder)["storage"]["stl_path"] == str(stl.resolve())


# ------------------------------------------------------------------ Save all


def _stl_on_share(share):
    """The STL folder on the share, ready (its marker in place), as chosen in Settings."""
    stl = _folder(share, "STL")
    storage.mark_location(stl)
    storage.configure(stl_path=str(stl.resolve()))
    return stl


def test_save_all_with_no_folder_chosen_uses_farmhand_configs_beside_the_stl_folder(db_session, share):
    _stl_on_share(share)
    svc.save_config(db_session, {"preferences": {"farm_cost_order": [3, 1], "printer_sort": {"key": "wired", "dir": "desc"}}})
    out = svc.save_all(db_session)
    folder = share / svc.DEFAULT_FOLDER
    assert out["saved"] and out["mirror"]["ok"] and svc.location_path(db_session) == str(folder.resolve())
    prefs = _file(folder)["preferences"]
    assert prefs["farm_cost_order"] == [3, 1] and prefs["printer_sort"] == {"key": "wired", "dir": "desc"}
    assert out["location"]["file"]["exists"]


def test_save_all_asks_before_replacing_settings_already_in_farmhand_configs(db_session, share):
    _stl_on_share(share)
    folder = _folder(share, svc.DEFAULT_FOLDER)
    _existing_file(folder, scheme="violet")
    out = svc.save_all(db_session)
    assert not out["saved"] and out["needs_choice"] and out["mirror"] is None
    assert _file(folder)["appearance"]["scheme"] == "violet" and svc.location_path(db_session) is None  # nothing changed
    out = svc.save_all(db_session, "overwrite")
    assert out["saved"] and _file(folder)["appearance"]["scheme"] == "farmhand"


def test_save_all_writes_to_the_folder_already_chosen(db_session, share):
    folder = _folder(share)
    svc.set_location(db_session, str(folder))
    os.remove(folder / cs.CONFIG_FILENAME)
    out = svc.save_all(db_session)
    assert out["saved"] and (folder / cs.CONFIG_FILENAME).is_file()


def test_save_all_writes_each_projects_record_beside_its_files_too(db_session, share):
    import io

    from app.services import project_files, project_records
    from app.services.project_service import create_project

    from .factories import stl_bytes

    p = create_project(db_session, "Shark")
    project_files.upload(db_session, project_files.STL, p.id, "Fin.stl", io.BytesIO(stl_bytes()))
    record = project_records.record_path(db_session, p.folder)
    record.unlink(missing_ok=True)  # never written (a share away when it changed, say)

    svc.set_location(db_session, str(_folder(share)))
    out = svc.save_all(db_session)
    assert out["saved"] and out["records"]["projects"] == 1 and record.is_file()
    assert [(f["kind"], f["versions"][0]["filename"]) for f in json.loads(record.read_text())["files"]] == [("stl", "Fin ver 1.stl")]


def test_the_farm_cost_folder_is_saved_and_loaded_back(db_session, share):
    from app.services import farm_cost

    records = _folder(share, "farm cost records")
    farm_cost.set_location(db_session, str(records))
    folder = _folder(share)
    svc.set_location(db_session, str(folder))
    assert _file(folder)["farm_cost"] == {"records_path": str(records.resolve())}

    farm_cost.set_location(db_session, None)  # back to the default here...
    out = svc.restore(db_session)  # ...and Load all puts the saved one back
    assert "farm cost folder" in out["restored"]
    assert farm_cost.location_info(db_session)["path"] == str(records.resolve())


# ------------------------------------------------------------------ orders kept across Farmhands


def test_printer_orders_come_back_by_name_on_a_farmhand_that_numbers_them_differently(db_session, share):
    from app.services import printer_service

    for name in ("Lulzbot", "Prusa_2", "VT 1026"):  # here: 1, 2, 3
        printer_service.create_printer(db_session, name=name, kind=None, wired_ip=None, wireless_ip=None)
    folder = _folder(share)
    # written by a Farmhand where VT 1026 was 7, Prusa_2 was 1 and Lulzbot was 5 (and one this Farmhand hasn't got)
    prefs = {"farm_cost_order": [7, 1, 5, 9], "monitor_order": ["7:Front", "1:top", "9:Chamber", "5:rear"],
             "tool_links": [{"name": "Zebra", "url": "https://z.example"}, {"name": "Apple", "url": "https://a.example"}]}
    names = {7: "VT 1026", 1: "Prusa_2", 5: "Lulzbot", 9: "Gone printer"}
    cs.write_document(folder, cs.build_document(cs.normalize_config({"preferences": prefs}), None, None, [], printer_names=names))
    app_settings.put(db_session, svc.KEY_LOCATION, str(folder))
    db_session.commit()

    svc.restore(db_session)
    got = svc.get_config(db_session)["preferences"]
    assert got["farm_cost_order"] == [3, 2, 1]  # VT 1026, Prusa_2, Lulzbot, in this Farmhand's numbers
    assert got["monitor_order"] == ["3:Front", "2:top", "1:rear"]
    assert [link["name"] for link in got["tool_links"]] == ["Zebra", "Apple"]  # the Tools page's order, as it was


def test_the_settings_file_names_each_printer(db_session, share):
    from app.services import printer_service

    p = printer_service.create_printer(db_session, name="V2 BOG", kind=None, wired_ip=None, wireless_ip=None)
    folder = _folder(share)
    svc.set_location(db_session, str(folder))
    assert _file(folder)["printer_names"] == {str(p.id): "V2 BOG"}


def test_an_older_settings_file_keeps_its_orders_as_they_are(db_session, share):
    folder = _folder(share)
    doc = cs.build_document(cs.normalize_config({"preferences": {"farm_cost_order": [4, 2]}}), None, None, [])
    doc.pop("printer_names")
    cs.write_document(folder, doc)
    app_settings.put(db_session, svc.KEY_LOCATION, str(folder))
    db_session.commit()
    svc.restore(db_session)
    assert svc.get_config(db_session)["preferences"]["farm_cost_order"] == [4, 2]


def test_on_a_new_farmhand_the_orders_wait_for_the_printers_brought_back(db_session, share):
    """Load all on a Farmhand with no printers yet: they come back from the printers/ files, and the orders with them."""
    from app import records_store

    folder = _folder(share)
    prefs = {"farm_cost_order": [7, 1], "monitor_order": ["7:Front", "1:top"]}
    cs.write_document(folder, cs.build_document(cs.normalize_config({"preferences": prefs}), None, None, [],
                                                printer_names={7: "VT 1026", 1: "Prusa_2"}))
    docs = {  # their records, as the other Farmhand wrote them
        records_store.file_stem(name, set()): {**records_store.header(records_store.PRINTERS_DIR, name), "printer": {"connection_type": "moonraker"}}
        for name in ("Prusa_2", "VT 1026")
    }
    records_store.write_records(folder, records_store.PRINTERS_DIR, docs)
    app_settings.put(db_session, svc.KEY_LOCATION, str(folder))
    db_session.commit()

    svc.restore(db_session)
    from app.models import Printer

    ids = {p.name: p.id for p in db_session.query(Printer)}
    got = svc.get_config(db_session)["preferences"]
    assert got["farm_cost_order"] == [ids["VT 1026"], ids["Prusa_2"]]
    assert got["monitor_order"] == [f"{ids['VT 1026']}:Front", f"{ids['Prusa_2']}:top"]


def test_load_all_brings_in_the_projects_another_farmhand_keeps(db_session, other_farmhand, share):
    import io

    from app.models import Project
    from app.services import project_files, project_records
    from app.services.project_service import create_project

    from .factories import stl_bytes

    p = create_project(db_session, "Shark")
    project_files.upload(db_session, project_files.STL, p.id, "Fin.stl", io.BytesIO(stl_bytes()))
    project_records.write(db_session, p.id)
    folder = _folder(share)
    svc.set_location(db_session, str(folder))

    out = svc.set_location(other_farmhand, str(folder), "restore")["restored"]
    assert out["brought_in"]["projects"] == [{"name": "Shark", "files": {"doc": 0, "cad": 0, "stl": 1, "threemf": 0, "gcode": 0}, "added": False}]
    assert other_farmhand.query(Project).one().name == "Shark"
    again = svc.restore(other_farmhand)["brought_in"]  # it has them all now: nothing twice
    assert again == {"models": [], "threemfs": [], "projects": []}
