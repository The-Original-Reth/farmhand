from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..schemas.project import ProjectIn, ProjectOut
from ..services import project_cad_service, project_service
from ..services.project_service import out
from .common import preview_response, require_confirm, require_readable

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return [out(p) for p in project_service.list_projects(db)]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectIn, db: Session = Depends(get_db)):
    """Make a project. 409 if the name is empty, too long, or another project's (in any case)."""
    with answer_errors(409):
        return out(project_service.create_project(db, payload.name))


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    with answer_errors():
        return out(project_service.require_project(db, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
def rename_project(project_id: int, payload: ProjectIn, db: Session = Depends(get_db)):
    """Rename a project (the same rules as a new one's name)."""
    with answer_errors(409):
        return out(project_service.rename_project(db, project_id, payload.name))


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Delete a project with its CAD files (every version, for good)."""
    require_confirm(confirm)
    with answer_errors():
        project_service.delete_project(db, project_id)
    return Response(status_code=204)


# ---- the project's CAD files: uploaded, versioned, previewed, downloaded, deleted (a delete needs confirm=true) ----


@router.post("/{project_id}/cad", response_model=ProjectOut, status_code=201)
def upload_cad(project_id: int, file: UploadFile = File(...), note: str | None = Form(None), db: Session = Depends(get_db)):
    """A CAD file of any kind, as version 1. 503 if the project files folder isn't there right now."""
    with answer_errors():
        project_cad_service.upload(db, project_id, file.filename, file.file, note)
        return out(project_service.require_project(db, project_id))


@router.post("/{project_id}/cad/{cad_id}/versions", response_model=ProjectOut, status_code=201)
def upload_cad_version(
    project_id: int, cad_id: int, file: UploadFile = File(...), note: str | None = Form(None), db: Session = Depends(get_db),
):
    """A newer version of one of the project's CAD files."""
    with answer_errors():
        project_cad_service.add_version(db, project_id, cad_id, file.filename, file.file, note)
        return out(project_service.require_project(db, project_id))


@router.get("/{project_id}/cad/{cad_id}/versions/{version}/download")
def download_cad_version(project_id: int, cad_id: int, version: int, db: Session = Depends(get_db)):
    with answer_errors():
        v = project_cad_service.require_version(db, project_id, cad_id, version)
    require_readable(v.file_path)
    return FileResponse(v.file_path, filename=v.filename)


@router.get("/{project_id}/cad/{cad_id}/versions/{version}/preview")
def cad_version_preview(project_id: int, cad_id: int, version: int, request: Request, db: Session = Depends(get_db)):
    """Its preview (kept next to the file). 404 when none could be made, or its folder can't be reached."""
    with answer_errors():
        v = project_cad_service.require_version(db, project_id, cad_id, version)
    return preview_response(v.thumbnail_path, v.file_path, request)


@router.delete("/{project_id}/cad/{cad_id}/versions/{version}", response_model=ProjectOut)
def delete_cad_version(project_id: int, cad_id: int, version: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Delete one version's file for good. Deleting its only version deletes the CAD file."""
    require_confirm(confirm)
    with answer_errors():
        project_cad_service.delete_version(db, project_id, cad_id, version)
        return out(project_service.require_project(db, project_id))


@router.delete("/{project_id}/cad/{cad_id}", response_model=ProjectOut)
def delete_cad_file(project_id: int, cad_id: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Delete a CAD file and every version of it, for good."""
    require_confirm(confirm)
    with answer_errors():
        project_cad_service.delete_cad_file(db, project_id, cad_id)
        return out(project_service.require_project(db, project_id))
