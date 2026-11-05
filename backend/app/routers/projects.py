from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..schemas.project import BomOut, PartIn, PartUpdate, ProjectIn, ProjectOut
from ..services import project_files, project_parts, project_service
from ..services.project_files import CAD, STL, THREEMF, Kind
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
    """Delete a project with its own CAD files, STLs and 3MFs (every version, for good). What it used stays."""
    require_confirm(confirm)
    with answer_errors():
        project_service.delete_project(db, project_id)
    return Response(status_code=204)


# ---- models from the Models page: PUT puts one in the project, DELETE takes it out (the model itself stays) ----


@router.put("/{project_id}/source-models/{source_model_id}", response_model=ProjectOut)
def add_model(project_id: int, source_model_id: int, db: Session = Depends(get_db)):
    with answer_errors():
        return out(project_service.add_model(db, project_id, source_model_id))


@router.delete("/{project_id}/source-models/{source_model_id}", response_model=ProjectOut)
def remove_model(project_id: int, source_model_id: int, db: Session = Depends(get_db)):
    with answer_errors():
        return out(project_service.remove_model(db, project_id, source_model_id))


# ---- 3MFs and printers from the rest of Farmhand: PUT puts one in the project, DELETE takes it out (nothing else changes) ----


@router.put("/{project_id}/bundles/{bundle_id}", response_model=ProjectOut)
def add_bundle(project_id: int, bundle_id: int, db: Session = Depends(get_db)):
    """Use a 3MF in the project. The printer it's for comes too (taking the 3MF out later leaves the printer)."""
    with answer_errors():
        return out(project_service.add_bundle(db, project_id, bundle_id))


@router.delete("/{project_id}/bundles/{bundle_id}", response_model=ProjectOut)
def remove_bundle(project_id: int, bundle_id: int, db: Session = Depends(get_db)):
    with answer_errors():
        return out(project_service.remove_bundle(db, project_id, bundle_id))


@router.put("/{project_id}/printers/{printer_id}", response_model=ProjectOut)
def add_printer(project_id: int, printer_id: int, db: Session = Depends(get_db)):
    with answer_errors():
        return out(project_service.add_printer(db, project_id, printer_id))


@router.delete("/{project_id}/printers/{printer_id}", response_model=ProjectOut)
def remove_printer(project_id: int, printer_id: int, db: Session = Depends(get_db)):
    with answer_errors():
        return out(project_service.remove_printer(db, project_id, printer_id))


# ---- the project's own files, CAD (/cad), STL (/stl) and 3MF (/threemf): uploaded, versioned, previewed, downloaded,
# deleted ----


@router.post("/{project_id}/cad", response_model=ProjectOut, status_code=201)
def upload_cad(project_id: int, file: UploadFile = File(...), note: str | None = Form(None), db: Session = Depends(get_db)):
    """A CAD file of any kind, as version 1. 503 if the project files folder isn't there right now."""
    with answer_errors():
        project_files.upload(db, CAD, project_id, file.filename, file.file, note)
        return out(project_service.require_project(db, project_id))


