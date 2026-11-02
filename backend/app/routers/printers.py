from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..schemas.bundle import BundleOut
from ..schemas.notes import NotesConflictOut, NotesUpdate
from ..schemas.printer import (
    DefaultSubPrinterIn, PrinterCreate, SubPrinterCopyIn, PrinterDecommission, PrinterOut, PrinterUpdate, SubPrinterIn, SubPrinterPartIn, SubPrinterPartOut, SubPrinterPartRow,
    SubPrinterSettingsCopyOut,
)
from ..services import bundle_service, printer_service, sub_printer_service
from .common import require_confirm, require_printer

router = APIRouter(prefix="/printers", tags=["printers"])


@router.get("", response_model=list[PrinterOut])
def list_printers(db: Session = Depends(get_db)):
    return printer_service.list_printers(db)


@router.post("", response_model=PrinterOut, status_code=201)
def create_printer(payload: PrinterCreate, db: Session = Depends(get_db)):
    """A new printer. Its connection (Mainsail / Moonraker, or PrusaLink) and login can be given at once."""
    base = payload.model_dump(include={"name", "kind", "wired_ip", "wireless_ip"})
    link = payload.model_dump(exclude=set(base), exclude_none=True)
    with answer_errors(409):
        printer = printer_service.create_printer(db, **base)
    if link.get("connection_type") == "moonraker" and len(link) == 1:
        return printer  # the default: nothing more to set
    return printer_service.update_printer(db, printer.id, link)


@router.get("/{printer_id}", response_model=PrinterOut)
def get_printer(printer_id: int, db: Session = Depends(get_db)):
    return require_printer(db, printer_id)


@router.patch("/{printer_id}", response_model=PrinterOut)
def update_printer(printer_id: int, payload: PrinterUpdate, db: Session = Depends(get_db)):
    require_printer(db, printer_id)
    with answer_errors(409):
        return printer_service.update_printer(db, printer_id, payload.model_dump(exclude_unset=True))


@router.patch("/{printer_id}/decommission", response_model=PrinterOut)
def set_decommissioned(printer_id: int, payload: PrinterDecommission, db: Session = Depends(get_db)):
    with answer_errors():
        return printer_service.set_decommissioned(db, printer_id, payload.decommissioned)


@router.get("/{printer_id}/bundles", response_model=list[BundleOut])
def list_printer_bundles(printer_id: int, db: Session = Depends(get_db)):
    require_printer(db, printer_id)
    return bundle_service.list_bundles_for_printer(db, printer_id)


@router.post("/{printer_id}/sub-printers", response_model=PrinterOut, status_code=201)
def add_sub_printer(printer_id: int, payload: SubPrinterIn, db: Session = Depends(get_db)):
    """Add a sub printer (one of its printer presets in the slicer) by hand. 409 if it already has one by that name."""
    with answer_errors(409):
        return sub_printer_service.add(db, printer_id, payload.name)


@router.patch("/{printer_id}/sub-printers/{sub_printer_id}", response_model=PrinterOut)
def rename_sub_printer(printer_id: int, sub_printer_id: int, payload: SubPrinterIn, db: Session = Depends(get_db)):
    """Rename a sub printer. Its 3MFs stay linked to it. 409 if another of the printer's has that name."""
    with answer_errors(409):
        return sub_printer_service.rename(db, printer_id, sub_printer_id, payload.name)


@router.post("/{printer_id}/sub-printers/{sub_printer_id}/copy", response_model=PrinterOut, status_code=201)
def copy_sub_printer(
    printer_id: int, sub_printer_id: int, payload: SubPrinterCopyIn | None = None, db: Session = Depends(get_db)
):
    """
    A copy of a sub printer, with its parts, named `name` or "<its name> - copy". Its 3MFs and being the default stay
    with the original. 409 if the printer already has one by that name. Answers the printer as it now stands.
    """
    with answer_errors(409):
        return sub_printer_service.copy(db, printer_id, sub_printer_id, payload.name if payload else None)


@router.get("/{printer_id}/sub-printers/{sub_printer_id}/settings-copy", response_model=SubPrinterSettingsCopyOut)
def get_sub_printer_settings_copy(printer_id: int, sub_printer_id: int, db: Session = Depends(get_db)):
    """
    A copied sub printer's printer settings, as the one it was copied from had them: shown as its own until a 3MF
    sliced with it is uploaded. 404 when it has none (it isn't a copy, or no 3MF had been sliced with the original).
    """
    with answer_errors():
        return sub_printer_service.settings_copy(db, printer_id, sub_printer_id)


