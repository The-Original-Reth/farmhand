from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..names import download_name
from ..schemas.bundle import BundleOut, BundleVersionDetailOut, MonumentUpdate, StarUpdate, ThreeMFInspection
from ..schemas.notes import NotesConflictOut, NotesUpdate
from ..services import bundle_service, send_print

router = APIRouter(prefix="/bundles", tags=["bundles"])


def _require_readable(path: str) -> None:
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="That file isn't available right now. If it's stored on a network share, check that "
            "the share is mounted and reachable.",
        )


def _parse_source_model_ids(raw: str) -> list[int]:
    try:
        ids = json.loads(raw)
        return [int(i) for i in ids]
    except (json.JSONDecodeError, TypeError, ValueError):
        raise HTTPException(status_code=422, detail="source_model_ids must be a JSON array of ints")


@router.get("", response_model=list[BundleOut])
def list_bundles(db: Session = Depends(get_db)):
    """Every bundle in the archive, regardless of printer or source model — powers cross-file compare."""
    return bundle_service.list_all_bundles(db)


@router.post("/inspect", response_model=ThreeMFInspection)
def inspect_threemf(threemf: UploadFile = File(...), db: Session = Depends(get_db)):
    """Parse a 3MF without storing it: which printer was it sliced for, and is that printer registered?"""
    with answer_errors():
        return bundle_service.inspect_3mf(db, threemf.file)


@router.post("", response_model=BundleOut, status_code=201)
def create_bundle(
    source_model_ids: str = Form(..., description='JSON array, e.g. "[1,2]"'),
    printer_id: int | None = Form(None, description="Omit to auto-detect from the 3MF's own profile"),
    threemf: UploadFile = File(...),
    gcode: UploadFile | None = File(None, description="Optional — can be added later"),
    db: Session = Depends(get_db),
):
    with answer_errors():
        return bundle_service.create_bundle(
            db,
            source_model_ids=_parse_source_model_ids(source_model_ids),
            threemf_file_obj=threemf.file,
            threemf_filename=threemf.filename,
            gcode_file_obj=gcode.file if gcode else None,
            gcode_filename=gcode.filename if gcode else None,
            printer_id=printer_id,
        )


