"""Backups of a Klipper printer's config folder and Moonraker database, kept in the printer backups folder."""
from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from pathlib import Path

import pytest

from app import storage
from app.models import PrinterConfigBackup
from app.services import app_settings, config_backups as backups, printer_service

from .factories import klipper_printer


@pytest.fixture()
def settings_folder(tmp_path):
    """A printer backups folder chosen in Settings (on the NAS, say)."""
    folder = tmp_path / "printer-backups-chosen"
    folder.mkdir()
    storage.mark_location(folder)
    return folder


def _choose(db, folder) -> None:
    app_settings.put(db, app_settings.PRINTER_BACKUPS_DIR_KEY, str(folder))
    db.commit()


def _farm(moonraker):
    moonraker.config.update({
        "printer.cfg": b"[include macros/*.cfg]\n[printer]\nkinematics: corexy\n",
        "moonraker.conf": b"[server]\nhost: 0.0.0.0\n",
        "macros/start.cfg": b"[gcode_macro START]\ngcode:\n  G28\n",
        "printer-20241101_120000.cfg": b"Klipper's own dated copy",
        "config_backups/old.cfg": b"Moonraker's own backup",
        "timelapse.zip": b"PK...",
    })
    moonraker.db["maintenance"] = {"abc": {"name": "Lube rails"}}
    moonraker.add_job("000001", "frog.gcode", print_s=3600)


def test_a_backup_saves_the_config_folder_and_moonrakers_database_on_the_nas(db_session, moonraker, settings_folder):
    _farm(moonraker)
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)

    b = backups.take_backup(db_session, p)

    paths = sorted(f.path for f in b.files)
    assert paths == [
        "macros/start.cfg", "moonraker-database/history.json", "moonraker-database/maintenance.json", "moonraker.conf", "printer.cfg",
    ]
    assert {s["path"] for s in b.skipped} == {
        "printer-20241101_120000.cfg", "config_backups/old.cfg", "timelapse.zip",
        "moonraker-database/moonraker-sql.db",  # no SSH to the printer set up: the backup goes ahead without it
    }
    assert "Farmhand's SSH key" in next(x["reason"] for x in b.skipped if x["path"].endswith(".db"))
    folder = settings_folder / "VT 1190"
    assert Path(b.folder).parent == folder
    assert (Path(b.folder) / "macros" / "start.cfg").read_bytes().startswith(b"[gcode_macro")
    history = json.loads(backups.view_file(db_session, p, b.id, "moonraker-database/history.json")["text"])
    assert history["count"] == 1 and history["jobs"][0]["filename"] == "frog.gcode" and history["totals"]["total_jobs"] == 1
    # only GETs were sent to the printer
    assert {m for m, _ in moonraker.requests} == {"GET"}


def test_with_no_folder_chosen_they_go_in_backup_in_the_farmhand_folder(db_session, moonraker):
    _farm(moonraker)
    p = klipper_printer(db_session)
    b = backups.take_backup(db_session, p)
    default = storage.effective_root("stl").parent / "backup"
    assert Path(b.folder).parent == default / "VT 1190"
    info = backups.location_info(db_session)
    assert info["is_default"] and info["path"] == str(default) and info["status"]["ready"]


def test_a_settings_folder_whose_share_dropped_is_refused(db_session, moonraker, settings_folder):
    _farm(moonraker)
    _choose(db_session, settings_folder)
    (settings_folder / storage.MARKER_NAME).unlink()
    with pytest.raises(storage.StorageUnavailableError):
        backups.take_backup(db_session, klipper_printer(db_session))


def test_only_the_newest_ten_are_kept_and_the_oldest_files_go(db_session, moonraker, settings_folder):
    _farm(moonraker)
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)
    first = backups.take_backup(db_session, p)
    first_folder = first.folder
    for _ in range(10):
        backups.take_backup(db_session, p)
    rows = db_session.query(PrinterConfigBackup).filter_by(printer_id=p.id).all()
    assert len(rows) == 10 and first.id not in {r.id for r in rows}
    import os
    assert not os.path.exists(first_folder)
    assert len(list((settings_folder / "VT 1190").iterdir())) == 10


