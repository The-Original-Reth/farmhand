from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class BundleVersion(Base):
    """
    A single versioned 3MF+gcode upload within a bundle's history.

    Per spec:
      - Minimum of 5 versions kept as full files (3MF+gcode). On the 6th,
        the oldest non-monument version is pruned: full_files_retained
        flips to False and threemf_path/gcode_path are cleared, but
        `settings` (the parsed parameters) and the thumbnail are always
        kept — a version is re-parsed fresh from its own stored 3MF at
        upload time, not cached from a prior parse, so `settings` here IS
        that fresh parse's output, permanently retained even after pruning.
      - version 1 is a monument by default; monumenting requires a note;
        un-monumenting requires explicit confirmation (modeled here as the
        service layer requiring an explicit confirm flag, not a DB
        constraint).
      - Any two arbitrary versions (not just adjacent ones) can be diffed;
        `settings` being a flat JSON dict of every parsed key is exactly
        what makes that possible without a rigid per-setting schema, and
        matches the spec's requirement that unmapped/unknown fields still
        get a display field rather than being dropped.
    """

    __tablename__ = "bundle_versions"
    __table_args__ = (UniqueConstraint("bundle_id", "version", name="uq_bundle_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)  # original uploaded .3mf filename
    slicer_family: Mapped[str] = mapped_column(String(50), nullable=False)  # "prusaslicer" | "orcaslicer"
    slicer_display_name: Mapped[str] = mapped_column(String(100), nullable=False)  # "PrusaSlicer 2.9.5-rc1"
    printer_profile_name: Mapped[str | None] = mapped_column(String(120))  # as read from the 3MF itself

    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    monument: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    monument_note: Mapped[str | None] = mapped_column(Text)

    full_files_retained: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    threemf_path: Mapped[str | None] = mapped_column(String(500))  # null once pruned
    gcode_path: Mapped[str | None] = mapped_column(String(500))  # null once pruned
    thumbnail_path: Mapped[str | None] = mapped_column(String(500))  # kept even when pruned

    settings: Mapped[dict] = mapped_column(JSON, nullable=False)  # kept even when pruned

    bundle: Mapped["Bundle"] = relationship(back_populates="versions")
