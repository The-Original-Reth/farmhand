from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..timeutil import utc_now


class PrinterConfigBackup(Base):
    """
    One backup of a Klipper printer's config folder (printer.cfg, moonraker.conf, macros, includes...), as read from
    its Moonraker. The files themselves are in the printer backups folder, by default backup/ in the Farmhand folder (`folder`, absolute,
    like every path Farmhand stores); these rows only say what's there. The newest 10 per printer are kept (see
    services/config_backups.py).
    """

    __tablename__ = "printer_config_backups"
    __table_args__ = (Index("ix_config_backups_printer_taken", "printer_id", "taken_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), nullable=False, index=True)
    taken_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)  # manual | automatic | before_restore
    folder: Mapped[str] = mapped_column(Text, nullable=False)  # where its files are, on the NAS
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # [{path, reason}] left out of it

    printer: Mapped["Printer"] = relationship(back_populates="config_backups")  # noqa: F821
    files: Mapped[list["PrinterConfigBackupFile"]] = relationship(
        back_populates="backup", cascade="all, delete-orphan", order_by="PrinterConfigBackupFile.path"
    )


class PrinterConfigBackupFile(Base):
    """One file of a backup: its path in the printer's config folder, and a fingerprint to compare backups by."""

    __tablename__ = "printer_config_backup_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    backup_id: Mapped[int] = mapped_column(ForeignKey("printer_config_backups.id"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(500), nullable=False)  # e.g. "printer.cfg", "macros/start.cfg"
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    modified: Mapped[float | None] = mapped_column(Float)  # when the printer says it was last changed (unix time)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    backup: Mapped[PrinterConfigBackup] = relationship(back_populates="files")


class PrinterSshCheck(Base):
    """
    Whether Farmhand could last log in to the printer's Pi over SSH (services/printer_ssh.py), so its Backups section
    can say "Tested" without trying again on every visit. Set by Test SSH, and kept current by each backup's copy of
    Moonraker's database: a failed login there removes the row.
    """

    __tablename__ = "printer_ssh_checks"

    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), primary_key=True)
    tested_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    user: Mapped[str] = mapped_column(String(100), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)

    printer: Mapped["Printer"] = relationship(back_populates="ssh_check")  # noqa: F821
