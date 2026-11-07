from __future__ import annotations

import io
import os
import struct
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import storage
from app.database import Base
from app.models import Project, ProjectPart
from app.services import project_files, project_records, project_scan
from app.services.project_files import DOC, STL, THREEMF
from app.services.project_service import create_project, project_folder, require_project, set_counts


def _stl() -> bytes:
    tri = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 10, 0, 0, 0, 10, 0, 0)
    return b"\0" * 80 + struct.pack("<I", 1) + tri


@pytest.fixture()
def other_farmhand():
    """A second Farmhand: its own (empty) database, sharing the same folders."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    yield db
    db.close()


def _shark(db) -> Project:
    p = create_project(db, "Shark")
    project_files.upload(db, DOC, p.id, "Quote.pdf", io.BytesIO(b"%PDF quote"), "From the shop")
    fin = project_files.upload(db, STL, p.id, "Fin.stl", io.BytesIO(_stl()))
    set_counts(db, p.id, "stl", fin.id, need=4, have=1, component="Fins")
    db.add(ProjectPart(project_id=p.id, name="M3 screw", need=8, have=2))
    db.commit()
    project_records.write(db, p.id)
    return require_project(db, p.id)


def test_a_project_comes_back_from_its_record_in_another_farmhand(db_session, other_farmhand):
    shark = _shark(db_session)
    folder = storage.effective_root("project") / shark.folder
    records = [n for n in os.listdir(folder) if project_records.is_record(n)]
    assert records == [f"farmhand-project-{project_records.instance_id(db_session)}.json"]

    out = project_scan.import_projects_folder(other_farmhand)
    assert [p["name"] for p in out["imported"]] == ["Shark"] and out["skipped"] == []
    there = other_farmhand.query(Project).one()
    assert there.folder == shark.folder  # its files used where they are, not copied
    assert there.doc_files[0].versions[0].file_path == shark.doc_files[0].versions[0].file_path
    assert there.doc_files[0].versions[0].note == "From the shop"
    fin = there.stl_files[0]
    assert (fin.component, fin.need, fin.have) == ("Fins", 4, 1)
    assert [(x.name, x.need, x.have) for x in there.parts] == [("M3 screw", 8, 2)]

    again = project_scan.import_projects_folder(other_farmhand)  # already here: not brought in twice
    assert again == {"imported": [], "skipped": []}


def test_two_farmhands_never_write_over_each_others_files(db_session, other_farmhand):
    shark = _shark(db_session)
    project_scan.import_projects_folder(other_farmhand)
    # the other Farmhand's own first project: not the Shark's folder, though both are project 1 to their own
    mine = create_project(other_farmhand, "Dragon")
    assert mine.folder != shark.folder
    # a file added there to the shared Shark lands beside the first Farmhand's, never over it
    there = other_farmhand.query(Project).filter_by(name="Shark").one()
    added = project_files.upload(other_farmhand, DOC, there.id, "Quote.pdf", io.BytesIO(b"%PDF other"))
    original = shark.doc_files[0].versions[0].file_path
    assert open(original, "rb").read() == b"%PDF quote"
    assert added.versions[0].file_path != original and os.path.isfile(added.versions[0].file_path)


def test_a_new_version_never_goes_into_a_folder_with_files_in_it(tmp_path):
    taken = tmp_path / "7" / "v1"
    taken.mkdir(parents=True)
    (taken / "Other farmhand.stl").write_bytes(b"x")
    assert storage._version_dir(tmp_path, 7, 1, fresh=True) == tmp_path / "7" / "v1-2"
    assert storage._version_dir(tmp_path, 7, 1) == taken  # finding a version's folder is unchanged
    assert storage.is_managed_layout(str(tmp_path / "7" / "v1-2" / "a.stl"), 7, 1)


def _dragon_egg(root):
    folder = root / "Dragon egg"
    (folder / "Stand").mkdir(parents=True)
    (folder / "Egg.stl").write_bytes(_stl())
    (folder / "Stand" / "Base.stl").write_bytes(_stl())
    (folder / "Egg plate.3mf").write_bytes(b"not a real 3mf")
    (folder / "Egg plate.gcode").write_bytes(b"G28\n")
    (folder / "Notes.pdf").write_bytes(b"%PDF notes")
    return folder


def _settle(folder):
    old = time.time() - 600
    for here, dirs, files in os.walk(folder):
        for name in [*dirs, *files]:
            os.utime(os.path.join(here, name), (old, old))
    os.utime(folder, (old, old))


def test_a_folder_dropped_in_is_brought_in_as_it_is(db_session):
    folder = _dragon_egg(storage.ready_root("project"))
    out = project_scan.import_projects_folder(db_session)
    assert out["imported"][0]["name"] == "Dragon egg"
    assert out["imported"][0]["files"] == {"doc": 1, "cad": 0, "stl": 2, "threemf": 1, "gcode": 1}
    p = db_session.query(Project).one()
    assert p.folder == "Dragon egg"
    assert sorted((f.versions[0].file_path, f.component) for f in p.stl_files) == sorted(
        [(str(folder / "Egg.stl"), None), (str(folder / "Stand" / "Base.stl"), "Stand")]
    )
    assert p.threemf_files[0].versions[0].gcode.file_path == str(folder / "Egg plate.gcode")
    assert (folder / "Notes.pdf").is_file()  # nothing moved or copied


def test_on_its_own_a_folder_still_being_copied_in_waits(db_session):
    folder = _dragon_egg(storage.ready_root("project"))
    out = project_scan.import_projects_folder(db_session, auto=True)
    assert out["imported"] == [] and "Still being copied in" in out["skipped"][0]["reason"]
    _settle(folder)
    assert project_scan.import_projects_folder(db_session, auto=True)["imported"][0]["name"] == "Dragon egg"


def test_a_folder_named_like_a_project_here_is_left_out(db_session):
    create_project(db_session, "dragon EGG")
    _dragon_egg(storage.ready_root("project"))
    out = project_scan.import_projects_folder(db_session)
    assert out["imported"] == [] and "already a project called" in out["skipped"][0]["reason"]


def test_deleting_a_project_takes_its_record_away(db_session):
    shark = _shark(db_session)
    from app.services.project_service import delete_project

    folder = storage.effective_root("project") / shark.folder
    delete_project(db_session, shark.id)
    assert not folder.exists()  # its files, its record, then its empty folder


def test_scan_projects_folder_over_the_api(api):
    _dragon_egg(storage.ready_root("project"))
    r = api.post("/projects/scan-projects-folder")
    assert r.status_code == 200 and r.json()["imported"][0]["name"] == "Dragon egg"
    assert [p["name"] for p in api.get("/projects").json()] == ["Dragon egg"]
