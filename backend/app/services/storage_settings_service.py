from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..models import BundleVersion, SourceModelVersion
from . import app_settings, project_files, project_service

KEYS = {"stl": "stl_storage_dir", "threemf": "threemf_storage_dir", "project": "project_storage_dir"}


def _configure(custom: dict[str, str | None]) -> None:
    storage.configure(stl_path=custom["stl"], threemf_path=custom["threemf"], project_path=custom["project"])


def _overlap_message(a: str, b: str) -> str:
    return (
        f"The {storage.FOLDER_LABELS[a]} and {storage.FOLDER_LABELS[b]} locations must be different folders, and neither "
        "can be inside the other — their files are organised by number and would collide."
    )


def apply_saved_locations(db: Session) -> None:
    """Load the chosen locations into the storage module (called at startup)."""
    _configure({kind: app_settings.get(db, key) for kind, key in KEYS.items()})


def count_project_files(db: Session, pick: Callable[[str], bool]) -> int:
    """How many versions of projects' own files (CAD files, STLs) have a file `pick(path)` picks."""
    return sum(1 for v in project_files.all_versions(db) if v.file_path and pick(v.file_path))


def count_version_files(db: Session, stl: Callable[[str], bool], threemf: Callable[[str], bool]) -> tuple[int, int]:
    """
    How many STL versions have a file `stl(path)` picks, and how many 3MF versions have a 3MF or G-code `threemf(path)`
    picks (a 3MF version counts once, whichever of its files it is).
    """
    n_stl = sum(1 for path in db.scalars(select(SourceModelVersion.file_path)) if path and stl(path))
    n_3mf = sum(
        1
        for paths in db.execute(select(BundleVersion.threemf_path, BundleVersion.gcode_path))
        if any(p and threemf(p) for p in paths)
    )
    return n_stl, n_3mf


def _outside(root) -> Callable[[str], bool]:
    """Whether a recorded file's path is outside this folder, by its path alone: the folder is resolved once, the files
    never (each lookup is a round trip to the NAS, and there are hundreds), as recorded paths are absolute already."""
    roots = {os.path.normpath(str(root)), os.path.realpath(str(root))}

    def outside(path: str) -> bool:
        p = os.path.normpath(path)
        return not any(p == r or p.startswith(r.rstrip(os.sep) + os.sep) for r in roots)

    return outside


def _count_outside(db: Session) -> dict:
    n_stl, n_3mf = count_version_files(db, _outside(storage.effective_root("stl")), _outside(storage.effective_root("threemf")))
    return {"stl": n_stl, "threemf": n_3mf, "project": count_project_files(db, _outside(storage.effective_root("project")))}


def describe(db: Session) -> dict:
    def location(kind: str) -> dict:
        return {
            "path": str(storage.effective_root(kind)),
            "default_path": str(storage.default_root(kind)),
            "is_default": storage.custom_path(kind) is None,
            "status": storage.location_status(kind),
        }

    return {
        "browse_root": str(storage.browse_root()),
        "stl": location("stl"),
        "threemf": location("threemf"),
        "project": location("project"),
        "outside": _count_outside(db),
    }


def save(db: Session, changes: dict) -> dict:
    """
    Apply chosen locations. `changes` maps "stl_path"/"threemf_path"/"project_path" to a folder, or
    None to go back to the default; omitted keys are left alone. Everything is
    validated before anything is written, so a bad choice changes nothing.
    """
    chosen: dict[str, Path | None] = {}
    for kind in storage.KINDS:
        field = f"{kind}_path"
        if field in changes:
            raw = changes[field]
            chosen[kind] = storage.validate_location(raw) if raw else None

    def resulting_custom(kind: str) -> str | None:
        if kind in chosen:
            return str(chosen[kind]) if chosen[kind] else None
        return storage.custom_path(kind)

    roots = {k: Path(resulting_custom(k) or storage.default_root(k)) for k in storage.KINDS}
    clash = storage.overlapping_kinds(roots)
    if clash:
        raise ValueError(_overlap_message(*clash))

    for kind, path in chosen.items():
        if path is not None:
            storage.mark_location(path)
        app_settings.put(db, KEYS[kind], str(path) if path else None)
    db.commit()
    _configure({k: resulting_custom(k) for k in storage.KINDS})
    return describe(db)


