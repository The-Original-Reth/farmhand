"""
What the rest of the printer config backups package shares: the limits, what's left out of a backup, safe names,
and finding a printer's backups in the database.
"""
from __future__ import annotations

import fnmatch
import logging
import re
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import storage
from ...errors import NotFound
from ...models import Printer, PrinterConfigBackup
from .. import app_settings

log = logging.getLogger("farmhand.backups")

KEEP = 10
DEFAULT_FOLDER = storage.BACKUP_FOLDER  # in the folder above the STL folder
KEY_LOCATION = app_settings.PRINTER_BACKUPS_DIR_KEY  # the folder chosen in Settings; none = the default
DATABASE_DIR = "moonraker-database"  # the part of a backup that came from Moonraker's database, not its config folder
DATABASE_FILE = f"{DATABASE_DIR}/moonraker-sql.db"  # Moonraker's database itself, copied over SSH when it can be
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_BACKUP_BYTES = 50 * 1024 * 1024
# Left out, as klipper-backup leaves them out: Klipper's own dated copies of printer.cfg, editor and backup leftovers,
# results and archives (big, and not configuration), and Moonraker's own backups folder
SKIP_FOLDERS = {"config_backups", ".git", ".github", "ShakeTune_results", "__pycache__", DATABASE_DIR}
SKIP_NAMES = (
    "*.swp", "*.tmp", "*.bak", "*.bkp", "*.csv", "*.zip", "*.gz", "*.png", "*.jpg", "*.jpeg",
    "printer-[0-9]*_[0-9]*.cfg", ".moonraker.conf.bkp",
)
TRIGGERS = ("manual", "automatic", "before_restore")


def _require_klipper(printer: Printer) -> None:
    if printer.connection_type == "prusalink":
        raise ValueError("PrusaLink printers have no config folder Farmhand can back up.")


def _skip_reason(path: str, size: int) -> str | None:
    parts = PurePosixPath(path).parts
    if not parts or PurePosixPath(path).is_absolute() or ".." in parts or "\\" in path:
        return "an unsafe file name"
    if any(p in SKIP_FOLDERS for p in parts[:-1]):
        return "in a folder that isn't configuration"
    if any(fnmatch.fnmatch(parts[-1], pattern) for pattern in SKIP_NAMES):
        return "a backup, temporary or results file"
    if size > MAX_FILE_BYTES:
        return f"bigger than {MAX_FILE_BYTES // (1024 * 1024)} MB"
    return None


def _safe_name(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ._-]+", "_", name).strip(" .")
    return cleaned[:80] or fallback


def _backups(db: Session, printer: Printer) -> list[PrinterConfigBackup]:
    return list(db.scalars(
        select(PrinterConfigBackup).where(PrinterConfigBackup.printer_id == printer.id)
        .order_by(PrinterConfigBackup.taken_at.desc(), PrinterConfigBackup.id.desc())
    ))


def _require_backup(db: Session, printer: Printer, backup_id: int) -> PrinterConfigBackup:
    b = db.get(PrinterConfigBackup, backup_id)
    if b is None or b.printer_id != printer.id:
        raise NotFound("That backup isn't kept any more.")
    return b


def _previous(rows: list[PrinterConfigBackup], backup: PrinterConfigBackup) -> PrinterConfigBackup | None:
    i = rows.index(backup)
    return rows[i + 1] if i + 1 < len(rows) else None
