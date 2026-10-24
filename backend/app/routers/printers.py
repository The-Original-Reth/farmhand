from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.bundle import BundleOut
from ..schemas.notes import NotesConflictOut, NotesUpdate
from ..schemas.printer import PrinterCreate, PrinterDecommission, PrinterOut, PrinterUpdate
from ..services import bundle_service, printer_service

router = APIRouter(prefix="/printers", tags=["printers"])


@router.get("", response_model=list[PrinterOut])
def list_printers(db: Session = Depends(get_db)):
    return printer_service.list_printers(db)


@router.post("", response_model=PrinterOut, status_code=201)
def create_printer(payload: PrinterCreate, db: Session = Depends(get_db)):
    try:
        return printer_service.create_printer(db, **payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{printer_id}", response_model=PrinterOut)
def get_printer(printer_id: int, db: Session = Depends(get_db)):
    printer = printer_service.get_printer(db, printer_id)
    if printer is None:
        raise HTTPException(status_code=404, detail="Printer not found")
    return printer


@router.patch("/{printer_id}", response_model=PrinterOut)
def update_printer(printer_id: int, payload: PrinterUpdate, db: Session = Depends(get_db)):
    if printer_service.get_printer(db, printer_id) is None:
        raise HTTPException(status_code=404, detail="Printer not found")
    try:
        return printer_service.update_printer(db, printer_id, payload.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.patch("/{printer_id}/decommission", response_model=PrinterOut)
def set_decommissioned(printer_id: int, payload: PrinterDecommission, db: Session = Depends(get_db)):
    try:
        return printer_service.set_decommissioned(db, printer_id, payload.decommissioned)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{printer_id}/bundles", response_model=list[BundleOut])
def list_printer_bundles(printer_id: int, db: Session = Depends(get_db)):
    if printer_service.get_printer(db, printer_id) is None:
        raise HTTPException(status_code=404, detail="Printer not found")
    return bundle_service.list_bundles_for_printer(db, printer_id)


@router.put("/{printer_id}/notes", response_model=PrinterOut, responses={409: {"model": NotesConflictOut}})
def save_notes(printer_id: int, payload: NotesUpdate, db: Session = Depends(get_db)):
    """
    Save the notes about a printer. Send the revision the text was based on: if someone else has saved since, this
    answers 409 with their current notes (nothing is overwritten) so the person can decide what to do.
    """
    try:
        return printer_service.set_notes(db, printer_id, payload.notes, payload.base_revision)
    except printer_service.NotesConflict as c:
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(c),
                "current": {
                    "notes": c.printer.notes,
                    "notes_revision": c.printer.notes_revision,
                    "notes_updated_at": c.printer.notes_updated_at.isoformat() if c.printer.notes_updated_at else None,
                },
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404 if "No printer" in str(e) else 422, detail=str(e))
