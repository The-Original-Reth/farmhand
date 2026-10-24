from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Bundle(Base):
    """
    A 3MF bundle's persistent identity — the thing that has a version
    history, per spec's versioning rules (rolling window, monuments, diff).

    CORRECTED DATA MODEL: the original spec assumed each 3MF/bundle was 1:1
    with exactly one source model ("An STL/OBJ/STEP source file is general —
    it can have multiple 3MF children"). Real uploaded files showed the
    reverse can also be true: a single 3MF plate can be sliced from MORE
    THAN ONE source model at once (a mixed plate — e.g. two different
    keychain designs printed together on one bed). So the relationship is
    many-to-many, via BundleSourceModel, not a single source_model_id FK.

    What's still 1:1 and still locked for the bundle's whole life, per
    spec: the printer. printer_id is set once at bundle creation and never
    changed.
    """

    __tablename__ = "bundles"

    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    printer: Mapped["Printer"] = relationship(back_populates="bundles")
    source_model_links: Mapped[list["BundleSourceModel"]] = relationship(
        back_populates="bundle", cascade="all, delete-orphan"
    )
    versions: Mapped[list["BundleVersion"]] = relationship(
        back_populates="bundle", order_by="BundleVersion.version.desc()", cascade="all, delete-orphan"
    )

    # Notes about this 3MF and whether it's starred (see BundleNote / BundleStar). Both go when the bundle does.
    note_row: Mapped["BundleNote | None"] = relationship(  # noqa: F821
        back_populates="bundle", cascade="all, delete-orphan", uselist=False
    )
    star_row: Mapped["BundleStar | None"] = relationship(  # noqa: F821
        back_populates="bundle", cascade="all, delete-orphan", uselist=False
    )

    @property
    def notes(self) -> str:
        return self.note_row.body if self.note_row else ""

    @property
    def notes_revision(self) -> int:
        """0 = never had notes. Counts up with every save, so it names one exact version of the text."""
        return self.note_row.revision if self.note_row else 0

    @property
    def notes_updated_at(self) -> dt.datetime | None:
        return self.note_row.updated_at if self.note_row else None

    @property
    def starred(self) -> bool:
        return self.star_row is not None

    @property
    def source_models(self) -> list["SourceModel"]:
        return [link.source_model for link in self.source_model_links]

    @property
    def latest_version(self) -> "BundleVersion | None":
        return self.versions[0] if self.versions else None


class BundleSourceModel(Base):
    """Join table: which source model(s) a bundle's 3MF was sliced from."""

    __tablename__ = "bundle_source_models"

    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id"), primary_key=True)
    source_model_id: Mapped[int] = mapped_column(ForeignKey("source_models.id"), primary_key=True)

    bundle: Mapped["Bundle"] = relationship(back_populates="source_model_links")
    source_model: Mapped["SourceModel"] = relationship(back_populates="bundle_links")
