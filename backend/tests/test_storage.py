from __future__ import annotations

import io
import os

import pytest

from app import config, storage


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """A throwaway /data-like tree: tmp/data/storage is the app's own disk, tmp/data is the browse root."""
    data = tmp_path / "data"
    (data / "storage").mkdir(parents=True)
    monkeypatch.setattr(config.settings, "storage_root", str(data / "storage"))
    monkeypatch.setattr(config.settings, "storage_browse_root", str(data))
    storage.reset()
    yield data
    storage.reset()


def _chosen_folder(data, name="nas/stl"):
    d = data / name
    d.mkdir(parents=True)
    storage.mark_location(d)
    return d


# ---------------------------------------------------------------- where things go


def test_defaults_keep_the_original_layout(isolated_storage):
    data = isolated_storage
    assert storage.source_model_version_dir(1, 2) == data / "storage" / "source_models" / "1" / "v2"
    assert storage.bundle_version_dir(3, 1) == data / "storage" / "bundles" / "3" / "v1"


def test_chosen_locations_are_used_independently(isolated_storage):
    data = isolated_storage
    stl = _chosen_folder(data, "nas/stl")
    storage.configure(stl_path=str(stl))  # only STL moved; 3MF still default
    assert storage.source_model_version_dir(1, 1) == stl / "1" / "v1"
    assert storage.bundle_version_dir(1, 1) == data / "storage" / "bundles" / "1" / "v1"


def test_thumbnails_always_stay_on_local_disk(isolated_storage):
    data = isolated_storage
    storage.configure(stl_path=str(_chosen_folder(data, "nas/stl")), threemf_path=str(_chosen_folder(data, "nas/3mf")))
    local = data / "storage" / "thumbnails"
    assert storage.source_model_thumbnail_dir(1, 1) == local / "source_models" / "1" / "v1"
    assert storage.bundle_thumbnail_dir(2, 3) == local / "bundles" / "2" / "v3"


# ---------------------------------------------------------------- the unmounted-share guard


def test_a_chosen_folder_without_its_marker_is_refused_and_nothing_is_written(isolated_storage):
    nas = isolated_storage / "nas"
    nas.mkdir()  # exists, but it's the bare directory a dropped mount leaves behind: no marker
    storage.configure(threemf_path=str(nas))
    with pytest.raises(storage.StorageUnavailableError, match="marker"):
        storage.bundle_version_dir(1, 1)
    assert list(nas.iterdir()) == []

    storage.mark_location(nas)  # re-selecting it writes the marker again
    assert storage.bundle_version_dir(1, 1) == nas / "1" / "v1"


def test_a_chosen_folder_that_has_disappeared_is_refused(isolated_storage):
    storage.configure(stl_path=str(isolated_storage / "gone"))
    with pytest.raises(storage.StorageUnavailableError, match="isn't available"):
        storage.source_model_version_dir(1, 1)


# ---------------------------------------------------------------- choosing a location


@pytest.fixture()
def share(isolated_storage, monkeypatch):
    """A folder that behaves like a connected NAS share: a mount point under the browse root."""
    nas = isolated_storage / "nas" / "lab"
    nas.mkdir(parents=True)
    real = str(nas.resolve())
    monkeypatch.setattr(storage, "_is_mount", lambda p: os.path.realpath(p) == real)
    return nas


def test_validate_location_accepts_folders_on_a_share_and_in_local_storage(isolated_storage, share):
    sub = share / "stl"
    sub.mkdir()
    assert storage.validate_location(str(sub)) == sub.resolve()
    assert storage.validate_location(str(share)) == share.resolve()  # the share's own top level
    local = isolated_storage / "storage" / "mine"
    local.mkdir()
    assert storage.validate_location(str(local)) == local.resolve()  # Farmhand's own volume persists too


def test_a_folder_that_would_not_survive_a_restart_is_refused(isolated_storage):
    # Not a mount and not in Farmhand's storage: e.g. the empty folder a *disconnected* share
    # is mounted over, which lives in the container's throwaway filesystem.
    disconnected = isolated_storage / "nas" / "lab"
    disconnected.mkdir(parents=True)
    with pytest.raises(ValueError, match="lost when the container restarts"):
        storage.validate_location(str(disconnected))
    with pytest.raises(ValueError, match="lost when the container restarts"):
        storage.validate_location(str(isolated_storage))  # the browse root itself


def test_validate_location_rejects_bad_choices(isolated_storage, tmp_path):
    data = isolated_storage
    (data / "nas").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError, match="full path"):
        storage.validate_location("nas/stl")
    with pytest.raises(ValueError, match="Choose a folder"):
        storage.validate_location("  ")
    with pytest.raises(ValueError, match="isn't under"):
        storage.validate_location(str(outside))
    with pytest.raises(ValueError, match="isn't under"):  # ../ traversal out of the browse root
        storage.validate_location(str(data / "nas" / ".." / ".." / "outside"))
    with pytest.raises(ValueError, match="existing folder"):
        storage.validate_location(str(data / "nas" / "not-created-yet"))