def test_the_list_says_what_changed_since_the_backup_before(db_session, moonraker, settings_folder):
    _farm(moonraker)
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)
    older = backups.take_backup(db_session, p)
    moonraker.config["printer.cfg"] += b"[fan]\npin: PA8\n"
    moonraker.config["extras.cfg"] = b"[led]\n"
    del moonraker.config["moonraker.conf"]
    newer = backups.take_backup(db_session, p)

    listed = backups.list_backups(db_session, p)
    assert [b["id"] for b in listed["backups"]] == [newer.id, older.id]
    assert listed["backups"][0]["changes"] == {"added": ["extras.cfg"], "changed": ["printer.cfg"], "removed": ["moonraker.conf"]}
    assert listed["backups"][1]["changes"] is None
    assert listed["every_days"] == 30 and listed["keep"] == 10

    diff = backups.diff_file(db_session, p, newer.id, "printer.cfg")
    assert diff["change"] == "changed" and "+[fan]" in diff["diff"] and diff["previous_id"] == older.id
    detail = backups.backup_detail(db_session, p, newer.id)
    assert {f["path"]: f["change"] for f in detail["files"]}["macros/start.cfg"] == "same"


def test_a_backup_downloads_as_a_zip(db_session, moonraker, settings_folder):
    _farm(moonraker)
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)
    b = backups.take_backup(db_session, p)
    data, name = backups.zip_backup(db_session, p, b.id)
    assert name.startswith("VT 1190-") and name.endswith(".zip")
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert any(n.endswith("/macros/start.cfg") for n in names) and len(names) == b.file_count


def test_a_file_is_put_back_on_the_printer_after_a_safety_backup(db_session, moonraker, settings_folder):
    _farm(moonraker)
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)
    good = backups.take_backup(db_session, p)
    moonraker.config["macros/start.cfg"] = b"broken"

    done = backups.restore_file(db_session, p, good.id, "macros/start.cfg")

    assert moonraker.config["macros/start.cfg"].startswith(b"[gcode_macro START]")
    safety = db_session.get(PrinterConfigBackup, done["safety_backup_id"])
    assert safety.trigger == "before_restore"
    assert backups.view_file(db_session, p, safety.id, "macros/start.cfg")["text"] == "broken"
    assert "Restart Klipper" in done["message"]


def test_nothing_is_put_back_while_printing_or_from_the_database(db_session, moonraker, settings_folder):
    _farm(moonraker)
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)
    b = backups.take_backup(db_session, p)
    with pytest.raises(ValueError, match="database"):
        backups.restore_file(db_session, p, b.id, "moonraker-database/history.json")
    moonraker.print_state = "printing"
    with pytest.raises(ValueError, match="printing"):
        backups.restore_file(db_session, p, b.id, "printer.cfg")
    assert not moonraker.uploads


def test_an_automatic_backup_comes_when_due_and_waits_for_a_print_to_end(db_session, moonraker, settings_folder):
    _farm(moonraker)
    p = klipper_printer(db_session)
    _choose(db_session, settings_folder)
    moonraker.print_state = "printing"
    assert backups.backup_if_due(db_session, p) is None
    moonraker.print_state = "standby"
    first = backups.backup_if_due(db_session, p)
    assert first is not None and first.trigger == "automatic"
    assert backups.backup_if_due(db_session, p) is None  # not due again for 30 days
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=31)
    assert backups.backup_if_due(db_session, p, now=later) is not None

    backups.set_every_days(db_session, 0)
    assert backups.backup_if_due(db_session, p, now=later + dt.timedelta(days=400)) is None
    with pytest.raises(ValueError):
        backups.set_every_days(db_session, 400)


def test_a_prusalink_printer_has_no_backups(db_session, moonraker, settings_folder):
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session, name="Prusa_2", ip="10.0.6.40")
    p = printer_service.update_printer(db_session, p.id, {"connection_type": "prusalink"})
    assert backups.list_backups(db_session, p)["supported"] is False
    with pytest.raises(ValueError, match="PrusaLink"):
        backups.take_backup(db_session, p)
    assert backups.backup_if_due(db_session, p) is None


