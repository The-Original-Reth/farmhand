"""
Scan projects: the project files folder brought in as it is. Every folder in it that isn't one of this Farmhand's own
projects becomes one, its files used where they are (nothing is copied): a folder another Farmhand keeps (sharing the
folders, or from before this computer) comes back from its records; a folder dropped in by hand as found.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import storage
from ...models import Printer, Project, ProjectFolder, ProjectPart, ProjectThreemfGcode, SourceModel
from ...record_files import parse_iso, resolve_from
from ...thumbnails.cad_preview import render_cad_preview
from .. import project_records
from ..app_settings import instance_id
from ..project_files import CAD, DOC, STL, THREEMF
from ..project_service import add_model, create_project, link_printer, project_folder, set_counts
from .common import component, existing_names, files_in, kind_of, no_counts, printer_for, subfolders

KINDS = {"doc": DOC, "cad": CAD, "stl": STL, "threemf": THREEMF}
_KIND_FOLDERS = ("docs", "cad", "stl", "threemf")


def _version_row(kind, f, number: int, path: Path, filename: str, note=None, uploaded_at=None):
    preview = storage.preview_beside(str(path))
    if not os.path.exists(preview):
        png = render_cad_preview(str(path))  # fails soft: no preview is better than no project
        preview = storage.save_preview_beside(str(path), png) if png else None
    return kind.version_cls(
        **{kind.file_fk: f.id}, version=number, filename=filename, file_path=str(path), thumbnail_path=preview,
        size_bytes=os.path.getsize(path), note=note, **({"uploaded_at": uploaded_at} if uploaded_at else {}),
    )


def _whole(value, default: int) -> int:
    return value if type(value) is int and value >= 0 else default


def _add_files(db: Session, project: Project, base: Path, records: list[dict], warnings: list[str]) -> dict:
    """
    The files in the records (every Farmhand's together) that the project doesn't have yet, added: a file in any of
    them comes in once, and a newer version of a file it has is added to that file. Files that aren't there any more
    are left out; nothing it has is changed or removed. Answers how many of each kind were added to.
    """
    counts = no_counts()
    have: dict[str, object] = {}  # every version's file the project has: the project file it belongs to
    for kind in KINDS.values():
        for f in getattr(project, f"{kind.key}_files"):
            for v in f.versions:
                have[str(Path(v.file_path))] = f
    for record in records:
        for entry in record.get("files") or []:
            kind = KINDS.get(entry.get("kind")) if isinstance(entry, dict) else None
            versions = [v for v in (entry.get("versions") or []) if isinstance(v, dict)] if kind else []
            here = [(v, resolve_from(base, v.get("path"))) for v in sorted(versions, key=lambda v: v.get("version") or 0)]
            here = [(v, p) for v, p in here if p and p.is_file()]
            new = [(v, p) for v, p in here if str(p) not in have]
            if not new:
                continue
            f = next((have[str(p)] for _, p in here if str(p) in have), None)
            if f is None:
                f = kind.file_cls(project_id=project.id)
                if kind is THREEMF and entry.get("printer"):
                    printer = db.scalar(select(Printer).where(Printer.name == entry["printer"]))
                    f.printer_id = printer.id if printer else None
                db.add(f)
                db.flush()
                first, is_new = 1, True
            else:
                first, is_new = max((v.version for v in f.versions), default=0) + 1, False
            for n, (v, path) in enumerate(new, start=first):
                row = _version_row(kind, f, n, path, str(v.get("filename") or path.name)[:255], v.get("note"), parse_iso(v.get("uploaded_at")))
                db.add(row)
                have[str(path)] = f
                gcode = v.get("gcode") if kind is THREEMF and isinstance(v.get("gcode"), dict) else None
                gpath = resolve_from(base, gcode.get("path")) if gcode else None
                if gpath and gpath.is_file():
                    db.flush()
                    db.add(ProjectThreemfGcode(version_id=row.id, filename=str(gcode.get("filename") or gpath.name)[:255], file_path=str(gpath)))
                    counts["gcode"] += 1
            db.flush()
            db.refresh(f)  # its versions, as now
            if is_new and kind is STL:
                set_counts(db, project.id, "stl", f.id, need=entry.get("need") or 1, have=entry.get("have") or 0,
                           component=component(entry.get("component"), warnings))
            if kind is THREEMF and f.printer_id:
                link_printer(db, project.id, f.printer_id)
            counts[kind.key] += 1
    return counts


def _from_records(db: Session, project: Project, base: Path, records: list[dict], warnings: list[str]) -> dict:
    """The project's files, parts, models and printers as the records in its folder have them (see _add_files)."""
    counts = _add_files(db, project, base, records, warnings)
    latest = records[0]
    for part in latest.get("parts") or []:
        if isinstance(part, dict) and str(part.get("name") or "").strip():
            db.add(ProjectPart(
                project_id=project.id, name=str(part["name"]).strip()[:200], need=_whole(part.get("need"), 1),
                have=_whole(part.get("have"), 0), link=part.get("link") or None, note=part.get("note") or None,
            ))
    for use in latest.get("models") or []:
        model = db.scalar(select(SourceModel).where(SourceModel.name == use.get("name"))) if isinstance(use, dict) else None
        if model is None:
            if isinstance(use, dict) and use.get("name"):
                warnings.append(f"The model {use['name']} isn't in Models here, so it isn't in the project.")
            continue
        add_model(db, project.id, model.id)
        set_counts(db, project.id, "model", model.id, need=use.get("need") or 1, have=use.get("have") or 0,
                   component=component(use.get("component"), warnings))
    for name in latest.get("printers") or []:
        printer = db.scalar(select(Printer).where(Printer.name == name))
        if printer:
            link_printer(db, project.id, printer.id)
    return counts


def _is_preview(path: Path) -> bool:
    """A preview Farmhand keeps beside a file ("Fin.stl.png" beside "Fin.stl"): part of that file, not one of its own."""
    return path.name.lower().endswith(".png") and path.with_suffix("").is_file()


def _farmhand_layout(folder: Path) -> bool:
    """A project folder in Farmhand's own layout (docs/12/v1/..., stl/3/v2/...): another Farmhand's, not one dropped in."""
    for kind in _KIND_FOLDERS:
        try:
            for owner in os.scandir(folder / kind):
                if owner.is_dir() and owner.name.split("-")[0].isdigit() and any(
                    v.is_dir() and v.name.startswith("v") for v in os.scandir(owner.path)
                ):
                    return True
        except OSError:
            continue
    return False


def _as_found(db: Session, project: Project, folder: Path, files: list[Path], warnings: list[str]) -> dict:
    """A folder dropped in by hand: its files as they are, each by its kind (as copy_in.py brings them in)."""
    counts = no_counts()
    files = [f for f in files if not _is_preview(f)]
    threemfs: dict[tuple[Path, str], int] = {}  # (folder, stem) -> the version id of a 3MF brought in
    for path in [p for p in files if kind_of(p.name) != "gcode"] + [p for p in files if kind_of(p.name) == "gcode"]:
        kind_key = kind_of(path.name)
        try:
            if kind_key == "gcode":
                version_id = threemfs.get((path.parent, Path(path.stem).stem.lower())) or threemfs.get((path.parent, path.stem.lower()))
                if version_id:
                    db.add(ProjectThreemfGcode(version_id=version_id, filename=path.name[:255], file_path=str(path)))
                    counts["gcode"] += 1
                    continue
                kind_key = "doc"  # no 3MF of its name: a document
            kind = KINDS[kind_key]
            f = kind.file_cls(project_id=project.id)
            if kind is THREEMF:
                printer = printer_for(db, path)
                f.printer_id = printer.id if printer else None
            db.add(f)
            db.flush()
            row = _version_row(kind, f, 1, path, path.name[:255])
            db.add(row)
            db.flush()
            if kind is STL and path.parent != folder:
                set_counts(db, project.id, "stl", f.id, component=component(path.parent.relative_to(folder).as_posix(), warnings))
            if kind is THREEMF:
                threemfs[(path.parent, path.stem.lower())] = row.id
                if f.printer_id:
                    link_printer(db, project.id, f.printer_id)
            counts[kind_key] += 1
        except (ValueError, OSError) as e:
            warnings.append(f"{path.relative_to(folder).as_posix()} wasn't brought in: {e}")
    return counts


def _repair(db: Session, project_id: int, folder: Path, others: list[dict], taken: set[str]) -> dict | None:
    """
    A project here that came in before its records did (from another Farmhand's numbered folder, named after it: "1"),
    whose folder now holds that Farmhand's record: rebuilt from it, named as it is there, with its files, versions,
    notes, sub-components, counts and parts. Only this Farmhand's entries for it are replaced: no file is touched.
    """
    project = db.get(Project, project_id)
    if project is None or not others or project.name != folder.name or others[0]["name"] == project.name:
        return None
    for rows in (project.doc_files, project.cad_files, project.stl_files, project.threemf_files, project.parts,
                 project.model_links, project.printer_links):
        for row in list(rows):
            rows.remove(row)  # entries only: delete-orphan removes the rows, never the files they point at
    db.flush()
    warnings: list[str] = []
    name = " ".join(str(others[0]["name"]).split())
    if name.lower() in taken:
        warnings.append(f"There's already a project called {name} here, so this one keeps its name.")
    else:
        taken.discard(project.name.lower())
        project.name = name
        taken.add(name.lower())
    try:
        counts = _from_records(db, project, folder, others, warnings)
        db.commit()
    except (ValueError, OSError) as e:
        db.rollback()
        return {"project_id": project_id, "name": project.name, "files": {}, "warnings": [f"Couldn't be rebuilt: {e}"], "repaired": True}
    project_records.request_write(project.id)
    return {"project_id": project.id, "name": project.name, "files": counts, "warnings": warnings, "repaired": True}


def _add_newer(db: Session, project_id: int, folder: Path, others: list[dict]) -> dict | None:
    """
    A project here whose folder another Farmhand shares: the files that Farmhand added since (in its record, and on the
    NAS) added here too, such as a 3MF uploaded there after this one had the project (Load all settings). Only adds;
    None when there's nothing new. others: the other Farmhands' records in its folder.
    """
    project = db.get(Project, project_id)
    if project is None or not others:
        return None
    warnings: list[str] = []
    try:
        counts = _add_files(db, project, folder, others, warnings)
    except (ValueError, OSError) as e:
        db.rollback()
        return {"project_id": project_id, "name": project.name, "files": {}, "warnings": [f"The files added in another Farmhand couldn't be added: {e}"], "added": True}
    if not any(counts.values()):
        db.rollback()
        return None
    db.commit()
    project_records.request_write(project.id)
    return {"project_id": project.id, "name": project.name, "files": counts, "warnings": warnings, "added": True}


def import_projects_folder(db: Session, add_missing: bool = False) -> dict:
    """
    Scan projects (see the top of this file). One named like a project already here is left out. add_missing (Load
    all settings): a project here already whose folder another Farmhand shares gets the files that Farmhand added
    since, too (added).
    Answers {imported: [{project_id, name, files, warnings, repaired?, added?}], skipped: [{name, reason}]}.
    StorageUnavailableError while the project files folder isn't there.
    """
    root = storage.ready_root("project")
    ours: dict[str, int] = {}
    for pid in db.scalars(select(Project.id)):
        ours[project_folder(db, pid)] = pid  # every project here gets its folder recorded first, so it's never taken
    db.commit()
    me = instance_id(db)
    taken = existing_names(db)
    imported, skipped = [], []
    for entry in subfolders(root):
        folder = Path(entry.path)
        records = [r for r in project_records.read_records(folder) if r.get("instance") != me]  # the other Farmhands'
        if entry.name in ours:
            changed = _repair(db, ours[entry.name], folder, records, taken) or (add_missing and _add_newer(db, ours[entry.name], folder, records))
            if changed:
                imported.append(changed)
            continue
        try:
            files = [f for f in files_in(folder) if not project_records.is_record(f.name)]
        except (ValueError, OSError) as e:
            skipped.append({"name": entry.name, "reason": str(e)})
            continue
        name = " ".join(str(records[0]["name"] if records else entry.name).split())
        if not files and not records:
            continue  # an empty folder: nothing to bring in
        if not records and _farmhand_layout(folder):
            skipped.append({
                "name": entry.name,
                "reason": "Another Farmhand keeps this project. It comes in, with its name and everything, once that "
                "Farmhand has written its record there: update it to this version of Farmhand.",
            })
            continue
        if name.lower() in taken:
            skipped.append({"name": name, "reason": f"There's already a project called {name} here."})
            continue
        warnings: list[str] = []
        project = None
        try:
            project = create_project(db, name)
            if project.folder_row:
                project.folder_row.folder = entry.name  # its files are where they were found
            else:
                project.folder_row = ProjectFolder(project_id=project.id, folder=entry.name)
            db.flush()
            counts = _from_records(db, project, folder, records, warnings) if records else _as_found(db, project, folder, files, warnings)
            db.commit()
        except (ValueError, OSError) as e:
            db.rollback()
            if project is not None and db.get(Project, project.id) is not None:
                db.delete(db.get(Project, project.id))  # not half brought in: tried again next time
                db.commit()
            skipped.append({"name": name, "reason": str(e)})
            continue
        taken.add(name.lower())
        project_records.request_write(project.id)
        imported.append({"project_id": project.id, "name": name, "files": counts, "warnings": warnings})
    return {"imported": imported, "skipped": skipped}
