"""
Putting a backup back on the printer: one config file, the whole backup (config files and Moonraker settings), or
Moonraker's database. A backup of how things are now is always taken first.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import tempfile
from pathlib import Path, PurePosixPath

from sqlalchemy.orm import Session

from ... import storage
from ...models import Printer, PrinterConfigBackup
from ...timeutil import as_utc, utc_iso, utc_now
from .. import printer_ssh
from ..moonraker import client
from .common import DATABASE_DIR, DATABASE_FILE, _require_backup, _require_klipper, _skip_reason
from .taking import take_backup
from .viewing import _file_row, _read


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
