"""Writing the records: a model's or 3MF's record beside its files, every one of them, or one after a change in the
background."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import record_files, storage
from ...models import Bundle, SourceModel
from ...record_files import iso_or_none, relative_to
from ..app_settings import instance_id
from .reading import FORMAT, MODEL_PREFIX, THREEMF_PREFIX, log

background = record_files.BackgroundWriter("library-record", "a library record")


def _record_folder(paths: list[tuple[str | None, int]], owner_id: int, root: Path) -> Path | None:
    """Where an owner's record goes: the {id} folder this Farmhand keeps its versions in ({root}/{id}/v{n}/...), else
    the folder of the STL / 3MF folder its files are in (another Farmhand filed them there, or they were brought in
    where they sat). None for files loose at the top of it or outside it: records are only looked for one folder down."""
    for path, version in paths:
        if path and storage.is_managed_layout(path, owner_id, version):
            return Path(path).parent.parent
    base = root.resolve()
    for path, _ in paths:
        try:
            parts = Path(path).resolve().relative_to(base).parts if path else ()
        except (OSError, ValueError):
            continue
        if len(parts) >= 2 and not parts[0].startswith("."):
            return base / parts[0]
    return None


# ------------------------------------------------------------------ writing


def write_model(db: Session, model_id: int) -> bool:
    model = db.get(SourceModel, model_id)
    if model is None:
        return False
    root = storage.effective_root("stl")
    folder = _record_folder([(v.file_path, v.version) for v in model.versions], model.id, root)
    if folder is None:
        return False
    me = instance_id(db)
    record_files.write_json(folder / f"{MODEL_PREFIX}{me}.json", {
        "farmhand_model": FORMAT, "instance": me, "saved_at": record_files.stamp(),
        "note": "Written by Farmhand whenever this model changes: another Farmhand sharing the folder brings it in from it.",
        "name": model.name, "file_type": model.file_type.value, "notes": model.notes,
        "versions": [
            {"version": v.version, "path": relative_to(v.file_path, root), "preview": relative_to(v.thumbnail_path, root), "note": v.note,
             "uploaded_at": iso_or_none(v.uploaded_at)}
            for v in sorted(model.versions, key=lambda v: v.version)
        ],
    })
    return True


def write_bundle(db: Session, bundle_id: int) -> bool:
    bundle = db.get(Bundle, bundle_id)
    if bundle is None:
        return False
    root = storage.effective_root("threemf")
    folder = _record_folder([(v.threemf_path or v.thumbnail_path, v.version) for v in bundle.versions], bundle.id, root)
    if folder is None:
        return False
    me = instance_id(db)
    star = bundle.star_row.version.version if bundle.star_row and bundle.star_row.version else None
    record_files.write_json(folder / f"{THREEMF_PREFIX}{me}.json", {
        "farmhand_3mf": FORMAT, "instance": me, "saved_at": record_files.stamp(),
        "note": "Written by Farmhand whenever this 3MF changes: another Farmhand sharing the folder brings it in from it.",
        "printer": bundle.printer.name if bundle.printer else None,
        "models": [link.source_model.name for link in bundle.source_model_links if link.source_model],
        "notes": bundle.notes, "starred_version": star,
        "versions": [
            {
                "version": v.version, "filename": v.filename, "threemf": relative_to(v.threemf_path, root), "gcode": relative_to(v.gcode_path, root),
                "preview": relative_to(v.thumbnail_path, root), "uploaded_at": iso_or_none(v.uploaded_at), "monument": v.monument,
                "monument_note": v.monument_note, "slicer_family": v.slicer_family, "slicer_display_name": v.slicer_display_name,
                "printer_profile_name": v.printer_profile_name, "settings": v.settings,
                "sub_printer": v.sub_printer_name,  # the printer's preset it was sliced with, as chosen here
            }
            for v in sorted(bundle.versions, key=lambda v: v.version)
        ],
    })
    return True


def write_all(db: Session) -> int:
    written = 0
    for kind, ids, write in (("stl", select(SourceModel.id), write_model), ("threemf", select(Bundle.id), write_bundle)):
        try:
            storage.ready_root(kind)
        except storage.StorageUnavailableError:
            continue  # that folder is away: written with the next change, or when Farmhand starts
        for owner_id in list(db.scalars(ids)):
            try:
                written += bool(write(db, owner_id))
            except Exception:  # noqa: BLE001 - one record failing must not stop the rest
                log.exception("Writing the record of %s %s failed", kind, owner_id)
    return written


def request_write(kind: str | None = None, owner_id: int | None = None) -> None:
    """After a change: that model's or 3MF's record (or every one), written in the background."""
    def write_it(db: Session):
        if kind == "model" and owner_id:
            write_model(db, owner_id)
        elif kind == "bundle" and owner_id:
            write_bundle(db, owner_id)
        else:
            write_all(db)

    background.run(write_it)
