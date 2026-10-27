from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..errors import NotFound
from .. import notes as notes_helper
from ..notes import NotesConflict  # noqa: F401  (raised by set_notes)
from .. import scanner, storage
from . import bundle_service
from ..models import SourceFileType, SourceModel, SourceModelNote, SourceModelVersion
from ..thumbnails.stl_render import render_stl_thumbnail

log = logging.getLogger("farmhand.source_models")


def list_source_models(db: Session) -> list[SourceModel]:
    # its versions and notes loaded a batch at a time, not two queries per model
    return list(db.scalars(select(SourceModel).order_by(SourceModel.name).options(selectinload(SourceModel.versions), selectinload(SourceModel.note_row))))


def get_source_model(db: Session, source_model_id: int) -> SourceModel | None:
    return db.get(SourceModel, source_model_id)


def get_source_model_version(db: Session, source_model_id: int, version: int) -> SourceModelVersion | None:
    return db.scalar(
        select(SourceModelVersion).where(
            SourceModelVersion.source_model_id == source_model_id,
            SourceModelVersion.version == version,
        )
    )


def create_source_model(
    db: Session, *, name: str, file_type: SourceFileType, file_obj=None, note: str | None = None
) -> SourceModel:
    """
    Create a new source model 'folder'. The geometry file is optional at
    creation time — per the upload flow, a new STL folder can be created
    from within a 3MF upload without the file being available yet, and
    filled in later via add_source_model_version.
    """
    model = SourceModel(name=name, file_type=file_type)
    db.add(model)
    db.flush()  # get model.id before writing files

    if file_obj is not None:
        add_source_model_version(db, source_model_id=model.id, file_obj=file_obj, filename=name, note=note)

    db.commit()
    db.refresh(model)
    return model


