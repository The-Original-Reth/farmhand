"""
A slicer plugin and the library (the plugin API's library:read, library:write and prints:send; docs/plugins.md): the
files the operator sent it from Farmhand, read by their refs; the 3MF it sliced from them, filed where they came from
and named the way Farmhand names 3MFs; and the G-code it made, sent to a printer the way Farmhand sends one
(send_print: never while the printer is busy).

A ref names one file, the same way Farmhand's "Send to <plugin>" puts it in the plugin page's address:

  model:<id>                    a model in Models (its newest version)
  3mf:<version id>              one version of a 3MF in Models
  project-stl:<project>:<file>  a project's own STL (its newest version)
  project-3mf:<project>:<file>  a project's own 3MF (its newest version)

Where a sliced 3MF goes (plan() says so before save() does it):

  - re-sliced from one 3MF, for the printer it's on: that 3MF's next version ("Goldfish ver 3.3mf")
  - from one project's own files: a 3MF of that project's own (its next version, when it's re-sliced from one of
    them for the same printer); models sent with them are put in the project too
  - from one model (or a 3MF in Models, for another printer): a new 3MF in Models, sliced from that model
  - from several models: a new 3MF in Models sliced from all of them (a mixed plate), and a new project that uses
    those models and the 3MF
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...errors import NotFound
from ...models import Bundle, BundleVersion, Printer, Project, ProjectStlFile, ProjectThreemfFile, SourceModel
from ...names import clean_file_name, without_version
from ...parsers.gcode import GCODE_EXTENSIONS
from .. import bundle_service, project_files, project_service, send_print
from ..bundle_service.versions import check_gcode_name

_REF = re.compile(r"^(model|3mf):(\d+)$|^(project-stl|project-3mf):(\d+):(\d+)$")
MAX_REFS = 50
# Kinds of model a slicer opens; a STEP file in Models isn't one of them
SLICEABLE = {"stl", "obj", "3mf"}


@dataclass(frozen=True)
class Ref:
    kind: str  # model, 3mf, project-stl, project-3mf
    first: int  # the model, the 3MF version, or the project
    file_id: int | None = None  # a project's own file

    def __str__(self) -> str:
        return f"{self.kind}:{self.first}" + (f":{self.file_id}" if self.file_id is not None else "")


def parse_ref(text: str) -> Ref:
    m = _REF.match((text or "").strip())
    if not m:
        raise ValueError(
            f"\"{text}\" doesn't name a file in Farmhand. A file is named like model:12, 3mf:40, project-stl:3:7 or "
            "project-3mf:3:9."
        )
    if m.group(1):
        return Ref(m.group(1), int(m.group(2)))
    return Ref(m.group(3), int(m.group(4)), int(m.group(5)))


def parse_refs(texts: list[str]) -> list[Ref]:
    refs = list(dict.fromkeys(parse_ref(t) for t in texts if t and t.strip()))
    if not refs:
        raise ValueError("No file was named: send at least one ref, like model:12.")
    if len(refs) > MAX_REFS:
        raise ValueError(f"At most {MAX_REFS} files can be sent at once.")
    return refs


# ------------------------------------------------------------------ reading files (library:read)


@dataclass
class Found:
    """One file a ref names: what it is, where it is on disk, and where in Farmhand it belongs."""

    ref: Ref
    kind: str  # stl, obj, step, 3mf
    name: str  # as Farmhand shows it
    version: int
    path: str | None  # None: its file isn't kept any more
    printer_id: int | None = None  # a 3MF's printer
    model_ids: list[int] = field(default_factory=list)  # the models it is or was sliced from
    bundle: Bundle | None = None
    project: Project | None = None
    project_file: ProjectStlFile | ProjectThreemfFile | None = None

    def out(self) -> dict:
        return {
            "ref": str(self.ref), "kind": self.kind, "name": self.name, "version": self.version,
            "available": bool(self.path) and os.path.isfile(self.path), "sliceable": self.kind in SLICEABLE,
            "printer_id": self.printer_id, "model_ids": self.model_ids,
            "bundle_id": self.bundle.id if self.bundle else None,
            "project_id": self.project.id if self.project else None,
            "project_name": self.project.name if self.project else None,
        }


def _kind_of(name: str) -> str:
    return (os.path.splitext(name)[1].lstrip(".") or "stl").lower()


def find(db: Session, ref: Ref) -> Found:
    """The file a ref names; NotFound (404) when it isn't in Farmhand (any more)."""
    gone = NotFound(f"{ref} isn't in Farmhand any more (it was deleted, or never there).")
    if ref.kind == "model":
        model = db.get(SourceModel, ref.first)
        if model is None:
            raise gone
        newest = model.latest_version
        return Found(ref, model.file_type.value.lower() if newest is None else _kind_of(newest.file_path),
                     model.name, newest.version if newest else 0, newest.file_path if newest else None,
                     model_ids=[model.id])
    if ref.kind == "3mf":
        version = db.get(BundleVersion, ref.first)
        if version is None:
            raise gone
        bundle = version.bundle
        return Found(ref, "3mf", version.filename, version.version,
                     version.threemf_path if version.full_files_retained else None, printer_id=bundle.printer_id,
                     model_ids=[m.id for m in bundle.source_models], bundle=bundle)
    project = db.get(Project, ref.first)
    kind = project_files.STL if ref.kind == "project-stl" else project_files.THREEMF
    f = db.get(kind.file_cls, ref.file_id)
    if project is None or f is None or f.project_id != project.id or not f.versions:
        raise gone
    newest = max(f.versions, key=lambda v: v.version)
    return Found(ref, "3mf" if kind is project_files.THREEMF else _kind_of(newest.filename), newest.filename,
                 newest.version, newest.file_path, printer_id=getattr(f, "printer_id", None), project=project,
                 project_file=f)


