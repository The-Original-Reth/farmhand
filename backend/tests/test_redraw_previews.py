from __future__ import annotations

import io
import os

import numpy as np
import pytest

from app import storage
from app.errors import NotFound
from app.models import SourceFileType
from app.services import source_model_service as svc


def _cube_stl_bytes():
    v = np.array([(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)], dtype=np.float32)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = np.array([[v[q[0]], v[q[1]], v[q[2]]] for q in quads] + [[v[q[0]], v[q[2]], v[q[3]]] for q in quads])
    rec = np.zeros(len(tris), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["v"] = tris
    return b"cube".ljust(80, b" ") + np.uint32(len(tris)).tobytes() + rec.tobytes()


def _model(db, name="Cube.stl", data=None, file_type=SourceFileType.stl):
    return svc.create_source_model(
        db, name=name, file_type=file_type, file_obj=io.BytesIO(data if data is not None else _cube_stl_bytes())
    )


def test_redrawing_replaces_an_old_preview_with_a_freshly_drawn_one(db_session):
    model = _model(db_session)
    version = model.versions[0]
    with open(version.thumbnail_path, "wb") as f:
        f.write(b"an old, perforated preview")

    assert svc.regenerate_thumbnail(db_session, model.id, 1) is True

    with open(version.thumbnail_path, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"  # a real image now
    assert storage.is_inside(version.thumbnail_path, storage.thumbnails_root())


def test_a_preview_stored_beside_the_model_file_in_the_old_layout_is_moved_to_local_disk(db_session):
    model = _model(db_session)
    version = model.versions[0]
    old = os.path.join(os.path.dirname(version.file_path), "thumbnail.png")  # where the first versions kept it
    with open(old, "wb") as f:
        f.write(b"old")
    version.thumbnail_path = old
    db_session.commit()

    assert svc.regenerate_thumbnail(db_session, model.id, 1) is True

    db_session.expire_all()
    new = svc.get_source_model_version(db_session, model.id, 1).thumbnail_path
    assert new != old and storage.is_inside(new, storage.thumbnails_root()) and os.path.exists(new)
    assert not os.path.exists(old)  # the stale one is tidied away...
    assert os.path.exists(version.file_path)  # ...and the model file itself is untouched


def test_redrawing_never_replaces_a_preview_with_nothing_when_the_file_is_unreachable(db_session):
    model = _model(db_session)
    thumb = model.versions[0].thumbnail_path
    before = open(thumb, "rb").read()
    os.remove(model.versions[0].file_path)  # e.g. the share it lives on is disconnected

    with pytest.raises(ValueError, match="isn't available right now"):
        svc.regenerate_thumbnail(db_session, model.id, 1)
    assert open(thumb, "rb").read() == before


def test_there_is_nothing_to_redraw_for_non_stl_or_unreadable_files(db_session):
    obj = _model(db_session, "part.obj", data=b"v 0 0 0\n", file_type=SourceFileType.obj)
    assert svc.regenerate_thumbnail(db_session, obj.id, 1) is False  # no OBJ renderer

    junk = _model(db_session, "junk.stl", data=b"not really an stl " * 20)
    assert junk.versions[0].thumbnail_path is None
    assert svc.regenerate_thumbnail(db_session, junk.id, 1) is False  # can't be read: no change, no error


def test_an_unreadable_file_keeps_the_preview_it_already_had(db_session):
    model = _model(db_session)
    thumb = model.versions[0].thumbnail_path
    with open(model.versions[0].file_path, "wb") as f:
        f.write(b"overwritten with junk")
    assert svc.regenerate_thumbnail(db_session, model.id, 1) is False
    assert os.path.exists(thumb)


def test_an_unknown_version_is_a_clear_error(db_session):
    with pytest.raises(NotFound, match="No version"):
        svc.regenerate_thumbnail(db_session, 999, 1)
