from __future__ import annotations

import io
import os
import zipfile

import pytest
from PIL import Image

from app import storage
from app.services import storage_settings_service
from app.thumbnails.cad_preview import render_cad_preview
from .factories import stl_bytes as _stl_bytes


def _project(api, name="Bracket job"):
    return api.post("/projects", json={"name": name}).json()["id"]


def _upload(api, pid, name="Bracket.f3d", data=b"fusion data", note=None, cad_id=None):
    url = f"/projects/{pid}/cad" + (f"/{cad_id}/versions" if cad_id else "")
    return api.post(url, files={"file": (name, io.BytesIO(data))}, data={"note": note} if note else {})


def _png_bytes(size=(64, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


# ------------------------------------------------------------------ uploading and versions


def test_a_cad_file_is_uploaded_versioned_downloaded_and_deleted(api):
    pid = _project(api)
    r = _upload(api, pid, note="First sketch")
    assert r.status_code == 201
    cad = r.json()["cad_files"][0]
    assert cad["name"] == "Bracket ver 1.f3d"
    assert cad["versions"][0]["version"] == 1 and cad["versions"][0]["note"] == "First sketch"
    assert cad["versions"][0]["size_bytes"] == len(b"fusion data")

    r = _upload(api, pid, name="Bracket ver 1.f3d", data=b"fusion data, wider", cad_id=cad["id"])
    cad = r.json()["cad_files"][0]
    assert cad["name"] == "Bracket ver 2.f3d"  # "ver 1" replaced, not added to
    assert [v["version"] for v in cad["versions"]] == [2, 1]  # newest first

    r = api.get(f"/projects/{pid}/cad/{cad['id']}/versions/1/download")
    assert r.status_code == 200 and r.content == b"fusion data"
    assert "Bracket%20ver%201.f3d" in r.headers["content-disposition"]

    kept = api.get(f"/projects/{pid}").json()["cad_files"][0]
    root = storage.effective_root("project")
    assert (root / str(pid) / "cad" / str(cad["id"]) / "v2" / "Bracket ver 2.f3d").is_file()

    assert api.delete(f"/projects/{pid}/cad/{cad['id']}/versions/2").status_code == 409  # no confirm=true
    r = api.delete(f"/projects/{pid}/cad/{cad['id']}/versions/2", params={"confirm": "true"})
    assert [v["version"] for v in r.json()["cad_files"][0]["versions"]] == [1]
    assert not (root / str(pid) / "cad" / str(cad["id"]) / "v2").exists()  # its emptied folder went too

    r = api.delete(f"/projects/{pid}/cad/{cad['id']}/versions/1", params={"confirm": "true"})
    assert r.json()["cad_files"] == []  # the last version takes the CAD file with it
    assert kept["id"] == cad["id"]


def test_deleting_a_project_deletes_its_cad_files_and_its_folder(api):
    pid = _project(api)
    cad_id = _upload(api, pid).json()["cad_files"][0]["id"]
    _upload(api, pid, cad_id=cad_id)
    folder = storage.effective_root("project") / str(pid)
    assert folder.is_dir()
    api.delete(f"/projects/{pid}", params={"confirm": "true"}).raise_for_status()
    assert not folder.exists()


def test_a_cad_file_of_another_project_is_not_found(api):
    a, b = _project(api, "A"), _project(api, "B")
    cad_id = _upload(api, a).json()["cad_files"][0]["id"]
    assert api.get(f"/projects/{b}/cad/{cad_id}/versions/1/download").status_code == 404
    assert _upload(api, b, cad_id=cad_id).status_code == 404
    assert api.delete(f"/projects/{b}/cad/{cad_id}", params={"confirm": "true"}).status_code == 404
    assert _upload(api, 999).status_code == 404


# ------------------------------------------------------------------ previews


def test_an_stl_obj_or_fusion_file_gets_a_preview(api):
    pid = _project(api)
    obj = b"v 0 0 0\nv 10 0 0\nv 0 10 0\nv 0 0 10\nf 1 2 3\nf 1 2 4\nf 1/1 3/1 4/1\n"
    fusion = io.BytesIO()
    with zipfile.ZipFile(fusion, "w") as z:
        z.writestr("FusionAssetName[Active]/Bracket.xml", "<x/>")
        z.writestr("Previews/small.png", _png_bytes())
    for name, data in (("Part.stl", _stl_bytes()), ("Part.obj", obj), ("Bracket.f3d", fusion.getvalue())):
        cad = _upload(api, pid, name=name, data=data).json()["cad_files"][-1]
        assert cad["versions"][0]["has_preview"], name
        r = api.get(f"/projects/{pid}/cad/{cad['id']}/versions/1/preview")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png", name
        assert Image.open(io.BytesIO(r.content)).size == (256, 256)


def test_a_file_with_no_preview_still_uploads(api):
    pid = _project(api)
    cad = _upload(api, pid, name="Housing.SLDPRT", data=b"\xd0\xcf\x11\xe0 solidworks").json()["cad_files"][0]
    assert cad["versions"][0]["has_preview"] is False
    assert api.get(f"/projects/{pid}/cad/{cad['id']}/versions/1/preview").status_code == 404
    # and a broken STEP is just a file without a preview
    cad = _upload(api, pid, name="Broken.step", data=b"not a step file").json()["cad_files"][-1]
    assert cad["versions"][0]["has_preview"] is False


def test_a_step_file_is_drawn(tmp_path):
    gmsh = pytest.importorskip("gmsh", reason="gmsh (and the libraries it loads) isn't installed here")
    path = str(tmp_path / "Block.step")
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.occ.addBox(0, 0, 0, 20, 10, 5)
        gmsh.model.occ.synchronize()
        gmsh.write(path)
    finally:
        gmsh.finalize()
    png = render_cad_preview(path)
    assert png is not None
    img = Image.open(io.BytesIO(png))
    assert img.size == (256, 256) and img.getextrema() != ((255, 255), (255, 255), (255, 255))  # not blank


# ------------------------------------------------------------------ the project files folder


def test_cad_files_go_to_the_chosen_project_files_folder(api, db_session, share):
    chosen = share / "projects"
    chosen.mkdir()
    out = storage_settings_service.save(db_session, {"project_path": str(chosen)})
    assert out["project"]["path"] == str(chosen.resolve()) and not out["project"]["is_default"]

    pid = _project(api)
    cad = _upload(api, pid).json()["cad_files"][0]
    assert (chosen / str(pid) / "cad" / str(cad["id"]) / "v1" / "Bracket ver 1.f3d").is_file()

    os.remove(chosen / storage.MARKER_NAME)  # what an unmounted share looks like
    r = _upload(api, pid, name="Other.step")
    assert r.status_code == 503
    assert len(api.get(f"/projects/{pid}").json()["cad_files"]) == 1  # nothing recorded


def test_the_project_files_folder_must_be_its_own(db_session, share):
    chosen = share / "files"
    (chosen / "inner").mkdir(parents=True)
    with pytest.raises(ValueError, match="The STL and project files locations must be different folders"):
        storage_settings_service.save(db_session, {"stl_path": str(chosen), "project_path": str(chosen / "inner")})
    assert storage.custom_path("project") is None


# ------------------------------------------------------------------ documents: any file, versioned, with notes


def test_a_document_is_uploaded_versioned_and_deleted_with_its_notes(api):
    pid = _project(api)
    r = api.post(f"/projects/{pid}/doc", files={"file": ("Quote.pdf", io.BytesIO(b"%PDF-1.4 quote"))}, data={"note": "From the shop"})
    assert r.status_code == 201
    doc = r.json()["doc_files"][0]
    assert doc["name"] == "Quote ver 1.pdf" and doc["versions"][0]["note"] == "From the shop"
    assert doc["versions"][0]["has_preview"] is False  # a PDF has none
    r = api.post(f"/projects/{pid}/doc/{doc['id']}/versions", files={"file": ("Quote.pdf", io.BytesIO(b"%PDF-1.4 v2"))}, data={"note": "Price agreed"})
    doc = r.json()["doc_files"][0]
    assert doc["name"] == "Quote ver 2.pdf" and [(v["version"], v["note"]) for v in doc["versions"]] == [(2, "Price agreed"), (1, "From the shop")]
    root = storage.effective_root("project")
    assert (root / str(pid) / "docs" / str(doc["id"]) / "v2" / "Quote ver 2.pdf").is_file()
    assert api.get(f"/projects/{pid}/doc/{doc['id']}/versions/1/download").content == b"%PDF-1.4 quote"
    assert r.json()["cad_files"] == []  # a document isn't a CAD file

    pic = api.post(f"/projects/{pid}/doc", files={"file": ("Photo.jpg", io.BytesIO(_png_bytes((300, 120))))}).json()["doc_files"][-1]
    assert pic["versions"][0]["has_preview"]  # a picture is its own preview
    r = api.get(f"/projects/{pid}/doc/{pic['id']}/versions/1/preview")
    assert r.status_code == 200 and Image.open(io.BytesIO(r.content)).size == (256, 256)

    r = api.delete(f"/projects/{pid}/doc/{doc['id']}", params={"confirm": "true"})
    assert [d["name"] for d in r.json()["doc_files"]] == ["Photo ver 1.jpg"]
    api.delete(f"/projects/{pid}", params={"confirm": "true"}).raise_for_status()
    assert not (root / str(pid)).exists()


def test_a_document_opens_in_the_browser_and_cant_run_scripts(api):
    pid = _project(api)
    doc = api.post(f"/projects/{pid}/doc", files={"file": ("Quote.pdf", io.BytesIO(b"%PDF-1.4 quote"))}).json()["doc_files"][0]
    r = api.get(f"/projects/{pid}/doc/{doc['id']}/versions/1/view")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 quote"
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")  # shown, not saved
    assert r.headers["content-security-policy"] == "sandbox" and r.headers["x-content-type-options"] == "nosniff"
    page = api.post(f"/projects/{pid}/doc", files={"file": ("Notes.html", io.BytesIO(b"<script>alert(1)</script>"))}).json()["doc_files"][-1]
    assert api.get(f"/projects/{pid}/doc/{page['id']}/versions/1/view").headers["content-security-policy"] == "sandbox"
    assert api.get(f"/projects/{pid}/doc/{doc['id']}/versions/9/view").status_code == 404


# ------------------------------------------------------------------ arranging


def _doc(api, pid, name):
    return api.post(f"/projects/{pid}/doc", files={"file": (name, io.BytesIO(b"x"))}).json()["doc_files"][-1]["id"]


def test_documents_are_arranged_and_stay_that_way(api):
    pid = _project(api)
    a, b, c = (_doc(api, pid, n) for n in ("A.txt", "B.txt", "C.txt"))
    r = api.put(f"/projects/{pid}/doc/order", json={"ids": [c, a, b]})
    assert r.status_code == 200 and [d["id"] for d in r.json()["doc_files"]] == [c, a, b]
    d = _doc(api, pid, "D.txt")  # a new one goes after those arranged
    assert [x["id"] for x in api.get(f"/projects/{pid}").json()["doc_files"]] == [c, a, b, d]
    api.delete(f"/projects/{pid}/doc/{a}", params={"confirm": "true"})  # its place goes with it
    assert [x["id"] for x in api.get(f"/projects/{pid}").json()["doc_files"]] == [c, b, d]


def test_cad_files_are_arranged_on_their_own(api):
    pid = _project(api)
    x = _upload(api, pid, name="X.f3d").json()["cad_files"][-1]["id"]
    y = _upload(api, pid, name="Y.f3d").json()["cad_files"][-1]["id"]
    doc = _doc(api, pid, "Quote.pdf")
    assert [f["id"] for f in api.put(f"/projects/{pid}/cad/order", json={"ids": [y, x]}).json()["cad_files"]] == [y, x]
    assert [d["id"] for d in api.get(f"/projects/{pid}").json()["doc_files"]] == [doc]  # the documents are left as they were


def test_an_out_of_date_order_is_turned_down(api):
    pid = _project(api)
    a, b = _doc(api, pid, "A.txt"), _doc(api, pid, "B.txt")
    for ids in ([a], [a, b, b], [a, b, 999]):
        r = api.put(f"/projects/{pid}/doc/order", json={"ids": ids})
        assert r.status_code == 422 and "reload the page" in r.json()["detail"]
    assert api.put(f"/projects/999/doc/order", json={"ids": []}).status_code == 404
