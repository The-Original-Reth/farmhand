"""
Backups of each Klipper printer's configuration, kept on the NAS.

A backup is every file in the printer's config folder (printer.cfg, moonraker.conf, macros, includes...), read from its
Moonraker with GET requests only, plus what its Moonraker keeps in its database (the whole print history and totals,
and every namespace it hands out: Mainsail's settings, maintenance...), saved as JSON under moonraker-database/.

The files go in the printer backups folder: by default "backup" in the Farmhand folder (the one above the STL folder,
beside farm-cost and farmhand-configs, so on the NAS when that's where the STL folder is), or one chosen on the Settings
page like the other save locations. Each is <folder>/<printer name>/<YYYY-MM-DD_HH-MM-SS>/..., and the database only
records what each backup holds (path, size, a fingerprint), so two backups can be compared.
The newest KEEP per printer are kept: taking one more deletes the oldest (its rows first, then exactly its files).

One is taken with Back up now, and on its own every `config_backup_days` days (a preference, 30 to start; 0 = never)
by the printer sync in the background, never while the printer is printing. A single config file can be put back on
the printer, or a whole backup with Restore (every config file and Moonraker setting that differs from the printer's
now; nothing is deleted). Farmhand takes a backup of how things are first, so a restore can itself be undone.
"""
from __future__ import annotations

import datetime as dt
import difflib
import fnmatch
import hashlib
import io
import os
import json
import logging
import re
import shlex
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..errors import NotFound
from ..models import Printer, PrinterConfigBackup, PrinterConfigBackupFile
from ..timeutil import as_utc, utc_iso, utc_now
from . import app_settings, config_service, printer_ssh
from .moonraker import client

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


# ------------------------------------------------------------------ where they're kept


def default_folder() -> Path:
    """The printer backups folder when none is chosen: "backup" in the folder above the STL / OBJ / STEP folder."""
    return storage.named_folder(storage.effective_root("stl").parent, DEFAULT_FOLDER)


def _chosen(db: Session) -> str | None:
    return app_settings.get(db, KEY_LOCATION)


def backups_folder(db: Session) -> Path:
    """
    Where a new backup goes, only while it can be written: a chosen folder still has its marker, the default's STL
    folder is ready. So an unmounted share never gets a backup on the local disk underneath it
    (StorageUnavailableError otherwise).
    """
    chosen = _chosen(db)
    if chosen:
        return storage.ensure_ready_folder(chosen, "printer backups folder")
    folder = storage.named_folder(storage.ready_root("stl").parent, DEFAULT_FOLDER)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def location_info(db: Session) -> dict:
    """For Settings: {path, is_default, default_path, status: {exists, writable, marker_ok, ready}}."""
    chosen = _chosen(db)
    default = default_folder()
    if chosen:
        return {"path": chosen, "is_default": False, "default_path": str(default), "status": storage.folder_status(Path(chosen))}
    try:
        storage.ready_root("stl")
        ready = True
    except storage.StorageUnavailableError:
        ready = False
    status = {"exists": default.is_dir(), "writable": ready, "marker_ok": ready, "ready": ready}  # made when first used
    return {"path": str(default), "is_default": True, "default_path": str(default), "status": status}


def set_location(db: Session, raw: str | None) -> dict:
    """
    Choose the printer backups folder (None or "" = back to the default). A chosen folder must be one that lasts (on a
    connected share or in Farmhand's own storage) and can be written; it gets Farmhand's marker. ValueError says why
    one can't be used. Backups already taken stay where they are (each knows its own folder).
    """
    if raw and raw.strip():
        real = storage.validate_location(raw.strip())
        storage.mark_location(real)
        app_settings.put(db, KEY_LOCATION, str(real))
    else:
        app_settings.put(db, KEY_LOCATION, None)
    db.commit()
    return location_info(db)


