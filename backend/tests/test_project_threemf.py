from __future__ import annotations

import io
import zipfile

from PIL import Image

from app import storage
from app.services import bundle_service, printer_service, project_service

from . import factories as make


def _project(api, name="Frogs"):
    return api.post("/projects", json={"name": name}).json()["id"]


def _printer(api, name="VT 1190"):
    return api.post("/printers", json={"name": name}).json()["id"]


def _threemf_bytes() -> bytes:
    """A 3MF-shaped ZIP carrying its own thumbnail, as a slicer writes it."""
    pic = io.BytesIO()
    Image.new("RGB", (120, 90), (30, 140, 160)).save(pic, format="PNG")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("3D/3dmodel.model", "<model/>")
        z.writestr("Metadata/thumbnail.png", pic.getvalue())
    return out.getvalue()


def _upload(api, pid, name="Frog plate.3mf", printer_id=None, data=None):
    fields = {"printer_id": str(printer_id)} if printer_id is not None else {}
    return api.post(f"/projects/{pid}/threemf", files={"file": (name, io.BytesIO(data or _threemf_bytes()))}, data=fields)


# ------------------------------------------------------------------ 3MFs from the rest of Farmhand


def test_a_3mf_used_by_a_project_brings_its_printer_and_leaves_it(db_session, sample_3mf_paths):
    printer = make.printer(db_session)
    bundle = make.bundle(db_session, sample_3mf_paths["frog_vt1190"], printer_id=printer.id)
    project = project_service.create_project(db_session, "Frogs")

    out = project_service.out(project_service.add_bundle(db_session, project.id, bundle.id))
    assert out["bundle_ids"] == [bundle.id] and out["printer_ids"] == [printer.id]  # its printer came with it
    out = project_service.out(project_service.add_bundle(db_session, project.id, bundle.id))
    assert out["bundle_ids"] == [bundle.id] and out["printer_ids"] == [printer.id]  # once each

    out = project_service.out(project_service.remove_bundle(db_session, project.id, bundle.id))
    assert out["bundle_ids"] == [] and out["printer_ids"] == [printer.id]  # the printer stays

    project_service.add_bundle(db_session, project.id, bundle.id)
    bundle_service.delete_bundle(db_session, bundle.id)
    out = project_service.out(project_service.require_project(db_session, project.id))
    assert out["bundle_ids"] == [] and out["printer_ids"] == [printer.id]  # deleting the 3MF took it out


def test_a_missing_3mf_or_printer_is_not_found(api):
    pid = _project(api)
    assert api.put(f"/projects/{pid}/bundles/999").status_code == 404
    assert api.put(f"/projects/{pid}/printers/999").status_code == 404
    assert _upload(api, pid, printer_id=999).status_code == 404


def test_a_printer_is_added_by_hand_and_taken_out(api):
    pid = _project(api)
    a, b = _printer(api, "VT 1190"), _printer(api, "V2 BOG")
    assert api.put(f"/projects/{pid}/printers/{a}").json()["printer_ids"] == [a]
    assert api.put(f"/projects/{pid}/printers/{b}").json()["printer_ids"] == [a, b]
    assert api.delete(f"/projects/{pid}/printers/{a}").json()["printer_ids"] == [b]
    assert api.get("/printers").status_code == 200 and len(api.get("/printers").json()) == 2  # nothing deleted


def test_deleting_a_printer_takes_it_out_of_projects(db_session):
    printer = make.printer(db_session)
    project = project_service.create_project(db_session, "Frogs")
    project_service.add_printer(db_session, project.id, printer.id)
    printer.decommissioned = True
    db_session.commit()
    printer_service.delete_printer(db_session, printer.id)
    assert project_service.out(project_service.require_project(db_session, project.id))["printer_ids"] == []


# ------------------------------------------------------------------ 3MFs uploaded to the project only


def test_a_3mf_kept_in_the_project_has_its_printer_versions_and_a_preview(api):
    pid = _project(api)
    printer = _printer(api)
    r = _upload(api, pid, printer_id=printer)
    assert r.status_code == 201
    p = r.json()
    f = p["threemf_files"][0]
    assert f["name"] == "Frog plate ver 1.3mf" and f["printer_id"] == printer
    assert p["printer_ids"] == [printer]  # its printer came into the project
    assert p["bundle_ids"] == [] and api.get("/bundles").json() == []  # not in Models or Printers
    assert f["versions"][0]["has_preview"]  # the picture inside the 3MF
    r = api.get(f"/projects/{pid}/threemf/{f['id']}/versions/1/preview")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"

    r = api.post(f"/projects/{pid}/threemf/{f['id']}/versions", files={"file": ("Frog plate ver 1.3mf", io.BytesIO(_threemf_bytes()))})
    assert [v["version"] for v in r.json()["threemf_files"][0]["versions"]] == [2, 1]
    root = storage.effective_root("project")
    assert (root / str(pid) / "threemf" / str(f["id"]) / "v2" / "Frog plate ver 2.3mf").is_file()

    api.delete(f"/projects/{pid}", params={"confirm": "true"}).raise_for_status()
    assert not (root / str(pid)).exists()
    assert len(api.get("/printers").json()) == 1  # the printer stays


def test_a_project_3mf_can_go_without_a_printer_and_must_be_a_3mf(api):
    pid = _project(api)
    r = _upload(api, pid)
    assert r.status_code == 201 and r.json()["threemf_files"][0]["printer_id"] is None and r.json()["printer_ids"] == []
    r = _upload(api, pid, name="Frog.stl", data=b"solid x")
    assert r.status_code == 422 and ".3mf" in r.json()["detail"]
