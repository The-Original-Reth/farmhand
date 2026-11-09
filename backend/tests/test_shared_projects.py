from __future__ import annotations

import io
import os


from app import storage
from app.models import Project, ProjectPart
from app.services import project_files, project_records
from app.services.project_scan import common as scan_common, folder_sync
from app.services.project_files import DOC, STL
from app.services.project_service import create_project, require_project, set_counts
from .factories import stl_bytes as _stl


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

    out = folder_sync.import_projects_folder(other_farmhand)
    assert [p["name"] for p in out["imported"]] == ["Shark"] and out["skipped"] == []
    there = other_farmhand.query(Project).one()
    assert there.folder == shark.folder  # its files used where they are, not copied
    assert there.doc_files[0].versions[0].file_path == shark.doc_files[0].versions[0].file_path
    assert there.doc_files[0].versions[0].note == "From the shop"
    fin = there.stl_files[0]
    assert (fin.component, fin.need, fin.have) == ("Fins", 4, 1)
    assert [(x.name, x.need, x.have) for x in there.parts] == [("M3 screw", 8, 2)]

    again = folder_sync.import_projects_folder(other_farmhand)  # already here: not brought in twice
    assert again == {"imported": [], "skipped": []}


def test_two_farmhands_never_write_over_each_others_files(db_session, other_farmhand):
    shark = _shark(db_session)
    folder_sync.import_projects_folder(other_farmhand)
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
    assert storage.roots._version_dir(tmp_path, 7, 1, fresh=True) == tmp_path / "7" / "v1-2"
    assert storage.roots._version_dir(tmp_path, 7, 1) == taken  # finding a version's folder is unchanged
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


def test_a_folder_dropped_in_is_brought_in_as_it_is(db_session):
    folder = _dragon_egg(storage.ready_root("project"))
    out = folder_sync.import_projects_folder(db_session)
    assert out["imported"][0]["name"] == "Dragon egg"
    assert out["imported"][0]["files"] == {"doc": 1, "cad": 0, "stl": 2, "threemf": 1, "gcode": 1}
    p = db_session.query(Project).one()
    assert p.folder == "Dragon egg"
    assert sorted((f.versions[0].file_path, f.component) for f in p.stl_files) == sorted(
        [(str(folder / "Egg.stl"), None), (str(folder / "Stand" / "Base.stl"), "Stand")]
    )
    assert p.threemf_files[0].versions[0].gcode.file_path == str(folder / "Egg plate.gcode")
    assert (folder / "Notes.pdf").is_file()  # nothing moved or copied


def test_a_folder_named_like_a_project_here_is_left_out(db_session):
    create_project(db_session, "dragon EGG")
    _dragon_egg(storage.ready_root("project"))
    out = folder_sync.import_projects_folder(db_session)
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


def test_another_farmhands_folder_without_its_record_is_left_out(db_session, other_farmhand):
    shark = _shark(db_session)
    folder = storage.effective_root("project") / shark.folder
    for name in os.listdir(folder):
        if project_records.is_record(name):
            os.remove(folder / name)  # as from a Farmhand from before records
    out = folder_sync.import_projects_folder(other_farmhand)
    assert out["imported"] == [] and "Another Farmhand keeps this project" in out["skipped"][0]["reason"]
    assert other_farmhand.query(Project).count() == 0


def test_a_project_brought_in_as_its_number_is_rebuilt_from_the_record(db_session, other_farmhand):

    shark = _shark(db_session)  # its files have previews beside them, as Farmhand keeps them
    folder = storage.effective_root("project") / shark.folder
    record = next(n for n in os.listdir(folder) if project_records.is_record(n))
    os.rename(folder / record, folder.parent / record)  # not written yet when the other Farmhand looked
    # ...so the other brought the numbered folder in as found (as before this was fixed)
    p = create_project(other_farmhand, shark.folder)
    p.folder_row.folder = shark.folder
    files = [f for f in scan_common.files_in(folder) if not project_records.is_record(f.name)]
    folder_sync._as_found(other_farmhand, p, folder, files, [])
    other_farmhand.commit()
    assert other_farmhand.query(Project).one().name == shark.folder

    os.rename(folder.parent / record, folder / record)  # the first Farmhand writes its record
    out = folder_sync.import_projects_folder(other_farmhand)
    assert out["imported"][0]["repaired"] and out["imported"][0]["name"] == "Shark"
    there = other_farmhand.query(Project).one()
    assert there.name == "Shark" and there.folder == shark.folder
    assert [len(there.doc_files), len(there.stl_files)] == [1, 1]  # no previews taken for documents
    assert (there.stl_files[0].component, there.stl_files[0].need) == ("Fins", 4)
    assert there.stl_files[0].versions[0].thumbnail_path  # its picture
    assert [x.name for x in there.parts] == ["M3 screw"]
    assert all(os.path.isfile(v.file_path) for f in there.doc_files + there.stl_files for v in f.versions)
    assert folder_sync.import_projects_folder(other_farmhand)["imported"] == []  # once


def test_load_all_adds_the_files_another_farmhand_added_to_a_project_both_have(db_session, other_farmhand):
    shark = _shark(db_session)
    folder_sync.import_projects_folder(other_farmhand)  # the other Farmhand has the Shark now
    # then files are added to it here: a new file, and a new version of one both have
    project_files.upload(db_session, STL, shark.id, "Tail.stl", io.BytesIO(_stl()))
    fin = require_project(db_session, shark.id).stl_files[0]
    project_files.add_version(db_session, STL, shark.id, fin.id, "Fin.stl", io.BytesIO(_stl()))
    project_records.write(db_session, shark.id)

    # a scan on its own leaves a project it has alone...
    assert folder_sync.import_projects_folder(other_farmhand) == {"imported": [], "skipped": []}
    # ...Load all settings adds what it's missing, once, using the same files
    out = folder_sync.import_projects_folder(other_farmhand, add_missing=True)
    assert [(p["name"], p["files"]["stl"], p["updated"]) for p in out["imported"]] == [("Shark", 2, True)]
    there = other_farmhand.query(Project).one()
    mine = require_project(db_session, shark.id)
    paths = lambda p: sorted(v.file_path for f in p.stl_files for v in f.versions)  # noqa: E731
    assert paths(there) == paths(mine) and len(there.stl_files) == 2
    assert sorted(v.version for f in there.stl_files if f.versions[0].filename.startswith("Fin") for v in f.versions) == [1, 2]
    assert folder_sync.import_projects_folder(other_farmhand, add_missing=True) == {"imported": [], "skipped": []}
