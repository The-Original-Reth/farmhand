from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..models import BundleVersion, SourceModelVersion
from . import app_settings

KEYS = {"stl": "stl_storage_dir", "threemf": "threemf_storage_dir"}


def apply_saved_locations(db: Session) -> None:
    """Load the chosen locations into the storage module (called at startup)."""
    storage.configure(stl_path=app_settings.get(db, KEYS["stl"]), threemf_path=app_settings.get(db, KEYS["threemf"]))


def _count_outside(db: Session) -> dict:
    stl_root = storage.effective_root("stl")
    threemf_root = storage.effective_root("threemf")

    n_stl = sum(
        1
        for path in db.scalars(select(SourceModelVersion.file_path))
        if path and not storage.is_inside(path, stl_root)
    )
    n_3mf = 0
    for threemf_path, gcode_path in db.execute(select(BundleVersion.threemf_path, BundleVersion.gcode_path)):
        if any(p and not storage.is_inside(p, threemf_root) for p in (threemf_path, gcode_path)):
            n_3mf += 1
    return {"stl": n_stl, "threemf": n_3mf}


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
        "outside": _count_outside(db),
    }


def save(db: Session, changes: dict) -> dict:
    """
    Apply chosen locations. `changes` maps "stl_path"/"threemf_path" to a folder, or
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
    if storage.overlaps(roots["stl"], roots["threemf"]):
        raise ValueError(
            "The STL and 3MF locations must be different folders, and neither can be inside the other — "
            "their files are organised by number and would collide."
        )

    for kind, path in chosen.items():
        if path is not None:
            storage.mark_location(path)
        app_settings.put(db, KEYS[kind], str(path) if path else None)
    db.commit()
    storage.configure(stl_path=resulting_custom("stl"), threemf_path=resulting_custom("threemf"))
    return describe(db)


def restore_locations(db: Session, stl_path: str | None, threemf_path: str | None) -> tuple[list[str], list[str]]:
    """
    Put the STL/3MF folders from a settings file back. Unlike save(), this doesn't require the folder to exist
    right now: it may live on a share that hasn't reconnected yet. That is safe, because every write still
    checks the folder is really there (and has its marker) first. Returns (what was applied, warnings).
    """
    applied: list[str] = []
    warnings: list[str] = []
    chosen: dict[str, str | None] = {}
    for kind, raw, label in (("stl", stl_path, "STL folder"), ("threemf", threemf_path, "3MF folder")):
        if not raw:
            continue
        try:
            chosen[kind] = str(storage.resolve_location(raw))  # must be somewhere folders can be chosen; nothing else is checked
        except ValueError as e:
            warnings.append(f"The {label} was skipped: {e}")

    def resulting(kind: str) -> str | None:
        return chosen.get(kind, storage.custom_path(kind))

    roots = {k: Path(resulting(k) or storage.default_root(k)) for k in storage.KINDS}
    if chosen and storage.overlaps(roots["stl"], roots["threemf"]):
        return [], ["The STL and 3MF folders in the settings file overlap, so neither was restored."]

    for kind, path in chosen.items():
        app_settings.put(db, KEYS[kind], path)
        applied.append("STL folder" if kind == "stl" else "3MF folder")
    db.commit()
    storage.configure(stl_path=resulting("stl"), threemf_path=resulting("threemf"))
    return applied, warnings


def migrate(db: Session) -> dict:
    """
    Move files that live outside the currently selected locations into them.

    Each file is copied, its size verified, the database updated and committed,
    and only then is the original deleted — so a failure at any point leaves the
    file readable at its recorded path. Thumbnails are brought onto local disk too.
    """
    thumbs_root = storage.thumbnails_root()
    stl_root = storage.effective_root("stl")
    threemf_root = storage.effective_root("threemf")
    result: dict = {"moved_stl": 0, "moved_threemf": 0, "missing": [], "failed": []}

    def relocate(old: str | None, root: Path, dest_dir_fn, copies: list[str]) -> tuple[str | None, str | None]:
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

    for v in list(db.scalars(select(SourceModelVersion))):
        label = f"{v.source_model.name} v{v.version}"
        sid, ver = v.source_model_id, v.version
        copies: list[str] = []
        try:
            if v.file_path and not storage.is_inside(v.file_path, stl_root) and not os.path.exists(v.file_path):
                result["missing"].append(label)
            stale: list[tuple[str, bool]] = []  # (file, may its emptied folders be tidied?)
            managed_before = storage.is_managed_layout(v.file_path, sid, ver)
            new_file, old_file = relocate(
                v.file_path, stl_root, lambda: storage.source_model_version_dir(sid, ver), copies
            )
            if new_file:
                v.file_path = new_file
                stale.append((old_file, managed_before))
                old_preview = storage.preview_beside(old_file)
                if os.path.isfile(old_preview):  # the preview kept with the file moves with it
                    copies.append(storage.copy_verified(old_preview, Path(new_file).parent, name=Path(new_file).name + ".png"))
                    stale.append((old_preview, managed_before))
            new_thumb, old_thumb = relocate(
                v.thumbnail_path, thumbs_root, lambda: storage.source_model_thumbnail_dir(sid, ver), copies
            )
            if new_thumb:
                v.thumbnail_path = new_thumb
                stale.append((old_thumb, True))
            if stale:
                db.commit()
                for stale_path, prune in stale:
                    storage.delete_files([stale_path], prune=prune)
                if new_file:
                    result["moved_stl"] += 1
        except storage.StorageUnavailableError:
            db.rollback()
            storage.delete_files(copies)
            raise
        except OSError as e:
            db.rollback()
            storage.delete_files(copies)  # originals are untouched; drop the copies made so far
            result["failed"].append({"name": label, "error": str(e)})

    for v in list(db.scalars(select(BundleVersion))):
        label = f"{v.filename} v{v.version}"
        bid, ver = v.bundle_id, v.version
        copies = []
        try:
            stale = []
            moved_any = False
            if v.full_files_retained:
                if v.threemf_path and not storage.is_inside(v.threemf_path, threemf_root) and not os.path.exists(v.threemf_path):
                    result["missing"].append(label)
                new_3mf, old_3mf = relocate(
                    v.threemf_path, threemf_root, lambda: storage.bundle_version_dir(bid, ver), copies
                )
                if new_3mf:
                    v.threemf_path = new_3mf
                    stale.append(old_3mf)
                    moved_any = True
                    old_preview = storage.preview_beside(old_3mf)
                    if os.path.isfile(old_preview):  # the preview kept with the 3MF moves with it
                        copies.append(storage.copy_verified(old_preview, Path(new_3mf).parent, name=Path(new_3mf).name + ".png"))
                        stale.append(old_preview)
                new_gcode, old_gcode = relocate(
                    v.gcode_path, threemf_root, lambda: storage.bundle_version_dir(bid, ver), copies
                )
                if new_gcode:
                    v.gcode_path = new_gcode
                    stale.append(old_gcode)
                    moved_any = True
            new_thumb, old_thumb = relocate(
                v.thumbnail_path, thumbs_root, lambda: storage.bundle_thumbnail_dir(bid, ver), copies
            )
            if new_thumb:
                v.thumbnail_path = new_thumb
                stale.append(old_thumb)
            if stale:
                db.commit()
                storage.delete_files(stale)
                if moved_any:
                    result["moved_threemf"] += 1
        except storage.StorageUnavailableError:
            db.rollback()
            storage.delete_files(copies)
            raise
        except OSError as e:
            db.rollback()
            storage.delete_files(copies)  # originals are untouched; drop the copies made so far
            result["failed"].append({"name": label, "error": str(e)})

    return result
