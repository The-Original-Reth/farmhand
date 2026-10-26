"""
Each STL's preview is kept next to the STL file too ("Frog.stl.png"), so it sits with the model on the NAS: drawn
with it, redrawn with it, deleted with it, and served from there if the app's own copy is gone.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

from app import storage
from app.models import SourceFileType
from app.services import source_model_service as svc

from .test_redraw_previews import _cube_stl_bytes
from .test_scan import _write_tetrahedron

PNG = b"\x89PNG\r\n\x1a\n"


def _model(db, name="Cube.stl"):
    return svc.create_source_model(db, name=name, file_type=SourceFileType.stl, file_obj=io.BytesIO(_cube_stl_bytes()))


def test_an_uploaded_stl_gets_its_preview_next_to_it(db_session):
    v = _model(db_session).versions[0]
    beside = Path(v.file_path + ".png")
    assert beside.name == "Cube.stl.png" and beside.parent == Path(v.file_path).parent
    assert beside.read_bytes() == Path(v.thumbnail_path).read_bytes()  # the same picture as the app's own copy
    assert storage.is_inside(v.thumbnail_path, storage.thumbnails_root())  # which still lives on local disk


def test_a_file_that_isnt_an_stl_preview_gets_none(db_session):
    m = svc.create_source_model(db_session, name="Part.step", file_type=SourceFileType.step, file_obj=io.BytesIO(b"ISO-10303-21;"))
    assert not os.path.exists(m.versions[0].file_path + ".png")


def test_redrawing_redraws_the_one_next_to_the_stl_too(db_session):
    m = _model(db_session)
    beside = Path(m.versions[0].file_path + ".png")
    beside.write_bytes(b"an old preview")
    assert svc.regenerate_thumbnail(db_session, m.id, 1) is True
    assert beside.read_bytes().startswith(PNG)


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
    moved = model.versions[0].file_path
    assert Path(moved + ".png").read_bytes().startswith(PNG)
    assert not os.path.exists(str(f) + ".png")  # nothing left where the file was found


def test_existing_models_get_their_preview_copied_next_to_them_once(db_session):
    v = _model(db_session).versions[0]
    os.remove(v.file_path + ".png")  # as made before previews were kept with their files
    assert svc.save_missing_previews_beside(db_session) == 1
    assert Path(v.file_path + ".png").read_bytes() == Path(v.thumbnail_path).read_bytes()
    assert svc.save_missing_previews_beside(db_session) == 0  # nothing more to do


def test_a_preview_that_cant_be_written_next_to_the_stl_doesnt_stop_the_upload(db_session, monkeypatch):
    real = Path.write_bytes

    def refuse(self, data):
        if self.name.endswith(".png.part"):
            raise PermissionError(13, "Permission denied")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", refuse)
    v = _model(db_session).versions[0]
    assert v.thumbnail_path and os.path.exists(v.thumbnail_path)  # the app's own copy is there, so it still shows
    assert not os.path.exists(v.file_path + ".png") and not os.path.exists(v.file_path + ".png.part")


def test_the_preview_is_served_from_next_to_the_stl_when_the_apps_copy_is_gone(api):
    m = api.post("/source-models", data={"name": "Cube.stl", "file_type": "STL"}, files={"file": ("Cube.stl", _cube_stl_bytes())}).json()
    url = f"/source-models/{m['id']}/versions/1/thumbnail"
    assert api.get(url).content.startswith(PNG)
    for p in Path(storage.thumbnails_root()).rglob("thumbnail.png"):
        p.unlink()  # e.g. the app's disk was rebuilt; the NAS still has its copy
    r = api.get(url)
    assert r.status_code == 200 and r.content.startswith(PNG)
