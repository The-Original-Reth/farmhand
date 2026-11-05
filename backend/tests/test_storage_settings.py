from __future__ import annotations

import io
import os

import pytest

from app import config, storage
from app.models import AppSetting, SourceFileType
from app.services import bundle_service, printer_service, source_model_service
from app.services import storage_settings_service as svc

from . import factories as make


@pytest.fixture()
def share(tmp_path, monkeypatch):
    """A fake *connected* NAS share (a mount point) inside the area the Storage page may browse."""
    area = tmp_path / "data"
    nas = area / "nas" / "lab"
    nas.mkdir(parents=True)
    monkeypatch.setattr(config.settings, "storage_browse_root", str(area))
    real = str(nas.resolve())
    monkeypatch.setattr(storage, "_is_mount", lambda p: os.path.realpath(p) == real)
    return nas


def _folder(share, name):
    d = share / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ choosing locations


def test_choosing_locations_is_saved_marked_and_reported(db_session, share):
    stl, threemf = _folder(share, "stl"), _folder(share, "3mf")

    out = svc.save(db_session, {"stl_path": str(stl), "threemf_path": str(threemf)})

    assert out["stl"]["path"] == str(stl.resolve()) and not out["stl"]["is_default"]
    assert out["threemf"]["path"] == str(threemf.resolve())
    assert out["stl"]["status"]["ready"] and out["threemf"]["status"]["ready"]
    assert (stl / storage.MARKER_NAME).is_file() and (threemf / storage.MARKER_NAME).is_file()
    assert db_session.get(AppSetting, "stl_storage_dir").value == str(stl.resolve())


def test_chosen_locations_survive_a_restart(db_session, share):
    stl = _folder(share, "stl")
    svc.save(db_session, {"stl_path": str(stl)})

    storage.reset()  # what a fresh process looks like before startup runs...
    assert storage.custom_path("stl") is None
    svc.apply_saved_locations(db_session)  # ...and what startup does
    assert storage.custom_path("stl") == str(stl.resolve())


def test_null_resets_a_location_to_its_default(db_session, share):
    svc.save(db_session, {"stl_path": str(_folder(share, "stl"))})
    out = svc.save(db_session, {"stl_path": None})
    assert out["stl"]["is_default"]
    assert db_session.get(AppSetting, "stl_storage_dir") is None


def test_stl_and_3mf_cannot_share_or_nest_folders_and_a_bad_save_changes_nothing(db_session, share):
    a = _folder(share, "a")
    inner = _folder(share, "a/inner")
    with pytest.raises(ValueError, match="must be different"):
        svc.save(db_session, {"stl_path": str(a), "threemf_path": str(a)})
    with pytest.raises(ValueError, match="must be different"):
        svc.save(db_session, {"stl_path": str(a), "threemf_path": str(inner)})
    assert storage.custom_path("stl") is None and storage.custom_path("threemf") is None
    assert db_session.get(AppSetting, "stl_storage_dir") is None
    assert not (a / storage.MARKER_NAME).exists()  # validated before anything was written


def test_choosing_a_disconnected_shares_empty_folder_is_refused(db_session, tmp_path, monkeypatch):
    """The folder a share mounts over is just an empty directory in the container while it's disconnected."""
    area = tmp_path / "data"
    (area / "nas" / "lab").mkdir(parents=True)
    monkeypatch.setattr(config.settings, "storage_browse_root", str(area))
    with pytest.raises(ValueError, match="lost when the container restarts"):
        svc.save(db_session, {"stl_path": str(area / "nas" / "lab")})
    assert db_session.get(AppSetting, "stl_storage_dir") is None