def _new_folder(db: Session, printer: Printer, taken_at: dt.datetime) -> Path:
    base = backups_folder(db) / _safe_name(printer.name, f"printer-{printer.id}")
    stamp = taken_at.strftime("%Y-%m-%d_%H-%M-%S")
    folder, n = base / stamp, 1
    while folder.exists():  # two in one second, or another Farmhand sharing the folder
        n += 1
        folder = base / f"{stamp}-{n}"
    return folder


# ------------------------------------------------------------------ taking one


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
    database = _copy_database(printer, folder, taken_at)
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


def _copy_database(printer: Printer, folder: Path, taken_at: dt.datetime) -> "PrinterConfigBackupFile | str":
    """
    Moonraker's database file, into the backup's folder: Moonraker makes a safe copy of it on the printer
    (POST /server/database/backup), Farmhand copies that over SSH and removes it from the printer. Its row, or why
    there's none (SSH not set up, a Moonraker too old to make copies...): the rest of the backup goes ahead either way.
    """
    try:
        t = printer_ssh.target(printer)
        printer_ssh.run(t, "true")  # SSH works, before Moonraker is asked to make anything
    except (printer_ssh.SshError, client.MoonrakerError) as e:
        return f"not copied: {e}"
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


# ------------------------------------------------------------------ looking at them


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
                "folder": None, "backups": []}
    rows = _backups(db, printer)
    return {
        "supported": True, "keep": KEEP, "every_days": every_days(db),
        "next_due_at": utc_iso(next_due_at(db, printer)), "folder": location_info(db)["path"],
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


# ------------------------------------------------------------------ putting a file back


RESTART = "Restart Klipper (FIRMWARE_RESTART, or Restart in Mainsail) for it to take effect."


def _not_printing(printer: Printer) -> None:
    if client.print_state(printer) in ("printing", "paused"):
        raise ValueError(f"{printer.name} is printing. Put files back once the print has finished.")


# Moonraker namespaces never written back: kept by Moonraker itself, or rebuilt by it (file metadata, update state)
NOT_RESTORED_NAMESPACES = {"history", "moonraker", "gcode_metadata", "update_manager", "announcements"}


def _namespaces(backup: PrinterConfigBackup) -> dict[str, dict]:
    """The Moonraker namespaces a backup holds that a restore writes back: {namespace: {key: value}}."""
    out = {}
    for f in backup.files:
        if not (f.path.startswith(f"{DATABASE_DIR}/") and f.path.endswith(".json")):
            continue
        try:
            saved = json.loads(_read(backup, f.path))
        except ValueError:
            continue
        ns = saved.get("namespace") if isinstance(saved, dict) else None
        if isinstance(ns, str) and ns not in NOT_RESTORED_NAMESPACES and isinstance(saved.get("value"), dict):
            out[ns] = saved["value"]
    return out


def _restore_plan(printer: Printer, backup: PrinterConfigBackup) -> dict:
    """
    What a restore would change, compared with the printer as it is now (read with GETs only):
      files: {put_back: [paths that differ or are gone from it], same: n, read_only: [paths it won't let be changed]}
      settings: [{namespace, keys: [keys whose value differs or is missing]}] (Moonraker's database, e.g. Mainsail's)
      left_alone: [config files on the printer now that aren't in the backup: never deleted]
    plus what's needed to do it (_files, _settings).
    """
    wanted = {f.path: f for f in backup.files if not f.path.startswith(f"{DATABASE_DIR}/")}
    on_printer = {f["path"]: f for f in client.config_files(printer)}
    put_back, same, locked = [], 0, []
    for path, row in sorted(wanted.items()):
        listed = on_printer.get(path)
        if listed is not None and listed["size"] == row.size and hashlib.sha256(client.config_file(printer, path)).hexdigest() == row.sha256:
            same += 1
        elif listed is not None and not listed["writable"]:
            locked.append(path)
        else:
            put_back.append(path)
    over_ssh, read_only = [], locked
    if locked and printer_ssh.check(printer)["ok"]:
        over_ssh, read_only = locked, []
    settings = []
    namespaces = _namespaces(backup)
    for ns, saved in sorted(namespaces.items()):
        now = client.database_namespace(printer, ns)
        keys = sorted(k for k, v in saved.items() if now.get(k, _MISSING) != v)
        if keys:
            settings.append({"namespace": ns, "keys": keys})
    left_alone = sorted(p for p in on_printer if p not in wanted and _skip_reason(p, on_printer[p]["size"]) is None)
    return {
        "files": {"put_back": put_back, "over_ssh": over_ssh, "same": same, "read_only": read_only},
        "settings": settings, "left_alone": left_alone,
        "_settings": {s["namespace"]: {k: namespaces[s["namespace"]][k] for k in s["keys"]} for s in settings},
    }


_MISSING = object()


def _public(plan: dict) -> dict:
    return {k: v for k, v in plan.items() if not k.startswith("_")}


def restore_preview(db: Session, printer: Printer, backup_id: int) -> dict:
    """What Restore would change on the printer, without changing anything."""
    _require_klipper(printer)
    backup = _require_backup(db, printer, backup_id)
    return {"backup_id": backup.id, "taken_at": utc_iso(backup.taken_at), **_public(_restore_plan(printer, backup))}


def restore_backup(db: Session, printer: Printer, backup_id: int) -> dict:
    """
    Put a whole backup back on the printer: each config file in it that differs from the printer's now (or is gone from
    it) is written back, and each Moonraker setting (Mainsail's, maintenance...) that differs. Nothing is deleted:
    files added on the printer since stay. Read-only files (links such as mainsail.cfg) are left alone, and Moonraker's
    print history can't be written back. Refused while printing. A backup of how things are now is taken first. A file
    or setting that can't be written is reported and the rest still go back. Klipper isn't restarted.
    """
    _require_klipper(printer)
    backup = _require_backup(db, printer, backup_id)
    taken_at = backup.taken_at
    _not_printing(printer)
    plan = _restore_plan(printer, backup)
    data = {path: _read(backup, path) for path in plan["files"]["put_back"]}  # all read before anything is written
    locked = {path: _read(backup, path) for path in plan["files"]["over_ssh"]}
    safety = take_backup(db, printer, "before_restore")
    restored, failed = [], []
    for path, content in data.items():
        try:
            client.put_config_file(printer, path, content)
            restored.append(path)
        except client.MoonrakerError as e:
            if e.kind in ("unreachable", "no_address", "unauthorized"):
                raise
            failed.append({"path": path, "error": str(e)})
    for path, content in locked.items():
        try:
            _write_over_ssh(printer, path, content)
            restored.append(path)
        except (printer_ssh.SshError, ValueError) as e:
            failed.append({"path": path, "error": str(e)})
    settings_written = 0
    for ns, items in plan["_settings"].items():
        for key, value in items.items():
            try:
                client.put_database_item(printer, ns, key, value)
                settings_written += 1
            except client.MoonrakerError as e:
                if e.kind in ("unreachable", "no_address", "unauthorized"):
                    raise
                failed.append({"path": f"{ns}: {key}", "error": str(e)})
    parts = []
    if restored:
        parts.append(f"{plural(len(restored), 'config file')} put back")
    if settings_written:
        parts.append(f"{plural(settings_written, 'Moonraker setting')} put back")
    if parts:
        message = f"{' and '.join(parts)} on {printer.name}, as in the backup of {as_utc(taken_at):%Y-%m-%d %H:%M} UTC."
        if restored:
            message += f" {RESTART}"
        if settings_written:
            message += " Reload Mainsail's page to see its settings."
    else:
        message = f"Nothing to put back: {printer.name} is already as it was in that backup."
    if failed:
        message += f" {plural(len(failed), 'item')} couldn't be written: see below."
    return {
        "from_backup_taken_at": as_utc(taken_at).isoformat(), "safety_backup_id": safety.id, "restored": restored,
        "settings_written": settings_written, "failed": failed, "message": message, **_public(plan),
    }


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _write_over_ssh(printer: Printer, path: str, content: bytes) -> None:
    """
    Write a config file Moonraker holds read-only (mainsail.cfg: a link into Mainsail's mainsail-config package) where
    it really is, over SSH: the link stays. Only ever a file inside the printer user's home folder.
    """
    t = printer_ssh.target(printer)
    linked = f"{t.data_folder}/config/{path}"
    real = printer_ssh.run(t, f"readlink -f {shlex.quote(linked)}").strip()
    home = f"/home/{t.user}/"
    if not real.startswith(home) or " " in real:
        raise ValueError(f"{path} is really {real or 'nowhere'}, outside {home}: Farmhand won't write it.")
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(content)
    try:
        printer_ssh.send(t, Path(tmp.name), real)
    finally:
        os.unlink(tmp.name)


def restore_database(db: Session, printer: Printer, backup_id: int) -> dict:
    """
    Put Moonraker's database back as it was in a backup (print history, Mainsail's settings, maintenance, everything
    in it): the copy is sent over SSH to the printer's backup/database folder and Moonraker restores it
    (POST /server/database/restore), then restarts itself. Refused while printing. A backup of how things are now is
    taken first (with its own database copy), so this can be undone the same way.
    """
    _require_klipper(printer)
    backup = _require_backup(db, printer, backup_id)
    if not any(f.path == DATABASE_FILE for f in backup.files):
        raise ValueError("This backup has no copy of Moonraker's database: SSH to the printer wasn't set up when it was taken.")
    taken_at = backup.taken_at
    local = Path(backup.folder) / Path(*PurePosixPath(DATABASE_FILE).parts)
    if not local.is_file():
        raise storage.StorageUnavailableError(f"The database copy of this backup can't be read from its folder ({backup.folder}).")
    _not_printing(printer)
    t = printer_ssh.target(printer)
    printer_ssh.run(t, "true")
    safety = take_backup(db, printer, "before_restore")
    name = f"farmhand-restore-{utc_now():%Y%m%d-%H%M%S}.db"
    folder = f"{t.data_folder}/backup/database"
    printer_ssh.run(t, f"mkdir -p {shlex.quote(folder)}")
    printer_ssh.send(t, local, f"{folder}/{name}")
    try:
        client.restore_database(printer, name)
    finally:
        try:
            printer_ssh.run(t, f"rm -f {shlex.quote(folder + '/' + name)}")
        except printer_ssh.SshError:
            pass
    return {
        "from_backup_taken_at": as_utc(taken_at).isoformat(), "safety_backup_id": safety.id,
        "message": f"Moonraker's database on {printer.name} is back as it was in the backup of {as_utc(taken_at):%Y-%m-%d %H:%M} UTC "
                   "(print history, Mainsail's settings, maintenance). Moonraker restarts itself now; Mainsail reconnects "
                   "in a few seconds.",
    }


def restore_file(db: Session, printer: Printer, backup_id: int, path: str) -> dict:
    """
    Put one config file of a backup back on the printer, replacing the one there. Refused while it's printing. A
    backup of how things are now is taken first. Klipper only reads its config when it restarts: that's left to the
    person, as Farmhand never restarts a printer.
    """
    _require_klipper(printer)
    if path.startswith(f"{DATABASE_DIR}/"):
        raise ValueError("What came from Moonraker's database can be downloaded, but not put back on the printer.")
    backup = _require_backup(db, printer, backup_id)
    _file_row(backup, path)
    taken_at = backup.taken_at
    data = _read(backup, path)
    _not_printing(printer)
    listed = next((f for f in client.config_files(printer) if f["path"] == path), None)
    safety = take_backup(db, printer, "before_restore")
    if listed is not None and not listed["writable"]:
        _write_over_ssh(printer, path, data)  # read-only to Moonraker: written where it really is, over SSH
    else:
        client.put_config_file(printer, path, data)
    when = as_utc(taken_at).isoformat()
    return {
        "path": path, "from_backup_taken_at": when, "safety_backup_id": safety.id,
        "message": f"{path} is back on {printer.name} as it was in that backup. {RESTART}",
    }
