from __future__ import annotations

import os

import pytest

from app import config, storage
from .factories import stl_bytes as _stl


@pytest.fixture()
def nas(api, tmp_path, monkeypatch):
    """A folder of project folders, under the browse root, as on a NAS."""
    monkeypatch.setattr(config.settings, "storage_browse_root", str(tmp_path))
    root = tmp_path / "nas" / "Projects"
    shark = root / "Shark"
    (shark / "Fins").mkdir(parents=True)
    (shark / "Body" / "Left").mkdir(parents=True)
    (shark / "Stand.stl").write_bytes(_stl())
    (shark / "Fins" / "Dorsal fin.stl").write_bytes(_stl())
    (shark / "Body" / "Left" / "Gill.stl").write_bytes(_stl())
    (shark / "Quote.pdf").write_bytes(b"%PDF-1.4 quote")
    (shark / "Shark body.step").write_bytes(b"ISO-10303-21; not really")
    (shark / "Plate.3mf").write_bytes(b"not a real 3mf")
    (shark / "Plate.gcode").write_bytes(b"G28\n")
    (shark / "Loose.bgcode").write_bytes(b"GCDE")
    (shark / ".DS_Store").write_bytes(b"x")
    (shark / "Thumbs.db").write_bytes(b"x")
    (root / "Frog").mkdir()
    (root / "Frog" / "Frog.stl").write_bytes(_stl())
    (root / ".hidden").mkdir()
    return root


def test_a_folder_of_projects_is_scanned(api, nas):
    api.post("/projects", json={"name": "frog"})  # already here, in another case
    r = api.get("/projects/scan", params={"path": str(nas)})
    assert r.status_code == 200
    folders = {f["name"]: f for f in r.json()["folders"]}
    assert list(folders) == ["Frog", "Shark"]  # the hidden folder left out
    assert folders["Shark"]["files"] == {"doc": 1, "cad": 1, "stl": 3, "threemf": 1, "gcode": 2}
    assert folders["Shark"]["total"] == 8 and not folders["Shark"]["in_farmhand"]
    assert folders["Frog"]["in_farmhand"]


def test_a_project_folder_is_imported_with_its_files_sorted(api, nas):
    r = api.post("/projects/import", json={"path": str(nas / "Shark")})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["name"] == "Shark" and out["warnings"] == []
    assert out["files"] == {"doc": 2, "cad": 1, "stl": 3, "threemf": 1, "gcode": 1}
    p = api.get(f"/projects/{out['project_id']}").json()
    stls = {f["name"]: f["component"] for f in p["stl_files"]}
    assert stls == {"Stand ver 1.stl": None, "Dorsal fin ver 1.stl": "Fins", "Gill ver 1.stl": "Body/Left"}
    assert [f["name"] for f in p["cad_files"]] == ["Shark body ver 1.step"]
    assert sorted(f["name"] for f in p["doc_files"]) == ["Loose ver 1.bgcode", "Quote ver 1.pdf"]  # a G-code with no 3MF
    plate = p["threemf_files"][0]
    assert plate["name"] == "Plate ver 1.3mf" and plate["printer_id"] is None  # not a printer here
    assert plate["versions"][0]["gcode_name"] == "Plate.gcode"  # the G-code of the same name went with it
    assert (nas / "Shark" / "Stand.stl").is_file()  # the originals stay where they were

    again = api.post("/projects/import", json={"path": str(nas / "Shark")})
    assert again.status_code == 409 and "already a project called Shark" in again.json()["detail"]


def test_only_folders_under_the_browse_root_and_not_farmhands_own(api, nas, tmp_path):
    outside = tmp_path.parent
    assert api.get("/projects/scan", params={"path": str(outside)}).status_code == 422
    assert api.post("/projects/import", json={"path": str(nas / "Nope")}).status_code == 422
    own = storage.ready_root("project")
    r = api.get("/projects/scan", params={"path": str(own)})
    assert r.status_code == 422 and "Farmhand keeps its own files there" in r.json()["detail"]
    # a folder holding Farmhand's storage can be scanned, but that subfolder is marked, and it can't be imported
    above = storage.local_root().parent
    marked = {f["name"]: f["error"] for f in api.get("/projects/scan", params={"path": str(above)}).json()["folders"]}
    assert marked[storage.local_root().name].startswith("Farmhand keeps its own files there")
    assert api.post("/projects/import", json={"path": str(storage.local_root())}).status_code == 422
    assert api.post("/projects/import", json={"path": str(above)}).status_code == 422  # it holds them


def test_the_check_finds_missing_changed_and_unknown_files(api, nas):
    pid = api.post("/projects/import", json={"path": str(nas / "Shark")}).json()["project_id"]
    assert api.get("/projects/check").json()["problems"] == []
    p = api.get(f"/projects/{pid}").json()
    root = storage.effective_root("project")
    quote = next(d for d in p["doc_files"] if d["name"].startswith("Quote"))
    stand = next(f for f in p["stl_files"] if f["name"].startswith("Stand"))
    os.remove(root / str(pid) / "docs" / str(quote["id"]) / "v1" / "Quote ver 1.pdf")
    (root / str(pid) / "stl" / str(stand["id"]) / "v1" / "Stand ver 1.stl").write_bytes(b"shorter")
    (root / str(pid) / "stray.txt").write_text("left here by hand")

    out = api.get("/projects/check").json()
    found = {(x["filename"], x["problem"].split(":")[0]) for x in out["problems"]}
    assert found == {("Quote ver 1.pdf", "missing"), ("Stand ver 1.stl", "changed outside Farmhand")}
    assert all(x["project"] == "Shark" for x in out["problems"])
    assert out["unknown"] == [os.path.realpath(root / str(pid) / "stray.txt")] and out["error"] is None
    assert out["projects"] == 1 and out["files_checked"] == 7  # its versions (the G-code goes with its 3MF's)