def test_the_api_backs_up_lists_downloads_and_deletes(klipper, moonraker, share):
    api, pid = klipper
    _farm(moonraker)
    assert api.get("/printers/config-backups/location").json()["is_default"] is True
    folder = share / "backups-here"  # on a connected NAS share, so it can be chosen
    folder.mkdir()
    chosen = api.put("/printers/config-backups/location", json={"path": str(folder)})
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["is_default"] is False and (folder / storage.MARKER_NAME).is_file()
    assert api.put("/printers/config-backups/location", json={"path": "/nowhere/at/all"}).status_code == 422

    made = api.post(f"/printers/{pid}/config-backups")
    assert made.status_code == 201, made.text
    bid = made.json()["id"]
    assert made.json()["backups"][0]["file_count"] == 5

    assert api.get(f"/printers/{pid}/config-backups/{bid}").json()["files"][0]["path"] == "macros/start.cfg"
    assert api.get(f"/printers/{pid}/config-backups/{bid}/file", params={"path": "printer.cfg"}).json()["text"].startswith("[include")
    zipped = api.get(f"/printers/{pid}/config-backups/{bid}/download")
    assert zipped.status_code == 200 and zipped.headers["content-type"] == "application/zip"
    one = api.get(f"/printers/{pid}/config-backups/{bid}/file/download", params={"path": "moonraker.conf"})
    assert one.content == b"[server]\nhost: 0.0.0.0\n"
    assert api.get(f"/printers/{pid}/config-backups/{bid}/file", params={"path": "nope.cfg"}).status_code == 404

    assert api.get(f"/printers/{pid}/config-backups/{bid}/restore-preview").json()["files"]["put_back"] == []
    restored = api.post(f"/printers/{pid}/config-backups/{bid}/restore-all")
    assert restored.status_code == 200 and restored.json()["message"].startswith("Nothing to put back")
    bid = restored.json()["backups"][-1]["id"]  # (the restore took a backup first)

    assert api.put("/printers/config-backups/schedule", json={"every_days": 7}).json() == {"every_days": 7}
    assert api.get(f"/printers/{pid}/config-backups").json()["every_days"] == 7

    assert api.delete(f"/printers/{pid}/config-backups/{bid}").status_code == 409
    for b in api.get(f"/printers/{pid}/config-backups").json()["backups"]:
        assert api.delete(f"/printers/{pid}/config-backups/{b['id']}", params={"confirm": "true"}).status_code == 200
    assert api.get(f"/printers/{pid}/config-backups").json()["backups"] == []
    assert not list(p for p in folder.iterdir() if p.name != storage.MARKER_NAME)
    assert api.put("/printers/config-backups/location", json={"path": None}).json()["is_default"] is True


def test_the_chosen_folder_is_saved_with_the_settings_and_put_back(db_session, tmp_path, share):
    from app.services import config_service

    settings = tmp_path / "farmhand-configs"
    settings.mkdir()
    storage.mark_location(settings)
    app_settings.put(db_session, config_service.KEY_LOCATION, str(settings))
    chosen = share / "backups-here"  # on a connected NAS share
    chosen.mkdir()
    backups.set_location(db_session, str(chosen))
    config_service.mirror(db_session)
    assert json.loads((settings / "farmhand-config.json").read_text())["printer_backups"] == {"path": str(chosen.resolve())}

    backups.set_location(db_session, None)
    out = config_service.restore(db_session)
    assert "printer backups folder" in out["restored"]
    assert backups.location_info(db_session)["path"] == str(chosen.resolve())