def describe(db: Session, texts: list[str]) -> dict:
    return {"files": [find(db, ref).out() for ref in parse_refs(texts)]}


def file_of(db: Session, text: str) -> tuple[str, str]:
    """Where the ref's file is on disk, and the name to download it as."""
    found = find(db, parse_ref(text))
    if not found.path or not os.path.isfile(found.path):
        raise NotFound(f"{found.name}'s file isn't kept any more, or its storage folder isn't there right now.")
    return found.path, found.name


# ------------------------------------------------------------------ filing a sliced 3MF (library:write)


@dataclass
class Plan:
    action: str  # new_version, new_3mf, new_3mf_and_project, project_3mf, project_3mf_version
    name: str  # the 3MF's name, without "ver N" (Farmhand adds it) or ".3mf"
    printer: Printer
    model_ids: list[int]
    bundle: Bundle | None = None  # new_version
    project: Project | None = None  # project_3mf(_version)
    project_file: ProjectThreemfFile | None = None  # project_3mf_version
    project_name: str | None = None  # new_3mf_and_project

    def out(self) -> dict:
        says = {
            "new_version": f"the next version of {self.name} on {self.printer.name}",
            "new_3mf": f"a new 3MF, {self.name}, on {self.printer.name}",
            "new_3mf_and_project": f"a new 3MF, {self.name}, on {self.printer.name}, sliced from {len(self.model_ids)} "
            f"models, and a new project, {self.project_name}, with those models and the 3MF",
            "project_3mf": f"a new 3MF, {self.name}, in the project {self.project.name if self.project else ''}",
            "project_3mf_version": f"the next version of {self.name} in the project "
            f"{self.project.name if self.project else ''}",
        }[self.action]
        return {
            "action": self.action, "name": self.name, "printer_id": self.printer.id, "printer_name": self.printer.name,
            "model_ids": self.model_ids, "bundle_id": self.bundle.id if self.bundle else None,
            "project_id": self.project.id if self.project else None,
            "project_name": self.project.name if self.project else self.project_name,
            "file_id": self.project_file.id if self.project_file else None, "says": f"Saved as {says}.",
        }


def _stem(name: str) -> str:
    return without_version(os.path.splitext(name)[0])


def _printer(db: Session, printer_id: int) -> Printer:
    printer = db.get(Printer, printer_id)
    if printer is None or printer.decommissioned:
        raise NotFound("Printer not found")
    return printer


def _default_project_name(models: list[SourceModel]) -> str:
    stems = [_stem(m.name) for m in models]
    return " + ".join(stems) if len(stems) <= 3 else f"{stems[0]} + {len(stems) - 1} more"


def plan(db: Session, texts: list[str], printer_id: int, name: str | None = None, project_name: str | None = None) -> Plan:
    """Where a 3MF sliced from these files for this printer goes, and what it's called (see the module's notes)."""
    printer = _printer(db, printer_id)
    found = [find(db, ref) for ref in parse_refs(texts)]
    projects = {f.project.id: f.project for f in found if f.project is not None}
    if len(projects) > 1:
        raise ValueError(
            "These files are from different projects (" + ", ".join(p.name for p in projects.values()) + "), and a "
            "3MF can be filed in only one. Send files from one project at a time."
        )
    model_ids = list(dict.fromkeys(i for f in found for i in f.model_ids))
    lone = found[0] if len(found) == 1 else None
    if projects:
        project = next(iter(projects.values()))
        if lone and lone.ref.kind == "project-3mf" and lone.printer_id == printer.id:
            return Plan("project_3mf_version", _name(name, _stem(lone.name)), printer, model_ids, project=project,
                        project_file=lone.project_file)
        default = _stem(lone.name) if lone else project.name
        return Plan("project_3mf", _name(name, default), printer, model_ids, project=project)
    if lone and lone.bundle is not None and lone.printer_id == printer.id:
        return Plan("new_version", _name(name, _stem(lone.bundle.latest_version.filename)), printer, model_ids,
                    bundle=lone.bundle)
    if not model_ids:
        raise ValueError("None of these files is a model in Farmhand, so there's nothing to file the 3MF under.")
    models = list(db.scalars(select(SourceModel).where(SourceModel.id.in_(model_ids))))
    models.sort(key=lambda m: model_ids.index(m.id))
    if len(models) == 1:
        default = _stem(lone.name) if lone and lone.bundle is not None else _stem(models[0].name)
        return Plan("new_3mf", _name(name, default), printer, model_ids)
    wanted = " ".join((project_name or name or _default_project_name(models)).split())
    clash = db.scalar(select(Project).where(func.lower(Project.name) == wanted.lower()))
    if clash is not None:
        raise ValueError(f"There's already a project called {clash.name}. Choose another name for the new project.")
    return Plan("new_3mf_and_project", _name(name, wanted), printer, model_ids, project_name=wanted)


