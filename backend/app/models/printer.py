from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Printer(Base):
    """
    The trunk of the archive's hierarchy.

    Per spec: name (not IP address) is the primary business key — this
    resolves an earlier design issue where multiple printers could share an
    IP. A printer may have two IPs (wired preferred over wireless); a
    'decommissioned' flag retires a unit without deleting its history.
    """

    __tablename__ = "printers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    kind: Mapped[str | None] = mapped_column(String(200))  # e.g. "Voron Trident (Klipper / Moonraker)"
    wired_ip: Mapped[str | None] = mapped_column(String(45))
    wireless_ip: Mapped[str | None] = mapped_column(String(45))
    decommissioned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    bundles: Mapped[list["Bundle"]] = relationship(back_populates="printer")

    # Notes about the printer (see PrinterNote). Goes when the printer does.
    note_row: Mapped["PrinterNote | None"] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan", uselist=False
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
    def preferred_ip(self) -> str | None:
        """Wired is always preferred when both are available, per spec."""
        return self.wired_ip or self.wireless_ip