def test_a_symlink_cannot_be_used_to_escape_the_browse_root(isolated_storage, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = isolated_storage / "link"
    os.symlink(outside, link)
    with pytest.raises(ValueError, match="isn't under"):
        storage.validate_location(str(link))


def test_mark_location_is_idempotent(isolated_storage):
    nas = isolated_storage / "nas"
    nas.mkdir()
    storage.mark_location(nas)
    storage.mark_location(nas)
    assert (nas / storage.MARKER_NAME).is_file()


def test_overlaps(isolated_storage):
    a, b = isolated_storage / "a", isolated_storage / "b"
    (a / "inner").mkdir(parents=True)
    b.mkdir()
    assert storage.overlaps(a, a)
    assert storage.overlaps(a, a / "inner") and storage.overlaps(a / "inner", a)
    assert not storage.overlaps(a, b)


def test_location_status(isolated_storage):
    default = storage.location_status("stl")
    assert default["ready"] and default["exists"] and default["writable"]

    nas = isolated_storage / "nas"
    nas.mkdir()
    storage.configure(stl_path=str(nas))
    unmarked = storage.location_status("stl")
    assert unmarked["exists"] and not unmarked["marker_ok"] and not unmarked["ready"]

    storage.mark_location(nas)
    assert storage.location_status("stl")["ready"]

    storage.configure(stl_path=str(isolated_storage / "gone"))
    gone = storage.location_status("stl")
    assert not gone["exists"] and not gone["ready"]


# ---------------------------------------------------------------- the folder picker


def test_list_subdirs(isolated_storage, tmp_path):
    data = isolated_storage
    (data / "nas" / "stl").mkdir(parents=True)
    (data / "nas" / "3mf").mkdir()
    (data / "nas" / ".hidden").mkdir()
    (data / "readme.txt").write_text("not a folder")
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, data / "sneaky")

    top = storage.list_subdirs(None)
    assert top["parent"] is None and top["path"] == top["root"]
    assert [e["name"] for e in top["entries"]] == ["nas", "storage"]  # no files, no symlink out, sorted
    assert all("is_mount" in e for e in top["entries"])

    nas = storage.list_subdirs(str(data / "nas"))
    assert [e["name"] for e in nas["entries"]] == ["3mf", "stl"]  # hidden folder skipped
    assert nas["parent"] == top["path"]


def test_list_subdirs_will_not_look_outside_the_browse_root(isolated_storage, tmp_path):
    with pytest.raises(ValueError, match="isn't under"):
        storage.list_subdirs(str(tmp_path))


# ---------------------------------------------------------------- writing safely


