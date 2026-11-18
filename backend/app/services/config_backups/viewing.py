"""
Looking at a printer's config backups: the list, one backup's files, a file's contents or what changed in it, a zip
of a whole backup, and deleting one.
"""
from __future__ import annotations

import difflib
import io
import zipfile
from pathlib import Path, PurePosixPath

from sqlalchemy.orm import Session

from ... import storage
from ...errors import NotFound
from ...models import Printer, PrinterConfigBackup, PrinterConfigBackupFile
from ...timeutil import as_utc, utc_iso
from .common import DATABASE_DIR, DATABASE_FILE, KEEP, _backups, _previous, _require_backup, _safe_name
from .location import location_info
from .ssh import ssh_status
from .taking import _remove_files, every_days, next_due_at


def _changes(backup: PrinterConfigBackup, previous: PrinterConfigBackup | None) -> dict | None:
    if previous is None:
        return None
    now = {f.path: f.sha256 for f in backup.files}
    before = {f.path: f.sha256 for f in previous.files}
    return {
        "added": sorted(p for p in now if p not in before),
        "changed": sorted(p for p in now if p in before and before[p] != now[p]),
        "removed": sorted(p for p in before if p not in now),
    }


def _summary(backup: PrinterConfigBackup, previous: PrinterConfigBackup | None) -> dict:
    return {
        "id": backup.id, "taken_at": utc_iso(backup.taken_at), "trigger": backup.trigger, "folder": backup.folder,
        "file_count": backup.file_count, "total_bytes": backup.total_bytes, "skipped": backup.skipped or [],
        "has_database": any(f.path == DATABASE_FILE for f in backup.files),
        "previous_id": previous.id if previous else None, "changes": _changes(backup, previous),
    }


def list_backups(db: Session, printer: Printer) -> dict:
    """A printer's backups, newest first, each with what changed since the one before it, and the schedule."""
    if printer.connection_type == "prusalink":
        return {"supported": False, "keep": KEEP, "every_days": every_days(db), "next_due_at": None,
                "folder": None, "ssh": None, "backups": []}
    rows = _backups(db, printer)
    return {
        "supported": True, "keep": KEEP, "every_days": every_days(db),
        "next_due_at": utc_iso(next_due_at(db, printer)), "folder": location_info(db)["path"],
        "ssh": ssh_status(db, printer),
        "backups": [_summary(b, _previous(rows, b)) for b in rows],
    }


def backup_detail(db: Session, printer: Printer, backup_id: int) -> dict:
    """One backup's files, each saying whether it was added or changed since the backup before (or is the same)."""
    rows = _backups(db, printer)
    backup = _require_backup(db, printer, backup_id)
    previous = _previous(rows, backup)
    before = {f.path: f.sha256 for f in previous.files} if previous else None
    files = [{
        "path": f.path, "size": f.size, "modified": f.modified, "database": f.path.startswith(f"{DATABASE_DIR}/"),
        "change": None if before is None else "added" if f.path not in before else "changed" if before[f.path] != f.sha256 else "same",
    } for f in backup.files]
    return {**_summary(backup, previous), "files": files}


def _file_row(backup: PrinterConfigBackup, path: str) -> PrinterConfigBackupFile:
    for f in backup.files:
        if f.path == path:
            return f
    raise NotFound(f"{path} isn't in that backup.")


def _read(backup: PrinterConfigBackup, path: str) -> bytes:
    target = Path(backup.folder) / Path(*PurePosixPath(path).parts)
    try:
        return target.read_bytes()
    except OSError:
        raise storage.StorageUnavailableError(
            f"{path} from this backup can't be read from its folder ({backup.folder}). If it's on a network share, check "
            "that the share is mounted, and that the file hasn't been removed from the folder."
        ) from None


def read_file(db: Session, printer: Printer, backup_id: int, path: str) -> tuple[bytes, str]:
    """(contents, the file's own name) of one file of a backup, for a download."""
    backup = _require_backup(db, printer, backup_id)
    _file_row(backup, path)
    return _read(backup, path), PurePosixPath(path).name


def _as_text(data: bytes) -> str | None:
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def view_file(db: Session, printer: Printer, backup_id: int, path: str) -> dict:
    data, _ = read_file(db, printer, backup_id, path)
    text = _as_text(data)
    return {"path": path, "size": len(data), "binary": text is None, "text": text}


def diff_file(db: Session, printer: Printer, backup_id: int, path: str) -> dict:
    """How one file of a backup differs from the same file in the backup before it, as a unified diff."""
    rows = _backups(db, printer)
    backup = _require_backup(db, printer, backup_id)
    row = _file_row(backup, path)
    previous = _previous(rows, backup)
    out = {"path": path, "previous_id": previous.id if previous else None,
           "previous_taken_at": utc_iso(previous.taken_at) if previous else None, "binary": False, "diff": None, "change": None}
    if previous is None:
        return out
    before_row = next((f for f in previous.files if f.path == path), None)
    out["change"] = "added" if before_row is None else "same" if before_row.sha256 == row.sha256 else "changed"
    if out["change"] == "same":
        out["diff"] = ""
        return out
    now = _as_text(_read(backup, path))
    before = "" if before_row is None else _as_text(_read(previous, path))
    if now is None or before is None:
        out["binary"] = True
        return out
    out["diff"] = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), now.splitlines(keepends=True),
        fromfile=f"{path} (before)", tofile=f"{path} (this backup)",
    ))
    return out


def zip_backup(db: Session, printer: Printer, backup_id: int) -> tuple[bytes, str]:
    """A whole backup as one zip: (its bytes, its file name)."""
    backup = _require_backup(db, printer, backup_id)
    top = f"{_safe_name(printer.name, f'printer-{printer.id}')}-{as_utc(backup.taken_at).strftime('%Y-%m-%d_%H-%M-%S')}"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for f in backup.files:
            z.writestr(f"{top}/{f.path}", _read(backup, f.path))
    return buffer.getvalue(), f"{top}.zip"


def delete_backup(db: Session, printer: Printer, backup_id: int) -> None:
    backup = _require_backup(db, printer, backup_id)
    folder, paths = Path(backup.folder), [f.path for f in backup.files]
    db.delete(backup)
    db.commit()  # the row first, then exactly its files
    _remove_files(folder, paths)
