"""
The Models library on the NAS with what it is: a record beside each model's files (in the STL folder) and each 3MF's
(in the 3MF folder), like a project's (project_records): the model's name, type, notes and every version's file; the
3MF's printer, the models it was sliced from, notes, starred version, and every version's 3MF, G-code, preview,
monument and slicer settings (so a version whose files were pruned comes back too).

So the library isn't only in this Farmhand's database: another Farmhand sharing the folders (or a new one after this
computer is gone) brings every model and 3MF in from them, its files used where they are. Each Farmhand writes its own
record (farmhand-model-<its id>.json, farmhand-3mf-<its id>.json), so two never write over each other's.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..models import (
    Bundle, BundleNote, BundleSourceModel, BundleStar, BundleVersion, Printer, ProjectSourceModel, SourceFileType,
    SourceModel, SourceModelNote, SourceModelVersion,
)
from .project_records import instance_id

log = logging.getLogger("farmhand.library_records")

MODEL_PREFIX = "farmhand-model-"
THREEMF_PREFIX = "farmhand-3mf-"
FORMAT = 1
MAX_RECORD_BYTES = 20_000_000  # a 3MF's record holds every version's slicer settings


def is_record(name: str) -> bool:
    return (name.startswith(MODEL_PREFIX) or name.startswith(THREEMF_PREFIX)) and name.endswith(".json")


def _when(value) -> str | None:
    return value.isoformat() if isinstance(value, dt.datetime) else None


def _parse_when(value):
    try:
        return dt.datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _rel(path: str | None, root: Path) -> str | None:
    """A file's place in the record: relative to the STL or 3MF folder when it's inside it, else as it is."""
    if not path:
        return None
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path


def _at(root: Path, where) -> Path | None:
    if not isinstance(where, str) or not where:
        return None
    p = Path(where)
    return p if p.is_absolute() else root / p


def _own_folder(paths: list[tuple[str | None, int]], owner_id: int) -> Path | None:
    """The {id} folder this Farmhand keeps an owner's versions in ({root}/{id}/v{n}/...), or None for files it was given
    where they sat (another Farmhand's, or imported from where they were): those get no record from it."""
    for path, version in paths:
        if path and storage.is_managed_layout(path, owner_id, version):
            return Path(path).parent.parent
    return None


# ------------------------------------------------------------------ writing


def _write(folder: Path, prefix: str, doc: dict, me: str) -> None:
    storage.write_text_atomically(folder / f"{prefix}{me}.json", json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def write_model(db: Session, model_id: int) -> bool:
    model = db.get(SourceModel, model_id)
    if model is None:
        return False
    folder = _own_folder([(v.file_path, v.version) for v in model.versions], model.id)
    if folder is None:
        return False
    root = storage.effective_root("stl")
    me = instance_id(db)
    _write(folder, MODEL_PREFIX, {
        "farmhand_model": FORMAT, "instance": me, "saved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "note": "Written by Farmhand whenever this model changes: another Farmhand sharing the folder brings it in from it.",
        "name": model.name, "file_type": model.file_type.value, "notes": model.notes,
        "versions": [
            {"version": v.version, "path": _rel(v.file_path, root), "preview": _rel(v.thumbnail_path, root), "note": v.note,
             "uploaded_at": _when(v.uploaded_at)}
            for v in sorted(model.versions, key=lambda v: v.version)
        ],
    }, me)
    return True


def write_bundle(db: Session, bundle_id: int) -> bool:
    bundle = db.get(Bundle, bundle_id)
    if bundle is None:
        return False
    folder = _own_folder([(v.threemf_path or v.thumbnail_path, v.version) for v in bundle.versions], bundle.id)
    if folder is None:
        return False
    root = storage.effective_root("threemf")
    me = instance_id(db)
    star = bundle.star_row.version.version if bundle.star_row and bundle.star_row.version else None
    _write(folder, THREEMF_PREFIX, {
        "farmhand_3mf": FORMAT, "instance": me, "saved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "note": "Written by Farmhand whenever this 3MF changes: another Farmhand sharing the folder brings it in from it.",
        "printer": bundle.printer.name if bundle.printer else None,
        "models": [link.source_model.name for link in bundle.source_model_links if link.source_model],
        "notes": bundle.notes, "starred_version": star,
        "versions": [
            {
                "version": v.version, "filename": v.filename, "threemf": _rel(v.threemf_path, root), "gcode": _rel(v.gcode_path, root),
                "preview": _rel(v.thumbnail_path, root), "uploaded_at": _when(v.uploaded_at), "monument": v.monument,
                "monument_note": v.monument_note, "slicer_family": v.slicer_family, "slicer_display_name": v.slicer_display_name,
                "printer_profile_name": v.printer_profile_name, "settings": v.settings,
            }
            for v in sorted(bundle.versions, key=lambda v: v.version)
        ],
    }, me)
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


_background = False  # switched on when the app starts (not in tests, which write records themselves)


def enable_background_writes() -> None:
    global _background
    _background = True


def request_write(kind: str | None = None, owner_id: int | None = None) -> None:
    """After a change: that model's or 3MF's record (or every one), written in the background."""
    if not _background:
        return
    from ..database import SessionLocal

    def run():
        try:
            with SessionLocal() as db:
                if kind == "model" and owner_id:
                    write_model(db, owner_id)
                elif kind == "bundle" and owner_id:
                    write_bundle(db, owner_id)
                else:
                    write_all(db)
        except storage.StorageUnavailableError:
            pass
        except Exception:  # noqa: BLE001 - a record failing must never take anything down
            log.exception("Writing a library record failed")

    threading.Thread(target=run, name="library-record", daemon=True).start()


# ------------------------------------------------------------------ reading


def _records(root: Path, prefix: str, marker: str) -> list[tuple[Path, dict]]:
    """Every record of that kind in the folder's {id} folders: (its folder, the record)."""
    out = []
    try:
        folders = [Path(e.path) for e in os.scandir(root) if e.is_dir() and not e.name.startswith(".")]
    except OSError:
        return out
    for folder in folders:
        try:
            names = [n for n in os.listdir(folder) if n.startswith(prefix) and n.endswith(".json")]
        except OSError:
            continue
        for name in names:
            try:
                path = folder / name
                if path.stat().st_size > MAX_RECORD_BYTES:
                    continue
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(doc, dict) and doc.get(marker) == FORMAT:
                out.append((folder, doc))
    return out


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
                p = _at(root, v.get(key)) if isinstance(v, dict) else None
                if p:
                    kept.add(os.path.realpath(p))
    return kept


# ------------------------------------------------------------------ bringing in


def _known(paths) -> set[str]:
    return {os.path.realpath(p) for p in paths if p}


def import_models(db: Session) -> dict:
    """The other Farmhand's models this one hasn't got, from their records, their files used where they are."""
    root = storage.ready_root("stl")
    me = instance_id(db)
    known = _known(db.scalars(select(SourceModelVersion.file_path)))
    brought, skipped = [], []
    for _, doc in _records(root, MODEL_PREFIX, "farmhand_model"):
        if doc.get("instance") == me or not isinstance(doc.get("name"), str):
            continue
        versions = [v for v in (doc.get("versions") or []) if isinstance(v, dict)]
        here = [(v, _at(root, v.get("path"))) for v in sorted(versions, key=lambda v: v.get("version") or 0)]
        here = [(v, p) for v, p in here if p and p.is_file()]
        if not here or any(os.path.realpath(p) in known for _, p in here):
            continue  # nothing there any more, or here already
        try:
            file_type = SourceFileType(doc.get("file_type"))
        except ValueError:
            skipped.append({"name": doc["name"], "reason": f"Its file type ({doc.get('file_type')}) isn't one Farmhand knows."})
            continue
        model = SourceModel(name=doc["name"][:255], file_type=file_type)
        db.add(model)
        db.flush()
        for n, (v, path) in enumerate(here, start=1):
            preview = _at(root, v.get("preview"))
            db.add(SourceModelVersion(
                source_model_id=model.id, version=n, file_path=str(path), thumbnail_path=str(preview) if preview and preview.is_file() else None,
                note=v.get("note"), **({"uploaded_at": _parse_when(v.get("uploaded_at"))} if _parse_when(v.get("uploaded_at")) else {}),
            ))
            known.add(os.path.realpath(path))
        if isinstance(doc.get("notes"), str) and doc["notes"].strip():
            model.note_row = SourceModelNote(source_model_id=model.id, body=doc["notes"], revision=1)
        db.commit()
        brought.append(model.name)
    return {"brought": brought, "skipped": skipped}


def import_bundles(db: Session) -> dict:
    """The other Farmhand's 3MFs this one hasn't got, from their records: for their printer (by name, it has to be
    here), with the models they were sliced from (by name, the ones here), every version with its settings."""
    root = storage.ready_root("threemf")
    me = instance_id(db)
    known = _known([*db.scalars(select(BundleVersion.threemf_path)), *db.scalars(select(BundleVersion.thumbnail_path))])
    brought, skipped = [], []
    for _, doc in _records(root, THREEMF_PREFIX, "farmhand_3mf"):
        if doc.get("instance") == me:
            continue
        versions = sorted([v for v in (doc.get("versions") or []) if isinstance(v, dict)], key=lambda v: v.get("version") or 0)
        found = [_at(root, v.get("threemf")) or _at(root, v.get("preview")) for v in versions]
        found = [p for p in found if p and p.is_file()]
        if not versions or not found or any(os.path.realpath(p) in known for p in found):
            continue  # nothing of it there any more, or here already
        label = versions[-1].get("filename") or "a 3MF"
        printer = db.scalar(select(Printer).where(Printer.name == doc.get("printer")))
        if printer is None:
            skipped.append({"name": label, "reason": f"It's for the printer {doc.get('printer')}, which isn't here: add it (or Load all settings), and it comes in."})
            continue
        bundle = Bundle(printer_id=printer.id)
        db.add(bundle)
        db.flush()
        for name in doc.get("models") or []:
            model = db.scalar(select(SourceModel).where(SourceModel.name == name).order_by(SourceModel.id))
            if model is not None and db.get(BundleSourceModel, (bundle.id, model.id)) is None:
                db.add(BundleSourceModel(bundle_id=bundle.id, source_model_id=model.id))
        starred = None
        for v in versions:
            threemf, gcode, preview = (_at(root, v.get(k)) for k in ("threemf", "gcode", "preview"))
            threemf = threemf if threemf and threemf.is_file() else None
            row = BundleVersion(
                bundle_id=bundle.id, version=int(v.get("version") or 1), filename=str(v.get("filename") or "")[:255],
                slicer_family=str(v.get("slicer_family") or "prusaslicer")[:50],
                slicer_display_name=str(v.get("slicer_display_name") or "")[:100],
                printer_profile_name=(str(v["printer_profile_name"])[:120] if v.get("printer_profile_name") else None),
                monument=bool(v.get("monument")), monument_note=v.get("monument_note"),
                full_files_retained=threemf is not None, threemf_path=str(threemf) if threemf else None,
                gcode_path=str(gcode) if threemf and gcode and gcode.is_file() else None,
                thumbnail_path=str(preview) if preview and preview.is_file() else None,
                settings=v.get("settings") if isinstance(v.get("settings"), dict) else {},
                **({"uploaded_at": _parse_when(v.get("uploaded_at"))} if _parse_when(v.get("uploaded_at")) else {}),
            )
            db.add(row)
            db.flush()
            if v.get("version") == doc.get("starred_version"):
                starred = row
        if starred is not None:
            bundle.star_row = BundleStar(bundle_id=bundle.id, version_id=starred.id)
        if isinstance(doc.get("notes"), str) and doc["notes"].strip():
            bundle.note_row = BundleNote(bundle_id=bundle.id, body=doc["notes"], revision=1)
        db.commit()
        known.update(os.path.realpath(p) for p in found)
        brought.append(label)
    return {"brought": brought, "skipped": skipped}


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
            p = _at(root, v.get("path")) if isinstance(v, dict) else None
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


def import_library(db: Session) -> dict:
    """Models, then 3MFs (they name the models): {models: [names], threemfs: [names], skipped: [{name, reason}]}. A folder
    that's away is passed over. Models whose files another Farmhand moved are found again first (and the doubles that
    left behind taken out), so they aren't brought in a second time."""
    out = {"models": [], "threemfs": [], "skipped": []}
    try:
        relinked = relink_moved_models(db)
        dropped = drop_doubles(db)
        if relinked or dropped:
            log.info("Models found where another Farmhand moved them: %s; doubles taken out: %s", relinked, dropped)
    except storage.StorageUnavailableError:
        pass
    try:
        r = import_models(db)
        out["models"], out["skipped"] = r["brought"], out["skipped"] + r["skipped"]
    except storage.StorageUnavailableError:
        pass
    try:
        r = import_bundles(db)
        out["threemfs"], out["skipped"] = r["brought"], out["skipped"] + r["skipped"]
    except storage.StorageUnavailableError:
        pass
    return out
