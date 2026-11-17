from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..services import config_backups as backups
from ..services import config_service, printer_ssh
from .common import require_confirm, require_printer

# Backups of a Klipper printer's config folder and Moonraker database, kept in the printer backups folder (see
# services/config_backups.py). A MoonrakerError becomes a 502, a NAS that isn't there a 503 (see main.py).
router = APIRouter(prefix="/printers", tags=["config backups"])


class ScheduleIn(BaseModel):
    every_days: int


class RestoreIn(BaseModel):
    path: str


def _download(data: bytes, filename: str, media_type: str) -> Response:
    return Response(data, media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}", "Cache-Control": "no-store",
    })


class LocationIn(BaseModel):
    path: str | None = None


@router.get("/config-backups/location")
def backups_location(db: Session = Depends(get_db)):
    """Where new backups go: {path, is_default, default_path, status} ("backup" in the Farmhand folder unless chosen)."""
    return backups.location_info(db)


@router.put("/config-backups/location")
def choose_backups_location(payload: LocationIn, db: Session = Depends(get_db)):
    """Choose the printer backups folder, or go back to the default (path null). 422 says why one can't be used."""
    with answer_errors():
        out = backups.set_location(db, payload.path)
    config_service.mirror_quietly(db)  # the settings copy holds which folder it is
    return out


@router.get("/config-backups/ssh-key")
def ssh_key():
    """
    Farmhand's own SSH public key, the line to add to each printer's ~/.ssh/authorized_keys so Farmhand can copy
    Moonraker's database into backups and write read-only files (mainsail.cfg). Made the first time it's asked for.
    """
    return {"public_key": printer_ssh.public_key()}


@router.post("/{printer_id}/ssh/test")
def ssh_test(printer_id: int, db: Session = Depends(get_db)):
    """Can Farmhand log in to this printer over SSH with its key? {ok, user, host, error, kind}. Never fails."""
    return printer_ssh.check(require_printer(db, printer_id))


@router.put("/config-backups/schedule")
def set_schedule(payload: ScheduleIn, db: Session = Depends(get_db)):
    """How many days between automatic backups, for every Klipper printer (0 = never). Saved with the settings."""
    with answer_errors():
        return {"every_days": backups.set_every_days(db, payload.every_days)}


@router.get("/{printer_id}/config-backups")
def list_backups(printer_id: int, db: Session = Depends(get_db)):
    """
    The printer's backups, newest first (the newest 10 are kept), with what changed since the one before each, and
    when the next automatic one is due. supported: false for a PrusaLink printer (it has no config folder to read).
    """
    return backups.list_backups(db, require_printer(db, printer_id))


@router.post("/{printer_id}/config-backups", status_code=201)
def take_backup(printer_id: int, db: Session = Depends(get_db)):
    """Back up now: read the config folder and Moonraker's database, write them to the NAS. Returns the list."""
    printer = require_printer(db, printer_id)
    with answer_errors():
        backup = backups.take_backup(db, printer, "manual")
    return {"id": backup.id, **backups.list_backups(db, printer)}


@router.get("/{printer_id}/config-backups/{backup_id}")
def backup_detail(printer_id: int, backup_id: int, db: Session = Depends(get_db)):
    with answer_errors():
        return backups.backup_detail(db, require_printer(db, printer_id), backup_id)


@router.get("/{printer_id}/config-backups/{backup_id}/download")
def download_backup(printer_id: int, backup_id: int, db: Session = Depends(get_db)):
    """The whole backup as a zip."""
    with answer_errors():
        data, name = backups.zip_backup(db, require_printer(db, printer_id), backup_id)
    return _download(data, name, "application/zip")


@router.get("/{printer_id}/config-backups/{backup_id}/file")
def view_file(printer_id: int, backup_id: int, path: str = Query(...), db: Session = Depends(get_db)):
    """One file of the backup as text ({path, size, binary, text}; text is null for a file that isn't text)."""
    with answer_errors():
        return backups.view_file(db, require_printer(db, printer_id), backup_id, path)


@router.get("/{printer_id}/config-backups/{backup_id}/file/download")
def download_file(printer_id: int, backup_id: int, path: str = Query(...), db: Session = Depends(get_db)):
    with answer_errors():
        data, name = backups.read_file(db, require_printer(db, printer_id), backup_id, path)
    return _download(data, name, "application/octet-stream")


@router.get("/{printer_id}/config-backups/{backup_id}/diff")
def diff_file(printer_id: int, backup_id: int, path: str = Query(...), db: Session = Depends(get_db)):
    """How one file differs from the backup before: {change: added | changed | same | null, diff (unified), binary}."""
    with answer_errors():
        return backups.diff_file(db, require_printer(db, printer_id), backup_id, path)


@router.post("/{printer_id}/config-backups/{backup_id}/restore")
def restore_file(printer_id: int, backup_id: int, payload: RestoreIn, db: Session = Depends(get_db)):
    """
    Put one config file of the backup back on the printer (refused while it prints: 409). A backup of how things are
    now is taken first. Klipper needs a restart afterwards, which is left to the person.
    """
    printer = require_printer(db, printer_id)
    with answer_errors(409):
        done = backups.restore_file(db, printer, backup_id, payload.path)
    return {**done, **backups.list_backups(db, printer)}


@router.get("/{printer_id}/config-backups/{backup_id}/restore-preview")
def restore_preview(printer_id: int, backup_id: int, db: Session = Depends(get_db)):
    """
    What Restore would change, without changing anything: {files: {put_back, same, read_only}, settings: [{namespace,
    keys}], left_alone} (left_alone: config files on the printer now that aren't in the backup; never deleted).
    """
    with answer_errors():
        return backups.restore_preview(db, require_printer(db, printer_id), backup_id)


@router.post("/{printer_id}/config-backups/{backup_id}/restore-all")
def restore_backup(printer_id: int, backup_id: int, db: Session = Depends(get_db)):
    """
    Restore: put the whole backup back on the printer (409 while it prints): every config file and Moonraker setting
    (Mainsail's, maintenance...) that differs from the printer's now. Nothing is deleted; read-only files are left
    alone; Moonraker's print history can't be written back. A backup of how things are now is taken first. Answers
    {message, restored, settings_written, failed, ...the plan, ...the list}. Klipper isn't restarted.
    """
    printer = require_printer(db, printer_id)
    with answer_errors(409):
        done = backups.restore_backup(db, printer, backup_id)
    return {**done, **backups.list_backups(db, printer)}


@router.post("/{printer_id}/config-backups/{backup_id}/restore-database")
def restore_database(printer_id: int, backup_id: int, db: Session = Depends(get_db)):
    """
    Put Moonraker's database back as it was in the backup (its copy, sent over SSH; Moonraker restores it and restarts
    itself). 409 while printing or when the backup has no database copy. A backup of how things are is taken first.
    """
    printer = require_printer(db, printer_id)
    with answer_errors(409):
        done = backups.restore_database(db, printer, backup_id)
    return {**done, **backups.list_backups(db, printer)}


@router.delete("/{printer_id}/config-backups/{backup_id}")
def delete_backup(printer_id: int, backup_id: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
    require_confirm(confirm, "Deleting a backup removes its files from the NAS — pass confirm=true to proceed")
    printer = require_printer(db, printer_id)
    with answer_errors():
        backups.delete_backup(db, printer, backup_id)
    return backups.list_backups(db, printer)
