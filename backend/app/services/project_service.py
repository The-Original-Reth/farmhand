"""
Projects: a piece of work for the farm. A project has a name, and its own CAD files (project_cad_service.py); its STL
files, 3MF files, printers and parts come later.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import storage
from ..errors import NotFound
from ..models import Project, ProjectCadFile

MAX_NAME_LENGTH = 200

_LOAD = (selectinload(Project.cad_files).selectinload(ProjectCadFile.versions),)


def out(project: Project) -> dict:
    """A project as the API answers it: its name, and its CAD files with their versions (newest first)."""
    return {
        "id": project.id,
        "name": project.name,
        "created_at": project.created_at,
        "cad_files": [
            {
                "id": cad.id,
                "name": cad.versions[0].filename if cad.versions else "",  # its newest version's
                "created_at": cad.created_at,
                "versions": [
                    {
                        "version": v.version, "filename": v.filename, "size_bytes": v.size_bytes, "note": v.note,
                        "uploaded_at": v.uploaded_at, "has_preview": bool(v.thumbnail_path),
                    }
                    for v in cad.versions
                ],
            }
            for cad in project.cad_files
        ],
    }


def list_projects(db: Session) -> list[Project]:
    return list(db.scalars(select(Project).options(*_LOAD).order_by(func.lower(Project.name))))


def require_project(db: Session, project_id: int) -> Project:
    db.expire_all()  # CAD files just added or deleted are read fresh
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
    """Delete the project and its CAD files: rows first, then the files, then its folder if that's left empty."""
    from .project_cad_service import files_of_project  # (it imports this module)

    project = require_project(db, project_id)
    paths = files_of_project(db, project_id)
    db.delete(project)
    db.commit()
    storage.delete_files(paths)
    storage.tidy_project_folder(project_id)