def restore_locations(
    db: Session, stl_path: str | None, threemf_path: str | None, project_path: str | None = None
) -> tuple[list[str], list[str]]:
    """
    Put the STL/3MF/project files folders from a settings file back. Unlike save(), this doesn't require the folder to exist
    right now: it may live on a share that hasn't reconnected yet. That is safe, because every write still
    checks the folder is really there (and has its marker) first. Returns (what was applied, warnings).
    """
    applied: list[str] = []
    warnings: list[str] = []
    chosen: dict[str, str | None] = {}
    labels = {k: f"{storage.FOLDER_LABELS[k]} folder" for k in storage.KINDS}
    for kind, raw in (("stl", stl_path), ("threemf", threemf_path), ("project", project_path)):
        label = labels[kind]
        if not raw:
            continue
        try:
            chosen[kind] = str(storage.resolve_location(raw))  # must be somewhere folders can be chosen; nothing else is checked
        except ValueError as e:
            warnings.append(f"The {label} was skipped: {e}")

    def resulting(kind: str) -> str | None:
        return chosen.get(kind, storage.custom_path(kind))

    roots = {k: Path(resulting(k) or storage.default_root(k)) for k in storage.KINDS}
    clash = storage.overlapping_kinds(roots) if chosen else None
    if clash:
        a, b = clash
        return [], [f"The {labels[a]} and {labels[b]} in the settings file overlap, so no folder was restored."]

    for kind, path in chosen.items():
        app_settings.put(db, KEYS[kind], path)
        applied.append(labels[kind])
    db.commit()
    _configure({k: resulting(k) for k in storage.KINDS})
    return applied, warnings


def _relocate(old: str | None, root: Path, dest_dir_fn, copies: list[str]) -> tuple[str | None, str | None]:
    """
    Copy `old` into its new home. Returns (new_path, old_path_to_delete), or (None, None)
    if nothing needed moving. Each new copy is recorded in `copies` so a later failure
    for the same version can remove the copies it already made.
    """
    if not old or storage.is_inside(old, root):
        return None, None
    if not os.path.exists(old):
        return None, None
    new = storage.copy_verified(old, dest_dir_fn())
    copies.append(new)
    return new, old


def _move_preview(v, old_file: str, new_file: str, copies: list[str]) -> str | None:
    """The preview kept beside a moved file moves with it. Returns the old preview, to delete, or None if it had none."""
    old_preview = storage.preview_beside(old_file)
    if not os.path.isfile(old_preview):
        return None
    new_preview = storage.copy_verified(old_preview, Path(new_file).parent, name=Path(new_file).name + ".png")
    copies.append(new_preview)
    if v.thumbnail_path == old_preview:
        v.thumbnail_path = new_preview
    return old_preview


def _note_missing(path: str | None, root: Path, label: str, result: dict) -> None:
    """A recorded file outside the location that isn't there any more is reported, not failed."""
    if path and not storage.is_inside(path, root) and not os.path.exists(path):
        result["missing"].append(label)


@contextmanager
def _moving(db: Session, label: str, result: dict):
    """
    One version's move: yields the list its new copies are recorded in. On a failure the database is rolled back and
    those copies removed, so the originals stay readable at their recorded paths; a folder that isn't there stops the
    whole move, any other failure is reported and the next version goes on.
    """
    copies: list[str] = []
    try:
        yield copies
    except storage.StorageUnavailableError:
        db.rollback()
        storage.delete_files(copies)
        raise
    except OSError as e:
        db.rollback()
        storage.delete_files(copies)  # originals are untouched; drop the copies made so far
        result["failed"].append({"name": label, "error": str(e)})


