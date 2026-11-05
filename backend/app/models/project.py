from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from ..database import Base


def _now():
    return dt.datetime.now(dt.timezone.utc)


class Project(Base):
    """
    A piece of work for the farm: its CAD files, its STL files (models from the Models page, and STLs of its own), and
    in time its 3MF files, printers and parts. Its own files are kept in the project files folder (chosen on the
    Settings page), one folder per project.
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # the project's own files: they belong to it, and go when it does
    cad_files: Mapped[list["ProjectCadFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectCadFile.id"
    )
    stl_files: Mapped[list["ProjectStlFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectStlFile.id"
    )
    # models from the Models page it uses: only pointed at (taking one out, or deleting the project, leaves the model)
    model_links: Mapped[list["ProjectSourceModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectSourceModel.added_at"
    )


# A project's own files, CAD or STL, each kind in tables of its own but alike: a file with numbered versions, each kept
# in {project files}/{project id}/{cad|stl}/{file id}/v{n}/, named like a 3MF version ("Bracket ver 2.f3d"), with its
# preview next to it when one could be made. A file is shown by its newest version's name. No version is pruned: these
# can't be made again from anything else. (services/project_files.py handles both kinds.)


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
    """An STL (or OBJ) uploaded to a project only, not put in Models: it belongs to the project."""

    __tablename__ = "project_stl_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
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
    A model from the Models page used in a project. Keyed by (project, model), so a model is in a project at most once;
    deleting the model takes it out of every project.
    """

    __tablename__ = "project_source_models"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    source_model_id: Mapped[int] = mapped_column(ForeignKey("source_models.id"), primary_key=True, index=True)
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="model_links")
    source_model: Mapped["SourceModel"] = relationship(  # noqa: F821
        backref=backref("project_links", cascade="all, delete-orphan")
    )