def test_restore_puts_back_changed_files_and_moonraker_settings_and_deletes_nothing(db_session, moonraker, settings_folder):
    _farm(moonraker)
    moonraker.config["mainsail.cfg"] = b"[virtual_sdcard]\n"
    moonraker.read_only.add("mainsail.cfg")
    moonraker.db["mainsail"] = {"general": {"printername": "VT 1190"}}
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)
    good = backups.take_backup(db_session, p)

    moonraker.config["printer.cfg"] = b"broken"  # changed since
    del moonraker.config["macros/start.cfg"]  # gone since
    moonraker.config["extras.cfg"] = b"[led]\n"  # added since: stays
    moonraker.db["mainsail"]["general"] = {"printername": "renamed"}
    moonraker.db["maintenance"]["new"] = {"name": "added since"}  # a key added since: stays

    preview = backups.restore_preview(db_session, p, good.id)
    assert preview["files"] == {"put_back": ["macros/start.cfg", "printer.cfg"], "over_ssh": [], "same": 2, "read_only": []}
    assert preview["settings"] == [{"namespace": "mainsail", "keys": ["general"]}]
    assert preview["left_alone"] == ["extras.cfg"]
    assert not moonraker.uploads  # a preview changes nothing

    done = backups.restore_backup(db_session, p, good.id)

    assert done["restored"] == ["macros/start.cfg", "printer.cfg"] and done["settings_written"] == 1 and not done["failed"]
    assert moonraker.config["printer.cfg"].startswith(b"[include") and moonraker.config["macros/start.cfg"].startswith(b"[gcode_macro")
    assert moonraker.config["extras.cfg"] == b"[led]\n"
    assert moonraker.db["mainsail"]["general"] == {"printername": "VT 1190"}
    assert moonraker.db["maintenance"]["new"] == {"name": "added since"}
    assert "Restart Klipper" in done["message"]
    safety = db_session.get(PrinterConfigBackup, done["safety_backup_id"])
    assert safety.trigger == "before_restore" and backups.view_file(db_session, p, safety.id, "printer.cfg")["text"] == "broken"

    again = backups.restore_preview(db_session, p, good.id)
    assert again["files"]["put_back"] == [] and again["settings"] == []


def test_restore_waits_for_a_print_to_finish(db_session, moonraker, settings_folder):
    _farm(moonraker)
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)
    b = backups.take_backup(db_session, p)
    moonraker.print_state = "printing"
    with pytest.raises(ValueError, match="printing"):
        backups.restore_backup(db_session, p, b.id)
    assert not moonraker.uploads


# ------------------------------------------------------------------ over SSH: Moonraker's database file, mainsail.cfg


def test_with_ssh_each_backup_holds_moonrakers_database_file(db_session, moonraker, printer_pi, settings_folder):
    _farm(moonraker)
    printer_pi.accepts_key = True
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)

    b = backups.take_backup(db_session, p)

    row = next(f for f in b.files if f.path == "moonraker-database/moonraker-sql.db")
    copy = Path(b.folder) / "moonraker-database" / "moonraker-sql.db"
    assert copy.read_bytes().startswith(b"SQLite format 3") and row.size == copy.stat().st_size
    assert not [f for f in printer_pi.files if "/backup/database/" in f]  # the copy on the printer was removed
    assert backups.backup_detail(db_session, p, b.id)["files"]
    assert backups.view_file(db_session, p, b.id, "moonraker-database/moonraker-sql.db")["binary"] is True


def test_an_older_moonraker_backs_up_without_its_database_file(db_session, moonraker, printer_pi, settings_folder):
    _farm(moonraker)
    printer_pi.accepts_key = True
    moonraker.can_back_up_database = False
    _choose(db_session, settings_folder)
    b = backups.take_backup(db_session, klipper_printer(db_session))
    assert "too old" in next(x["reason"] for x in b.skipped if x["path"].endswith(".db"))
    assert b.file_count == 5


def test_restore_database_sends_the_copy_and_moonraker_restores_it(db_session, moonraker, printer_pi, settings_folder):
    _farm(moonraker)
    printer_pi.accepts_key = True
    moonraker.db["mainsail"] = {"general": {"printername": "VT 1190"}}
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)
    good = backups.take_backup(db_session, p)
    moonraker.db["mainsail"]["general"] = {"printername": "changed since"}

    done = backups.restore_database(db_session, p, good.id)

    assert moonraker.db["mainsail"]["general"] == {"printername": "VT 1190"}
    assert len(moonraker.restored) == 1 and moonraker.restored[0].startswith("farmhand-restore-")
    assert not [f for f in printer_pi.files if "/backup/database/" in f]  # the sent copy was removed after
    safety = db_session.get(PrinterConfigBackup, done["safety_backup_id"])
    assert any(f.path.endswith("moonraker-sql.db") for f in safety.files)  # how it was, kept first
    assert "restarts itself" in done["message"]

    moonraker.print_state = "printing"
    with pytest.raises(ValueError, match="printing"):
        backups.restore_database(db_session, p, good.id)


