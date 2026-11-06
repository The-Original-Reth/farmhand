from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class FileVersionOut(BaseModel):
    version: int
    filename: str  # as kept: "Bracket ver 2.f3d"
    size_bytes: int
    note: str | None  # what changed in this version
    uploaded_at: dt.datetime
    has_preview: bool
    gcode_name: str | None = None  # a 3MF version's G-code, if it has one


class ProjectFileOut(BaseModel):
    """A project's own file: a document, a CAD file, an STL or a 3MF."""

    id: int
    printer_id: int | None = None  # a 3MF's: the printer it's for (absent for CAD and STL files)
    need: int | None = None  # an STL's: how many prints of it the project needs
    have: int | None = None  # and how many it has
    component: str | None = None  # an STL's: the sub-component it's in ("Fins", "Body/Left"), or none
    name: str  # its newest version's file name
    created_at: dt.datetime
    versions: list[FileVersionOut]  # newest first


class ModelUseOut(BaseModel):
    """A model from Models a project uses, and how many prints of it the project needs and has."""

    id: int
    need: int
    have: int
    component: str | None = None  # the sub-component it's in, or none


class Counts(BaseModel):
    """How many are needed and how many there are; only those sent change."""

    need: int | None = None
    have: int | None = None


class FileOrder(BaseModel):
    """A project's documents or CAD files, in the order to put them: every one, first to last."""

    ids: list[int]


class StlChange(Counts):
    """An STL's counts, and the sub-component it's in ("Body/Left" for one inside another; blank or null: none).
    Only what's sent changes."""

    component: str | None = None


class PartOut(BaseModel):
    id: int
    name: str
    need: int
    have: int
    link: str | None  # where to buy it
    note: str | None


class ProjectOut(BaseModel):
    id: int
    name: str
    created_at: dt.datetime
    doc_files: list[ProjectFileOut] = []  # its documents: any file
    cad_files: list[ProjectFileOut] = []
    stl_files: list[ProjectFileOut] = []  # STLs of its own (not in Models)
    threemf_files: list[ProjectFileOut] = []  # 3MFs of its own (not in Models)
    source_model_ids: list[int] = []  # models from the Models page it uses
    source_models: list[ModelUseOut] = []  # the same, with how many it needs and has of each
    bundle_ids: list[int] = []  # 3MFs from the rest of Farmhand it uses
    printer_ids: list[int] = []  # printers it uses (brought by its 3MFs, or added)
    parts: list[PartOut] = []  # its parts list (bill of materials), in the order added


class PartIn(BaseModel):
    name: str
    need: int = 1
    have: int = 0
    link: str | None = None
    note: str | None = None


class PartUpdate(BaseModel):
    """Only the fields sent are changed; a blank or null link or note clears it."""

    name: str | None = None
    need: int | None = None
    have: int | None = None
    link: str | None = None
    note: str | None = None


class BomOut(BaseModel):
    project: ProjectOut
    added: int  # how many parts the BOM had


class ProjectIn(BaseModel):
    """A new project, or a project's new name."""

    name: str