@router.get("/{bundle_id}", response_model=BundleOut)
def get_bundle(bundle_id: int, db: Session = Depends(get_db)):
    bundle = bundle_service.get_bundle(db, bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle not found")
    return bundle


@router.post("/{bundle_id}/versions", response_model=BundleOut, status_code=201)
def add_bundle_version(
    bundle_id: int,
    threemf: UploadFile = File(...),
    gcode: UploadFile | None = File(None, description="Optional — can be added later"),
    db: Session = Depends(get_db),
):
    """The 'Update' button — printer is already locked, no printer_id here."""
    with answer_errors():
        bundle_service.add_bundle_version(
            db,
            bundle_id=bundle_id,
            threemf_file_obj=threemf.file,
            threemf_filename=threemf.filename,
            gcode_file_obj=gcode.file if gcode else None,
            gcode_filename=gcode.filename if gcode else None,
        )
    return bundle_service.get_bundle(db, bundle_id)


@router.put("/{bundle_id}/star", response_model=BundleOut)
def set_starred_version(bundle_id: int, payload: StarUpdate, db: Session = Depends(get_db)):
    """Star one version of this 3MF (only one at a time; never version 1), or send version_id: null to clear it."""
    with answer_errors():
        return bundle_service.set_starred_version(db, bundle_id, payload.version_id)


@router.put("/{bundle_id}/notes", response_model=BundleOut, responses={409: {"model": NotesConflictOut}})
def save_notes(bundle_id: int, payload: NotesUpdate, db: Session = Depends(get_db)):
    """
    Save the notes about a 3MF. Send the revision the text was based on: if someone else has saved since, this
    answers 409 with their current notes (nothing is overwritten) so the person can decide what to do.
    """
    with answer_errors():
        return bundle_service.set_notes(db, bundle_id, payload.notes, payload.base_revision)


@router.get("/versions/{version_id}", response_model=BundleVersionDetailOut)
def get_bundle_version(version_id: int, db: Session = Depends(get_db)):
    """Full detail including parsed settings — this is what the compare/diff view fetches for each side."""
    from ..models import BundleVersion

    version = db.get(BundleVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Bundle version not found")
    return version


@router.patch("/versions/{version_id}/monument", response_model=BundleVersionDetailOut)
def set_monument(version_id: int, payload: MonumentUpdate, db: Session = Depends(get_db)):
    with answer_errors():
        return bundle_service.set_monument(
            db, version_id=version_id, monument=payload.monument, note=payload.note, confirm=payload.confirm
        )


class Rename(BaseModel):
    filename: str


@router.patch("/versions/{version_id}", response_model=BundleVersionDetailOut)
def rename_version(version_id: int, payload: Rename, db: Session = Depends(get_db)):
    """Rename a 3MF version (what it's shown and downloaded as; it always stays a .3mf). Files stay put."""
    with answer_errors():
        return bundle_service.rename_version(db, version_id, payload.filename)


def _version_filename(db: Session, version_id: int) -> str:
    from ..models import BundleVersion

    return db.get(BundleVersion, version_id).filename


@router.get("/versions/{version_id}/download/3mf")
def download_3mf(version_id: int, db: Session = Depends(get_db)):
    with answer_errors(409):
        threemf_path, _ = bundle_service.download_bundle_version(db, version_id)
    _require_readable(threemf_path)
    # downloaded under its current name (it may have been renamed since it was stored)
    return FileResponse(threemf_path, filename=download_name(_version_filename(db, version_id), threemf_path))


@router.get("/versions/{version_id}/download/gcode")
def download_gcode(version_id: int, db: Session = Depends(get_db)):
    with answer_errors(409):
        _, gcode_path = bundle_service.download_bundle_version(db, version_id)
    if gcode_path is None:
        raise HTTPException(status_code=404, detail="No gcode file was uploaded for this version")
    _require_readable(gcode_path)
    stem = os.path.splitext(_version_filename(db, version_id))[0]  # the gcode follows its 3MF's name
    return FileResponse(gcode_path, filename=download_name(stem, gcode_path))


@router.put("/versions/{version_id}/gcode", response_model=BundleOut)
def upload_gcode(version_id: int, gcode: UploadFile = File(...), db: Session = Depends(get_db)):
    """Give a 3MF version its G-code (a .gcode or .bgcode sliced from it), replacing one it already had."""
    with answer_errors():
        version = bundle_service.attach_gcode(db, version_id, gcode.file, gcode.filename)
    return bundle_service.get_bundle(db, version.bundle_id)


@router.post("/versions/{version_id}/print")
def send_to_printer(version_id: int, db: Session = Depends(get_db)):
    """
    Send the version's G-code to the printer it was sliced for and start printing it. Refused (409) while that
    printer is busy; a printer that can't be reached answers 502.
    """
    with answer_errors():
        try:
            return send_print.send_gcode(db, version_id)
        except send_print.PrinterBusy as e:
            raise HTTPException(status_code=409, detail=str(e)) from None


@router.get("/versions/{version_id}/thumbnail")
def get_version_thumbnail(version_id: int, db: Session = Depends(get_db)):
    """
    The 3MF's own embedded thumbnail. Kept even after a version is pruned
    (files removed) — this is served straight from disk, not gated on
    full_files_retained, since the thumbnail specifically survives pruning.
    """
    from ..models import BundleVersion

    version = db.get(BundleVersion, version_id)
    if version is None or not version.thumbnail_path:
        raise HTTPException(status_code=404, detail="No thumbnail for this version")
    return FileResponse(version.thumbnail_path, media_type="image/png", headers={"Cache-Control": "no-cache"})


# ---- deletion: permanent, so each requires an explicit confirm=true ----

def _require_confirm(confirm: bool) -> None:
    if not confirm:
        raise HTTPException(status_code=409, detail="Deleting is permanent — pass confirm=true to proceed")


@router.delete("/versions/{version_id}", status_code=204)
def delete_bundle_version(version_id: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """
    Delete one version's files and parsed settings. Deleting a bundle's last
    remaining version deletes the whole bundle.
    """
    _require_confirm(confirm)
    from ..models import BundleVersion

    if db.get(BundleVersion, version_id) is None:
        raise HTTPException(status_code=404, detail="Bundle version not found")
    bundle_service.delete_bundle_version(db, version_id)
    return Response(status_code=204)


@router.delete("/{bundle_id}", status_code=204)
def delete_bundle(bundle_id: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Delete a bundle and every one of its versions."""
    _require_confirm(confirm)
    if bundle_service.get_bundle(db, bundle_id) is None:
        raise HTTPException(status_code=404, detail="Bundle not found")
    bundle_service.delete_bundle(db, bundle_id)
    return Response(status_code=204)
