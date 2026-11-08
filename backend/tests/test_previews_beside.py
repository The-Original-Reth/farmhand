"""
Every preview is kept next to its file, and only there, so it sits with the file on the NAS: "Frog.stl" has
"Frog.stl.png" and "Goldfish ver 2.3mf" has "Goldfish ver 2.3mf.png". Made with the file, deleted with it, moved with
it, kept where the 3MF was when a 3MF version is pruned, and served from there. The app keeps no copy of its own; the
ones it kept before are moved out to their files.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

from app import storage
from app.models import SourceFileType
from app.services import previews
from app.services import source_model_service as svc

from . import factories as make

from .factories import cube_stl_bytes as _cube_stl_bytes, write_tetrahedron as _write_tetrahedron

PNG = b"\x89PNG\r\n\x1a\n"


def _model(db, name="Cube.stl"):
    return svc.create_source_model(db, name=name, file_type=SourceFileType.stl, file_obj=io.BytesIO(_cube_stl_bytes()))


def _nothing_in_the_app():
    root = storage.thumbnails_root()
    return not root.exists() or not any(p.is_file() for p in root.rglob("*"))


def _as_the_app_kept_it(db, v, kind="source_models", owner_id=None):
    """Give a version a preview in the app's own folder, as Farmhand did before, and none next to its file."""
    own = storage.thumbnails_root() / kind / str(owner_id or v.source_model_id) / f"v{v.version}" / "thumbnail.png"
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_bytes(PNG + b"the app's copy")
    if v.thumbnail_path and os.path.exists(v.thumbnail_path):
        os.remove(v.thumbnail_path)
    v.thumbnail_path = str(own)
    db.commit()
    return own


def test_an_uploaded_stl_gets_its_preview_next_to_it_and_nowhere_else(db_session):
    v = _model(db_session).versions[0]
    beside = Path(v.file_path + ".png")
    assert beside.name == "Cube.stl.png" and beside.parent == Path(v.file_path).parent
    assert v.thumbnail_path == str(beside) and beside.read_bytes().startswith(PNG)
    assert _nothing_in_the_app()


def test_a_file_that_isnt_an_stl_preview_gets_none(db_session):
    m = svc.create_source_model(db_session, name="Part.step", file_type=SourceFileType.step, file_obj=io.BytesIO(b"ISO-10303-21;"))
    assert not os.path.exists(m.versions[0].file_path + ".png") and m.versions[0].thumbnail_path is None


def test_redrawing_redraws_the_one_next_to_the_stl(db_session):
    m = _model(db_session)
    beside = Path(m.versions[0].file_path + ".png")
    beside.write_bytes(b"an old preview")
    assert svc.regenerate_thumbnail(db_session, m.id, 1) is True
    assert beside.read_bytes().startswith(PNG) and _nothing_in_the_app()


def test_deleting_a_version_or_a_model_deletes_the_preview_next_to_it(db_session):
    m = _model(db_session)
    svc.add_source_model_version(db_session, source_model_id=m.id, file_obj=io.BytesIO(_cube_stl_bytes()), filename="Cube.stl")
    v1, v2 = sorted(svc.get_source_model(db_session, m.id).versions, key=lambda v: v.version)
    svc.delete_source_model_version(db_session, m.id, 2)
    assert not os.path.exists(v2.file_path + ".png") and not os.path.exists(Path(v2.file_path).parent)  # folder tidied too
    first = v1.file_path
    svc.delete_source_model(db_session, m.id)
    assert not os.path.exists(first + ".png") and not os.path.exists(first)


def test_a_scanned_in_stl_gets_its_preview_next_to_it_where_it_was_moved(db_session):
    root = storage.ready_root("stl")
    f = _write_tetrahedron(root / "Animals" / "Frog.stl")
    model = svc.import_scanned_file(db_session, str(f))
    v = model.versions[0]
    assert v.thumbnail_path == v.file_path + ".png" and Path(v.thumbnail_path).read_bytes().startswith(PNG)
    assert not os.path.exists(str(f) + ".png")  # nothing left where the file was found
    assert _nothing_in_the_app()


