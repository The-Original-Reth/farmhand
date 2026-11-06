"""
Projects: a piece of work for the farm. A project has a name; its own documents, CAD files, STLs and 3MFs
(project_files.py); and
models, 3MFs and printers from the rest of Farmhand it uses, only pointed at. A 3MF it uses brings the printer it's for.
And its parts list (project_parts.py).
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import storage
from ..errors import NotFound
from ..models import (
    Bundle, Printer, Project, ProjectBundle, ProjectCadFile, ProjectDocFile, ProjectModelComponent, ProjectPrinter,
    ProjectSourceModel, ProjectStlFile, ProjectStlFileComponent, ProjectThreemfFile, ProjectThreemfVersion, SourceFileType,
    SourceModel,
)

MAX_NAME_LENGTH = 200
MAX_COMPONENT_LENGTH = 200
KEEP = object()  # set_counts: leave the sub-component as it is

_LOAD = (
    selectinload(Project.doc_files).selectinload(ProjectDocFile.versions),
    selectinload(Project.cad_files).selectinload(ProjectCadFile.versions),
    selectinload(Project.stl_files).selectinload(ProjectStlFile.versions),
    selectinload(Project.stl_files).selectinload(ProjectStlFile.component_row),
    selectinload(Project.threemf_files).selectinload(ProjectThreemfFile.versions).selectinload(ProjectThreemfVersion.gcode),
    selectinload(Project.model_links).selectinload(ProjectSourceModel.component_row),
    selectinload(Project.bundle_links),
    selectinload(Project.printer_links),
    selectinload(Project.parts),
)


def _files_out(files) -> list[dict]:
    """A project's own files (CAD, STL or 3MF) as the API answers them: each named after its newest version (a 3MF
    also says which printer it's for)."""
    return [
        {
            "id": f.id,
            **({"printer_id": f.printer_id} if isinstance(f, ProjectThreemfFile) else {}),
            **({"need": f.need, "have": f.have, "component": f.component} if isinstance(f, ProjectStlFile) else {}),
            "name": f.versions[0].filename if f.versions else "",
            "created_at": f.created_at,
            "versions": [
                {
                    "version": v.version, "filename": v.filename, "size_bytes": v.size_bytes, "note": v.note,
                    "uploaded_at": v.uploaded_at, "has_preview": bool(v.thumbnail_path),
                    **({"gcode_name": v.gcode.filename if v.gcode else None} if hasattr(v, "gcode") else {}),
                }
                for v in f.versions
            ],
        }
        for f in files
    ]


def out(project: Project) -> dict:
    """A project as the API answers it: its own CAD files, STLs and 3MFs with their versions (newest first), and the
    ids of the models, 3MFs and printers from the rest of Farmhand it uses (in the order they were added)."""
    return {
        "id": project.id,
        "name": project.name,
        "created_at": project.created_at,
        "doc_files": _files_out(project.doc_files),
        "cad_files": _files_out(project.cad_files),
        "stl_files": _files_out(project.stl_files),
        "threemf_files": _files_out(project.threemf_files),
        "source_model_ids": [link.source_model_id for link in project.model_links],
        "source_models": [
            {"id": link.source_model_id, "need": link.need, "have": link.have, "component": link.component}
            for link in project.model_links
        ],
        "bundle_ids": [link.bundle_id for link in project.bundle_links],
        "printer_ids": [link.printer_id for link in project.printer_links],
        "parts": [
            {"id": p.id, "name": p.name, "need": p.need, "have": p.have, "link": p.link, "note": p.note}
            for p in project.parts
        ],
    }


def list_projects(db: Session) -> list[Project]:
    return list(db.scalars(select(Project).options(*_LOAD).order_by(func.lower(Project.name))))


def require_project(db: Session, project_id: int) -> Project:
    db.expire_all()  # files and links just added or removed are read fresh
    project = db.scalar(select(Project).options(*_LOAD).where(Project.id == project_id))
    if project is None:
        raise NotFound("Project not found")
    return project


