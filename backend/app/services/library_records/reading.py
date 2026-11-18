"""Reading the records back: every model's or 3MF's record in the folder's {id} folders, newest first, and the model
files other Farmhands keep. What the records are called and how big they may be is here too."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy.orm import Session

from ... import record_files, storage
from ...record_files import resolve_from
from ..app_settings import instance_id

log = logging.getLogger("farmhand.library_records")

MODEL_PREFIX = "farmhand-model-"
THREEMF_PREFIX = "farmhand-3mf-"
FORMAT = 1
MAX_RECORD_BYTES = 20_000_000  # a 3MF's record holds every version's slicer settings


def _records(root: Path, prefix: str, marker: str) -> list[tuple[Path, dict]]:
    """Every record of that kind in the folder's {id} folders, (its folder, the record), the newest first: where two
    Farmhands' records describe the same files, the one saved last is brought in."""
    try:
        folders = [Path(e.path) for e in os.scandir(root) if e.is_dir() and not e.name.startswith(".")]
    except OSError:
        return []
    out = []
    for folder in folders:
        for name in record_files.names_in(folder, prefix):
            doc = record_files.read_json(folder / name, MAX_RECORD_BYTES)
            if isinstance(doc, dict) and doc.get(marker) == FORMAT:
                out.append((folder, doc))
    return record_files.newest_first(out, lambda r: r[1])


def files_kept_by_others(db: Session) -> set[str]:
    """Every model file (and preview) in the STL folder another Farmhand keeps: the Models scan leaves them alone."""
    root = storage.effective_root("stl")
    me = instance_id(db)
    kept: set[str] = set()
    for _, doc in _records(root, MODEL_PREFIX, "farmhand_model"):
        if doc.get("instance") == me:
            continue
        for v in doc.get("versions") or []:
            for key in ("path", "preview"):
                p = resolve_from(root, v.get(key)) if isinstance(v, dict) else None
                if p:
                    kept.add(os.path.realpath(p))
    return kept
