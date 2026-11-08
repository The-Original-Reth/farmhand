"""Deleting exactly the files Farmhand recorded, and tidying the empty folders it made for them: never a recursive delete."""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import Path

from .roots import effective_root

log = logging.getLogger("farmhand.storage")


_VERSION_DIR = re.compile(r"^v\d+(-\d+)?$")  # v3, or v3-2 beside another Farmhand's v3
_ID_DIR = re.compile(r"^\d+$")


def rmdir_if_empty(d: Path) -> bool:
    try:
        d.rmdir()  # only ever succeeds on an empty directory
        return True
    except OSError:
        return False


def is_managed_layout(path: str | None, owner_id: int, version: int) -> bool:
    """
    Is this file where Farmhand itself put it — `.../{owner_id}/v{version}/{file}`? Files found by a scan
    are filed that way too now, but ones imported by earlier versions were registered where they sat, and
    the folders around those belong to the person who made them, so deleting such a file must never tidy
    those folders away.
    """
    if not path:
        return False
    parent = Path(path).parent
    in_version = parent.name == f"v{version}" or re.fullmatch(rf"v{version}-\d+", parent.name) is not None
    return in_version and parent.parent.name == str(owner_id)


def delete_files(paths: Iterable[str | None], prune: bool = True) -> None:
    """
    Delete exactly the files we recorded, then (if `prune`) tidy up the now-empty `v{n}` and `{id}`
    folders we created for them. Never deletes anything else — no recursive removes —
    which matters when the folder is someone's network share.
    """
    folders = {_delete_quietly(Path(p)) for p in paths if p}
    if prune:
        for d in folders:
            _prune_version_folder(d)


def _delete_quietly(path: Path) -> Path:
    """Delete one file (already gone is fine; anything else is logged, not raised). Returns the folder it was in."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Couldn't delete %s: %s", path, e)
    return path.parent


def tidy_project_folder(project_folder: str) -> None:
    """After a project's files were deleted: its docs/, cad/, stl/ and threemf/ folders and its own folder go if they're
    empty (nothing else)."""
    root = effective_root("project") / project_folder
    for d in (root / "docs", root / "cad", root / "stl", root / "threemf", root):
        if d.is_dir():
            rmdir_if_empty(d)


def _prune_version_folder(d: Path) -> None:
    """Remove a `v{n}` folder if it's empty, then its `{id}` folder if that's empty too. Other folders are left alone."""
    if _VERSION_DIR.match(d.name):
        rmdir_if_empty(d)
        if _ID_DIR.match(d.parent.name):
            rmdir_if_empty(d.parent)
