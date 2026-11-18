"""Files another Farmhand moved: models pointed at their files where that Farmhand's records say they are now, and
the doubles that left behind taken out of the library."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import storage
from ...models import BundleSourceModel, ProjectSourceModel, SourceModel
from ...record_files import resolve_from
from ..app_settings import instance_id
from .reading import MODEL_PREFIX, _records


# ------------------------------------------------------------------ files another Farmhand moved


def relink_moved_models(db: Session) -> list[str]:
    """
    Models whose files are gone from where this Farmhand put them, because another Farmhand sharing the STL folder took
    them in and moved them into its own folders (its Models scan did, before it left other Farmhands' files alone):
    each pointed at its file where it is now, found in that Farmhand's records by the model's name and the file's
    name. The model itself (its 3MFs, projects, notes) stays as it is; no file is touched. Answers the names relinked.
    """
    root = storage.ready_root("stl")
    me = instance_id(db)
    # where the other Farmhands' records say each model's files are: (model name, file name) -> paths there now
    elsewhere: dict[tuple[str, str], set[str]] = {}
    for _, doc in _records(root, MODEL_PREFIX, "farmhand_model"):
        if doc.get("instance") == me or not isinstance(doc.get("name"), str):
            continue
        for v in doc.get("versions") or []:
            p = resolve_from(root, v.get("path")) if isinstance(v, dict) else None
            if p and p.is_file():
                elsewhere.setdefault((doc["name"], p.name), set()).add(str(p))
    relinked = []
    for model in db.scalars(select(SourceModel)):
        versions = [v for v in model.versions if v.file_path]
        if not versions or any(os.path.exists(v.file_path) for v in versions):
            continue  # nothing of it is missing (or it has no file at all)
        moves = {}
        for v in versions:
            found = elsewhere.get((model.name, Path(v.file_path).name), set())
            if len(found) != 1:
                break  # not found, or more than one place it could be: left as it is
            moves[v] = found.pop()
        else:
            for v, path in moves.items():
                v.file_path = path
                preview = storage.preview_beside(path)
                v.thumbnail_path = preview if preview and os.path.exists(preview) else v.thumbnail_path
            db.commit()
            relinked.append(model.name)
    return relinked


def drop_doubles(db: Session) -> list[str]:
    """
    Models brought in from another Farmhand's records that are the same as one this Farmhand already has (every one of
    their files is that model's, after relink_moved_models): taken out of the library, as long as nothing uses them (no
    3MF sliced from them, no project, no notes of their own). Only their entries go: the files are the older model's.
    """
    owner: dict[str, int] = {}
    models = list(db.scalars(select(SourceModel).order_by(SourceModel.id)))
    for model in models:
        for v in model.versions:
            if v.file_path:
                owner.setdefault(os.path.realpath(v.file_path), model.id)
    dropped = []
    for model in models:
        paths = [os.path.realpath(v.file_path) for v in model.versions if v.file_path]
        older = {owner.get(p) for p in paths}
        if not paths or len(older) != 1 or older == {model.id} or None in older:
            continue
        in_use = (
            db.scalar(select(BundleSourceModel).where(BundleSourceModel.source_model_id == model.id).limit(1)) is not None
            or db.scalar(select(ProjectSourceModel).where(ProjectSourceModel.source_model_id == model.id).limit(1)) is not None
            or bool(model.notes.strip())
        )
        if in_use:
            continue
        name = model.name
        for v in list(model.versions):
            db.delete(v)  # the entry: the file is the older model's
        db.delete(model)
        db.commit()
        dropped.append(name)
    return dropped