def test_save_upload_strips_any_path_from_the_filename(isolated_storage, tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    saved = storage.save_upload(dest, "../../evil.stl", io.BytesIO(b"data"))
    assert saved == str(dest / "evil.stl")
    assert (dest / "evil.stl").read_bytes() == b"data"
    assert not (tmp_path / "evil.stl").exists()


def test_a_failed_upload_leaves_nothing_behind(isolated_storage, tmp_path):
    class Dropped:
        def read(self, n=-1):
            raise OSError("share dropped mid-write")

    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(OSError):
        storage.save_upload(dest, "a.3mf", Dropped())
    assert list(dest.iterdir()) == []  # no truncated file, no .part file


def test_copy_verified(isolated_storage, tmp_path):
    src = tmp_path / "src.3mf"
    src.write_bytes(b"x" * 1000)
    dest = tmp_path / "dest"
    dest.mkdir()

    new = storage.copy_verified(src, dest)
    assert new == str(dest / "src.3mf") and (dest / "src.3mf").read_bytes() == b"x" * 1000
    assert src.exists()  # a copy, not a move
    assert [p.name for p in dest.iterdir()] == ["src.3mf"]  # no .part leftovers

    renamed = storage.copy_verified(src, dest, name="other.3mf")  # also used for uploads under their own name
    assert renamed == str(dest / "other.3mf")
    storage.copy_verified(src, dest)  # re-running over an existing copy just replaces it


# ---------------------------------------------------------------- deleting safely


def test_delete_files_removes_only_the_recorded_files_and_the_empty_folders_made_for_them(isolated_storage):
    root = isolated_storage / "nas"
    for rel in ("7/v1/a.3mf", "7/v2/b.3mf", "8/v1/c.3mf", "8/v1/keep.txt"):
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")

    storage.delete_files([str(root / "7/v1/a.3mf")])
    assert not (root / "7/v1").exists()  # emptied, so tidied
    assert (root / "7/v2/b.3mf").exists()  # a sibling version is untouched

    storage.delete_files([str(root / "7/v2/b.3mf")])
    assert not (root / "7").exists()  # the id folder went once its last version did
    assert root.exists()  # the root itself is never removed

    storage.delete_files([str(root / "8/v1/c.3mf")])
    assert (root / "8/v1/keep.txt").exists()  # someone else's file in the folder is left alone


def test_delete_files_ignores_missing_files_and_none(isolated_storage):
    storage.delete_files([None, "", str(isolated_storage / "nope" / "1" / "v1" / "gone.stl")])


# ---------------------------------------------------------------- shares, picker and New folder


def test_share_folders_are_reported_as_a_separate_volume(isolated_storage, share):
    storage.configure(stl_path=str(share))
    assert storage.location_status("stl")["separate_volume"]
    storage.configure(stl_path=None)
    assert not storage.location_status("stl")["separate_volume"]  # the default lives on the app's own volume


def test_the_picker_flags_mount_points(isolated_storage, share):
    entries = {e["name"]: e["is_mount"] for e in storage.list_subdirs(str(share.parent))["entries"]}
    assert entries == {"lab": True}
    assert {e["name"]: e["is_mount"] for e in storage.list_subdirs(None)["entries"]} == {"nas": False, "storage": False}


def test_create_folder_on_a_share_and_in_local_storage(isolated_storage, share):
    made = storage.create_folder(str(share), "STL files")
    assert made == share.resolve() / "STL files" and made.is_dir()
    local = storage.create_folder(str(isolated_storage / "storage"), "extra")
    assert local.is_dir()


def test_create_folder_refuses_places_that_would_not_persist(isolated_storage, share):
    for parent in (isolated_storage, isolated_storage / "nas"):  # the browse root, and the folder shares are mounted under
        with pytest.raises(ValueError, match="connected network share"):
            storage.create_folder(str(parent), "oops")
    assert not (isolated_storage / "oops").exists() and not (isolated_storage / "nas" / "oops").exists()


def test_create_folder_validates_the_name(isolated_storage, share):
    for bad in ("", "  ", "../x", "a/b", ".hidden", "x" * 81, "bad:name", "a\\b"):
        with pytest.raises(ValueError, match="Folder names"):
            storage.create_folder(str(share), bad)
    storage.create_folder(str(share), "Parts (v2)+extra")  # the allowed punctuation
    with pytest.raises(ValueError, match="already a folder"):
        storage.create_folder(str(share), "Parts (v2)+extra")


def test_create_folder_cannot_be_pointed_outside_the_browse_root(isolated_storage, share, tmp_path):
    with pytest.raises(ValueError, match="isn't under"):
        storage.create_folder(str(tmp_path), "x")


# ---------------------------------------------------------------- files registered in place (scanned)


def test_managed_layout_is_recognised_exactly(isolated_storage):
    assert storage.is_managed_layout("/data/stl/7/v2/Frog.stl", 7, 2)
    assert not storage.is_managed_layout("/data/stl/7/v2/Frog.stl", 8, 2)  # someone else's id
    assert not storage.is_managed_layout("/data/stl/7/v2/Frog.stl", 7, 3)
    assert not storage.is_managed_layout("/data/stl/Animals/Frog.stl", 7, 1)  # a file found by a scan
    assert not storage.is_managed_layout(None, 7, 1)


def test_deleting_without_pruning_never_removes_the_owners_own_empty_folders(isolated_storage):
    # a person's own folders that happen to be named like ours
    theirs = isolated_storage / "nas" / "2023" / "v2"
    theirs.mkdir(parents=True)
    model = theirs / "Frog.stl"
    model.write_text("x")

    storage.delete_files([str(model)], prune=False)
    assert not model.exists()  # the file itself goes
    assert theirs.is_dir() and theirs.parent.is_dir()  # their folders stay, empty or not

    ours = isolated_storage / "nas" / "5" / "v1"
    ours.mkdir(parents=True)
    (ours / "a.stl").write_text("x")
    storage.delete_files([str(ours / "a.stl")])  # default: tidy the folders we made
    assert not ours.exists() and not ours.parent.exists()


def test_ready_root(isolated_storage):
    assert storage.ready_root("stl") == isolated_storage / "storage" / "source_models"  # default is created on demand
    nas = isolated_storage / "nas"
    nas.mkdir()
    storage.configure(stl_path=str(nas))
    with pytest.raises(storage.StorageUnavailableError, match="marker"):
        storage.ready_root("stl")  # a scan must not report "nothing new" about a share that isn't there
    storage.mark_location(nas)
    assert storage.ready_root("stl") == nas
