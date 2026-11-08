from __future__ import annotations

import errno
import hashlib
import io
import os

import pytest

from app import config, storage
from app.models import SourceFileType, SourceModel, SourceModelVersion
from app.services import source_model_service as svc
from app.services import storage_settings_service as storage_settings

from .conftest import symlink
from .factories import write_tetrahedron as _write_tetrahedron


@pytest.fixture()
def stl_root(db_session):
    """The (default) STL folder — somewhere files can be dropped in from outside Farmhand."""
    return storage.ready_root("stl")


def _paths(scan):
    return {f["name"]: f for f in scan["files"]}


# ------------------------------------------------------------------ scanning


def test_a_scan_finds_new_files_and_ignores_what_is_already_in_the_library(db_session, stl_root):
    svc.create_source_model(db_session, name="Uploaded.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 100))
    _write_tetrahedron(stl_root / "Frog.stl")
    _write_tetrahedron(stl_root / "Animals" / "Shark.stl")
    (stl_root / "notes.txt").write_text("not a model")

    found = _paths(svc.scan_for_new_files(db_session))
    assert set(found) == {"Frog.stl", "Shark.stl"}  # not Uploaded.stl (known), not notes.txt
    assert found["Shark.stl"]["folder"] == "Animals" and found["Frog.stl"]["folder"] == ""
    assert found["Frog.stl"]["file_type"] == "STL" and found["Frog.stl"]["size_bytes"] > 0


def test_a_scan_flags_names_that_already_exist_as_models(db_session, stl_root):
    svc.create_source_model(db_session, name="frog.stl", file_type=SourceFileType.stl)
    _write_tetrahedron(stl_root / "Frog.stl")
    _write_tetrahedron(stl_root / "Shark.stl")
    found = _paths(svc.scan_for_new_files(db_session))
    assert found["Frog.stl"]["name_in_library"] is True  # same name, ignoring case: worth a second look
    assert found["Shark.stl"]["name_in_library"] is False


def test_a_scan_refuses_to_report_on_a_folder_that_looks_unmounted(db_session, tmp_path):
    bare = tmp_path / "share"
    bare.mkdir()  # what a dropped mount leaves behind: no marker
    storage.configure(stl_path=str(bare))
    with pytest.raises(storage.StorageUnavailableError):
        svc.scan_for_new_files(db_session)  # "0 new files" about a share that isn't there would mislead
    with pytest.raises(storage.StorageUnavailableError):
        svc.import_scanned_files(db_session, [str(bare / "x.stl")])


# ------------------------------------------------------------------ importing


def _digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _legacy_registered_in_place(db, path, name="Frog.stl"):
    """How earlier versions of Farmhand imported a scanned file: registered where it sat, nothing moved."""
    model = SourceModel(name=name, file_type=SourceFileType.stl)
    db.add(model)
    db.flush()
    db.add(SourceModelVersion(source_model_id=model.id, version=1, file_path=str(path), note=svc.SCAN_NOTE))
    db.commit()
    return model.id


def test_importing_files_the_model_in_farmhands_own_layout_like_an_upload(db_session, stl_root):
    original = _write_tetrahedron(stl_root / "Animals" / "Frogs" / "Frog hat ü.stl")
    before = _digest(original)

    results = svc.import_scanned_files(db_session, [str(original)])

    assert results[0]["ok"] and results[0]["error"] is None
    model = db_session.get(SourceModel, results[0]["source_model_id"])
    version = model.versions[0]
    expected = stl_root / str(model.id) / "v1" / "Frog hat ü.stl"  # exactly where an upload would have gone
    assert model.name == "Frog hat ü.stl" and model.file_type == SourceFileType.stl
    assert version.file_path == str(expected) and expected.is_file()
    assert _digest(expected) == before  # the very same bytes
    assert not original.exists()  # moved, not copied: one copy only
    assert (stl_root / "Animals" / "Frogs").is_dir()  # ...and the folders it was in are left alone
    assert storage.is_managed_layout(version.file_path, model.id, 1)
    assert version.thumbnail_path == str(expected) + ".png" and os.path.exists(version.thumbnail_path)  # beside it


def test_the_note_remembers_where_the_file_came_from(db_session, stl_root):
    nested = _write_tetrahedron(stl_root / "Animals" / "Frogs" / "A.stl")
    top = _write_tetrahedron(stl_root / "B.stl")
    results = svc.import_scanned_files(db_session, [str(nested), str(top)])
    notes = {db_session.get(SourceModel, r["source_model_id"]).name: db_session.get(SourceModel, r["source_model_id"]).versions[0].note for r in results}
    assert notes["A.stl"] == f"{svc.SCAN_NOTE} — moved here from Animals/Frogs"
    assert notes["B.stl"] == f"{svc.SCAN_NOTE} — moved here from the top level of the STL folder"


def test_two_files_with_the_same_name_in_different_folders_both_move_without_clobbering(db_session, stl_root):
    a = _write_tetrahedron(stl_root / "Set A" / "Frog.stl")
    b = _write_tetrahedron(stl_root / "Set B" / "Frog.stl")
    b.write_bytes(b.read_bytes() + b"")  # same content is fine too: they're separate models
    results = svc.import_scanned_files(db_session, [str(a), str(b)])
    assert all(r["ok"] for r in results) and results[0]["source_model_id"] != results[1]["source_model_id"]
    paths = [db_session.get(SourceModel, r["source_model_id"]).versions[0].file_path for r in results]
    assert len(set(paths)) == 2 and all(os.path.isfile(p) for p in paths) and not a.exists() and not b.exists()


def test_a_file_with_spaces_and_odd_characters_keeps_its_name(db_session, stl_root):
    f = _write_tetrahedron(stl_root / "My models" / "Dragon (v2) - final #3.stl")
    result = svc.import_scanned_files(db_session, [str(f)])[0]
    version = db_session.get(SourceModel, result["source_model_id"]).versions[0]
    assert os.path.basename(version.file_path) == "Dragon (v2) - final #3.stl" and os.path.isfile(version.file_path)


# ---- moving is safe: whatever goes wrong, the file ends up where it was, with no trace of the attempt


def _nothing_left_behind(db_session, stl_root, original, digest):
    assert original.is_file() and _digest(original) == digest  # the file is exactly where it was
    assert db_session.query(SourceModel).count() == 0 and db_session.query(SourceModelVersion).count() == 0
    stray = [p for p in stl_root.rglob("*") if p.is_file() and p != original]
    assert stray == []  # no copy, no .part file
    assert not any(p.is_dir() and p.name.isdigit() for p in stl_root.iterdir())  # no empty {id} folder either
    assert not any(storage.thumbnails_root().rglob("*.png"))  # nor an orphaned preview


def test_a_file_that_cannot_be_moved_stays_put_and_is_not_added(db_session, stl_root, monkeypatch):
    f = _write_tetrahedron(stl_root / "Locked" / "Frog.stl")
    digest = _digest(f)

    def refuse(src, dst):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(storage.os, "rename", refuse)  # e.g. a read-only share, or no right to remove files from that folder
    result = svc.import_scanned_files(db_session, [str(f)])[0]

    assert not result["ok"] and "Couldn't move Frog.stl" in result["error"] and "Permission denied" in result["error"]
    assert "left where it is and not added" in result["error"]
    _nothing_left_behind(db_session, stl_root, f, digest)


def test_across_filesystems_the_move_is_a_verified_copy_then_delete(db_session, stl_root, monkeypatch):
    f = _write_tetrahedron(stl_root / "Other disk" / "Frog.stl")
    digest = _digest(f)

    def different_device(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(storage.os, "rename", different_device)
    result = svc.import_scanned_files(db_session, [str(f)])[0]

    assert result["ok"]
    version = db_session.get(SourceModel, result["source_model_id"]).versions[0]
    assert _digest(version.file_path) == digest and not f.exists()
    assert not list(stl_root.rglob("*.part"))


def test_if_the_original_cannot_be_deleted_after_a_cross_device_copy_nothing_is_left_doubled(db_session, stl_root, monkeypatch):
    f = _write_tetrahedron(stl_root / "Read only" / "Frog.stl")
    digest = _digest(f)
    monkeypatch.setattr(storage.os, "rename", lambda s, d: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    real_unlink = storage.Path.unlink

    def unlink(self, *a, **k):
        if self == f:
            raise PermissionError(errno.EROFS, "Read-only file system")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(storage.Path, "unlink", unlink)
    result = svc.import_scanned_files(db_session, [str(f)])[0]

    assert not result["ok"] and "Read-only file system" in result["error"]
    monkeypatch.undo()
    _nothing_left_behind(db_session, stl_root, f, digest)  # the copy was removed again: no duplicates


def test_if_saving_the_record_fails_after_the_move_the_file_is_put_back(db_session, stl_root, monkeypatch):
    f = _write_tetrahedron(stl_root / "Animals" / "Frog.stl")
    digest = _digest(f)
    real_commit = db_session.commit
    calls = {"n": 0}

    def commit():
        calls["n"] += 1
        raise RuntimeError("database went away")

    monkeypatch.setattr(db_session, "commit", commit)
    with pytest.raises(RuntimeError, match="database went away"):
        svc.import_scanned_file(db_session, str(f))
    monkeypatch.setattr(db_session, "commit", real_commit)
    db_session.rollback()

    assert calls["n"] == 1
    _nothing_left_behind(db_session, stl_root, f, digest)  # moved, then moved back: nothing lost, nothing orphaned


def test_one_file_that_fails_does_not_stop_the_others_in_the_batch(db_session, stl_root, monkeypatch):
    bad = _write_tetrahedron(stl_root / "A" / "Bad.stl")
    good = _write_tetrahedron(stl_root / "B" / "Good.stl")
    real_rename = os.rename

    def picky(src, dst):
        if str(src) == str(bad):
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_rename(src, dst)

    monkeypatch.setattr(storage.os, "rename", picky)
    results = svc.import_scanned_files(db_session, [str(bad), str(good)])
    assert [r["ok"] for r in results] == [False, True]
    assert bad.is_file() and not good.exists()
    assert [m.name for m in svc.list_source_models(db_session)] == ["Good.stl"]


def test_a_path_too_long_to_store_is_refused_before_anything_moves(db_session, stl_root, monkeypatch):
    f = _write_tetrahedron(stl_root / "Frog.stl")
    digest = _digest(f)
    monkeypatch.setattr(svc, "MAX_PATH_LENGTH", 30)  # the real limit (500) can't be reached with a short folder
    result = svc.import_scanned_files(db_session, [str(f)])[0]
    assert not result["ok"] and "too long" in result["error"]
    _nothing_left_behind(db_session, stl_root, f, digest)


def test_a_scan_of_an_unmounted_folder_still_refuses_and_moves_nothing(db_session, tmp_path, monkeypatch):
    area = tmp_path / "data"
    nas = area / "nas" / "lab"
    nas.mkdir(parents=True)
    monkeypatch.setattr(config.settings, "storage_browse_root", str(area))
    monkeypatch.setattr(storage, "_is_mount", lambda p: os.path.realpath(p) == str(nas.resolve()))
    folder = nas / "stl"
    folder.mkdir()
    storage_settings.save(db_session, {"stl_path": str(folder)})
    f = _write_tetrahedron(folder / "Frog.stl")
    (folder / storage.MARKER_NAME).unlink()  # the share dropped: only the bare folder is left
    with pytest.raises(storage.StorageUnavailableError):
        svc.import_scanned_files(db_session, [str(f)])
    assert f.is_file()


def test_a_second_scan_finds_nothing_after_importing(db_session, stl_root):
    f = _write_tetrahedron(stl_root / "Frog.stl")
    svc.import_scanned_files(db_session, [str(f)])
    assert svc.scan_for_new_files(db_session)["files"] == []


def test_obj_and_step_files_import_without_a_preview(db_session, stl_root):
    (stl_root / "a.obj").write_text("v 0 0 0\n")
    (stl_root / "b.STEP").write_text("ISO-10303")
    results = svc.import_scanned_files(db_session, [str(stl_root / "a.obj"), str(stl_root / "b.STEP")])
    assert all(r["ok"] for r in results)
    models = {m.name: m for m in svc.list_source_models(db_session)}
    assert models["a.obj"].file_type == SourceFileType.obj and models["b.STEP"].file_type == SourceFileType.step
    assert models["a.obj"].versions[0].thumbnail_path is None


def test_a_path_from_the_browser_is_never_trusted(db_session, stl_root, tmp_path):
    good = _write_tetrahedron(stl_root / "Good.stl")
    outside = _write_tetrahedron(tmp_path / "elsewhere" / "Outside.stl")
    (stl_root / "readme.txt").write_text("x")
    link = stl_root / "link.stl"
    symlink(good, link)
    known = svc.create_source_model(db_session, name="K.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 50))
    deep = _write_tetrahedron(stl_root.joinpath(*["d" * 100] * 5) / "x.stl")  # a 500+ character path: it's filed under a short one now

    attempts = [
        str(outside),  # outside the STL folder
        str(stl_root / ".." / "escape.stl"),  # traversal
        str(stl_root / "readme.txt"),  # not a model file
        str(stl_root / "missing.stl"),  # gone
        str(link),  # symlinks aren't followed
        known.versions[0].file_path,  # already in the library
        str(good),  # ...and a good one in the same batch
        str(deep),  # a very deep original location is fine: the file is filed under a short path
    ]
    results = svc.import_scanned_files(db_session, attempts)

    assert [r["ok"] for r in results] == [False] * 6 + [True, True]
    assert all(r["error"] for r in results[:6])
    assert "isn't in the STL folder" in results[0]["error"] and "isn't in the STL folder" in results[1]["error"]
    assert "already in the library" in results[5]["error"]
    assert {m.name for m in svc.list_source_models(db_session)} == {"K.stl", "Good.stl", "x.stl"}  # one bad file didn't stop the good ones
    assert outside.is_file() and link.is_symlink()  # the refused files were not touched


def test_importing_the_same_file_twice_adds_it_once(db_session, stl_root):
    f = _write_tetrahedron(stl_root / "Frog.stl")
    first, second = svc.import_scanned_files(db_session, [str(f), str(f)])
    assert first["ok"] and not second["ok"] and "isn't there any more" in second["error"]  # it was moved by the first
    assert db_session.query(SourceModel).count() == 1


# ------------------------------------------------------------------ deleting scanned files


def test_deleting_an_imported_file_tidies_farmhands_folders_but_not_the_ones_it_came_from(db_session, stl_root):
    f = _write_tetrahedron(stl_root / "Animals" / "Frogs" / "Frog.stl")
    model_id = svc.import_scanned_files(db_session, [str(f)])[0]["source_model_id"]
    version = db_session.get(SourceModel, model_id).versions[0]
    filed, thumb = version.file_path, version.thumbnail_path

    svc.delete_source_model(db_session, model_id)

    assert not os.path.exists(filed) and not os.path.exists(thumb)
    assert not (stl_root / str(model_id)).exists()  # the layout Farmhand made is tidied away, like an upload's
    assert (stl_root / "Animals" / "Frogs").is_dir()  # the person's own folders are never removed


def test_files_registered_in_place_by_earlier_versions_still_protect_their_owners_folders(db_session, stl_root):
    # folders that happen to be named like Farmhand's own "{id}/v{n}" layout
    f = _write_tetrahedron(stl_root / "2023" / "v1" / "Frog.stl")
    model_id = _legacy_registered_in_place(db_session, f)
    svc.delete_source_model_version(db_session, model_id, 1)
    assert not f.exists()
    assert (stl_root / "2023" / "v1").is_dir()  # the person's (now empty) folders are not tidied away


def test_deleting_a_whole_legacy_model_also_leaves_the_owners_folders(db_session, stl_root):
    f = _write_tetrahedron(stl_root / "7" / "v1" / "Frog.stl")
    model_id = _legacy_registered_in_place(db_session, f)
    svc.delete_source_model(db_session, model_id)
    assert not f.exists() and (stl_root / "7" / "v1").is_dir()


def test_files_uploaded_through_farmhand_still_tidy_their_own_folders(db_session, stl_root):
    model = svc.create_source_model(db_session, name="Up.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 100))
    folder = stl_root / str(model.id)
    assert folder.is_dir()
    svc.delete_source_model(db_session, model.id)
    assert not folder.exists()  # the layout Farmhand made is cleaned up, as before


# ------------------------------------------------------------------ moving locations later


def test_moving_to_a_new_location_brings_files_registered_in_place_into_the_managed_layout(db_session, stl_root, tmp_path, monkeypatch):
    area = tmp_path / "data"
    nas = area / "nas" / "lab"
    nas.mkdir(parents=True)
    monkeypatch.setattr(config.settings, "storage_browse_root", str(area))
    monkeypatch.setattr(storage, "_is_mount", lambda p: os.path.realpath(p) == str(nas.resolve()))

    f = _write_tetrahedron(stl_root / "2023" / "v1" / "Frog.stl")
    model_id = _legacy_registered_in_place(db_session, f)  # imported in place by an earlier version

    target = nas / "stl"
    target.mkdir()
    storage_settings.save(db_session, {"stl_path": str(target)})
    result = storage_settings.migrate(db_session)

    assert result["moved_stl"] == 1 and result["failed"] == []
    db_session.expire_all()
    new_path = db_session.get(SourceModel, model_id).versions[0].file_path
    assert new_path == str(target.resolve() / str(model_id) / "v1" / "Frog.stl") and os.path.exists(new_path)
    assert not f.exists() and (stl_root / "2023" / "v1").is_dir()  # original gone; the owner's folders left in place
