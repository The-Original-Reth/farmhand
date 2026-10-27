from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class PrinterConnection(Base):
    """
    How Farmhand reaches a printer's Moonraker, and what it last heard from it. One row per printer, created the
    first time it's needed; with no row the defaults apply (Moonraker on port 7125 of the printer's IP, no API key).

    Its own table, not columns on printers: the database is built with create_all, which creates missing tables but
    never alters existing ones, so adding a table keeps every existing install working.

    NOTE: like a network share's password, the API key is stored as-is (Farmhand has to present it on every call)
    and is never sent back out through the API.
    """

    __tablename__ = "printer_connections"

    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), primary_key=True)
    moonraker_url: Mapped[str | None] = mapped_column(String(255))  # null = http://<preferred IP>:7125
    api_key: Mapped[str | None] = mapped_column(Text)

    last_sync_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(Text)  # null when the last sync worked
    # Moonraker's lifetime job totals as of the last good sync (its /server/history/totals "job_totals")
    totals: Mapped[dict | None] = mapped_column(JSON)
    # ...and its "auxiliary_totals" (e.g. a power meter's energy_consumption summed over all prints)
    auxiliary_totals: Mapped[list | None] = mapped_column(JSON)

    printer: Mapped["Printer"] = relationship(back_populates="connection_row")  # noqa: F821


SERVICE_INTERVAL_HOURS = 1500


class PrinterServiceReminder(Base):
    """
    The 1500-hour service reminder Farmhand keeps for every printer (in Farmhand, not on the printer). It's due once
    the printer's total print time, as last synced from Moonraker, has grown by 1500 hours since the count started:
    the first sync that brought totals, or the last time the service was marked done.

    No row yet = counting hasn't started (the printer hasn't been synced). `history` lists each time it was done.
    """

    __tablename__ = "printer_service_reminders"

    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_hours: Mapped[float] = mapped_column(Float, nullable=False, default=SERVICE_INTERVAL_HOURS)
    start_printtime: Mapped[float] = mapped_column(Float, nullable=False)  # printer's total print seconds at the start
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # [{done_at, printtime, hours, note}]

    printer: Mapped["Printer"] = relationship(back_populates="service_row")  # noqa: F821


class PrinterEnergyReading(Base):
    """
    A reading of the printer's power meter (a Moonraker [sensor] with an "energy" value, in kWh), taken at each sync
    and every few minutes in the background. Moonraker only knows the meter's current value, so these readings are
    what lets Farmhand say how much the whole printer (idle included) used in a month or a year.
    """

    __tablename__ = "printer_energy_readings"
    # a printer's readings in time order: its latest, its first, all of them by month
    __table_args__ = (Index("ix_energy_readings_printer_taken", "printer_id", "taken_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), nullable=False, index=True)
    taken_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sensor: Mapped[str] = mapped_column(String(120), nullable=False)
    energy_kwh: Mapped[float] = mapped_column(Float, nullable=False)

    printer: Mapped["Printer"] = relationship(back_populates="energy_readings")  # noqa: F821


class PrinterServiceNote(Base):
    """
    Free-text notes kept with a printer's 1500-hour service (what the service involves on this machine, parts to
    have ready...). The same design and saving rules as the other notes (app/notes.py): its own table, a revision
    that only goes up, a save refused if someone else saved in between. Keyed by printer, so notes can be written
    before the service count has started.
    """

    __tablename__ = "printer_service_notes"

    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )

    printer: Mapped["Printer"] = relationship(back_populates="service_note_row")  # noqa: F821


class PrintJob(Base):
    """
    One print from a printer's Moonraker job history, copied into Farmhand by a sync. Kept even after the printer
    forgets it (history cleared, SD card reflashed): this is the archive's copy. Updated while it can still change
    (in progress), matched by Moonraker's own job_id.
    """

    __tablename__ = "print_jobs"
    __table_args__ = (
        UniqueConstraint("printer_id", "job_id", name="uq_print_job"),
        Index("ix_print_jobs_printer_start", "printer_id", "start_time"),  # a printer's history, newest first
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False)  # Moonraker's id for it
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # completed | cancelled | error | in_progress | ...
    start_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    print_duration: Mapped[float] = mapped_column(Float, nullable=False, default=0)  # seconds actually printing
    total_duration: Mapped[float] = mapped_column(Float, nullable=False, default=0)  # seconds, pauses included
    filament_used: Mapped[float] = mapped_column(Float, nullable=False, default=0)  # mm
    job_metadata: Mapped[dict | None] = mapped_column("metadata", JSON)  # the gcode's metadata at the time
    # From a power meter set up in Moonraker ([sensor] with history fields); null when the printer has none
    energy_kwh: Mapped[float | None] = mapped_column(Float)
    avg_power_w: Mapped[float | None] = mapped_column(Float)
    max_power_w: Mapped[float | None] = mapped_column(Float)
    auxiliary: Mapped[list | None] = mapped_column(JSON)  # everything Moonraker recorded alongside the job, as given
    synced_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )

    printer: Mapped["Printer"] = relationship(back_populates="print_jobs")  # noqa: F821
