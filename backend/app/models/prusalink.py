from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..timeutil import utc_now


class PrusaLinkConnection(Base):
    """
    A printer reached through PrusaLink (a Prusa Core One, MK4, XL...) instead of Moonraker. Having this row is what
    makes it a PrusaLink printer; with none, it's a Moonraker one.

    PrusaLink keeps no print history, so Farmhand records the prints itself: every time it looks at the printer it
    notes the job that's running (current_job_id is PrusaLink's own id for it, current_print_id the PrintJob row
    Farmhand keeps for it), and closes that record once the job has ended.

    NOTE: like a Moonraker API key, the password is stored as-is (it's needed on every call) and is never sent back
    out through the API or written to the copy on the NAS.
    """

    __tablename__ = "printer_prusalink"

    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), primary_key=True)
    url: Mapped[str | None] = mapped_column(String(255))  # null = http://<preferred IP>
    username: Mapped[str] = mapped_column(String(120), nullable=False, default="maker")
    password: Mapped[str | None] = mapped_column(Text)

    current_job_id: Mapped[int | None] = mapped_column(Integer)
    current_print_id: Mapped[int | None] = mapped_column(Integer)
    last_progress: Mapped[float | None] = mapped_column()  # percent, as last seen: tells a finished job from a lost one

    printer: Mapped["Printer"] = relationship(back_populates="prusalink_row")  # noqa: F821


class MaintenanceEntry(Base):
    """
    A maintenance reminder kept in Farmhand, for printers with nowhere else to keep one (PrusaLink has no database
    to share with). `entry` has exactly the shape Mainsail gives a reminder in Moonraker (see
    app/services/moonraker/maintenance.py), so both kinds of printer use the same rules and the same page.
    """

    __tablename__ = "printer_maintenance"
    __table_args__ = (UniqueConstraint("printer_id", "key", name="uq_printer_maintenance"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    entry: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    printer: Mapped["Printer"] = relationship(back_populates="maintenance_rows")  # noqa: F821
