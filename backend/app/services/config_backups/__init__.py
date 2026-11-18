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

The package: common.py (limits, what's left out, finding backups), location.py (where they're kept), ssh.py (SSH
tested or not), taking.py (taking one, the schedule), viewing.py (looking at them, deleting one) and restoring.py
(putting a file, a backup or Moonraker's database back).
"""
from .common import (  # noqa: F401
    DATABASE_DIR, DATABASE_FILE, DEFAULT_FOLDER, KEEP, KEY_LOCATION, MAX_BACKUP_BYTES, MAX_FILE_BYTES, SKIP_FOLDERS,
    SKIP_NAMES, TRIGGERS, _backups, _previous, _require_backup, _require_klipper, _safe_name, _skip_reason, log,
)
from .location import _chosen, _new_folder, backups_folder, default_folder, location_info, set_location  # noqa: F401
from .ssh import _record_ssh, ssh_status, test_ssh  # noqa: F401
from .taking import (  # noqa: F401
    _copy_database, _keep_newest, _remove_files, backup_if_due, every_days, next_due_at, set_every_days, take_backup,
)
from .viewing import (  # noqa: F401
    _as_text, _changes, _file_row, _read, _summary, backup_detail, delete_backup, diff_file, list_backups, read_file,
    view_file, zip_backup,
)
from .restoring import (  # noqa: F401
    _MISSING, NOT_RESTORED_NAMESPACES, RESTART, _namespaces, _not_printing, _public, _restore_plan, _write_over_ssh,
    plural, restore_backup, restore_database, restore_file, restore_preview,
)
