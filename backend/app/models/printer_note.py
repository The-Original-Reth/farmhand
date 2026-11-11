from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..timeutil import utc_now


class PrinterNote(Base):
    """
    Free-text notes about a printer (nozzle and bed quirks, calibration, maintenance, where it lives...). The same
    design as SourceModelNote, for the same reasons:

    It's its own table, not a column on printers: the database is built with create_all, which creates missing
    tables but never alters existing ones, so adding a table keeps every existing install working.

    `revision` only ever goes up — clearing the notes keeps the row (with an empty body) rather than deleting it —
    so "this revision" always identifies one specific version of the text, which is what lets a save be refused
    when someone else has saved in the meantime. The rules for saving live in app/notes.py.
    """

    __tablename__ = "printer_notes"

    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    printer: Mapped["Printer"] = relationship(back_populates="note_row")  # noqa: F821
