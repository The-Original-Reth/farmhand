"""
What every part of a project's services starts from: the project itself (require_project, with all it holds loaded), and
the printers it uses. Kept apart from project_service, which uses project_files, project_records and project_parts,
so that they can use these without importing it.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..errors import NotFound
from ..models import (
    Printer, Project, ProjectCadFile, ProjectDocFile, ProjectPrinter, ProjectSourceModel, ProjectStlFile, ProjectThreemfFile,
    ProjectThreemfVersion,
)

_LOAD = (
    selectinload(Project.doc_files).selectinload(ProjectDocFile.versions),
    selectinload(Project.doc_files).selectinload(ProjectDocFile.position_row),
    selectinload(Project.cad_files).selectinload(ProjectCadFile.versions),
    selectinload(Project.cad_files).selectinload(ProjectCadFile.position_row),
    selectinload(Project.stl_files).selectinload(ProjectStlFile.versions),
    selectinload(Project.stl_files).selectinload(ProjectStlFile.component_row),
    selectinload(Project.threemf_files).selectinload(ProjectThreemfFile.versions).selectinload(ProjectThreemfVersion.gcode),
    selectinload(Project.model_links).selectinload(ProjectSourceModel.component_row),
    selectinload(Project.bundle_links),
    selectinload(Project.printer_links),
    selectinload(Project.parts),
)


def require_project(db: Session, project_id: int) -> Project:
    db.expire_all()  # files and links just added or removed are read fresh
    project = db.scalar(select(Project).options(*_LOAD).where(Project.id == project_id))
    if project is None:
        raise NotFound("Project not found")
    return project


def link_printer(db: Session, project_id: int, printer_id: int) -> None:
    """The project uses this printer (already does: nothing changes). Committed."""
    if db.get(ProjectPrinter, (project_id, printer_id)) is None:
        db.add(ProjectPrinter(project_id=project_id, printer_id=printer_id))
        db.commit()


def require_printer_exists(db: Session, printer_id: int) -> None:
    if db.get(Printer, printer_id) is None:
        raise NotFound("Printer not found")
