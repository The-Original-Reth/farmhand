from __future__ import annotations

import datetime as dt
import os
import enum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..notes import HasNotes
from ..timeutil import utc_now


class SourceFileType(str, enum.Enum):
    stl = "STL"
    obj = "OBJ"
    step = "STEP"


class SourceModel(HasNotes, Base):
    """
    The branch level: a general STL/OBJ/STEP source file. General in the
    sense that it can relate to multiple 3MF bundles (different printers,
    different slicer variants, or shared into a mixed-plate bundle with
    other source models — see Bundle's many-to-many note).
    """

    __tablename__ = "source_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # original filename
    file_type: Mapped[SourceFileType] = mapped_column(Enum(SourceFileType), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    versions: Mapped[list["SourceModelVersion"]] = relationship(
        back_populates="source_model",
        order_by="SourceModelVersion.version.desc()",
        cascade="all, delete-orphan",
    )
    # Deleting a model removes its link rows (the bundles themselves are
    # handled explicitly in source_model_service.delete_source_model).
    bundle_links: Mapped[list["BundleSourceModel"]] = relationship(
        back_populates="source_model", cascade="all"
    )

    # Notes about the model as a whole (see SourceModelNote). Goes when the model goes.
    note_row: Mapped["SourceModelNote | None"] = relationship(  # noqa: F821
        back_populates="source_model", cascade="all, delete-orphan", uselist=False
    )

    @property
    def latest_version(self) -> "SourceModelVersion | None":
        return self.versions[0] if self.versions else None


class SourceModelVersion(Base):
    """
    A version of a source model's own geometry file. This is separate from
    3MF/bundle versioning — the spec's rolling-window/monument/pruning
    rules apply to 3MF bundle versions, not source model versions, which
    are much simpler (just a plain history, no pruning).
    """

    __tablename__ = "source_model_versions"
    __table_args__ = (UniqueConstraint("source_model_id", "version", name="uq_source_model_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_model_id: Mapped[int] = mapped_column(ForeignKey("source_models.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    source_model: Mapped["SourceModel"] = relationship(back_populates="versions")

    @property
    def thumbnail_rev(self) -> int:
        """When its preview was last drawn (0 if it has none here): part of the preview's address, so a redrawn
        preview has a new one and browsers can keep each picture for good."""
        try:
            return os.stat(self.thumbnail_path).st_mtime_ns if self.thumbnail_path else 0
        except OSError:
            return 0