def _clean_name(db: Session, name: str, except_id: int | None = None) -> str:
    """Spaces tidied; never empty, too long, or another project's name (in any case)."""
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("A project needs a name.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"A project's name can be at most {MAX_NAME_LENGTH} characters.")
    clash = db.scalar(select(Project).where(func.lower(Project.name) == name.lower(), Project.id != (except_id or 0)))
    if clash is not None:
        raise ValueError(f"There's already a project called {clash.name}.")
    return name


def create_project(db: Session, name: str) -> Project:
    project = Project(name=_clean_name(db, name))
    db.add(project)
    db.commit()
    return require_project(db, project.id)


def rename_project(db: Session, project_id: int, name: str) -> Project:
    project = require_project(db, project_id)
    project.name = _clean_name(db, name, except_id=project.id)
    db.commit()
    return require_project(db, project_id)


def delete_project(db: Session, project_id: int) -> None:
    """Delete the project and its own files (rows first, then files, then its folder if that's left empty). The models,
    3MFs and printers it used stay where they are."""
    from .project_files import files_of_project  # (it imports this module)

    project = require_project(db, project_id)
    paths = files_of_project(db, project_id)
    db.delete(project)
    db.commit()
    storage.delete_files(paths)
    storage.tidy_project_folder(project_id)


# ---- models from the Models page ----


def add_model(db: Session, project_id: int, source_model_id: int) -> Project:
    """Use a model from Models in the project (already in it: nothing changes)."""
    require_project(db, project_id)
    if db.get(SourceModel, source_model_id) is None:
        raise NotFound("Source model not found")
    if db.get(ProjectSourceModel, (project_id, source_model_id)) is None:
        db.add(ProjectSourceModel(project_id=project_id, source_model_id=source_model_id))
        db.commit()
    return require_project(db, project_id)


def remove_model(db: Session, project_id: int, source_model_id: int) -> Project:
    """Take a model out of the project. The model itself stays in Models."""
    require_project(db, project_id)
    link = db.get(ProjectSourceModel, (project_id, source_model_id))
    if link is not None:
        db.delete(link)
        db.commit()
    return require_project(db, project_id)


def upload_to_models(
    db: Session, project_id: int, filename: str, file_obj, note: str | None = None, component: str | None = None,
) -> Project:
    """An STL uploaded on a project's page and also put in Models: a new model there (in the STL folder), which the
    project then uses (in `component`, if one is given)."""
    from . import source_model_service
    from .project_files import STL, check_type

    require_project(db, project_id)
    check_type(STL, filename)
    name = Path(filename or "").name
    file_type = SourceFileType.obj if name.lower().endswith(".obj") else SourceFileType.stl
    model = source_model_service.create_source_model(db, name=name, file_type=file_type, file_obj=file_obj, note=note)
    add_model(db, project_id, model.id)
    return set_counts(db, project_id, "model", model.id, component=component)


# ---- 3MFs from the rest of Farmhand, and printers ----


def link_printer(db: Session, project_id: int, printer_id: int) -> None:
    """The project uses this printer (already does: nothing changes). Committed."""
    if db.get(ProjectPrinter, (project_id, printer_id)) is None:
        db.add(ProjectPrinter(project_id=project_id, printer_id=printer_id))
        db.commit()


def add_bundle(db: Session, project_id: int, bundle_id: int) -> Project:
    """Use a 3MF from the rest of Farmhand in the project. The printer it's for comes into the project too."""
    require_project(db, project_id)
    bundle = db.get(Bundle, bundle_id)
    if bundle is None:
        raise NotFound("Bundle not found")
    if db.get(ProjectBundle, (project_id, bundle_id)) is None:
        db.add(ProjectBundle(project_id=project_id, bundle_id=bundle_id))
        db.commit()
    link_printer(db, project_id, bundle.printer_id)
    return require_project(db, project_id)


def remove_bundle(db: Session, project_id: int, bundle_id: int) -> Project:
    """Take a 3MF out of the project. The 3MF itself stays, and so does its printer in the project."""
    require_project(db, project_id)
    link = db.get(ProjectBundle, (project_id, bundle_id))
    if link is not None:
        db.delete(link)
        db.commit()
    return require_project(db, project_id)


def add_printer(db: Session, project_id: int, printer_id: int) -> Project:
    require_project(db, project_id)
    if db.get(Printer, printer_id) is None:
        raise NotFound("Printer not found")
    link_printer(db, project_id, printer_id)
    return require_project(db, project_id)


def remove_printer(db: Session, project_id: int, printer_id: int) -> Project:
    """Take a printer out of the project. The printer itself, and the project's 3MFs for it, stay."""
    require_project(db, project_id)
    link = db.get(ProjectPrinter, (project_id, printer_id))
    if link is not None:
        db.delete(link)
        db.commit()
    return require_project(db, project_id)


# ---- how many prints of an STL a project needs and has, and which of its sub-components it's in ----


def clean_component(component: str | None) -> str | None:
    """
    A sub-component's name, kept as its folders are: "Body / Left" or "Body\\Left" is "Body/Left" (one inside
    another). Blank is none. Spaces tidied in each part; at most MAX_COMPONENT_LENGTH characters.
    """
    parts = [" ".join(p.split()) for p in (component or "").replace("\\", "/").split("/")]
    name = "/".join(p for p in parts if p)
    if len(name) > MAX_COMPONENT_LENGTH:
        raise ValueError(f"A sub-component's name can be at most {MAX_COMPONENT_LENGTH} characters.")
    return name or None


def set_counts(db: Session, project_id: int, kind: str, thing_id: int, need=None, have=None, component=KEEP) -> Project:
    """
    How many of a model from Models (kind "model") or of one of the project's own STLs (kind "stl") the project needs
    and has, and the sub-component it's in (None: in none). Only what's given changes.
    """
    from .project_parts import clean_have, clean_need

    require_project(db, project_id)
    if kind == "model":
        row = db.get(ProjectSourceModel, (project_id, thing_id))
        if row is None:
            raise NotFound("That model isn't in this project")
    else:
        row = db.get(ProjectStlFile, thing_id)
        if row is None or row.project_id != project_id:
            raise NotFound("STL file not found")
    if need is not None:
        row.need = clean_need(need)
    if have is not None:
        row.have = clean_have(have)
    if component is not KEEP:
        name = clean_component(component)
        if name is None:
            row.component_row = None
        elif row.component_row is not None:
            row.component_row.component = name
        elif kind == "model":
            row.component_row = ProjectModelComponent(project_id=project_id, source_model_id=thing_id, component=name)
        else:
            row.component_row = ProjectStlFileComponent(stl_file_id=thing_id, component=name)
    db.commit()
    return require_project(db, project_id)
