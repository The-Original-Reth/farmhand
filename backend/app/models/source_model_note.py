from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class SourceModelNote(Base):
    """
    Free-text notes about a whole model (print settings that work, where it came from, licence...).
    Separate from SourceModelVersion.note, which describes one file version.

    It's its own table, not a column on source_models: the database is built with create_all, which creates
    missing tables but never alters existing ones, so adding a table keeps every existing install working.

    `revision` only ever goes up — clearing the notes keeps the row (with an empty body) rather than deleting
    it — so "this revision" always identifies one specific version of the text, which is what lets a save be
    refused when someone else has saved in the meantime.
    """

    __tablename__ = "source_model_notes"

    source_model_id: Mapped[int] = mapped_column(ForeignKey("source_models.id"), primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )

    source_model: Mapped["SourceModel"] = relationship(back_populates="note_row")  # noqa: F821
