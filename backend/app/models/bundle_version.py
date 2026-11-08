from __future__ import annotations

import datetime as dt
import os

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
      - version 1 is a monument by default (kept in full however many
        versions follow); Load all brings a version's monument back.
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
    slicer_family: Mapped[str] = mapped_column(String(50), nullable=False)  # "prusaslicer" | "orcaslicer" | "bambustudio"
    slicer_display_name: Mapped[str] = mapped_column(String(100), nullable=False)  # "PrusaSlicer 2.9.5-rc1"
    printer_profile_name: Mapped[str | None] = mapped_column(String(120))  # as read from the 3MF itself

    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    monument: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    monument_note: Mapped[str | None] = mapped_column(Text)

    full_files_retained: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    threemf_path: Mapped[str | None] = mapped_column(String(500))  # null once pruned
    gcode_path: Mapped[str | None] = mapped_column(String(500))  # null once pruned
    thumbnail_path: Mapped[str | None] = mapped_column(String(500))  # kept even when pruned

    # kept even when pruned. Deferred: often 30-60 KB, and only one version's detail or a compare needs it, so lists
    # of versions don't load it (it's read the first time .settings is used)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, deferred=True)

    bundle: Mapped["Bundle"] = relationship(back_populates="versions")
    # The printer profile (printer preset) it was sliced with, see BundleVersionSubPrinter. Goes with the version.
    sub_printer_link: Mapped["BundleVersionSubPrinter | None"] = relationship(  # noqa: F821
        back_populates="version", cascade="all, delete-orphan", uselist=False
    )

    @property
    def sub_printer_id(self) -> int | None:
        link = self.sub_printer_link
        return link.sub_printer_id if link else None

    @property
    def sub_printer_name(self) -> str | None:
        link = self.sub_printer_link
        return link.sub_printer.name if link and link.sub_printer else None

    @property
    def gcode_name(self) -> str | None:
        """What its G-code is shown and downloaded as: its 3MF's name with the G-code's extension. None = it has none."""
        if not self.gcode_path or not self.full_files_retained:
            return None
        return os.path.splitext(self.filename)[0] + os.path.splitext(self.gcode_path)[1]