def _name(typed: str | None, default: str) -> str:
    """The 3MF's name, without its extension: the one typed, else the default (checked like a typed file name)."""
    return os.path.splitext(clean_file_name(typed or default, extension=".3mf"))[0]


def save(
    db: Session, texts: list[str], printer_id: int, threemf: BinaryIO, gcode: BinaryIO | None = None,
    gcode_filename: str | None = None, name: str | None = None, project_name: str | None = None,
) -> dict:
    """File a sliced 3MF (and its G-code, if it comes with one) where plan() says. Returns plan's answer, with ids."""
    p = plan(db, texts, printer_id, name, project_name)
    filename = f"{p.name}.3mf"
    if gcode is not None:
        check_gcode_name(gcode_filename)
    out = p.out()
    if p.action in ("new_version", "new_3mf", "new_3mf_and_project"):
        gcode_name = (p.name + os.path.splitext(gcode_filename)[1].lower()) if gcode is not None else None
        if p.action == "new_version":
            version = bundle_service.add_bundle_version(
                db, bundle_id=p.bundle.id, threemf_file_obj=threemf, threemf_filename=filename,
                gcode_file_obj=gcode, gcode_filename=gcode_name,
            )
            bundle = version.bundle
        else:
            bundle = bundle_service.create_bundle(
                db, source_model_ids=p.model_ids, threemf_file_obj=threemf, threemf_filename=filename,
                gcode_file_obj=gcode, gcode_filename=gcode_name, printer_id=p.printer.id,
            )
            version = bundle.latest_version
        out.update(bundle_id=bundle.id, version_id=version.id, version=version.version, filename=version.filename)
        if p.action == "new_3mf_and_project":
            project = project_service.create_project(db, p.project_name)
            for model_id in p.model_ids:
                project_service.add_model(db, project.id, model_id)
            project_service.add_bundle(db, project.id, bundle.id)
            out.update(project_id=project.id, project_name=project.name)
        return out

    # A project's own 3MF
    project = p.project
    for model_id in p.model_ids:
        project_service.add_model(db, project.id, model_id)
    if p.action == "project_3mf_version":
        f = p.project_file
        project_files.add_version(db, project_files.THREEMF, project.id, f.id, filename, threemf)
        if f.printer_id is not None:
            project_service.link_printer(db, project.id, f.printer_id)
    else:
        f = project_files.upload(db, project_files.THREEMF, project.id, filename, threemf, printer_id=p.printer.id)
    db.expire_all()
    newest = max(db.get(ProjectThreemfFile, f.id).versions, key=lambda v: v.version)
    if gcode is not None:
        project_files.attach_gcode(db, project.id, f.id, newest.version,
                                   _stem(newest.filename) + f" ver {newest.version}" + os.path.splitext(gcode_filename)[1].lower(),
                                   gcode)
    out.update(project_id=project.id, project_name=project.name, file_id=f.id, version=newest.version,
               filename=newest.filename)
    return out


# ------------------------------------------------------------------ sending a G-code (prints:send)


def send(db: Session, printer_id: int, filename: str | None, gcode: BinaryIO) -> dict:
    """Send a G-code a plugin made to a printer and start it (never while it's busy). {sent, printer}"""
    printer = _printer(db, printer_id)
    name = Path(filename or "").name
    if os.path.splitext(name)[1].lower() not in GCODE_EXTENSIONS:
        raise ValueError("Only a sliced .gcode or .bgcode can be sent to a printer.")
    # spooled to a file of its own: the printer is sent it from there, a piece at a time
    with tempfile.TemporaryDirectory(prefix="farmhand-plugin-gcode-") as folder:
        path = os.path.join(folder, name)
        with open(path, "wb") as out:
            shutil.copyfileobj(gcode, out, 1024 * 1024)
        return send_print.send_file(db, printer, name, path)
