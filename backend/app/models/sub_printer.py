from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class SubPrinter(Base):
    """
    One of a printer's printer presets, as PrusaSlicer's Printers tab lists them under a physical printer: "V2 BOG"
    with "V2_BOG_Rapido_Ace_0.5_WC" and "V2_BOG_0.4_brass" under it. A 3MF says which one it was sliced with
    (printer_settings_id), so they're found from the 3MFs uploaded; they can also be added, renamed and removed by
    hand. Renaming one keeps the 3MFs already linked to it.

    Its own tables, not columns on printers and bundle_versions: the database is built with create_all, which creates
    missing tables but never adds columns to ones that exist.
    """

    __tablename__ = "sub_printer"
    __table_args__ = (UniqueConstraint("printer_id", "name", name="uq_sub_printer_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # the preset's name in the slicer
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    printer: Mapped["Printer"] = relationship(back_populates="sub_printers")  # noqa: F821
    # The parts fitted to it (see SubPrinterPart), in the order they were added. They go with it.
    parts: Mapped[list["SubPrinterPart"]] = relationship(
        back_populates="sub_printer", cascade="all, delete-orphan", order_by="SubPrinterPart.id"
    )
    # Other preset names that mean this sub printer (see SubPrinterAlias). They go with it.
    alias_rows: Mapped[list["SubPrinterAlias"]] = relationship(
        back_populates="sub_printer", cascade="all, delete-orphan", order_by="SubPrinterAlias.name"
    )

    @property
    def aliases(self) -> list[str]:
        return [a.name for a in self.alias_rows]


class SubPrinterAlias(Base):
    """
    A preset name a 3MF can carry that means this sub printer, though it isn't called that: its name before it was
    renamed, or a preset whose 3MFs were assigned to it by hand on upload. Farmhand's guess for the next 3MF with that
    preset is this sub printer.
    """

    __tablename__ = "sub_printer_alias"
    __table_args__ = (UniqueConstraint("sub_printer_id", "name", name="uq_sub_printer_alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sub_printer_id: Mapped[int] = mapped_column(ForeignKey("sub_printer.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    sub_printer: Mapped[SubPrinter] = relationship(back_populates="alias_rows")


class SubPrinterPart(Base):
    """
    A part fitted to a sub printer, written down by hand on its Printer parts page: "Hotend", made by "Phaetus",
    model "Rapido UHF", fitted on 2026-08-14, "swapped after the clog". Kept in Farmhand only; a 3MF knows nothing of
    these.
    """

    __tablename__ = "sub_printer_part"

    id: Mapped[int] = mapped_column(primary_key=True)
    sub_printer_id: Mapped[int] = mapped_column(ForeignKey("sub_printer.id"), nullable=False, index=True)
    part: Mapped[str] = mapped_column(String(120), nullable=False)  # what it is: "Hotend", "Nozzle", "Build plate"
    make: Mapped[str | None] = mapped_column(String(120))  # who makes it: "Phaetus"
    model: Mapped[str | None] = mapped_column(String(200))  # which one: "Rapido UHF"
    installed_on: Mapped[dt.date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    # Ticked "Add to name": its model is part of the name the sub printer can be renamed to (see PrinterParts.jsx)
    in_name: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    sub_printer: Mapped[SubPrinter] = relationship(back_populates="parts")


class BundleVersionSubPrinter(Base):
    """
    Which sub printer a 3MF version was sliced with. A row with no sub printer means the version has been looked at
    and names none (or its sub printer was removed), so it isn't looked at again.
    """

    __tablename__ = "bundle_version_sub_printer"

    bundle_version_id: Mapped[int] = mapped_column(ForeignKey("bundle_versions.id"), primary_key=True)
    sub_printer_id: Mapped[int | None] = mapped_column(ForeignKey("sub_printer.id"), index=True)

    version: Mapped["BundleVersion"] = relationship(back_populates="sub_printer_link")  # noqa: F821
    sub_printer: Mapped[SubPrinter | None] = relationship()
