from __future__ import annotations

import io
import struct

from app import storage


def _stl_bytes(size=10.0) -> bytes:
    """A binary STL of one triangle."""
    tri = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, size, 0, 0, 0, size, 0, 0)
    return b"\0" * 80 + struct.pack("<I", 1) + tri


def _project(api, name="Keychains"):
    return api.post("/projects", json={"name": name}).json()["id"]


def _model(api, name="Frog.stl"):
    return api.post("/source-models", data={"name": name, "file_type": "STL"}).json()["id"]


def _upload(api, pid, in_models, name="Frog.stl", data=None, note=None):
    fields = {"in_models": "true" if in_models else "false"}
    if note:
        fields["note"] = note
    return api.post(f"/projects/{pid}/stl", files={"file": (name, io.BytesIO(data or _stl_bytes()))}, data=fields)


# ------------------------------------------------------------------ models from the Models page


def test_a_model_from_models_is_added_and_taken_out(api):
    pid = _project(api)
    frog, shark = _model(api, "Frog.stl"), _model(api, "Shark.stl")
    assert api.put(f"/projects/{pid}/source-models/{frog}").json()["source_model_ids"] == [frog]
    assert api.put(f"/projects/{pid}/source-models/{shark}").json()["source_model_ids"] == [frog, shark]
    assert api.put(f"/projects/{pid}/source-models/{frog}").json()["source_model_ids"] == [frog, shark]  # once only
    assert api.put(f"/projects/{pid}/source-models/999").status_code == 404

    assert api.delete(f"/projects/{pid}/source-models/{frog}").json()["source_model_ids"] == [shark]
    assert api.get(f"/source-models/{frog}").status_code == 200  # the model itself stays


def test_a_model_used_by_a_project_stays_when_the_project_goes_and_leaves_it_when_deleted(api):
    a, b = _project(api, "A"), _project(api, "B")
    frog = _model(api)
    api.put(f"/projects/{a}/source-models/{frog}").raise_for_status()
    api.put(f"/projects/{b}/source-models/{frog}").raise_for_status()

    api.delete(f"/projects/{a}", params={"confirm": "true"}).raise_for_status()
    assert api.get(f"/source-models/{frog}").status_code == 200

    api.delete(f"/source-models/{frog}", params={"confirm": "true"}).raise_for_status()
    assert api.get(f"/projects/{b}").json()["source_model_ids"] == []


# ------------------------------------------------------------------ uploading on the project's page


def test_an_upload_also_put_in_models_becomes_a_model_the_project_uses(api):
    pid = _project(api)
    r = _upload(api, pid, in_models=True, name="Frog.stl", note="from the designer")
    assert r.status_code == 201
    p = r.json()
    assert p["stl_files"] == [] and len(p["source_model_ids"]) == 1
    model = api.get(f"/source-models/{p['source_model_ids'][0]}").json()
    assert model["name"] == "Frog.stl" and model["file_type"] == "STL"
    assert storage.is_inside(model["versions"][0]["file_path"], storage.effective_root("stl"))  # in the STL folder


def test_an_upload_kept_in_the_project_is_its_own_with_versions_and_a_preview(api):
    pid = _project(api)
    r = _upload(api, pid, in_models=False, name="Bracket.stl", note="first try")
    assert r.status_code == 201
    p = r.json()
    assert p["source_model_ids"] == []
    stl = p["stl_files"][0]
    assert stl["name"] == "Bracket ver 1.stl" and stl["versions"][0]["has_preview"]
    assert api.get("/source-models").json() == []  # not in Models

    r = api.post(f"/projects/{pid}/stl/{stl['id']}/versions", files={"file": ("Bracket ver 1.stl", io.BytesIO(_stl_bytes(20)))})
    assert r.status_code == 201
    assert [v["version"] for v in r.json()["stl_files"][0]["versions"]] == [2, 1]
    root = storage.effective_root("project")
    assert (root / str(pid) / "stl" / str(stl["id"]) / "v2" / "Bracket ver 2.stl").is_file()

    r = api.get(f"/projects/{pid}/stl/{stl['id']}/versions/2/preview")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert api.get(f"/projects/{pid}/stl/{stl['id']}/versions/1/download").content == _stl_bytes()

    r = api.delete(f"/projects/{pid}/stl/{stl['id']}", params={"confirm": "true"})
    assert r.json()["stl_files"] == []
    assert not (root / str(pid) / "stl" / str(stl["id"])).exists()


def test_only_stl_or_obj_files_are_taken_and_the_choice_must_be_made(api):
    pid = _project(api)
    r = _upload(api, pid, in_models=False, name="Bracket.step", data=b"ISO-10303-21;")
    assert r.status_code == 422 and ".stl or .obj" in r.json()["detail"]
    assert _upload(api, pid, in_models=True, name="Bracket.3mf", data=b"PK").status_code == 422
    assert api.get("/source-models").json() == []
    obj = _upload(api, pid, in_models=False, name="Part.obj", data=b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n").json()
    assert obj["stl_files"][0]["name"] == "Part ver 1.obj"
    # in_models has to be said
    r = api.post(f"/projects/{pid}/stl", files={"file": ("Frog.stl", io.BytesIO(_stl_bytes()))})
    assert r.status_code == 422


def test_deleting_a_project_deletes_its_own_stls_but_not_its_models(api):
    pid = _project(api)
    _upload(api, pid, in_models=False)
    _upload(api, pid, in_models=True, name="Shark.stl")
    model_id = api.get(f"/projects/{pid}").json()["source_model_ids"][0]
    folder = storage.effective_root("project") / str(pid)
    assert folder.is_dir()
    api.delete(f"/projects/{pid}", params={"confirm": "true"}).raise_for_status()
    assert not folder.exists()
    assert api.get(f"/source-models/{model_id}").status_code == 200


# ------------------------------------------------------------------ how many: have / need


def test_an_stl_in_a_project_has_how_many_it_needs_and_has(api):
    pid = _project(api)
    frog = _model(api)
    p = api.put(f"/projects/{pid}/source-models/{frog}").json()
    assert p["source_models"] == [{"id": frog, "need": 1, "have": 0}]  # 1 needed, none yet
    p = api.patch(f"/projects/{pid}/source-models/{frog}", json={"need": 24, "have": 6}).json()
    assert p["source_models"] == [{"id": frog, "need": 24, "have": 6}]
    p = api.patch(f"/projects/{pid}/source-models/{frog}", json={"have": 24}).json()
    assert p["source_models"][0] == {"id": frog, "need": 24, "have": 24}  # only what was sent changed

    own = _upload(api, pid, in_models=False).json()["stl_files"][0]
    assert own["need"] == 1 and own["have"] == 0
    p = api.patch(f"/projects/{pid}/stl/{own['id']}", json={"need": 10, "have": 2}).json()
    assert (p["stl_files"][0]["need"], p["stl_files"][0]["have"]) == (10, 2)

    assert api.patch(f"/projects/{pid}/source-models/{frog}", json={"need": 0}).status_code == 422
    assert api.patch(f"/projects/{pid}/stl/{own['id']}", json={"have": -1}).status_code == 422
    assert api.patch(f"/projects/{pid}/source-models/999", json={"need": 2}).status_code == 404
    other = _project(api, "Other")
    assert api.patch(f"/projects/{other}/stl/{own['id']}", json={"need": 2}).status_code == 404
