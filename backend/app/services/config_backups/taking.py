"""
Taking a printer config backup (Back up now, or on its own when one is due), and keeping only the newest ones.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shlex
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import storage
from ...models import Printer, PrinterConfigBackup, PrinterConfigBackupFile
from ...timeutil import as_utc, utc_now
from .. import config_service, printer_ssh
from ..moonraker import client
from .common import (
    DATABASE_DIR, DATABASE_FILE, KEEP, MAX_BACKUP_BYTES, TRIGGERS, _backups, _require_klipper, _safe_name, _skip_reason,
)
from .location import _new_folder, backups_folder
from .ssh import _record_ssh


def take_backup(db: Session, printer: Printer, trigger: str = "manual") -> PrinterConfigBackup:
    """Read the printer's config folder and Moonraker database, write them to the NAS, record them, keep the newest KEEP."""
    _require_klipper(printer)
    if trigger not in TRIGGERS:
        raise ValueError(f"Unknown backup trigger: {trigger}")
    backups_folder(db)  # the folder can be written to, before anything is asked of the printer

    files: dict[str, tuple[bytes, float | None]] = {}
    skipped: list[dict] = []
    total = 0
    for f in sorted(client.config_files(printer), key=lambda f: f["path"]):
        reason = _skip_reason(f["path"], f["size"])
        if reason is None and total + f["size"] > MAX_BACKUP_BYTES:
            reason = f"the backup would be bigger than {MAX_BACKUP_BYTES // (1024 * 1024)} MB"
        if reason:
            skipped.append({"path": f["path"], "reason": reason})
            continue
        try:
            data = client.config_file(printer, f["path"])
        except client.MoonrakerError as e:
            if e.kind != "not_found":
                raise
            skipped.append({"path": f["path"], "reason": "gone from the printer before it could be read"})
            continue
        files[f["path"]] = (data, f.get("modified"))
        total += len(data)
    for name, content in client.database_dump(printer).items():
        data = json.dumps(content, indent=2, ensure_ascii=False, default=str).encode("utf-8")
        files[f"{DATABASE_DIR}/{_safe_name(name, 'namespace')}.json"] = (data, None)

    taken_at = utc_now()
    folder = _new_folder(db, printer, taken_at)
    written: list[Path] = []
    try:
        for path, (data, _) in files.items():
            target = folder / Path(*PurePosixPath(path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            storage.write_bytes_atomically(target, data)
            written.append(target)
    except OSError as e:
        _remove_files(folder, [str(p.relative_to(folder).as_posix()) for p in written])
        raise storage.StorageUnavailableError(f"Couldn't write the backup to the printer backups folder ({folder}): {e}") from None

    rows = [
        PrinterConfigBackupFile(path=path, size=len(data), modified=modified, sha256=hashlib.sha256(data).hexdigest())
        for path, (data, modified) in files.items()
    ]
    database = _copy_database(db, printer, folder, taken_at)
    if isinstance(database, PrinterConfigBackupFile):
        rows.append(database)
    else:
        skipped.append({"path": DATABASE_FILE, "reason": database})
    backup = PrinterConfigBackup(
        printer_id=printer.id, taken_at=taken_at, trigger=trigger, folder=str(folder), skipped=skipped,
        file_count=len(rows), total_bytes=sum(f.size for f in rows), files=rows,
    )
    db.add(backup)
    db.commit()
    _keep_newest(db, printer)
    db.refresh(backup)
    return backup


def _copy_database(db: Session, printer: Printer, folder: Path, taken_at: dt.datetime) -> "PrinterConfigBackupFile | str":
    """
    Moonraker's database file, into the backup's folder: Moonraker makes a safe copy of it on the printer
    (POST /server/database/backup), Farmhand copies that over SSH and removes it from the printer. Its row, or why
    there's none (SSH not set up, a Moonraker too old to make copies...): the rest of the backup goes ahead either way.
    """
    try:
        t = printer_ssh.target(printer)
        printer_ssh.run(t, "true")  # SSH works, before Moonraker is asked to make anything
    except (printer_ssh.SshError, client.MoonrakerError) as e:
        if isinstance(e, printer_ssh.SshError):
            _record_ssh(db, printer, None)  # no longer "Tested"
        return f"not copied: {e}"
    _record_ssh(db, printer, t)
    name = f"farmhand-{taken_at:%Y%m%d-%H%M%S}.db"
    try:
        remote = client.backup_database(printer, name)
    except client.MoonrakerError as e:
        if e.kind == "not_found":
            return "not copied: this printer's Moonraker is too old to make a copy of its database"
        return f"not copied: Moonraker couldn't make a copy of its database: {e}"
    local = folder / Path(*PurePosixPath(DATABASE_FILE).parts)
    try:
        local.parent.mkdir(parents=True, exist_ok=True)
        printer_ssh.fetch(t, remote, local)
    except (printer_ssh.SshError, OSError) as e:
        return f"not copied: {e}"
    finally:
        if remote.startswith(f"{t.data_folder}/backup/database/farmhand-"):
            try:
                printer_ssh.run(t, f"rm -f {shlex.quote(remote)}")
            except printer_ssh.SshError:
                pass  # left on the printer: harmless
    digest = hashlib.sha256()
    with open(local, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return PrinterConfigBackupFile(path=DATABASE_FILE, size=local.stat().st_size, modified=None, sha256=digest.hexdigest())


def _keep_newest(db: Session, printer: Printer) -> None:
    rows = _backups(db, printer)
    old = rows[KEEP:]
    if not old:
        return
    gone = [(b.folder, [f.path for f in b.files]) for b in old]
    for b in old:
        db.delete(b)
    db.commit()  # rows first, then the files
    for folder, paths in gone:
        _remove_files(Path(folder), paths)


def _remove_files(folder: Path, paths: list[str]) -> None:
    """Delete exactly these files of a backup, then whichever of its folders that leaves empty (never a recursive delete)."""
    storage.delete_files([str(folder / Path(*PurePosixPath(p).parts)) for p in paths], prune=False)
    dirs = {folder / Path(*PurePosixPath(p).parts[:i]) for p in paths for i in range(1, len(PurePosixPath(p).parts))}
    for d in sorted(dirs, key=lambda d: len(d.parts), reverse=True):
        storage.rmdir_if_empty(d)
    if storage.rmdir_if_empty(folder):
        storage.rmdir_if_empty(folder.parent)  # the printer's folder, once its last backup has gone


def backup_if_due(db: Session, printer: Printer, now: dt.datetime | None = None) -> PrinterConfigBackup | None:
    """
    For the background sync: take an automatic backup if the newest one is `config_backup_days` old (or there's none),
    unless that's switched off (0) or the printer is printing (it waits for the next sync).
    """
    if printer.connection_type == "prusalink":
        return None
    due = next_due_at(db, printer, now)
    if due is None or due > (now or utc_now()):
        return None
    if client.print_state(printer) in ("printing", "paused"):
        return None
    return take_backup(db, printer, "automatic")


def every_days(db: Session) -> int:
    return config_service.get_config(db)["preferences"]["config_backup_days"]


def next_due_at(db: Session, printer: Printer, now: dt.datetime | None = None) -> dt.datetime | None:
    """When the next automatic backup is due (now, if there's none yet); None when automatic backups are off."""
    days = every_days(db)
    if days <= 0:
        return None
    newest = db.scalar(
        select(PrinterConfigBackup.taken_at).where(PrinterConfigBackup.printer_id == printer.id)
        .order_by(PrinterConfigBackup.taken_at.desc()).limit(1)
    )
    return as_utc(newest) + dt.timedelta(days=days) if newest else (now or utc_now())


def set_every_days(db: Session, days: int) -> int:
    if type(days) is not int or not 0 <= days <= 365:
        raise ValueError("Say how many days between automatic backups: a whole number from 1 to 365, or 0 for never.")
    return config_service.save_config(db, {"preferences": {"config_backup_days": days}})["preferences"]["config_backup_days"]
