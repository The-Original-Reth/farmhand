from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def _now():
    return dt.datetime.now(dt.timezone.utc)


class Project(Base):
    """
    A piece of work for the farm. It gathers its CAD files, and in time its STL files, 3MF files, printers and parts.
    Its own files are kept in the project files folder (chosen on the Settings page), one folder per project.
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # the project's own CAD files: they belong to it, and go when it does
    cad_files: Mapped[list["ProjectCadFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectCadFile.id"
    )


class ProjectCadFile(Base):
    """
    A CAD file of a project, any kind (Fusion, STEP, SolidWorks, OpenSCAD...), with its versions. Each version is kept,
    numbered, in {project files}/{project id}/cad/{id}/v{n}/, named like a 3MF version ("Bracket ver 2.f3d"), with its
    preview next to it when one could be made. A CAD file is shown by its newest version's name. No version is pruned:
    a CAD file can't be made again from anything else.
    """

    __tablename__ = "project_cad_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="cad_files")
    versions: Mapped[list["ProjectCadVersion"]] = relationship(
        back_populates="cad_file", order_by="ProjectCadVersion.version.desc()", cascade="all, delete-orphan"
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

    cad_file: Mapped["ProjectCadFile"] = relationship(back_populates="versions")