@router.delete("/{printer_id}/sub-printers/{sub_printer_id}", response_model=PrinterOut)
def remove_sub_printer(printer_id: int, sub_printer_id: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Remove a sub printer. Its 3MFs stay, with no sub printer. Answers the printer as it now stands."""
    require_confirm(confirm)
    with answer_errors():
        return sub_printer_service.remove(db, printer_id, sub_printer_id)


@router.put("/{printer_id}/default-sub-printer", response_model=PrinterOut)
def set_default_sub_printer(printer_id: int, payload: DefaultSubPrinterIn, db: Session = Depends(get_db)):
    """
    The sub printer its uploads start on: picked for every 3MF uploaded to it, whatever preset it was sliced with
    (it can still be changed on the upload). null: no default, Farmhand guesses from the preset.
    """
    with answer_errors():
        return sub_printer_service.set_default(db, printer_id, payload.sub_printer_id)


@router.get("/{printer_id}/sub-printers/{sub_printer_id}/parts", response_model=list[SubPrinterPartOut])
def list_sub_printer_parts(printer_id: int, sub_printer_id: int, db: Session = Depends(get_db)):
    """The parts written down for a sub printer (its Printer parts page), in the order they were added."""
    with answer_errors():
        return sub_printer_service.parts(db, printer_id, sub_printer_id)


@router.post("/{printer_id}/sub-printers/{sub_printer_id}/parts", response_model=list[SubPrinterPartOut], status_code=201)
def add_sub_printer_part(printer_id: int, sub_printer_id: int, payload: SubPrinterPartIn, db: Session = Depends(get_db)):
    """Write down a part fitted to a sub printer. Answers its parts as they now stand."""
    with answer_errors():
        return sub_printer_service.add_part(db, printer_id, sub_printer_id, payload.model_dump())


@router.put("/{printer_id}/sub-printers/{sub_printer_id}/parts", response_model=list[SubPrinterPartOut])
def save_sub_printer_parts(
    printer_id: int, sub_printer_id: int, payload: list[SubPrinterPartRow], confirm: bool = Query(False),
    db: Session = Depends(get_db),
):
    """
    Save the whole parts list at once (the Printer parts page's Save): a part with its id is changed, one without is
    added, and one left out is removed, which needs confirm=true. All of it or nothing. Answers the list.
    """
    rows = [row.model_dump() for row in payload]
    with answer_errors():
        left_out = sub_printer_service.parts_left_out(db, printer_id, sub_printer_id, rows)
    if left_out:
        require_confirm(confirm, "Saving removes parts: say confirm=true")
    with answer_errors():
        return sub_printer_service.save_parts(db, printer_id, sub_printer_id, rows)


@router.put("/{printer_id}/sub-printers/{sub_printer_id}/parts/{part_id}", response_model=list[SubPrinterPartOut])
def update_sub_printer_part(
    printer_id: int, sub_printer_id: int, part_id: int, payload: SubPrinterPartIn, db: Session = Depends(get_db)
):
    """Change a part (every field: a blank one is cleared). Answers its parts as they now stand."""
    with answer_errors():
        return sub_printer_service.update_part(db, printer_id, sub_printer_id, part_id, payload.model_dump())


@router.delete("/{printer_id}/sub-printers/{sub_printer_id}/parts/{part_id}", response_model=list[SubPrinterPartOut])
def delete_sub_printer_part(
    printer_id: int, sub_printer_id: int, part_id: int, confirm: bool = Query(False), db: Session = Depends(get_db)
):
    """Remove a part from the list. Answers its parts as they now stand."""
    require_confirm(confirm)
    with answer_errors():
        return sub_printer_service.delete_part(db, printer_id, sub_printer_id, part_id)


@router.put("/{printer_id}/notes", response_model=PrinterOut, responses={409: {"model": NotesConflictOut}})
def save_notes(printer_id: int, payload: NotesUpdate, db: Session = Depends(get_db)):
    """
    Save the notes about a printer. Send the revision the text was based on: if someone else has saved since, this
    answers 409 with their current notes (nothing is overwritten) so the person can decide what to do.
    """
    with answer_errors():
        return printer_service.set_notes(db, printer_id, payload.notes, payload.base_revision)
