from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
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
    # Other preset names that mean this printer profile (see SubPrinterAlias). They go with it.
    alias_rows: Mapped[list["SubPrinterAlias"]] = relationship(
        back_populates="sub_printer", cascade="all, delete-orphan", order_by="SubPrinterAlias.name"
    )
    # A copy's printer settings, copied from the printer profile it's a copy of (see SubPrinterSettingsCopy). They go with it.
    settings_copy: Mapped["SubPrinterSettingsCopy | None"] = relationship(
        back_populates="sub_printer", cascade="all, delete-orphan", uselist=False
    )

    @property
    def aliases(self) -> list[str]:
        return [a.name for a in self.alias_rows]

    @property
    def settings_copied_from(self) -> str | None:
        """The printer profile its printer settings were copied from, when it's a copy that has them."""
        return self.settings_copy.copied_from if self.settings_copy else None


class SubPrinterAlias(Base):
    """
    A preset name a 3MF can carry that means this printer profile, though it isn't called that: its name before it was
    renamed, or a preset whose 3MFs were assigned to it by hand on upload. Farmhand's guess for the next 3MF with that
    preset is this printer profile.
    """

    __tablename__ = "sub_printer_alias"
    __table_args__ = (UniqueConstraint("sub_printer_id", "name", name="uq_sub_printer_alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sub_printer_id: Mapped[int] = mapped_column(ForeignKey("sub_printer.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    sub_printer: Mapped[SubPrinter] = relationship(back_populates="alias_rows")


class DefaultSubPrinter(Base):
    """
    The printer profile a printer's uploads start on: a 3MF uploaded to it has this one picked, whatever preset it was
    sliced with (it can still be changed on the upload). At most one per printer; none means Farmhand guesses.
    """

    __tablename__ = "default_sub_printer"

    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), primary_key=True)
    sub_printer_id: Mapped[int] = mapped_column(ForeignKey("sub_printer.id"), nullable=False, index=True)

    printer: Mapped["Printer"] = relationship(back_populates="default_sub_printer_row")  # noqa: F821
    sub_printer: Mapped[SubPrinter] = relationship()


class SubPrinterPart(Base):
    """
    A part fitted to a printer profile, written down by hand on its Printer parts page: "Hotend", made by "Phaetus",
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
    # Ticked "Add to name": its model is part of the name the printer profile can be renamed to (see PrinterParts.jsx)
    in_name: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    sub_printer: Mapped[SubPrinter] = relationship(back_populates="parts")


class SubPrinterSettingsCopy(Base):
    """
    A copied printer profile's printer settings. A printer profile's settings are read from the 3MFs sliced with it, and a
    copy has none yet: so a copy keeps the settings of the one it was copied from, as they were (from its newest 3MF),
    and they're shown as its own until a 3MF sliced with it comes in. Kept whole, so a change to the original (or its
    removal) leaves the copy as it was.
    """

    __tablename__ = "sub_printer_settings_copy"

    sub_printer_id: Mapped[int] = mapped_column(ForeignKey("sub_printer.id"), primary_key=True)
    copied_from: Mapped[str] = mapped_column(String(120), nullable=False)  # the printer profile's name then
    from_file: Mapped[str | None] = mapped_column(String(255))  # the 3MF they were read from: "Frog.3mf · v3"
    copied_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))
    settings: Mapped[dict] = mapped_column(JSON, nullable=False)  # every setting, as a 3MF version's `settings`

    sub_printer: Mapped[SubPrinter] = relationship(back_populates="settings_copy")


class BundleVersionSubPrinter(Base):
    """
    Which printer profile a 3MF version was sliced with. A row with no printer profile means the version has been looked at
    and names none (or its printer profile was removed), so it isn't looked at again.
    """

    __tablename__ = "bundle_version_sub_printer"

    bundle_version_id: Mapped[int] = mapped_column(ForeignKey("bundle_versions.id"), primary_key=True)
    sub_printer_id: Mapped[int | None] = mapped_column(ForeignKey("sub_printer.id"), index=True)

    version: Mapped["BundleVersion"] = relationship(back_populates="sub_printer_link")  # noqa: F821
    sub_printer: Mapped[SubPrinter | None] = relationship()