def test_a_preview_that_cant_be_written_next_to_the_stl_doesnt_stop_the_upload(db_session, monkeypatch):
    real = Path.write_bytes

    def refuse(self, data):
        if self.name.endswith(".png.part"):
            raise PermissionError(13, "Permission denied")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", refuse)
    v = _model(db_session).versions[0]
    assert v.thumbnail_path is None  # no preview, and none kept anywhere else instead
    assert not os.path.exists(v.file_path + ".png") and not os.path.exists(v.file_path + ".png.part")
    assert _nothing_in_the_app()


def test_the_preview_is_served_from_next_to_the_stl(api):
    m = api.post("/source-models", data={"name": "Cube.stl", "file_type": "STL"}, files={"file": ("Cube.stl", _cube_stl_bytes())}).json()
    url = f"/source-models/{m['id']}/versions/1/thumbnail"
    assert api.get(url).content.startswith(PNG) and _nothing_in_the_app()
    beside = next(Path(storage.effective_root("stl")).rglob("Cube.stl.png"))
    beside.unlink()  # as if its share were offline: there's no other copy
    assert api.get(url).status_code == 404


# ------------------------------------------------------------------ copies the app kept itself, moved out


def test_the_apps_own_copies_are_moved_next_to_their_files(db_session):
    v = _model(db_session).versions[0]
    own = _as_the_app_kept_it(db_session, v)
    assert previews.move_app_copies_out(db_session) == 1
    db_session.refresh(v)
    assert v.thumbnail_path == v.file_path + ".png" and Path(v.thumbnail_path).read_bytes() == PNG + b"the app's copy"
    assert not own.exists() and not storage.thumbnails_root().exists()  # the app's folder is gone too
    assert previews.move_app_copies_out(db_session) == 0  # nothing more to do


def test_a_preview_already_next_to_the_file_is_kept_and_the_apps_copy_dropped(db_session):
    v = _model(db_session).versions[0]
    beside = Path(v.file_path + ".png")
    picture = beside.read_bytes()
    own = _as_the_app_kept_it(db_session, v)
    beside.write_bytes(picture)  # it was saved next to the file as well
    assert previews.move_app_copies_out(db_session) == 1
    db_session.refresh(v)
    assert v.thumbnail_path == str(beside) and beside.read_bytes() == picture and not own.exists()


def test_a_copy_whose_file_cant_be_reached_waits_for_next_time(db_session):
    v = _model(db_session).versions[0]
    own = _as_the_app_kept_it(db_session, v)
    hidden = v.file_path + ".away"
    os.rename(v.file_path, hidden)  # as if its share were offline
    assert previews.move_app_copies_out(db_session) == 0
    assert own.exists() and v.thumbnail_path == str(own)
    os.rename(hidden, v.file_path)  # the share is back
    assert previews.move_app_copies_out(db_session) == 1 and not own.exists()


# ------------------------------------------------------------------ 3MF files


def _bundle(db, sample_3mf_paths):
    make.printer(db)
    return make.bundle(db, sample_3mf_paths["frog_vt1190"], filename="Goldfish.3mf")


def test_an_uploaded_3mf_gets_its_preview_next_to_it_and_nowhere_else(db_session, sample_3mf_paths):
    v = _bundle(db_session, sample_3mf_paths).versions[0]
    beside = Path(v.threemf_path + ".png")
    assert beside.name == "Goldfish ver 1.3mf.png" and beside.parent == Path(v.threemf_path).parent
    assert v.thumbnail_path == str(beside) and beside.read_bytes().startswith(PNG)
    assert _nothing_in_the_app()


def test_deleting_a_3mf_version_or_the_whole_3mf_deletes_the_preview_next_to_it(db_session, sample_3mf_paths):
    from app.services import bundle_service

    b = _bundle(db_session, sample_3mf_paths)
    v2 = make.add_version(db_session, b, sample_3mf_paths["frog_vt1190"], filename="Goldfish.3mf")
    v2_3mf, v1_3mf = v2.threemf_path, b.versions[-1].threemf_path
    bundle_service.delete_bundle_version(db_session, v2.id)
    assert not os.path.exists(v2_3mf + ".png") and not os.path.exists(Path(v2_3mf).parent)  # folder tidied too
    bundle_service.delete_bundle(db_session, b.id)
    assert not os.path.exists(v1_3mf + ".png") and not os.path.exists(v1_3mf)


