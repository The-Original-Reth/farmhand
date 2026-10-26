from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..names import download_name
from ..notes import NotesConflict, conflict_response
from ..models import SourceFileType
from ..schemas.bundle import BundleOut
from ..schemas.source_model import NotesConflictOut, NotesUpdate, SourceModelOut
from ..schemas.scan import ScanImportOut, ScanImportRequest, ScanOut
from ..services import bundle_service, source_model_service

router = APIRouter(prefix="/source-models", tags=["source-models"])


@router.get("", response_model=list[SourceModelOut])
def list_source_models(db: Session = Depends(get_db)):
    return source_model_service.list_source_models(db)


@router.post("", response_model=SourceModelOut, status_code=201)
def create_source_model(
    name: str = Form(...),
    file_type: SourceFileType = Form(...),
    note: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    """
    Create a new STL folder. Per the upload-flow UI decision, the geometry
    file is optional here — a folder can be created (e.g. from within a
    3MF upload) and filled in with the actual STL/OBJ/STEP later.
    """
    try:
        return source_model_service.create_source_model(
            db, name=name, file_type=file_type, file_obj=file.file if file else None, note=note
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/scan", response_model=ScanOut)
def scan_stl_folder(db: Session = Depends(get_db)):
    """
    Look through the STL folder for model files not in the library yet (read-only; a POST so it's
    never cached). 503 if the folder looks unmounted, rather than a misleading "nothing new".
    """
    return source_model_service.scan_for_new_files(db)


@router.post("/scan/import", response_model=ScanImportOut)
def import_scanned(payload: ScanImportRequest, db: Session = Depends(get_db)):
    """Add files the scan found to the library, MOVING each into Farmhand's own folder layout (like an upload). Each file succeeds or fails on its own; a file that can't be moved stays where it was."""
    return {"results": source_model_service.import_scanned_files(db, payload.paths)}


@router.get("/{source_model_id}", response_model=SourceModelOut)
def get_source_model(source_model_id: int, db: Session = Depends(get_db)):
    model = source_model_service.get_source_model(db, source_model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Source model not found")
    return model


class Rename(BaseModel):
    name: str


@router.patch("/{source_model_id}", response_model=SourceModelOut)
def rename_source_model(source_model_id: int, payload: Rename, db: Session = Depends(get_db)):
    """Rename a model (what it's shown, searched and downloaded as; its extension stays, and its stored file keeps its own name)."""
    try:
        return source_model_service.rename(db, source_model_id, payload.name)
    except LookupError:
        raise HTTPException(status_code=404, detail="Source model not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.put("/{source_model_id}/notes", response_model=SourceModelOut, responses={409: {"model": NotesConflictOut}})
def save_notes(source_model_id: int, payload: NotesUpdate, db: Session = Depends(get_db)):
    """
    Save the notes about a model. Send the revision the text was based on: if someone else has saved since, this
    answers 409 with their current notes (nothing is overwritten) so the person can decide what to do.
    """
    try:
        return source_model_service.set_notes(db, source_model_id, payload.notes, payload.base_revision)
    except NotesConflict as c:
        return conflict_response(c)
    except ValueError as e:
        raise HTTPException(status_code=404 if "No source model" in str(e) else 422, detail=str(e))


@router.post("/{source_model_id}/versions", response_model=SourceModelOut, status_code=201)
def add_source_model_version(
    source_model_id: int,
    note: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        source_model_service.add_source_model_version(
            db, source_model_id=source_model_id, file_obj=file.file, filename=file.filename, note=note
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return source_model_service.get_source_model(db, source_model_id)


@router.get("/{source_model_id}/bundles", response_model=list[BundleOut])
def list_source_model_bundles(source_model_id: int, db: Session = Depends(get_db)):
    if source_model_service.get_source_model(db, source_model_id) is None:
        raise HTTPException(status_code=404, detail="Source model not found")
    return bundle_service.list_bundles_for_source_model(db, source_model_id)


@router.get("/{source_model_id}/versions/{version}/download")
def download_source_model_version(source_model_id: int, version: int, db: Session = Depends(get_db)):
    v = source_model_service.get_source_model_version(db, source_model_id, version)
    if v is None:
        raise HTTPException(status_code=404, detail="Source model version not found")
    if not os.path.exists(v.file_path):
        raise HTTPException(
            status_code=404,
            detail="That file isn't available right now. If it's stored on a network share, check that "
            "the share is mounted and reachable.",
        )
    return FileResponse(v.file_path, filename=download_name(v.source_model.name, v.file_path))  # under its current name


@router.get("/{source_model_id}/versions/{version}/thumbnail")
def get_source_model_version_thumbnail(source_model_id: int, version: int, db: Session = Depends(get_db)):
    v = source_model_service.get_source_model_version(db, source_model_id, version)
    if v is None or not v.thumbnail_path:
        raise HTTPException(status_code=404, detail="No thumbnail for this version")
    # no-cache = "check with me before reusing your copy" (cheap: unchanged files answer 304), so a
    # redrawn preview shows up instead of the browser's stale one
    return FileResponse(v.thumbnail_path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.post("/{source_model_id}/versions/{version}/thumbnail")
def redraw_source_model_version_thumbnail(source_model_id: int, version: int, db: Session = Depends(get_db)):
    """Redraw this version's preview from its file with the current renderer."""
    if source_model_service.get_source_model_version(db, source_model_id, version) is None:
        raise HTTPException(status_code=404, detail="Source model version not found")
    try:
        return {"updated": source_model_service.regenerate_thumbnail(db, source_model_id, version)}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ---- deletion: permanent, so each requires an explicit confirm=true ----

def _require_confirm(confirm: bool) -> None:
    if not confirm:
        raise HTTPException(status_code=409, detail="Deleting is permanent — pass confirm=true to proceed")


@router.delete("/{source_model_id}/versions/{version}", status_code=204)
def delete_source_model_version(
    source_model_id: int, version: int, confirm: bool = Query(False), db: Session = Depends(get_db)
):
    """Delete one version's file. The folder itself stays, even if that was its only version."""
    _require_confirm(confirm)
    if source_model_service.get_source_model_version(db, source_model_id, version) is None:
        raise HTTPException(status_code=404, detail="Source model version not found")
    source_model_service.delete_source_model_version(db, source_model_id, version)
    return Response(status_code=204)


@router.delete("/{source_model_id}", status_code=204)
def delete_source_model(
    source_model_id: int,
    cascade: bool = Query(False, description="Also delete 3MF bundles sliced only from this model"),
    confirm: bool = Query(False),
    db: Session = Depends(get_db),
):
    """
    Delete a whole STL folder and all its versions. 3MF bundles that also use
    other models just lose their link to this one; bundles sliced ONLY from
    this model are refused (409) unless cascade=true.
    """
    _require_confirm(confirm)
    if source_model_service.get_source_model(db, source_model_id) is None:
        raise HTTPException(status_code=404, detail="Source model not found")
    try:
        source_model_service.delete_source_model(db, source_model_id, cascade=cascade)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return Response(status_code=204)
