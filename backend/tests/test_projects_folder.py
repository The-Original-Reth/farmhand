from __future__ import annotations

import io
import os

import pytest

from app import storage


def _stl_folder(tmp_path, marked=True):
    """A chosen STL folder (on the NAS, say), with its marker when it's really there."""
    stl = tmp_path / "nas" / "STL"
    stl.mkdir(parents=True)
    if marked:
        storage.mark_location(stl)
    storage.configure(stl_path=str(stl))
    return stl


def test_with_farmhands_own_stl_folder_projects_stay_in_its_storage(api):
    assert storage.default_root("project") == storage.local_root() / "projects"


def test_projects_go_beside_a_chosen_stl_folder(api, tmp_path):
    stl = _stl_folder(tmp_path)
    assert storage.effective_root("project") == stl.parent / "Projects"
    pid = api.post("/projects", json={"name": "Shark"}).json()["id"]
    doc = api.post(f"/projects/{pid}/doc", files={"file": ("Quote.pdf", io.BytesIO(b"%PDF"))}).json()["doc_files"][0]
    assert (stl.parent / "Projects" / str(pid) / "docs" / str(doc["id"]) / "v1" / "Quote ver 1.pdf").is_file()


def test_a_projects_folder_already_there_is_used_whatever_its_capitals(api, tmp_path):
    (tmp_path / "nas" / "projects").mkdir(parents=True)
    _stl_folder(tmp_path)
    assert os.path.basename(storage.effective_root("project")) == "projects"


def test_nothing_is_written_under_an_unmounted_share(api, tmp_path):
    stl = _stl_folder(tmp_path, marked=False)  # the share is away: only the empty folder is left
    with pytest.raises(storage.StorageUnavailableError):
        storage.ready_root("project")
    assert not (stl.parent / "Projects").exists()


def test_project_files_already_in_farmhands_storage_are_offered_to_move(api, tmp_path):
    pid = api.post("/projects", json={"name": "Shark"}).json()["id"]
    api.post(f"/projects/{pid}/doc", files={"file": ("Quote.pdf", io.BytesIO(b"%PDF"))})
    assert api.get("/settings/storage").json()["outside"]["project"] == 0
    _stl_folder(tmp_path)  # the STL folder chosen on the NAS: projects now belong beside it
    assert api.get("/settings/storage").json()["outside"]["project"] == 1
