from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class BundleNote(Base):
    """
    Free-text notes about one 3MF file (a bundle: every version of it shares these notes). The same design as
    PrinterNote and SourceModelNote, for the same reasons:

    It's its own table, not a column on bundles: the database is built with create_all, which creates missing
    tables but never alters existing ones, so adding a table keeps every existing install working.

    `revision` only ever goes up — clearing the notes keeps the row (with an empty body) rather than deleting it —
    so "this revision" always identifies one specific version of the text, which is what lets a save be refused
    when someone else has saved in the meantime. The rules for saving live in app/notes.py.
    """

    __tablename__ = "bundle_notes"

    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id"), primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )

    bundle: Mapped["Bundle"] = relationship(back_populates="note_row")  # noqa: F821


class BundleStar(Base):
    """
    Which version of a 3MF someone has starred (gold). At most one per 3MF — bundle_id is the key, so starring
    another version moves the star — and never version 1, the initial upload, which always shows as silver.
    No row means nothing is starred.

    Its own table for the same create_all reason as BundleNote. (An earlier "bundle_stars" table starred the whole
    3MF; it's no longer used, and a database that has it just keeps it, unread.)
    """

    __tablename__ = "bundle_starred_versions"

    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id"), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("bundle_versions.id"), nullable=False)
    starred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )

    bundle: Mapped["Bundle"] = relationship(back_populates="star_row")  # noqa: F821
    # Lets a flush delete this row before the version it points at (Postgres enforces that foreign key)
    version: Mapped["BundleVersion"] = relationship()  # noqa: F821