def test_restore_database_needs_a_backup_with_its_copy(db_session, moonraker, settings_folder):
    _farm(moonraker)
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)
    b = backups.take_backup(db_session, p)  # no SSH: no database copy
    with pytest.raises(ValueError, match="no copy of Moonraker's database"):
        backups.restore_database(db_session, p, b.id)


def test_a_read_only_mainsail_cfg_is_written_in_place_over_ssh(db_session, moonraker, printer_pi, settings_folder):
    _farm(moonraker)
    moonraker.config["mainsail.cfg"] = b"[virtual_sdcard]\npath: ~/printer_data/gcodes\n"
    moonraker.read_only.add("mainsail.cfg")
    real = "/home/pi/mainsail-config/client.cfg"
    printer_pi.links["/home/pi/printer_data/config/mainsail.cfg"] = real
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)
    good = backups.take_backup(db_session, p)
    moonraker.config["mainsail.cfg"] = b"[virtual_sdcard]\npath: changed by an update\n"

    without_ssh = backups.restore_preview(db_session, p, good.id)
    assert without_ssh["files"]["read_only"] == ["mainsail.cfg"] and without_ssh["files"]["over_ssh"] == []

    printer_pi.accepts_key = True
    preview = backups.restore_preview(db_session, p, good.id)
    assert preview["files"]["over_ssh"] == ["mainsail.cfg"] and preview["files"]["read_only"] == []
    done = backups.restore_backup(db_session, p, good.id)

    assert "mainsail.cfg" in done["restored"] and not done["failed"]
    assert printer_pi.files[real] == b"[virtual_sdcard]\npath: ~/printer_data/gcodes\n"  # where the link points
    assert not [u for u in moonraker.uploads if u["filename"] == "mainsail.cfg"]  # never through Moonraker


def test_ssh_key_and_test_from_the_api(klipper, moonraker, printer_pi):
    api, pid = klipper
    key = api.get("/printers/config-backups/ssh-key").json()["public_key"]
    assert key.startswith("ssh-ed25519 ") and key.endswith("farmhand")
    refused = api.post(f"/printers/{pid}/ssh/test").json()
    assert refused["ok"] is False and refused["kind"] == "no_key"
    assert refused["tested_at"] is None
    assert api.get(f"/printers/{pid}/config-backups").json()["ssh"] is None  # never tested: no "Tested"
    printer_pi.accepts_key = True
    ok = api.post(f"/printers/{pid}/ssh/test").json()
    assert {k: ok[k] for k in ("ok", "user", "host", "error", "kind")} == {"ok": True, "user": "pi", "host": "10.0.6.21", "error": None, "kind": None}
    ssh = api.get(f"/printers/{pid}/config-backups").json()["ssh"]
    assert ssh == {"tested_at": ok["tested_at"], "user": "pi", "host": "10.0.6.21"}  # remembered: shown as "Tested"
    printer_pi.accepts_key = False
    api.post(f"/printers/{pid}/ssh/test")
    assert api.get(f"/printers/{pid}/config-backups").json()["ssh"] is None  # a failed test forgets it


def test_backups_keep_the_ssh_status_current(db_session, moonraker, printer_pi, settings_folder):
    _farm(moonraker)
    _choose(db_session, settings_folder)
    p = klipper_printer(db_session)
    printer_pi.accepts_key = True
    backups.take_backup(db_session, p)
    assert backups.list_backups(db_session, p)["ssh"]["user"] == "pi"  # its database copy logged in: tested
    printer_pi.accepts_key = False  # the key was removed from the Pi since
    backups.take_backup(db_session, p)
    assert backups.list_backups(db_session, p)["ssh"] is None