def test_a_pruned_version_keeps_its_preview_where_the_3mf_was(db_session, sample_3mf_paths, monkeypatch):
    from app import config
    from app.services import bundle_service

    monkeypatch.setattr(config.settings, "full_file_version_window", 1)
    b = _bundle(db_session, sample_3mf_paths)  # v1: a monument, never pruned
    v2 = make.add_version(db_session, b, sample_3mf_paths["frog_vt1190"], filename="Goldfish.3mf")
    v2_3mf = v2.threemf_path
    make.add_version(db_session, b, sample_3mf_paths["frog_vt1190"], filename="Goldfish.3mf")  # pushes v2 out of the window
    db_session.refresh(v2)
    assert not v2.full_files_retained and not os.path.exists(v2_3mf)
    assert v2.thumbnail_path == v2_3mf + ".png" and os.path.isfile(v2.thumbnail_path)  # the picture survives pruning
    bundle_service.delete_bundle_version(db_session, v2.id)
    assert not os.path.exists(v2_3mf + ".png")  # and goes when the version does


def test_the_apps_own_3mf_copies_are_moved_out_a_pruned_ones_into_the_3mf_folder(db_session, sample_3mf_paths, monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "full_file_version_window", 1)
    b = _bundle(db_session, sample_3mf_paths)
    v2 = make.add_version(db_session, b, sample_3mf_paths["frog_vt1190"], filename="Goldfish.3mf")
    make.add_version(db_session, b, sample_3mf_paths["frog_vt1190"], filename="Goldfish.3mf")  # prunes v2
    v1 = b.versions[-1]
    db_session.refresh(v2)
    _as_the_app_kept_it(db_session, v1, "bundles", b.id)
    _as_the_app_kept_it(db_session, v2, "bundles", b.id)
    assert previews.move_app_copies_out(db_session) == 2
    db_session.refresh(v1)
    db_session.refresh(v2)
    assert v1.thumbnail_path == v1.threemf_path + ".png" and os.path.isfile(v1.thumbnail_path)
    assert v2.thumbnail_path == str(storage.bundle_version_dir(b.id, 2) / f"{v2.filename}.png") and os.path.isfile(v2.thumbnail_path)
    assert _nothing_in_the_app()


def test_a_3mf_preview_is_served_from_next_to_the_3mf(api, sample_3mf_paths):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    mid = api.post("/source-models", data={"name": "Goldfish.stl", "file_type": "STL"}, files={"file": ("Goldfish.stl", b"x" * 64)}).json()["id"]
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        b = api.post("/bundles", data={"source_model_ids": f"[{mid}]", "printer_id": str(pid)}, files={"threemf": ("Goldfish.3mf", f.read())}).json()
    url = f"/bundles/versions/{b['versions'][0]['id']}/thumbnail"
    assert api.get(url).content.startswith(PNG) and _nothing_in_the_app()


# ------------------------------------------------------------------ browsers keeping previews


def test_a_preview_asked_for_by_revision_is_kept_for_good_and_a_redraw_gives_a_new_one(api):
    m = api.post("/source-models", data={"name": "Cube.stl", "file_type": "STL"}, files={"file": ("Cube.stl", _cube_stl_bytes())}).json()
    rev = m["versions"][0]["thumbnail_rev"]
    url = f"/source-models/{m['id']}/versions/1/thumbnail"
    assert rev and "immutable" in api.get(f"{url}?r={rev}").headers["cache-control"]
    assert api.get(url).headers["cache-control"] == "no-cache"  # without one: checked each time, as before
    assert api.post(url).status_code == 200  # redraw it
    assert api.get(f"/source-models/{m['id']}").json()["versions"][0]["thumbnail_rev"] != rev


def test_a_3mf_preview_asked_for_by_revision_is_kept_for_good(api, sample_3mf_paths):
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    mid = api.post("/source-models", data={"name": "Goldfish.stl", "file_type": "STL"}, files={"file": ("Goldfish.stl", b"x" * 64)}).json()["id"]
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        b = api.post("/bundles", data={"source_model_ids": f"[{mid}]", "printer_id": str(pid)}, files={"threemf": ("Goldfish.3mf", f.read())}).json()
    url = f"/bundles/versions/{b['versions'][0]['id']}/thumbnail"
    assert "immutable" in api.get(f"{url}?r=1").headers["cache-control"]
