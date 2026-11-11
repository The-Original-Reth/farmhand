from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import printer_links
from ..database import Base
from ..notes import HasNotes
from ..timeutil import utc_iso


class Printer(HasNotes, Base):
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

    # How to reach its Moonraker (see PrinterConnection) and its print history as last synced. Both go with it.
    connection_row: Mapped["PrinterConnection | None"] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan", uselist=False
    )
    print_jobs: Mapped[list["PrintJob"]] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan"
    )
    # Its 1500-hour service reminder, kept in Farmhand (see PrinterServiceReminder)
    service_row: Mapped["PrinterServiceReminder | None"] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan", uselist=False
    )
    service_note_row: Mapped["PrinterServiceNote | None"] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan", uselist=False
    )
    energy_readings: Mapped[list["PrinterEnergyReading"]] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan"
    )
    # The filament price, density and diameter read from each G-code in its history (see GcodeFilament)
    gcode_filaments: Mapped[list["GcodeFilament"]] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan"
    )
    # Reached through PrusaLink instead of Moonraker (see PrusaLinkConnection), and the maintenance Farmhand keeps
    # for it (a Moonraker printer's maintenance lives in Moonraker)
    prusalink_row: Mapped["PrusaLinkConnection | None"] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan", uselist=False
    )
    maintenance_rows: Mapped[list["MaintenanceEntry"]] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan"
    )
    # A camera Farmhand plays itself (a Buddy3D's RTSP stream, see PrinterCamera)
    camera_row: Mapped["PrinterCamera | None"] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan", uselist=False
    )

    # Its printer presets in the slicer (see SubPrinter), A to Z
    sub_printers: Mapped[list["SubPrinter"]] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan", order_by="SubPrinter.name"
    )
    # The one its uploads start on (see DefaultSubPrinter)
    default_sub_printer_row: Mapped["DefaultSubPrinter | None"] = relationship(  # noqa: F821
        back_populates="printer", cascade="all, delete-orphan", uselist=False
    )

    @property
    def default_sub_printer_id(self) -> int | None:
        return self.default_sub_printer_row.sub_printer_id if self.default_sub_printer_row else None

    @property
    def camera_address(self) -> str | None:
        return self.camera_row.address if self.camera_row else None

    @property
    def service(self) -> dict:
        """
        Where its 1500-hour service stands, from the print time last synced:
        state is "waiting" (no totals synced yet), "off", "ok" or "due".
        """
        from .printer_connection import SERVICE_INTERVAL_HOURS

        row = self.service_row
        totals = self.connection_row.totals if self.connection_row else None
        out = {
            "state": "waiting", "enabled": row.enabled if row else True,
            "interval_hours": row.interval_hours if row else SERVICE_INTERVAL_HOURS,
            "hours_since": None, "started_at": utc_iso(row.started_at) if row else None,
            "last_done": row.history[-1] if row and row.history else None,
            # notes kept with the service (PrinterServiceNote); revision 0 = never had any
            "notes": self.service_note_row.body if self.service_note_row else "",
            "notes_revision": self.service_note_row.revision if self.service_note_row else 0,
            "notes_updated_at": utc_iso(self.service_note_row.updated_at) if self.service_note_row else None,
        }
        if row is None or totals is None:
            return out
        out["hours_since"] = max(0.0, (float(totals.get("total_print_time") or 0) - row.start_printtime) / 3600)
        if not row.enabled:
            out["state"] = "off"
        else:
            out["state"] = "due" if out["hours_since"] >= row.interval_hours else "ok"
        return out

    @property
    def connection_type(self) -> str:
        """How Farmhand talks to it: "moonraker" (Klipper) or "prusalink" (a Prusa Core One, MK4, XL...)."""
        return "prusalink" if self.prusalink_row is not None else "moonraker"

    @property
    def prusalink_url_override(self) -> str | None:
        return self.prusalink_row.url if self.prusalink_row else None

    @property
    def prusalink_url(self) -> str | None:
        """
        Where its PrusaLink is: the address set for it, else port 80 of its IP, the wired one unless it answered at its
        Wi-Fi one last (printer_links). None = no IP.
        """
        return printer_links.current("prusalink", self.id, self.prusalink_urls)

    @property
    def prusalink_urls(self) -> list[str]:
        """
        Every address its PrusaLink may answer at, in the order to try. A Prusa answers on its cable and its Wi-Fi
        both, each at its own IP: so its wired IP, then its wireless one. An address set for it is the only one tried.
        """
        if self.prusalink_url_override:
            return [self.prusalink_url_override.rstrip("/")]
        return list(dict.fromkeys(f"http://{_host(ip)}" for ip in (self.wired_ip, self.wireless_ip) if ip))

    @property
    def prusalink_username(self) -> str | None:
        return self.prusalink_row.username if self.prusalink_row else None

    @property
    def has_prusalink_password(self) -> bool:
        return bool(self.prusalink_row and self.prusalink_row.password)

    @property
    def moonraker_url_override(self) -> str | None:
        return self.connection_row.moonraker_url if self.connection_row else None

    @property
    def moonraker_url(self) -> str | None:
        """
        Where its Moonraker is: the address set for it, else port 7125 of its IP, the wired one unless it answered at its
        Wi-Fi one last (printer_links). None = no IP.
        """
        return printer_links.current("moonraker", self.id, self.moonraker_urls)

    @property
    def moonraker_urls(self) -> list[str]:
        """
        Every address its Moonraker may answer at, in the order to try: a Klipper machine on cable and Wi-Fi answers at
        both its IPs, so its wired IP, then its wireless one. An address set for it is the only one tried.
        """
        if self.moonraker_url_override:
            return [self.moonraker_url_override.rstrip("/")]
        return list(dict.fromkeys(f"http://{_host(ip)}:7125" for ip in (self.wired_ip, self.wireless_ip) if ip))

    @property
    def mainsail_url(self) -> str | None:
        """Mainsail is served on port 80 of the same machine as Moonraker (at the IP Moonraker answers at)."""
        return mainsail_for(self.moonraker_url)

    @property
    def has_moonraker_api_key(self) -> bool:
        return bool(self.connection_row and self.connection_row.api_key)


def mainsail_for(moonraker_base: str | None) -> str | None:
    """Mainsail's address for a Moonraker address: port 80 of the same machine. None for none."""
    from urllib.parse import urlsplit

    host = urlsplit(moonraker_base).hostname if moonraker_base else None
    return f"http://{_host(host)}/" if host else None


def _host(host: str) -> str:
    """An IPv6 address needs square brackets inside a URL."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host