def test_a_folder_outside_the_share_area_is_rejected(db_session, share, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(ValueError, match="isn't under"):
        svc.save(db_session, {"stl_path": str(elsewhere)})


# ------------------------------------------------------------------ new uploads vs existing files


def test_new_files_go_to_the_chosen_location_and_old_ones_stay_where_they_were(db_session, share):
    old = make.model(db_session, "Old.stl", data=b"stl-bytes" * 50)
    old_path = old.versions[0].file_path

    stl = _folder(share, "stl")
    out = svc.save(db_session, {"stl_path": str(stl)})
    assert out["outside"]["stl"] == 1  # the old file is now outside the selected location

    new = make.model(db_session, "New.stl", data=b"stl-bytes" * 50)
    assert storage.is_inside(new.versions[0].file_path, stl)
    assert os.path.exists(old_path)  # untouched, still readable at its recorded path


def test_uploading_to_an_unmounted_chosen_folder_is_refused_and_nothing_is_written(db_session, share, sample_3mf_paths):
    threemf = _folder(share, "3mf")
    svc.save(db_session, {"threemf_path": str(threemf)})
    (threemf / storage.MARKER_NAME).unlink()  # the share dropped: only the empty folder underneath remains

    printer_service.create_printer(db_session, name="VT 1190", kind=None, wired_ip=None, wireless_ip=None)
    model = source_model_service.create_source_model(db_session, name="M.stl", file_type=SourceFileType.stl)
    with open(sample_3mf_paths["shark_vt1190"], "rb") as f:
        with pytest.raises(storage.StorageUnavailableError):
            bundle_service.create_bundle(
                db_session,
                source_model_ids=[model.id],
                threemf_file_obj=f,
                threemf_filename="a.3mf",
                gcode_file_obj=io.BytesIO(b"G28\n"),
                gcode_filename="a.gcode",
            )
    assert list(threemf.iterdir()) == []  # nothing landed in the bare folder


# ------------------------------------------------------------------ moving existing files


def test_migrate_moves_everything_into_the_chosen_locations(db_session, share, sample_3mf_paths):
    model = make.model(db_session, data=b"stl-bytes" * 50)
    make.printer(db_session)
    bundle = make.bundle(db_session, sample_3mf_paths["shark_vt1190"], [make.model(db_session, "B.stl")])
    stl_file = model.versions[0].file_path
    v = bundle.versions[0]
    old_3mf, old_gcode = v.threemf_path, v.gcode_path

    stl, threemf = _folder(share, "stl"), _folder(share, "3mf")
    out = svc.save(db_session, {"stl_path": str(stl), "threemf_path": str(threemf)})
    assert out["outside"] == {"stl": 1, "threemf": 1, "project": 0}

    result = svc.migrate(db_session)
    assert result["moved_stl"] == 1 and result["moved_threemf"] == 1
    assert result["failed"] == [] and result["missing"] == []

    db_session.expire_all()
    new_stl = source_model_service.get_source_model(db_session, model.id).versions[0].file_path
    new_v = bundle_service.get_bundle(db_session, bundle.id).versions[0]
    assert storage.is_inside(new_stl, stl) and os.path.exists(new_stl)
    assert storage.is_inside(new_v.threemf_path, threemf) and os.path.exists(new_v.threemf_path)
    assert storage.is_inside(new_v.gcode_path, threemf) and os.path.exists(new_v.gcode_path)
    assert new_v.thumbnail_path == new_v.threemf_path + ".png" and os.path.exists(new_v.thumbnail_path)  # moved with it
    new_model_v = source_model_service.get_source_model(db_session, model.id).versions[0]
    assert new_model_v.thumbnail_path in (None, new_stl + ".png")  # (this test's model isn't a real STL: no preview)
    assert not any(os.path.exists(p) for p in (stl_file, old_3mf, old_gcode))  # originals removed after the verified copy
    assert svc.describe(db_session)["outside"] == {"stl": 0, "threemf": 0, "project": 0}


def test_migrate_reports_a_file_that_isnt_where_the_database_says_without_failing(db_session, share):
    model = make.model(db_session, data=b"stl-bytes" * 50)
    os.remove(model.versions[0].file_path)  # lost out from under us

    svc.save(db_session, {"stl_path": str(_folder(share, "stl"))})
    result = svc.migrate(db_session)

    assert result["moved_stl"] == 0 and result["failed"] == []
    assert result["missing"] == ["Model.stl v1"]


def test_moving_an_stl_moves_the_preview_next_to_it(db_session, share):
    from .test_redraw_previews import _cube_stl_bytes

    model = make.model(db_session, data=_cube_stl_bytes())
    old = model.versions[0].file_path
    assert os.path.exists(old + ".png")
    stl = _folder(share, "stl")
    svc.save(db_session, {"stl_path": str(stl)})
    assert svc.migrate(db_session)["moved_stl"] == 1

    db_session.expire_all()
    new = source_model_service.get_source_model(db_session, model.id).versions[0].file_path
    assert storage.is_inside(new + ".png", stl) and os.path.exists(new + ".png")  # it moved with its file
    assert not os.path.exists(old + ".png") and not os.path.exists(old)


def test_moving_a_3mf_moves_the_preview_next_to_it(db_session, share, sample_3mf_paths):
    make.printer(db_session)
    bundle = make.bundle(db_session, sample_3mf_paths["shark_vt1190"], [make.model(db_session, "B.stl")])
    old = bundle.versions[0].threemf_path
    assert os.path.exists(old + ".png")
    threemf = _folder(share, "3mf")
    svc.save(db_session, {"threemf_path": str(threemf)})
    assert svc.migrate(db_session)["moved_threemf"] == 1

    db_session.expire_all()
    new = bundle_service.get_bundle(db_session, bundle.id).versions[0].threemf_path
    assert storage.is_inside(new + ".png", threemf) and os.path.exists(new + ".png")  # it moved with its 3MF
    assert not os.path.exists(old + ".png") and not os.path.exists(old)
