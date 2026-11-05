"""
Projects: a piece of work for the farm. A project has a name; its own CAD files and STLs (project_files.py); and models
from the Models page it uses, only pointed at. Its 3MF files, printers and parts come later.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import storage
from ..errors import NotFound
from ..models import Project, ProjectCadFile, ProjectSourceModel, ProjectStlFile, SourceFileType, SourceModel

MAX_NAME_LENGTH = 200

_LOAD = (
    selectinload(Project.cad_files).selectinload(ProjectCadFile.versions),
    selectinload(Project.stl_files).selectinload(ProjectStlFile.versions),
    selectinload(Project.model_links),
)


def _files_out(files) -> list[dict]:
    """A project's own files (CAD or STL) as the API answers them: each named after its newest version."""
    return [
        {
            "id": f.id,
            "name": f.versions[0].filename if f.versions else "",
            "created_at": f.created_at,
            "versions": [
                {
                    "version": v.version, "filename": v.filename, "size_bytes": v.size_bytes, "note": v.note,
                    "uploaded_at": v.uploaded_at, "has_preview": bool(v.thumbnail_path),
                }
                for v in f.versions
            ],
        }
        for f in files
    ]


def out(project: Project) -> dict:
    """A project as the API answers it: its own CAD files and STLs with their versions (newest first), and the ids of
    the models from the Models page it uses (in the order they were added)."""
    return {
        "id": project.id,
        "name": project.name,
        "created_at": project.created_at,
        "cad_files": _files_out(project.cad_files),
        "stl_files": _files_out(project.stl_files),
        "source_model_ids": [link.source_model_id for link in project.model_links],
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
    """Delete the project and its own files (rows first, then files, then its folder if that's left empty). The models
    it used stay in Models."""
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


def upload_to_models(db: Session, project_id: int, filename: str, file_obj, note: str | None = None) -> Project:
    """An STL uploaded on a project's page and also put in Models: a new model there (in the STL folder), which the
    project then uses."""
    from . import source_model_service
    from .project_files import STL, check_type

    require_project(db, project_id)
    check_type(STL, filename)
    name = Path(filename or "").name
    file_type = SourceFileType.obj if name.lower().endswith(".obj") else SourceFileType.stl
    model = source_model_service.create_source_model(db, name=name, file_type=file_type, file_obj=file_obj, note=note)
    return add_model(db, project_id, model.id)