def add_source_model_version(
    db: Session, *, source_model_id: int, file_obj, filename: str, note: str | None = None
) -> SourceModelVersion:
    model = get_source_model(db, source_model_id)
    if model is None:
        raise NotFound(f"No source model with id {source_model_id}")

    next_version = (model.latest_version.version + 1) if model.latest_version else 1
    dest_dir = storage.source_model_version_dir(source_model_id, next_version)
    file_path = storage.save_upload(dest_dir, filename, file_obj)

    thumbnail_path = None
    if model.file_type == SourceFileType.stl:
        # Real for STL (binary); OBJ/STEP auto-thumbnailing isn't built yet
        # (STEP is explicitly deferred per spec; OBJ just hasn't been
        # gotten to) — fails soft rather than blocking the upload either way.
        thumb_bytes = render_stl_thumbnail(file_path)
        if thumb_bytes:
            thumb_dir = storage.source_model_thumbnail_dir(source_model_id, next_version)
            thumbnail_path = storage.save_bytes(thumb_dir, "thumbnail.png", thumb_bytes)
            storage.save_preview_beside(file_path, thumb_bytes)  # and a copy with the STL, on the NAS if it's there

    version = SourceModelVersion(
        source_model_id=source_model_id,
        version=next_version,
        file_path=file_path,
        thumbnail_path=thumbnail_path,
        note=note,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def delete_source_model_version(db: Session, source_model_id: int, version: int) -> None:
    """Delete one version's file. The folder stays, even if that was its only version."""
    v = get_source_model_version(db, source_model_id, version)
    if v is None:
        raise NotFound(f"No version {version} of source model {source_model_id}")
    file_path, thumbnail_path = v.file_path, v.thumbnail_path
    managed = storage.is_managed_layout(file_path, v.source_model_id, v.version)
    db.delete(v)
    db.commit()
    # a scanned-in file's folders are the owner's, not ours; its preview beside it goes with it
    storage.delete_files([file_path, storage.preview_beside(file_path)], prune=managed)
    storage.delete_files([thumbnail_path])


def delete_source_model(db: Session, source_model_id: int, cascade: bool = False) -> list[int]:
    """
    Delete a source model folder and all its versions' files.

    3MF bundles sliced from several models (mixed plates) just lose their link
    to this one. A bundle sliced ONLY from this model would be left with no
    source at all: those are refused unless cascade=True, in which case they
    are deleted too. Returns the ids of any bundles deleted that way.
    """
    model = get_source_model(db, source_model_id)
    if model is None:
        raise NotFound(f"No source model with id {source_model_id}")

    exclusive = [
        b for b in bundle_service.list_bundles_for_source_model(db, source_model_id)
        if len(b.source_model_links) == 1
    ]
    if exclusive and not cascade:
        names = ", ".join(
            (b.latest_version.filename if b.latest_version else f"bundle {b.id}") for b in exclusive
        )
        raise ValueError(
            f"{len(exclusive)} 3MF file(s) were sliced only from this model ({names}). "
            "Delete those first, or delete with cascade to remove them too."
        )

    deleted_bundle_ids = [b.id for b in exclusive]
    for bundle_id in deleted_bundle_ids:
        bundle_service.delete_bundle(db, bundle_id)

    model = get_source_model(db, source_model_id)  # re-fetch: the commits above expired it
    doomed = [
        (v.file_path, storage.is_managed_layout(v.file_path, v.source_model_id, v.version), v.thumbnail_path)
        for v in model.versions
    ]
    db.delete(model)
    db.commit()
    for file_path, managed, thumbnail_path in doomed:
        storage.delete_files([file_path, storage.preview_beside(file_path)], prune=managed)
        storage.delete_files([thumbnail_path])
    return deleted_bundle_ids


# ------------------------------------------------------------------ redrawing previews


def regenerate_thumbnail(db: Session, source_model_id: int, version: int) -> bool:
    """
    Redraw a version's preview from its file with the current renderer — for previews made by an
    older renderer (the first one thinned detailed models, leaving them see-through). Returns False
    when there's nothing to draw (not an STL, or the file can't be read as one).

    Raises ValueError if the file isn't reachable (e.g. it's on a share that isn't connected): a
    redraw must never replace a preview with nothing.
    """
    v = get_source_model_version(db, source_model_id, version)
    if v is None:
        raise NotFound(f"No version {version} of source model {source_model_id}")
    if v.source_model.file_type != SourceFileType.stl:
        return False
    if not os.path.isfile(v.file_path):
        raise ValueError(
            "The model file isn't available right now. If it's on a network share, check that the share is connected."
        )
    image = render_stl_thumbnail(v.file_path)
    if not image:
        return False  # keep whatever preview there was
    storage.save_preview_beside(v.file_path, image)
    new_path = storage.save_bytes(storage.source_model_thumbnail_dir(source_model_id, version), "thumbnail.png", image)
    old_path = v.thumbnail_path
    if old_path != new_path:
        v.thumbnail_path = new_path
        db.commit()
        if old_path:
            storage.delete_files([old_path])  # an older preview that lived beside the model file
    return True


# ------------------------------------------------------------------ scanning the STL folder

SCAN_NOTE = "Found by scanning the STL folder"
_FILE_TYPES = {"STL": SourceFileType.stl, "OBJ": SourceFileType.obj, "STEP": SourceFileType.step}
MAX_PATH_LENGTH = 500  # source_model_versions.file_path is a String(500)


def _known_paths(db: Session) -> set[str]:
    return {scanner.normalise(p) for p in db.scalars(select(SourceModelVersion.file_path)) if p}


def scan_for_new_files(db: Session) -> dict:
    """
    Look through the STL folder for model files that aren't in the library yet — e.g. ones copied
    onto the NAS from another computer. Read-only: nothing is added until import_scanned_files.

    Raises StorageUnavailableError if the folder looks unmounted: reporting "nothing new" about
    a share that simply isn't there would be misleading.
    """
    root = storage.ready_root("stl")
    files, truncated = scanner.scan_folder(root, _known_paths(db))
    in_library = {name.casefold() for name in db.scalars(select(SourceModel.name))}
    return {
        "root": str(root),
        "truncated": truncated,
        "files": [
            {
                "path": f.path,
                "name": f.name,
                "folder": f.folder,
                "size_bytes": f.size_bytes,
                "file_type": f.file_type,
                "name_in_library": f.name.casefold() in in_library,  # likely a duplicate worth a second look
            }
            for f in files
        ],
    }


def _folder_label(full: str, root: Path) -> str:
    """Where a scanned file was, relative to the STL folder — kept in the version's note so it isn't forgotten."""
    rel = os.path.relpath(os.path.dirname(full), root)
    return "the top level of the STL folder" if rel == "." else rel.replace(os.sep, "/")


def import_scanned_file(db: Session, path: str) -> SourceModel:
    """
    Add one file found in the STL folder to the library, and FILE IT the way an upload is filed: moved into
    `{STL folder}/{model id}/v1/{name}`. The folders it was found in are left exactly as they are (even if
    that empties them), and the version's note records where it came from.

    The order matters, because this relocates a file someone owns: the preview is drawn from the original,
    the file is moved, then the database row is saved. If any step fails the file is put back where it was and
    nothing is left behind, so a failure never loses a file or leaves a record pointing at nothing.
    (The path comes from the browser, so it's checked all over again here; it is never trusted.)
    """
    root = storage.ready_root("stl")
    full = scanner.normalise(path)
    name = os.path.basename(full)

    if not storage.is_inside(full, root):
        raise ValueError("That file isn't in the STL folder.")
    file_type = scanner.file_type_for(name)
    if file_type is None:
        raise ValueError("That isn't an STL, OBJ or STEP file.")
    if os.path.islink(full) or not os.path.isfile(full):
        raise ValueError("That file isn't there any more.")
    if full in _known_paths(db):
        raise ValueError("That file is already in the library.")

    where = _folder_label(full, root)
    model = SourceModel(name=name, file_type=_FILE_TYPES[file_type])
    db.add(model)
    db.flush()  # the id names the folder it will be filed in

    thumbnail_path = thumb_bytes = None
    if file_type == "STL":
        thumb_bytes = render_stl_thumbnail(full)  # fails soft: no preview is better than no import
        if thumb_bytes:
            thumb_dir = storage.source_model_thumbnail_dir(model.id, 1)
            thumbnail_path = storage.save_bytes(thumb_dir, "thumbnail.png", thumb_bytes)

    dest_dir: Path | None = None
    moved_to: str | None = None
    try:
        dest_dir = storage.source_model_version_dir(model.id, 1)
        if len(str(dest_dir / name)) > MAX_PATH_LENGTH:
            raise ValueError(
                f"The file's name is too long for Farmhand to store it ({len(str(dest_dir / name))} characters in its path; "
                f"the limit is {MAX_PATH_LENGTH})."
            )
        moved_to = storage.move_file(full, dest_dir)
        db.add(
            SourceModelVersion(
                source_model_id=model.id, version=1, file_path=moved_to, thumbnail_path=thumbnail_path,
                note=f"{SCAN_NOTE} — moved here from {where}",
            )
        )
        db.commit()
        if thumb_bytes:
            storage.save_preview_beside(moved_to, thumb_bytes)
    except BaseException as e:
        db.rollback()
        if moved_to is not None:  # moved, but the record couldn't be saved: put the file back where it was
            try:
                storage.move_file(moved_to, os.path.dirname(full), name)
            except OSError:
                log.error("Couldn't put %s back at %s after a failed import; it is safe at %s", name, full, moved_to)
        if dest_dir is not None:
            storage._rmdir_if_empty(dest_dir)
            storage._rmdir_if_empty(dest_dir.parent)
        if thumbnail_path:
            storage.delete_files([thumbnail_path])
        if isinstance(e, OSError):
            reason = e.strerror or str(e)
            raise ValueError(
                f"Couldn't move {name} into Farmhand's folders ({reason}). It was left where it is and not added."
            ) from e
        raise
    db.refresh(model)
    return model


def import_scanned_files(db: Session, paths: list[str]) -> list[dict]:
    """Import each file on its own, so one bad file doesn't undo or block the rest."""
    results = []
    for path in paths:
        try:
            model = import_scanned_file(db, path)
            results.append({"path": path, "ok": True, "error": None, "source_model_id": model.id})
        except storage.StorageUnavailableError:
            db.rollback()
            raise  # nothing further can work; let the caller explain
        except (ValueError, OSError) as e:
            db.rollback()
            results.append({"path": path, "ok": False, "error": str(e), "source_model_id": None})
    return results


# ------------------------------------------------------------------ notes about a model

MAX_NOTES_LENGTH = notes_helper.MAX_NOTES_LENGTH


def rename(db: Session, source_model_id: int, name: str) -> SourceModel:
    """
    Change the name a model is shown, searched and downloaded by; its extension (.stl, .obj, .step) always stays.
    Its stored file keeps its own name.
    """
    from ..names import TYPE_EXTENSIONS, clean_file_name, extension_of

    model = get_source_model(db, source_model_id)
    if model is None:
        raise NotFound(f"No source model with id {source_model_id}")
    file_type = model.file_type.value if hasattr(model.file_type, "value") else str(model.file_type)
    model.name = clean_file_name(name, extension=extension_of(model.name, TYPE_EXTENSIONS.get(file_type, ".stl")))
    db.commit()
    db.refresh(model)
    return model


def set_notes(db: Session, source_model_id: int, notes: str, base_revision: int) -> SourceModel:
    """Save the notes for a model (the rules are in app/notes.py: conflict-safe, tidied, length-limited)."""
    model = get_source_model(db, source_model_id)
    if model is None:
        raise NotFound(f"No source model with id {source_model_id}")
    return notes_helper.save(
        db, owner=model, note_cls=SourceModelNote, owner_key="source_model_id", base_revision=base_revision,
        notes=notes, reload=lambda: get_source_model(db, source_model_id),
    )