def _migrate_stl(db: Session, v: SourceModelVersion, stl_root: Path, result: dict) -> None:
    label = f"{v.source_model.name} v{v.version}"
    sid, ver = v.source_model_id, v.version
    with _moving(db, label, result) as copies:
        _note_missing(v.file_path, stl_root, label, result)
        managed_before = storage.is_managed_layout(v.file_path, sid, ver)
        new_file, old_file = _relocate(v.file_path, stl_root, lambda: storage.source_model_version_dir(sid, ver), copies)
        if not new_file:
            return
        v.file_path = new_file
        stale = [old_file]
        old_preview = _move_preview(v, old_file, new_file, copies)
        if old_preview:
            stale.append(old_preview)
        db.commit()
        for stale_path in stale:
            storage.delete_files([stale_path], prune=managed_before)  # its emptied folders tidied if Farmhand laid them out
        result["moved_stl"] += 1


def _migrate_bundle(db: Session, v: BundleVersion, threemf_root: Path, thumbs_root: Path, result: dict) -> None:
    label = f"{v.filename} v{v.version}"
    bid, ver = v.bundle_id, v.version
    dest = lambda: storage.bundle_version_dir(bid, ver)  # noqa: E731
    with _moving(db, label, result) as copies:
        stale: list[str] = []
        moved_any = False
        if v.full_files_retained:
            _note_missing(v.threemf_path, threemf_root, label, result)
            new_3mf, old_3mf = _relocate(v.threemf_path, threemf_root, dest, copies)
            if new_3mf:
                v.threemf_path = new_3mf
                stale.append(old_3mf)
                moved_any = True
                old_preview = _move_preview(v, old_3mf, new_3mf, copies)
                if old_preview:
                    stale.append(old_preview)
            new_gcode, old_gcode = _relocate(v.gcode_path, threemf_root, dest, copies)
            if new_gcode:
                v.gcode_path = new_gcode
                stale.append(old_gcode)
                moved_any = True
        elif v.thumbnail_path and not storage.is_inside(v.thumbnail_path, thumbs_root):
            # pruned: its preview stayed where the 3MF was, and moves into the 3MF folder
            new_thumb, old_thumb = _relocate(v.thumbnail_path, threemf_root, dest, copies)
            if new_thumb:
                v.thumbnail_path = new_thumb
                stale.append(old_thumb)
        if stale:
            db.commit()
            storage.delete_files(stale)
            if moved_any:
                result["moved_threemf"] += 1


def _migrate_project_file(db: Session, v, project_root: Path, result: dict) -> None:
    label = f"{v.filename} v{v.version}"
    folder = next(k.folder for k in project_files.KINDS.values() if isinstance(v, k.version_cls))
    pfolder, cid, ver = project_service.project_folder(db, v.file.project_id), v.file.id, v.version
    with _moving(db, label, result) as copies:
        _note_missing(v.file_path, project_root, label, result)
        new_file, old_file = _relocate(
            v.file_path, project_root, lambda: storage.project_file_dir(pfolder, folder, cid, ver), copies
        )
        if not new_file:
            return
        v.file_path = new_file
        stale = [old_file]
        old_preview = _move_preview(v, old_file, new_file, copies)
        if old_preview:
            stale.append(old_preview)
        db.commit()
        storage.delete_files(stale)
        result["moved_project"] += 1


def migrate(db: Session) -> dict:
    """
    Move files that live outside the currently selected locations into them.

    Each file is copied, its size verified, the database updated and committed,
    and only then is the original deleted — so a failure at any point leaves the
    file readable at its recorded path. Each preview moves with its file (it's kept next to it); a pruned 3MF's,
    which stays where the 3MF was, moves into the 3MF folder.
    """
    thumbs_root = storage.thumbnails_root()  # copies from when the app kept its own: moved out by services/previews.py
    stl_root = storage.effective_root("stl")
    threemf_root = storage.effective_root("threemf")
    project_root = storage.effective_root("project")
    result: dict = {"moved_stl": 0, "moved_threemf": 0, "moved_project": 0, "missing": [], "failed": []}
    for v in list(db.scalars(select(SourceModelVersion))):
        _migrate_stl(db, v, stl_root, result)
    for v in list(db.scalars(select(BundleVersion))):
        _migrate_bundle(db, v, threemf_root, thumbs_root, result)
    for v in list(project_files.all_versions(db)):  # each version of a project's own CAD files and STLs
        _migrate_project_file(db, v, project_root, result)
    return result
