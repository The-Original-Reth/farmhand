from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from ..database import Base


def _now():
    return dt.datetime.now(dt.timezone.utc)


class Project(Base):
    """
    A piece of work for the farm: its documents; its CAD files; its STL and 3MF files (ones from the rest of Farmhand, and ones of its
    own); the printers those 3MFs are for; and its parts list. Its own files are kept in the project files folder (chosen on the
    Settings page), one folder per project.
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # the project's own files: they belong to it, and go when it does
    doc_files: Mapped[list["ProjectDocFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectDocFile.id"
    )
    cad_files: Mapped[list["ProjectCadFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectCadFile.id"
    )
    stl_files: Mapped[list["ProjectStlFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectStlFile.id"
    )
    threemf_files: Mapped[list["ProjectThreemfFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectThreemfFile.id"
    )
    # models from the Models page it uses: only pointed at (taking one out, or deleting the project, leaves the model)
    model_links: Mapped[list["ProjectSourceModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectSourceModel.added_at"
    )
    bundle_links: Mapped[list["ProjectBundle"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectBundle.added_at"
    )
    printer_links: Mapped[list["ProjectPrinter"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectPrinter.added_at"
    )
    # its parts list (bill of materials): what it needs that isn't printed
    parts: Mapped[list["ProjectPart"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectPart.id"
    )


# A project's own files, documents, CAD, STL or 3MF, each kind in tables of its own but alike: a file with numbered versions, each kept
# in {project files}/{project id}/{docs|cad|stl|threemf}/{file id}/v{n}/, named like a 3MF version ("Bracket ver 2.f3d"), with its
# preview next to it when one could be made. A file is shown by its newest version's name. No version is pruned: these
# can't be made again from anything else. (services/project_files.py handles both kinds.)


class ProjectDocFile(Base):
    """A document of a project: any file at all (a quote, drawings, instructions, photos, a spreadsheet...)."""

    __tablename__ = "project_doc_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="doc_files")
    versions: Mapped[list["ProjectDocVersion"]] = relationship(
        back_populates="file", order_by="ProjectDocVersion.version.desc()", cascade="all, delete-orphan"
    )


class ProjectDocVersion(Base):
    __tablename__ = "project_doc_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_file_id: Mapped[int] = mapped_column(ForeignKey("project_doc_files.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)  # as kept: "Quote ver 2.pdf"
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500))  # a picture's own preview, next to it
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)  # notes on this version
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    file: Mapped["ProjectDocFile"] = relationship(back_populates="versions")


class ProjectCadFile(Base):
    """A CAD file of a project, any kind (Fusion, STEP, SolidWorks, OpenSCAD...)."""

    __tablename__ = "project_cad_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="cad_files")
    versions: Mapped[list["ProjectCadVersion"]] = relationship(
        back_populates="file", order_by="ProjectCadVersion.version.desc()", cascade="all, delete-orphan"
    )


class ProjectCadVersion(Base):
    __tablename__ = "project_cad_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    cad_file_id: Mapped[int] = mapped_column(ForeignKey("project_cad_files.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)  # as kept: "Bracket ver 2.f3d"
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500))  # its preview, next to it ("... ver 2.f3d.png")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)  # what changed in this version
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    file: Mapped["ProjectCadFile"] = relationship(back_populates="versions")


class ProjectStlFile(Base):
    """An STL (or OBJ) uploaded to a project only, not put in Models: it belongs to the project. need / have: how many
    prints of it the project needs, and how many it has."""

    __tablename__ = "project_stl_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    need: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    have: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="stl_files")
    versions: Mapped[list["ProjectStlVersion"]] = relationship(
        back_populates="file", order_by="ProjectStlVersion.version.desc()", cascade="all, delete-orphan"
    )


class ProjectStlVersion(Base):
    __tablename__ = "project_stl_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    stl_file_id: Mapped[int] = mapped_column(ForeignKey("project_stl_files.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)  # as kept: "Bracket ver 2.stl"
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    file: Mapped["ProjectStlFile"] = relationship(back_populates="versions")


class ProjectSourceModel(Base):
    """
    A model from the Models page used in a project, with how many prints of it the project needs and has. Keyed by
    (project, model), so a model is in a project at most once; deleting the model takes it out of every project.
    """

    __tablename__ = "project_source_models"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    source_model_id: Mapped[int] = mapped_column(ForeignKey("source_models.id"), primary_key=True, index=True)
    need: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    have: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="model_links")
    source_model: Mapped["SourceModel"] = relationship(  # noqa: F821
        backref=backref("project_links", cascade="all, delete-orphan")
    )


class ProjectThreemfFile(Base):
    """
    A 3MF uploaded to a project only, not put in Models: it belongs to the project. It's sliced for one printer (chosen
    at upload, suggested from the file), which the project then uses too; a printer deleted later leaves it without one.
    """

    __tablename__ = "project_threemf_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    printer_id: Mapped[int | None] = mapped_column(ForeignKey("printers.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="threemf_files")
    printer: Mapped["Printer | None"] = relationship(  # noqa: F821
        backref=backref("project_threemf_files", passive_deletes=True)
    )
    versions: Mapped[list["ProjectThreemfVersion"]] = relationship(
        back_populates="file", order_by="ProjectThreemfVersion.version.desc()", cascade="all, delete-orphan"
    )


class ProjectThreemfVersion(Base):
    __tablename__ = "project_threemf_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    threemf_file_id: Mapped[int] = mapped_column(ForeignKey("project_threemf_files.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)  # as kept: "Plate ver 2.3mf"
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500))  # the picture inside the 3MF, next to it
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    file: Mapped["ProjectThreemfFile"] = relationship(back_populates="versions")
    # the G-code sliced from this version, if one was uploaded: it goes with the version
    gcode: Mapped["ProjectThreemfGcode | None"] = relationship(
        back_populates="version", cascade="all, delete-orphan", uselist=False
    )


class ProjectThreemfGcode(Base):
    """
    The G-code of one version of a project's own 3MF (a .gcode or .bgcode sliced from it), kept next to that 3MF and
    named as uploaded. Uploading another replaces it. It can be downloaded, or sent to the 3MF's printer.
    """

    __tablename__ = "project_threemf_gcodes"

    version_id: Mapped[int] = mapped_column(ForeignKey("project_threemf_versions.id"), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    version: Mapped["ProjectThreemfVersion"] = relationship(back_populates="gcode")


class ProjectBundle(Base):
    """
    A 3MF from the rest of Farmhand used in a project (one on the Models and Printers pages). Using one brings the
    printer it's for (ProjectPrinter); taking it out leaves the printer. Deleting the 3MF takes it out of every project.
    """

    __tablename__ = "project_bundles"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id"), primary_key=True, index=True)
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="bundle_links")
    bundle: Mapped["Bundle"] = relationship(  # noqa: F821
        backref=backref("project_links", cascade="all, delete-orphan")
    )


class ProjectPrinter(Base):
    """A printer a project uses: brought by its 3MFs, or added by hand. Deleting the printer takes it out of every project."""

    __tablename__ = "project_printers"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), primary_key=True, index=True)
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="printer_links")
    printer: Mapped["Printer"] = relationship(  # noqa: F821
        backref=backref("project_links", cascade="all, delete-orphan")
    )


class ProjectPart(Base):
    """
    One line of a project's parts list (its bill of materials): something it needs that isn't printed (screws, magnets,
    inserts...), how many it needs and has, a link to buy it, and notes. Added one by one, or from a BOM (a CSV file).
    """

    __tablename__ = "project_parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    need: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    have: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    link: Mapped[str | None] = mapped_column(String(1000))  # where to buy it: an http(s) address
    note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="parts")