@router.post("/{project_id}/stl", response_model=ProjectOut, status_code=201)
def upload_stl(
    project_id: int,
    file: UploadFile = File(...),
    in_models: bool = Form(..., description="true: also put it in Models (a new model the project uses); false: the project's own"),
    note: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """
    An STL (or OBJ) uploaded on a project's page. in_models=true: it becomes a new model in Models (kept in the STL
    folder) that the project uses. false: it belongs to the project, as version 1, in the project files folder. 422 for
    another kind of file; 503 if the folder it goes to isn't there right now.
    """
    with answer_errors():
        if in_models:
            return out(project_service.upload_to_models(db, project_id, file.filename, file.file, note))
        project_files.upload(db, STL, project_id, file.filename, file.file, note)
        return out(project_service.require_project(db, project_id))


@router.post("/{project_id}/threemf", response_model=ProjectOut, status_code=201)
def upload_threemf(
    project_id: int,
    file: UploadFile = File(...),
    printer_id: int | None = Form(None, description="The printer it's for: it comes into the project too"),
    note: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """
    A 3MF uploaded to the project only (one also put in Models is uploaded there, then used: PUT .../bundles/{id}), as
    version 1, with its printer. 422 for another kind of file; 404 for a printer that isn't there; 503 if the project
    files folder isn't there right now.
    """
    with answer_errors():
        project_files.upload(db, THREEMF, project_id, file.filename, file.file, note, printer_id=printer_id)
        return out(project_service.require_project(db, project_id))


def _file_routes(kind: Kind) -> None:
    """New version, download, preview and delete, for one kind of project file."""
    base = f"/{{project_id}}/{kind.key}/{{file_id}}"

    @router.post(f"{base}/versions", response_model=ProjectOut, status_code=201, name=f"upload_{kind.key}_version")
    def upload_version(
        project_id: int, file_id: int, file: UploadFile = File(...), note: str | None = Form(None), db: Session = Depends(get_db),
    ):
        with answer_errors():
            project_files.add_version(db, kind, project_id, file_id, file.filename, file.file, note)
            return out(project_service.require_project(db, project_id))

    @router.get(f"{base}/versions/{{version}}/download", name=f"download_{kind.key}_version")
    def download(project_id: int, file_id: int, version: int, db: Session = Depends(get_db)):
        with answer_errors():
            v = project_files.require_version(db, kind, project_id, file_id, version)
        require_readable(v.file_path)
        return FileResponse(v.file_path, filename=v.filename)

    @router.get(f"{base}/versions/{{version}}/preview", name=f"{kind.key}_version_preview")
    def preview(project_id: int, file_id: int, version: int, request: Request, db: Session = Depends(get_db)):
        """Its preview (kept next to the file). 404 when none could be made, or its folder can't be reached."""
        with answer_errors():
            v = project_files.require_version(db, kind, project_id, file_id, version)
        return preview_response(v.thumbnail_path, v.file_path, request)

    @router.delete(f"{base}/versions/{{version}}", response_model=ProjectOut, name=f"delete_{kind.key}_version")
    def delete_version(project_id: int, file_id: int, version: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
        """Delete one version's file for good. Deleting its only version deletes the file."""
        require_confirm(confirm)
        with answer_errors():
            project_files.delete_version(db, kind, project_id, file_id, version)
            return out(project_service.require_project(db, project_id))

    @router.delete(base, response_model=ProjectOut, name=f"delete_{kind.key}_file")
    def delete_file(project_id: int, file_id: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
        """Delete the file and every version of it, for good."""
        require_confirm(confirm)
        with answer_errors():
            project_files.delete_file(db, kind, project_id, file_id)
            return out(project_service.require_project(db, project_id))


for _kind in project_files.KINDS.values():
    _file_routes(_kind)


# ---- the parts list: parts added one at a time, or many from a BOM (a CSV file) ----


@router.post("/{project_id}/parts", response_model=ProjectOut, status_code=201)
def add_part(project_id: int, payload: PartIn, db: Session = Depends(get_db)):
    """Add a part: its name, quantity (1 or more), a link to buy it (https:// added if it has none) and notes. 422 for
    a missing name, a bad quantity or a link that isn't a web address."""
    with answer_errors():
        return out(project_parts.add_part(db, project_id, payload.name, payload.quantity, payload.link, payload.note))


@router.patch("/{project_id}/parts/{part_id}", response_model=ProjectOut)
def update_part(project_id: int, part_id: int, payload: PartUpdate, db: Session = Depends(get_db)):
    with answer_errors():
        return out(project_parts.update_part(db, project_id, part_id, payload.model_dump(exclude_unset=True)))


@router.delete("/{project_id}/parts/{part_id}", response_model=ProjectOut)
def delete_part(project_id: int, part_id: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
    require_confirm(confirm)
    with answer_errors():
        return out(project_parts.delete_part(db, project_id, part_id))


@router.post("/{project_id}/parts/bom", response_model=BomOut)
def upload_bom(
    project_id: int,
    file: UploadFile = File(..., description="A CSV file: a heading row (Part, Quantity, Link, Notes), then a part a row"),
    replace: bool = Form(False, description="true: the BOM's parts replace the list; false: they're added to it"),
    db: Session = Depends(get_db),
):
    """Many parts at once from a BOM. Every row is checked first: 422 names each one that's wrong, and nothing changes."""
    with answer_errors():
        project, added = project_parts.upload_bom(db, project_id, file.file.read(), replace)
        return {"project": out(project), "added": added}
