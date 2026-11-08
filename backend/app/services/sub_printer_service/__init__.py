"""
A printer's printer profiles: its printer presets in PrusaSlicer (BOSS edition), the entries listed under a physical
printer in the Printers tab. Each 3MF version is linked to the one it was sliced with (printer_settings_id); a
printer profile it names that isn't known yet is added. They can be added, renamed and removed by hand too.

In four parts: core.py (the profiles themselves), parts.py, linking.py (3MF versions to their profile) and
records.py (in the settings copy). Everything is used as sub_printer_service.<name>, as before.
"""
from __future__ import annotations

from .core import (
    DEFAULT_PARTS,
    DEFAULT_PART_NAMES,
    MAX_NAME,
    PART_FIELDS,
    add,
    copy,
    copy_name,
    known_as,
    remove,
    rename,
    set_default,
    settings_copy,
)
from .parts import (
    add_part,
    delete_part,
    parts,
    parts_left_out,
    save_parts,
    update_part,
)
from .linking import (
    link,
    link_missing,
    run_link_missing,
)
from .records import (
    record,
    restore,
)

__all__ = [
    "DEFAULT_PARTS",
    "DEFAULT_PART_NAMES",
    "MAX_NAME",
    "PART_FIELDS",
    "add",
    "add_part",
    "copy",
    "copy_name",
    "delete_part",
    "known_as",
    "link",
    "link_missing",
    "parts",
    "parts_left_out",
    "record",
    "remove",
    "rename",
    "restore",
    "run_link_missing",
    "save_parts",
    "set_default",
    "settings_copy",
    "update_part",
]
